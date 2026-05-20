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

export KLM_HOME
export KLM_ENV_NAME
export KLM_ENV_DIR
export KLM_BUNDLES_DIR
export KLM_DEPLOYMENT_FILE
export KLM_OWNER
export KLM_GROUP
export KLM_CORE_DIR="$CORE_DIR"
export PATH="$KLM_HOME/bin:$PATH"

log "Installing Task"
"$CORE_DIR/actions/tools/install-task.sh"

log "Installing Ansible"
"$CORE_DIR/actions/tools/install-ansible.sh"

command -v task >/dev/null 2>&1 || die "task not found after install"
command -v ansible-playbook >/dev/null 2>&1 || die "ansible-playbook not found after install"

log "config file=$CONFIG_FILE"
log "Running env prep"
"$CORE_DIR/actions/env/install-profile.sh"
"$CORE_DIR/actions/env/prep-env.sh" --config "$CONFIG_FILE"
"$CORE_DIR/actions/env/write-taskfile.sh"

# FOR KLM interface (In Dev)
#"$CORE_DIR/actions/env/install-launcher.sh"
#"$CORE_DIR/actions/env/write-env-file.sh"
#"$CORE_DIR/actions/env/write-global-env.sh"

if [[ "${#BUNDLES[@]}" -gt 0 ]]; then
  export KLM_BUNDLE_ARGS="${BUNDLES[*]}"

  log "Installing requested non-core bundles"
  log "Non-core bundles: ${BUNDLES[*]}"
  "$CORE_DIR/actions/bundles/install-bundles.sh"
else
  log "No non-core bundles requested"
  log "Skipping non-core bundle install"
fi

log "Writing environment Taskfile"
"$CORE_DIR/actions/env/write-taskfile.sh"

log "KLM core init complete"

log ""
log ""
log "!!!IMPORTANT!!!"
log ""
log "User must run command (as root):"
log "  export PATH=\$PATH:$KLM_HOME/bin"
log "Or user must exit session and log back in for PATH variable to update"
