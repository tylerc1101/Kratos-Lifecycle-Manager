#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  printf '[klm-core:env:prepare][ERROR] %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[klm-core:env:prepare] %s\n' "$*" >&2
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

CONFIG_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config|--deployment)
      CONFIG_FILE="${2:-}"
      shift 2
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

: "${KLM_HOME:?KLM_HOME is required}"
: "${KLM_ENV_DIR:?KLM_ENV_DIR is required}"
: "${KLM_BUNDLES_DIR:?KLM_BUNDLES_DIR is required}"
: "${KLM_DEPLOYMENT_FILE:?KLM_DEPLOYMENT_FILE is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

[[ -n "$CONFIG_FILE" ]] || die "Missing --config"
[[ -f "$CONFIG_FILE" ]] || die "Config not found: $CONFIG_FILE"

log "Creating environment directories"

as_root mkdir -p "$KLM_HOME/bin"
as_root mkdir -p "$KLM_ENV_DIR"
as_root mkdir -p "$KLM_BUNDLES_DIR"
as_root mkdir -p "$KLM_ENV_DIR/tmp"
as_root mkdir -p "$KLM_ENV_DIR/.ssh"
as_root mkdir -p "$KLM_ENV_DIR/.kubeconfig"

log "Copying deployment config"
as_root cp "$CONFIG_FILE" "$KLM_DEPLOYMENT_FILE"

log "Copying Ansible configuration template"
as_root cp "$KLM_BUNDLES_DIR/klm-core/actions/env/templates/ansible.cfg" "$KLM_ENV_DIR/ansible.cfg"

as_root chown -R "$KLM_OWNER:$KLM_GROUP" "$KLM_ENV_DIR"