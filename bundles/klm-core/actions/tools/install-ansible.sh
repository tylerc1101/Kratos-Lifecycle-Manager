#!/usr/bin/env bash
set -Eeuo pipefail

ACTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$ACTION_DIR/../.." && pwd)"

die() {
  printf '[klm-core:tools:ansible][ERROR] %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[klm-core:tools:ansible] %s\n' "$*" >&2
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

ANSIBLE_RPM_DIR="$CORE_DIR/images/ansible"

[[ -d "$ANSIBLE_RPM_DIR" ]] || die "Missing Ansible RPM directory: $ANSIBLE_RPM_DIR"

mapfile -t RPMS < <(find "$ANSIBLE_RPM_DIR" -type f -name "*.rpm" | sort)

if [[ "${#RPMS[@]}" -eq 0 ]]; then
  die "No RPMs found in $ANSIBLE_RPM_DIR"
fi

log "Installing Ansible RPMs from $ANSIBLE_RPM_DIR"

if command -v dnf >/dev/null 2>&1; then
  as_root dnf install -y "${RPMS[@]}"
elif command -v yum >/dev/null 2>&1; then
  as_root yum install -y "${RPMS[@]}"
elif command -v rpm >/dev/null 2>&1; then
  as_root rpm -Uvh --replacepkgs "${RPMS[@]}"
else
  die "No dnf, yum, or rpm found"
fi

if command -v ansible-playbook >/dev/null 2>&1; then
  log "Ansible installed:"
  ansible-playbook --version | head -n 1
else
  die "ansible-playbook not found after install"
fi