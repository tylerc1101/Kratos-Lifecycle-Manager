#!/usr/bin/env bash
set -Eeuo pipefail

KLM_GLOBAL_ENV="/etc/klm/klm.env"
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
  ./klm-init.sh --config ./gep2.yml --bundles ./bundles/*

Required deployment.yml values:
  all.vars.env_name
  all.vars.klm.home
  all.vars.klm.owner
  all.vars.klm.group
  all.vars.klm.core.version

Bundle requirements:
  - Each bundle must contain:
      manifest.yml

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

install_bundle() {
  local bundle_file="$1"

  [[ -f "$bundle_file" ]] || die "Bundle not found: $bundle_file"

  local tmp_dir
  tmp_dir="$(mktemp -d)"

  log "Extracting bundle: $bundle_file"

  tar -xzf "$bundle_file" -C "$tmp_dir"

  local bundle_root
  bundle_root="$(find_bundle_root "$tmp_dir")"

  local manifest
  manifest="$bundle_root/$MANIFEST_FILE"

  local bundle_name
  local bundle_version

  bundle_name="$(yaml_get "$manifest" "name")"
  bundle_version="$(yaml_get "$manifest" "version")"

  [[ -n "$bundle_name" ]] || die "Bundle missing name in $MANIFEST_FILE"
  [[ -n "$bundle_version" ]] || die "Bundle missing version in $MANIFEST_FILE"

  safe_name_check "$bundle_name"

  local target_dir
  target_dir="$KLM_BUNDLES_DIR/$bundle_name"

  log "Installing bundle:"
  log "  Name: $bundle_name"
  log "  Version: $bundle_version"
  log "  Target: $target_dir"

  as_root rm -rf "$target_dir"
  as_root mkdir -p "$target_dir"

  as_root cp -a "$bundle_root/." "$target_dir/"

  rm -rf "$tmp_dir"
}

validate_core_bundle() {
  local core_manifest
  core_manifest="$KLM_BUNDLES_DIR/klm-core/$MANIFEST_FILE"

  [[ -f "$core_manifest" ]] || die "klm-core bundle is required"

  local installed_version
  installed_version="$(yaml_get "$core_manifest" "version")"

  [[ -n "$installed_version" ]] || die "klm-core manifest missing version"

  if [[ "$installed_version" != "$KLM_CORE_VERSION" ]]; then
    die "Installed klm-core version '$installed_version' does not match deployment.yml version '$KLM_CORE_VERSION'"
  fi
}

write_global_env() {
  log "Writing global KLM environment"

  as_root mkdir -p /etc/klm

  as_root tee "$KLM_GLOBAL_ENV" >/dev/null <<EOF
KLM_HOME="$KLM_HOME"
EOF

  as_root chmod 0644 "$KLM_GLOBAL_ENV"
}

write_env_envfile() {
  log "Writing environment KLM env file"

  as_root tee "$KLM_ENV_DIR/klm.env" >/dev/null <<EOF
KLM_ENV_NAME="$KLM_ENV_NAME"
KLM_ENV_DIR="$KLM_ENV_DIR"
KLM_BUNDLES_DIR="$KLM_BUNDLES_DIR"
KLM_DEPLOYMENT_FILE="$KLM_DEPLOYMENT_FILE"
EOF

  as_root chmod 0644 "$KLM_ENV_DIR/klm.env"
  as_root chown "$KLM_OWNER:$KLM_GROUP" "$KLM_ENV_DIR/klm.env"
}

run_core_init() {
  local init_sh
  local init_py

  init_sh="$KLM_BUNDLES_DIR/klm-core/automation/init/init.sh"
  init_py="$KLM_BUNDLES_DIR/klm-core/automation/init/init.py"

  export KLM_HOME
  export KLM_ENV_NAME
  export KLM_ENV_DIR
  export KLM_BUNDLES_DIR
  export KLM_DEPLOYMENT_FILE

  if [[ -f "$init_sh" ]]; then
    log "Running klm-core init.sh"

    as_root chmod +x "$init_sh"

    as_root env \
      KLM_HOME="$KLM_HOME" \
      KLM_ENV_NAME="$KLM_ENV_NAME" \
      KLM_ENV_DIR="$KLM_ENV_DIR" \
      KLM_BUNDLES_DIR="$KLM_BUNDLES_DIR" \
      KLM_DEPLOYMENT_FILE="$KLM_DEPLOYMENT_FILE" \
      "$init_sh"

    return
  fi

  if [[ -f "$init_py" ]]; then
    log "Running klm-core init.py"

    as_root env \
      KLM_HOME="$KLM_HOME" \
      KLM_ENV_NAME="$KLM_ENV_NAME" \
      KLM_ENV_DIR="$KLM_ENV_DIR" \
      KLM_BUNDLES_DIR="$KLM_BUNDLES_DIR" \
      KLM_DEPLOYMENT_FILE="$KLM_DEPLOYMENT_FILE" \
      python3 "$init_py"

    return
  fi

  die "No klm-core init script found"
}

CONFIG_FILE=""
BUNDLES=()

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

[[ "${#BUNDLES[@]}" -gt 0 ]] || die "No bundles provided"

need_cmd python3
need_cmd tar
need_cmd find
need_cmd cp
need_cmd rm
need_cmd mktemp

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

log "Initializing KLM environment"
log "  Environment: $KLM_ENV_NAME"
log "  KLM_HOME: $KLM_HOME"
log "  Owner/Group: $KLM_OWNER:$KLM_GROUP"
log "  Core Version: $KLM_CORE_VERSION"

log "Creating directory structure"

as_root mkdir -p "$KLM_HOME"
as_root mkdir -p "$KLM_HOME/bin"
as_root mkdir -p "$KLM_ENV_DIR"
as_root mkdir -p "$KLM_BUNDLES_DIR"

log "Installing lightweight KLM launcher"

as_root install -m 0755 \
  "$KLM_BUNDLES_DIR/klm-core/bin/klm-launcher.sh" \
  "$KLM_HOME/bin/klm"

log "Copying deployment.yml"

as_root cp "$CONFIG_FILE" "$KLM_DEPLOYMENT_FILE"

for bundle in "${BUNDLES[@]}"; do
  install_bundle "$bundle"
done

validate_core_bundle

write_global_env
write_env_envfile

log "Installing KLM profile"

as_root tee /etc/profile.d/klm.sh >/dev/null <<EOF
export PATH="\$PATH:\$KLM_HOME/bin"
EOF

as_root chmod 0644 /etc/profile.d/klm.sh

log "Exporting Path"

as_root export PATH="$PATH:$KLM_HOME/bin"

log "Setting ownership"

as_root chown -R "$KLM_OWNER:$KLM_GROUP" "$KLM_ENV_DIR"

run_core_init

log "KLM init complete"
log "Run with:"
log "  klm"