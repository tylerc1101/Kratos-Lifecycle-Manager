#!/usr/bin/env bash
set -Eeuo pipefail

ACTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$ACTION_DIR/../.." && pwd)"

die() {
  echo "[klm-core:init][ERROR] $*" >&2
  exit 1
}

log() {
  echo "[klm-core:init] $*" >&2
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
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

: "${KLM_HOME:?KLM_HOME is required}"
: "${KLM_ENV_NAME:?KLM_ENV_NAME is required}"
: "${KLM_ENV_DIR:?KLM_ENV_DIR is required}"
: "${KLM_BUNDLES_DIR:?KLM_BUNDLES_DIR is required}"
: "${KLM_DEPLOYMENT_FILE:?KLM_DEPLOYMENT_FILE is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

[[ -f "$CONFIG_FILE" ]] || die "Config not found: $CONFIG_FILE"
[[ "${#BUNDLES[@]}" -gt 0 ]] || die "Missing --bundles"

export KLM_HOME
export KLM_ENV_NAME
export KLM_ENV_DIR
export KLM_BUNDLES_DIR
export KLM_DEPLOYMENT_FILE
export KLM_OWNER
export KLM_GROUP
export KLM_CORE_DIR="$CORE_DIR"
export KLM_BUNDLE_ARGS="${BUNDLES[*]}"
export PATH="$KLM_HOME/bin:$PATH"

log "Installing Task"
"$CORE_DIR/actions/tools/install-task.sh"

log "Installing Ansible"
"$CORE_DIR/actions/tools/install-ansible.sh"

command -v task >/dev/null 2>&1 || die "task not found after install"
command -v ansible-playbook >/dev/null 2>&1 || die "ansible-playbook not found after install"

log "Handing off to Task/Ansible"

log "Running env prep"
"$CORE_DIR/actions/tools/install-profile.sh"
"$CORE_DIR/actions/tools/write-env-file.sh"
"$CORE_DIR/actions/tools/wrtie-global-env.sh"
"$CORE_DIR/actions/tools/prep-env.sh"
"$CORE_DIR/actions/tools/install-launcher.sh"

log "KLM core init complete"