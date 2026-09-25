#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <bundle-directory>"
    exit 1
fi

BUNDLE_ROOT="/opt/Kratos-Lifecycle-Manager/bundles"
BUNDLE_DIR="${BUNDLE_ROOT}/${1}"

PUBLISH_DIR="${PUBLISH_DIR:-/var/opt/klm-repository/bundles}"

if [ ! -d "${BUNDLE_DIR}" ]; then
    echo "ERROR: Bundle directory does not exist:"
    echo "  ${BUNDLE_DIR}"
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

if ! command -v xz >/dev/null 2>&1; then
    echo "ERROR: xz is required to build compressed bundles."
    exit 1
fi


# ============================================================
# Read Bundle Metadata
# ============================================================

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


# ============================================================
# Validate Bundle Name
# ============================================================

if [ "${DIRECTORY_NAME}" != "${BUNDLE_NAME}" ]; then
    echo "ERROR: Bundle directory name must match bundle name."
    echo
    echo "  Directory: ${DIRECTORY_NAME}"
    echo "  Bundle:    ${BUNDLE_NAME}"
    exit 1
fi


# ============================================================
# Build Paths
# ============================================================

OUTPUT_NAME="${BUNDLE_NAME}-${BUNDLE_VERSION}.bundle"

TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "${TMP_DIR}"
}

trap cleanup EXIT

mkdir -p "${PUBLISH_DIR}"


# ============================================================
# Build Bundle
# ============================================================

echo "Building bundle:"
echo
echo "  Name:        ${BUNDLE_NAME}"
echo "  Version:     ${BUNDLE_VERSION}"
echo "  Source:      ${BUNDLE_DIR}"
echo "  Compression: xz"
echo


tar \
    --exclude='.git' \
    --exclude='.gitignore' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.DS_Store' \
    -I 'xz -T0 -6' \
    -cf "${TMP_DIR}/${OUTPUT_NAME}" \
    -C "$(dirname "${BUNDLE_DIR}")" \
    "${DIRECTORY_NAME}"


# ============================================================
# Publish
# ============================================================

mv \
    "${TMP_DIR}/${OUTPUT_NAME}" \
    "${PUBLISH_DIR}/${OUTPUT_NAME}"

chmod 0644 "${PUBLISH_DIR}/${OUTPUT_NAME}"

if id kratos >/dev/null 2>&1; then
    chown kratos:kratos "${PUBLISH_DIR}/${OUTPUT_NAME}"
fi


# ============================================================
# Results
# ============================================================

echo
echo "Bundle created:"
echo
echo "  ${PUBLISH_DIR}/${OUTPUT_NAME}"
echo
echo "Size:"
du -h "${PUBLISH_DIR}/${OUTPUT_NAME}"