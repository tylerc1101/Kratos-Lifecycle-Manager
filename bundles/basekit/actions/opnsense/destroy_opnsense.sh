#!/bin/bash
set -euo pipefail

VM_NAME="opnsense"
DISK_PATH="/var/lib/libvirt/images/opnsense.qcow2"
CONFIG_ISO="/var/lib/libvirt/config/vm_config/opnsense/opnsense_config.iso"

echo "Destroying OPNsense VM if it exists.."

if virsh --connect qemu:///system dominfo "${VM_NAME}" >/dev/null 2>&1; then
  VM_STATE="$(virsh --connect qemu:///system domstate "${VM_NAME}" || true)"

  if [[ "${VM_STATE}" == "running" ]]; then
    echo "Stopping ${VM_NAME}.."
    virsh --connect qemu:///system destroy "${VM_NAME}"
  fi

  echo "Undefining ${VM_NAME} and removing managed storage.."
  virsh --connect qemu:///system undefine "${VM_NAME}" --remove-all-storage --nvram || \
  virsh --connect qemu:///system undefine "${VM_NAME}" --remove-all-storage || \
  virsh --connect qemu:///system undefine "${VM_NAME}" || true
else
  echo "VM ${VM_NAME} does not exist."
fi

echo "Removing leftover OPNsense disk/config ISO if present.."
rm -f "${DISK_PATH}"
rm -f "${CONFIG_ISO}"

echo "OPNsense VM cleanup complete."