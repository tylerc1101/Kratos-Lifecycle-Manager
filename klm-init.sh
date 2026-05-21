#!/usr/bin/env bash
set -Eeuo pipefail

MANIFEST_FILE="manifest.yml"

die() {
  printf '[klm-init][ERROR] %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[klm-init] %s\n' "$*" >&2
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

usage() {
  cat <<EOF
KLM Init

Usage:
  ./klm-init.sh --config <deployment.yml> --bundles <bundle...>

Example:
  ./klm-init.sh --config ./deployment.yml --bundles ./dist/*.bundle
EOF
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

safe_name_check() {
  local name="$1"

  [[ -n "$name" ]] || die "Name is empty"
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || die "Unsafe name: $name"
  [[ "$name" != "." ]] || die "Invalid name"
  [[ "$name" != ".." ]] || die "Invalid name"
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

bundle_manifest_value() {
  local bundle_file="$1"
  local key="$2"
  local tmp_dir
  local bundle_root
  local manifest
  local value

  [[ -f "$bundle_file" ]] || die "Bundle is not a file: $bundle_file"

  tmp_dir="$(mktemp -d)"
  tar -xzf "$bundle_file" -C "$tmp_dir"

  bundle_root="$(find_bundle_root "$tmp_dir")"
  manifest="$bundle_root/$MANIFEST_FILE"

  value="$(yaml_get "$manifest" "$key")"

  rm -rf "$tmp_dir"

  printf '%s\n' "$value"
}

find_core_bundle() {
  local bundle
  local name
  local version

  for bundle in "${BUNDLES[@]}"; do
    [[ -f "$bundle" ]] || continue

    name="$(bundle_manifest_value "$bundle" "name")"
    version="$(bundle_manifest_value "$bundle" "version")"

    if [[ "$name" == "klm-core" && "$version" == "$KLM_CORE_VERSION" ]]; then
      printf '%s\n' "$bundle"
      return
    fi
  done

  die "Could not find klm-core bundle version $KLM_CORE_VERSION"
}

install_core_bundle() {
  local core_bundle="$1"
  local tmp_dir
  local bundle_root
  local manifest
  local name
  local version
  local target_dir

  [[ -f "$core_bundle" ]] || die "Core bundle is not a file: $core_bundle"

  log "Installing bootstrap core bundle: $core_bundle"

  tmp_dir="$(mktemp -d)"
  tar -xzf "$core_bundle" -C "$tmp_dir"

  bundle_root="$(find_bundle_root "$tmp_dir")"
  manifest="$bundle_root/$MANIFEST_FILE"

  name="$(yaml_get "$manifest" "name")"
  version="$(yaml_get "$manifest" "version")"

  [[ "$name" == "klm-core" ]] || die "Expected klm-core bundle, got: $name"
  [[ "$version" == "$KLM_CORE_VERSION" ]] || die "Expected klm-core $KLM_CORE_VERSION, got: $version"

  target_dir="$KLM_BUNDLES_DIR/$name"

  as_root rm -rf "$target_dir"
  as_root mkdir -p "$target_dir"
  as_root cp -a "$bundle_root/." "$target_dir/"

  rm -rf "$tmp_dir"

  log "Installed klm-core to: $target_dir"
}

run_core_init() {
  local init_sh

  init_sh="$KLM_BUNDLES_DIR/klm-core/actions/init/init.sh"

  [[ -f "$init_sh" ]] || die "No klm-core init script found: $init_sh"

  log "Handing off to klm-core init.sh"

  as_root chmod +x "$init_sh"

  as_root env \
    KLM_HOME="$KLM_HOME" \
    KLM_ENV_NAME="$KLM_ENV_NAME" \
    KLM_ENV_DIR="$KLM_ENV_DIR" \
    KLM_BUNDLES_DIR="$KLM_BUNDLES_DIR" \
    KLM_DEPLOYMENT_FILE="$KLM_DEPLOYMENT_FILE" \
    KLM_OWNER="$KLM_OWNER" \
    KLM_GROUP="$KLM_GROUP" \
    KLM_CORE_VERSION="$KLM_CORE_VERSION" \
    "$init_sh" \
      --config "$CONFIG_FILE" \
      --bundles "${NON_CORE_BUNDLES[@]}"
}

CONFIG_FILE=""
BUNDLES=()
NON_CORE_BUNDLES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config|--deployment)
      CONFIG_FILE="${2:-}"
      shift 2
      ;;
    --bundles)
      shift
      while [[ $# -gt 0 && "$1" != --* ]]; do
        BUNDLES+=("$1")
        shift
      done
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$CONFIG_FILE" ]] || die "Missing --config <deployment.yml>"
[[ -f "$CONFIG_FILE" ]] || die "Deployment config not found: $CONFIG_FILE"
[[ "${#BUNDLES[@]}" -gt 0 ]] || die "Missing --bundles <bundle...>"

need_cmd python3
need_cmd tar
need_cmd find
need_cmd mktemp
need_cmd cp
need_cmd rm
need_cmd wc
need_cmd head
need_cmd readlink

KLM_ENV_NAME="$(yaml_get "$CONFIG_FILE" "all.vars.env_name")"
KLM_HOME="$(yaml_get "$CONFIG_FILE" "all.vars.klm.home")"
KLM_OWNER="$(yaml_get "$CONFIG_FILE" "all.vars.klm.owner")"
KLM_GROUP="$(yaml_get "$CONFIG_FILE" "all.vars.klm.group")"
KLM_CORE_VERSION="$(yaml_get "$CONFIG_FILE" "all.vars.klm.core.version")"

[[ -n "$KLM_ENV_NAME" ]] || die "Missing all.vars.env_name"
[[ -n "$KLM_HOME" ]] || die "Missing all.vars.klm.home"
[[ -n "$KLM_OWNER" ]] || die "Missing all.vars.klm.owner"
[[ -n "$KLM_GROUP" ]] || die "Missing all.vars.klm.group"
[[ -n "$KLM_CORE_VERSION" ]] || die "Missing all.vars.klm.core.version"

safe_name_check "$KLM_ENV_NAME"

KLM_ENV_DIR="$KLM_HOME/env/$KLM_ENV_NAME"
KLM_BUNDLES_DIR="$KLM_ENV_DIR/bundles"
KLM_DEPLOYMENT_FILE="$KLM_ENV_DIR/deployment.yml"

log "Bootstrapping KLM environment"
log "  Environment: $KLM_ENV_NAME"
log "  KLM_HOME: $KLM_HOME"
log "  Owner/Group: $KLM_OWNER:$KLM_GROUP"
log "  Core Version: $KLM_CORE_VERSION"

log "Creating minimal directory structure"

as_root mkdir -p "$KLM_HOME"
as_root mkdir -p "$KLM_HOME/bin"
as_root mkdir -p "$KLM_ENV_DIR"
as_root mkdir -p "$KLM_BUNDLES_DIR"

CORE_BUNDLE="$(find_core_bundle)"
CORE_BUNDLE_REAL="$(readlink -f "$CORE_BUNDLE")"

for bundle in "${BUNDLES[@]}"; do
  bundle_real="$(readlink -f "$bundle")"

  if [[ "$bundle_real" == "$CORE_BUNDLE_REAL" ]]; then
    log "Core bundle will not be passed to addon installer: $bundle"
  else
    NON_CORE_BUNDLES+=("$bundle_real")
  fi
done

log "Requested bundles: ${BUNDLES[*]}"
log "Non-core bundles: ${NON_CORE_BUNDLES[*]:-none}"

install_core_bundle "$CORE_BUNDLE"

run_core_init

log "Bootstrap complete"
