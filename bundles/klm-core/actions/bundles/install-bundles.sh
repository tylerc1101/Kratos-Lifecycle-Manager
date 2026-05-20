#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  echo "[klm-bundle:install][ERROR] $*" >&2
  exit 1
}

log() {
  echo "[klm-bundle:install] $*" >&2
}

: "${KLM_ENV_DIR:?KLM_ENV_DIR is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

INSTALL_ROOT="$KLM_ENV_DIR/bundles"

mkdir -p "$INSTALL_ROOT"

if [[ -z "${KLM_BUNDLE_ARGS:-}" ]]; then
  log "No non-core bundles requested"
  exit 0
fi

read -r -a BUNDLES <<< "$KLM_BUNDLE_ARGS"

log "Bundles to install: ${BUNDLES[*]}"

find_bundle() {
  local bundle="$1"

  [[ -f "$bundle" ]] || die "Bundle not found: $bundle"

  echo "$bundle"
}

install_bundle() {
  local bundle_arg="$1"
  local bundle_file
  local bundle_base
  local bundle_name
  local target_dir

  bundle_file="$(find_bundle "$bundle_arg")"
  bundle_base="$(basename "$bundle_file")"

  bundle_name="${bundle_base%.bundle}"
  bundle_name="${bundle_name%.tgz}"
  bundle_name="${bundle_name%.tar.gz}"

  target_dir="$INSTALL_ROOT/$bundle_name"

  log "Installing bundle: $bundle_base"
  log "Install dir: $target_dir"

  rm -rf "$target_dir"
  mkdir -p "$target_dir"

  tar -xzf "$bundle_file" -C "$target_dir"

  chown -R "$KLM_OWNER:$KLM_GROUP" "$target_dir"

  log "Installed: $bundle_name"
}

for bundle in "${BUNDLES[@]}"; do
  install_bundle "$bundle"
done

log "Bundle install complete"
