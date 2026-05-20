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

as_root tee /etc/profile.d/klm.sh >/dev/null <<EOF
export PATH="$KLM_HOME/bin:\$PATH"
EOF

as_root chmod 0644 /etc/profile.d/klm.sh