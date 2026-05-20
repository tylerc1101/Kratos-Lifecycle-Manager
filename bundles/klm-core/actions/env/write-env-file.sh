#!/usr/bin/env bash
set -Eeuo pipefail

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

: "${KLM_ENV_NAME:?KLM_ENV_NAME is required}"
: "${KLM_ENV_DIR:?KLM_ENV_DIR is required}"
: "${KLM_BUNDLES_DIR:?KLM_BUNDLES_DIR is required}"
: "${KLM_DEPLOYMENT_FILE:?KLM_DEPLOYMENT_FILE is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

as_root tee "$KLM_ENV_DIR/klm.env" >/dev/null <<EOF
KLM_ENV_NAME="$KLM_ENV_NAME"
KLM_ENV_DIR="$KLM_ENV_DIR"
KLM_BUNDLES_DIR="$KLM_BUNDLES_DIR"
KLM_DEPLOYMENT_FILE="$KLM_DEPLOYMENT_FILE"
EOF

as_root chmod 0644 "$KLM_ENV_DIR/klm.env"
as_root chown "$KLM_OWNER:$KLM_GROUP" "$KLM_ENV_DIR/klm.env"