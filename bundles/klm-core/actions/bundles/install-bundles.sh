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
: "${KLM_BUNDLES_DIR:?KLM_BUNDLES_DIR is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"
: "${KLM_BUNDLE_ARGS:?KLM_BUNDLE_ARGS is required}"

INSTALL_ROOT="$KLM_ENV_DIR/bundles"

mkdir -p "$INSTALL_ROOT"

find_bundle() {
  local bundle="$1"

  [[ -f "$bundle" ]] && {
    echo "$bundle"
    return 0
  }

  [[ -f "$KLM_BUNDLES_DIR/$bundle" ]] && {
    echo "$KLM_BUNDLES_DIR/$bundle"
    return 0
  }

  [[ -f "$KLM_BUNDLES_DIR/$bundle.bundle" ]] && {
    echo "$KLM_BUNDLES_DIR/$bundle.bundle"
    return 0
  }

  die "Bundle not found: $bundle"
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

NON_CORE_BUNDLES=()

for bundle in "${BUNDLES[@]}"; do
  case "$(basename "$bundle")" in
    klm-core|klm-core-*|klm-core*.bundle|klm-core*.tgz|klm-core*.tar.gz)
      log "Skipping already-installed core bundle: $bundle"
      ;;
    *)
      NON_CORE_BUNDLES+=("$bundle")
      ;;
  esac
done

export KLM_BUNDLE_ARGS="${NON_CORE_BUNDLES[*]}"

if [[ "${#NON_CORE_BUNDLES[@]}" -gt 0 ]]; then
  log "Installing requested bundles"
  "$CORE_DIR/actions/bundles/install-bundles.sh"
else
  log "No non-core bundles requested"
fi

chown -R "$KLM_OWNER:$KLM_GROUP" "$INSTALL_ROOT"

log "Bundle install complete"
