#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# KLM Engine Entrypoint
# ----------------------------------------------------------------------

SEMAPHORE_CONFIG="${SEMAPHORE_CONFIG_PATH:-/etc/klm/config.json}"

KLM_STATE="/opt/openspace/state"
SEMAPHORE_DATA="${KLM_STATE}/semaphore"
TLS_DIR="${KLM_STATE}/tls"

SEMAPHORE_SECRETS="${SEMAPHORE_DATA}/secrets.env"

TLS_CERT="${TLS_DIR}/klm.crt"
TLS_KEY="${TLS_DIR}/klm.key"


# ----------------------------------------------------------------------
# Validate Semaphore configuration
# ----------------------------------------------------------------------

if [ ! -f "${SEMAPHORE_CONFIG}" ]; then
    echo "ERROR: Semaphore configuration was not found:"
    echo "  ${SEMAPHORE_CONFIG}"
    exit 1
fi


# ----------------------------------------------------------------------
# Create persistent runtime directories
# ----------------------------------------------------------------------

mkdir -p \
    "${SEMAPHORE_DATA}" \
    "${TLS_DIR}" \
    /tmp/klm


# ----------------------------------------------------------------------
# Run KLM CLI command when arguments are supplied
# ----------------------------------------------------------------------

if [ "$#" -gt 0 ]; then
    exec /usr/local/bin/klm-engine "$@"
fi


# ----------------------------------------------------------------------
# Generate persistent Semaphore secrets
#
# These values must remain the same across container recreation and
# engine upgrades.
# ----------------------------------------------------------------------

if [ ! -f "${SEMAPHORE_SECRETS}" ]; then

    echo "Generating Semaphore security keys..."

    umask 077

    COOKIE_HASH="$(openssl rand -base64 32)"
    COOKIE_ENCRYPTION="$(openssl rand -base64 32)"
    ACCESS_KEY_ENCRYPTION="$(openssl rand -base64 32)"

    {
        printf "SEMAPHORE_COOKIE_HASH='%s'\n" \
            "${COOKIE_HASH}"

        printf "SEMAPHORE_COOKIE_ENCRYPTION='%s'\n" \
            "${COOKIE_ENCRYPTION}"

        printf "SEMAPHORE_ACCESS_KEY_ENCRYPTION='%s'\n" \
            "${ACCESS_KEY_ENCRYPTION}"
    } > "${SEMAPHORE_SECRETS}"

    chmod 0600 "${SEMAPHORE_SECRETS}"

    echo "Semaphore security keys created."

else

    echo "Using existing Semaphore security keys."

fi


# ----------------------------------------------------------------------
# Load Semaphore secrets
# ----------------------------------------------------------------------

# shellcheck disable=SC1090
source "${SEMAPHORE_SECRETS}"

export SEMAPHORE_COOKIE_HASH
export SEMAPHORE_COOKIE_ENCRYPTION
export SEMAPHORE_ACCESS_KEY_ENCRYPTION


# ----------------------------------------------------------------------
# Generate persistent TLS certificate
# ----------------------------------------------------------------------

if [ ! -f "${TLS_CERT}" ] || [ ! -f "${TLS_KEY}" ]; then

    echo "Generating KLM TLS certificate..."

    rm -f "${TLS_CERT}" "${TLS_KEY}"

    openssl req \
        -x509 \
        -newkey rsa:4096 \
        -sha256 \
        -days 3650 \
        -nodes \
        -keyout "${TLS_KEY}" \
        -out "${TLS_CERT}" \
        -subj "/CN=KLM" \
        -addext "subjectAltName=DNS:KLM,DNS:localhost,IP:127.0.0.1"

    chmod 0600 "${TLS_KEY}"
    chmod 0644 "${TLS_CERT}"

    echo "KLM TLS certificate created."

else

    echo "Using existing KLM TLS certificate."

fi


# ----------------------------------------------------------------------
# Initialize Semaphore database
# ----------------------------------------------------------------------

echo "Initializing Semaphore database..."

semaphore user list \
    --config "${SEMAPHORE_CONFIG}" \
    > /tmp/klm/semaphore-users.txt


# ----------------------------------------------------------------------
# Create initial administrator
# ----------------------------------------------------------------------

if ! grep -Fxq "${SEMAPHORE_ADMIN}" /tmp/klm/semaphore-users.txt; then

    echo "Creating initial KLM administrator..."

    semaphore user add \
        --admin \
        --login "${SEMAPHORE_ADMIN}" \
        --name "${SEMAPHORE_ADMIN_NAME}" \
        --email "${SEMAPHORE_ADMIN_EMAIL}" \
        --password "${SEMAPHORE_ADMIN_PASSWORD}" \
        --config "${SEMAPHORE_CONFIG}"

    echo "Initial KLM administrator created."

else

    echo "KLM administrator already exists."

fi

rm -f /tmp/klm/semaphore-users.txt


# ----------------------------------------------------------------------
# Start Semaphore
# ----------------------------------------------------------------------

echo
echo "Starting KLM..."
echo "Semaphore configuration:"
echo "  ${SEMAPHORE_CONFIG}"
echo
echo "Semaphore database:"
echo "  ${SEMAPHORE_DATA}/database.sqlite"
echo
echo "KLM interface:"
echo "  https://0.0.0.0:3000"
echo

exec semaphore server \
    --config "${SEMAPHORE_CONFIG}"
