#!/usr/bin/env bash
set -Eeuo pipefail

ACTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$ACTION_DIR/../.." && pwd)"

die() {
  printf '[klm-core:tools:task][ERROR] %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[klm-core:tools:task] %s\n' "$*" >&2
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

: "${KLM_HOME:?KLM_HOME is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

TASK_SRC="$CORE_DIR/images/task/task"
TASK_DST="$KLM_HOME/bin/task"

[[ -f "$TASK_SRC" ]] || die "Missing bundled task binary: $TASK_SRC"

log "Installing task to $TASK_DST"

as_root mkdir -p "$KLM_HOME/bin"
as_root install -m 0755 "$TASK_SRC" "$TASK_DST"
as_root chown "$KLM_OWNER:$KLM_GROUP" "$TASK_DST"

log "Task version:"
"$TASK_DST" --version || true