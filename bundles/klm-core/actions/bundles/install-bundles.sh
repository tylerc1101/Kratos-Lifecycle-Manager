#!/usr/bin/env bash
set -Eeuo pipefail

MANIFEST_FILE="manifest.yml"

die() {
  echo "[klm-bundle:install][ERROR] $*" >&2
  exit 1
}

log() {
  echo "[klm-bundle:install] $*" >&2
}

: "${KLM_ENV_DIR:?KLM_ENV_DIR is required}"
: "${KLM_BUNDLES_DIR:?KLM_BUNDLES_DIR is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v tar >/dev/null 2>&1 || die "tar is required"

safe_name_check() {
  local name="$1"

  [[ -n "$name" ]] || die "Bundle name is empty"
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || die "Unsafe bundle name: $name"
  [[ "$name" != "." ]] || die "Invalid bundle name"
  [[ "$name" != ".." ]] || die "Invalid bundle name"
}

yaml_get() {
  local file="$1"
  local dotted_key="$2"

  python3 - "$file" "$dotted_key" <<'PY'
import sys
import yaml

file_path = sys.argv[1]
key_path = sys.argv[2].split(".")

with open(file_path, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

cur = data

for part in key_path:
    if not isinstance(cur, dict) or part not in cur:
        print("")
        sys.exit(0)
    cur = cur[part]

print(cur if cur is not None else "")
PY
}

find_bundle_root() {
  local extracted_dir="$1"

  if [[ -f "$extracted_dir/$MANIFEST_FILE" ]]; then
    printf '%s\n' "$extracted_dir"
    return
  fi

  local root_count
  root_count="$(find "$extracted_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"

  if [[ "$root_count" -eq 1 ]]; then
    local only_dir
    only_dir="$(find "$extracted_dir" -mindepth 1 -maxdepth 1 -type d | head -n1)"

    if [[ -f "$only_dir/$MANIFEST_FILE" ]]; then
      printf '%s\n' "$only_dir"
      return
    fi
  fi

  die "Invalid bundle: missing $MANIFEST_FILE"
}

install_bundle() {
  local bundle_file="$1"
  local tmp_dir
  local bundle_root
  local manifest
  local name
  local version
  local target_dir

  [[ -f "$bundle_file" ]] || die "Bundle not found: $bundle_file"

  log "Installing bundle file: $bundle_file"

  tmp_dir="$(mktemp -d)"
  tar -xzf "$bundle_file" -C "$tmp_dir"

  bundle_root="$(find_bundle_root "$tmp_dir")"
  manifest="$bundle_root/$MANIFEST_FILE"

  name="$(yaml_get "$manifest" "name")"
  version="$(yaml_get "$manifest" "version")"

  [[ -n "$name" ]] || die "Bundle manifest missing name: $manifest"
  [[ -n "$version" ]] || die "Bundle manifest missing version: $manifest"

  safe_name_check "$name"

  target_dir="$KLM_BUNDLES_DIR/$name"

  log "Bundle name: $name"
  log "Bundle version: $version"
  log "Install dir: $target_dir"

  rm -rf "$target_dir"
  mkdir -p "$target_dir"

  cp -a "$bundle_root/." "$target_dir/"

  chown -R "$KLM_OWNER:$KLM_GROUP" "$target_dir"

  rm -rf "$tmp_dir"

  log "Installed bundle: $name $version"
}

if [[ -z "${KLM_BUNDLE_ARGS:-}" ]]; then
  log "No non-core bundles requested"
  exit 0
fi

read -r -a BUNDLES <<< "$KLM_BUNDLE_ARGS"

log "Bundles to install: ${BUNDLES[*]}"

for bundle in "${BUNDLES[@]}"; do
  install_bundle "$bundle"
done

log "Bundle install complete"