#!/usr/bin/env bash
set -Eeuo pipefail

ACTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$ACTION_DIR/../.." && pwd)"

die() {
  printf '[klm-core:env:launcher][ERROR] %s\n' "$*" >&2
  exit 1
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

SRC="$CORE_DIR/bin/klm-launcher.sh"
DST="$KLM_HOME/bin/klm"

[[ -f "$SRC" ]] || die "Missing launcher: $SRC"

as_root mkdir -p "$KLM_HOME/bin"
as_root install -m 0755 "$SRC" "$DST"
as_root chown "$KLM_OWNER:$KLM_GROUP" "$DST"