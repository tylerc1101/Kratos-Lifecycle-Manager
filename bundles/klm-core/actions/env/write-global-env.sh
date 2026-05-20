#!/usr/bin/env bash
set -Eeuo pipefail

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

: "${KLM_HOME:?KLM_HOME is required}"

as_root mkdir -p /etc/klm

as_root tee /etc/klm/klm.env >/dev/null <<EOF
KLM_HOME="$KLM_HOME"
EOF

as_root chmod 0644 /etc/klm/klm.env