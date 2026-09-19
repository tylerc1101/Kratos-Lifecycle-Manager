#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <bundle-directory>"
    exit 1
fi

BUNDLE_DIR="/opt/Kratos-Lifecycle-Manager/bundles/${1}"
PUBLISH_DIR="${PUBLISH_DIR:-/opt/klm-repository/bundles}"

if [ ! -d "${BUNDLE_DIR}" ]; then
    echo "ERROR: Bundle directory does not exist: ${BUNDLE_DIR}"
    exit 1
fi

if [ ! -f "${BUNDLE_DIR}/bundle.yml" ]; then
    echo "ERROR: Missing bundle.yml"
    exit 1
fi

if [ ! -f "${BUNDLE_DIR}/semaphore.yml" ]; then
    echo "ERROR: Missing semaphore.yml"
    exit 1
fi

readarray -t BUNDLE_INFO < <(
    python3 - "${BUNDLE_DIR}/bundle.yml" <<'PY'
import sys
import yaml

with open(sys.argv[1], "r") as f:
    data = yaml.safe_load(f)

print(data["name"])
print(data["version"])
PY
)

BUNDLE_NAME="${BUNDLE_INFO[0]}"
BUNDLE_VERSION="${BUNDLE_INFO[1]}"
DIRECTORY_NAME="$(basename "${BUNDLE_DIR}")"

if [ "${DIRECTORY_NAME}" != "${BUNDLE_NAME}" ]; then
    echo "ERROR: Bundle directory name must match bundle name."
    echo "  Directory: ${DIRECTORY_NAME}"
    echo "  Bundle:    ${BUNDLE_NAME}"
    exit 1
fi

OUTPUT_NAME="${BUNDLE_NAME}-${BUNDLE_VERSION}.bundle"
TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "${TMP_DIR}"
}

trap cleanup EXIT

mkdir -p "${PUBLISH_DIR}"

echo "Building bundle:"
echo "  Name:    ${BUNDLE_NAME}"
echo "  Version: ${BUNDLE_VERSION}"
echo "  Source:  ${BUNDLE_DIR}"
echo

tar \
    --exclude='.git' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    -czf "${TMP_DIR}/${OUTPUT_NAME}" \
    -C "$(dirname "${BUNDLE_DIR}")" \
    "${DIRECTORY_NAME}"

mv "${TMP_DIR}/${OUTPUT_NAME}" \
   "${PUBLISH_DIR}/${OUTPUT_NAME}"

chmod 0644 "${PUBLISH_DIR}/${OUTPUT_NAME}"

echo
echo "Bundle created:"
echo "  ${PUBLISH_DIR}/${OUTPUT_NAME}"