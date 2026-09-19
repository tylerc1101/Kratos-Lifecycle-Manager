#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="/opt/Kratos-Lifecycle-Manager"

ENGINE_DIR="${PROJECT_ROOT}/engine"
VERSION_FILE="${ENGINE_DIR}/VERSION"

PUBLISH_DIR="${PUBLISH_DIR:-/opt/klm-repository/engine}"

IMAGE_NAME="klm-engine"


# --------------------------------------------------
# Validate
# --------------------------------------------------

if [ ! -d "${ENGINE_DIR}" ]; then
    echo "ERROR: Engine directory does not exist:"
    echo "  ${ENGINE_DIR}"
    exit 1
fi

if [ ! -f "${VERSION_FILE}" ]; then
    echo "ERROR: Missing engine version file:"
    echo "  ${VERSION_FILE}"
    exit 1
fi

if [ ! -f "${PROJECT_ROOT}/Containerfile" ]; then
    echo "ERROR: Missing Containerfile:"
    echo "  ${PROJECT_ROOT}/Containerfile"
    exit 1
fi


# --------------------------------------------------
# Version
# --------------------------------------------------

ENGINE_VERSION="$(tr -d '[:space:]' < "${VERSION_FILE}")"

if [ -z "${ENGINE_VERSION}" ]; then
    echo "ERROR: Engine version is empty."
    exit 1
fi

FULL_IMAGE="${IMAGE_NAME}:${ENGINE_VERSION}"
OUTPUT_NAME="${IMAGE_NAME}-${ENGINE_VERSION}.tar"

# --------------------------------------------------
# Build engine
# --------------------------------------------------

echo
echo "Building KLM Engine:"
echo "  Version: ${ENGINE_VERSION}"
echo "  Image:   ${FULL_IMAGE}"
echo

podman build \
    --tag "${FULL_IMAGE}" \
    --file "${PROJECT_ROOT}/Containerfile" \
    "${PROJECT_ROOT}"


# --------------------------------------------------
# Export engine
# --------------------------------------------------

mkdir -p "${PUBLISH_DIR}"

TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "${TMP_DIR}"
}

trap cleanup EXIT

echo
echo "Exporting engine image..."

podman save \
    --format docker-archive \
    --output "${TMP_DIR}/${OUTPUT_NAME}" \
    "${FULL_IMAGE}"


# --------------------------------------------------
# Publish
# --------------------------------------------------

mv \
    "${TMP_DIR}/${OUTPUT_NAME}" \
    "${PUBLISH_DIR}/${OUTPUT_NAME}"

chmod 0644 "${PUBLISH_DIR}/${OUTPUT_NAME}"


echo
echo "KLM Engine build complete."
echo
echo "Image:"
echo "  ${FULL_IMAGE}"
echo
echo "Artifact:"
echo "  ${PUBLISH_DIR}/${OUTPUT_NAME}"