#!/usr/bin/env bash
# run-make.sh
# Run one of the onboarder's /usr/local/bin scripts (deploy-kubernetes,
# deploy-harbor, deploy-rancher, ...) on klm_host via SSH + podman exec,
# streaming output live back to Semaphore.
#
# Usage:
#   run-make.sh <command> [args...]
#   run-make.sh deploy-kubernetes
#   run-make.sh deploy-harbor mcm
set -euo pipefail

# ---- config (override via env / Semaphore Environment) ----------------------
KLM_HOST="${KLM_HOST:-klm_host}"
KLM_SSH_USER="${KLM_SSH_USER:-}"                    # empty = ssh default/current user
KLM_SSH_KEY="${KLM_SSH_KEY:-/opt/openspace/.ssh/rancher_ssh_key}"
ONBOARDER_CONTAINER="${ONBOARDER_CONTAINER:-onboarder}"
ONBOARDER_BIN="${ONBOARDER_BIN:-/usr/local/bin}"
ONBOARDER_SUDO="${ONBOARDER_SUDO:-false}"           # true if container is rootful and ssh user isn't root

# ---- args -------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
  echo "usage: $0 <command> [args...]" >&2
  exit 2
fi
CMD="$1"; shift

# Command must be a bare name; it always resolves to ONBOARDER_BIN/<name>.
[[ "$CMD" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERROR: invalid command: $CMD" >&2; exit 2; }
for a in "$@"; do
  [[ "$a" =~ ^[A-Za-z0-9._=/:,-]+$ ]] || { echo "ERROR: invalid argument: $a" >&2; exit 2; }
done

# ---- build remote commands --------------------------------------------------
podman=(podman)
[[ "$ONBOARDER_SUDO" == "true" ]] && podman=(sudo -n podman)

script="${ONBOARDER_BIN}/${CMD}"

check_cmd="$(printf '%q ' "${podman[@]}" inspect -f '{{.State.Running}}' "$ONBOARDER_CONTAINER")"
exists_cmd="$(printf '%q ' "${podman[@]}" exec "$ONBOARDER_CONTAINER" test -x "$script")"
run_cmd="$(printf '%q ' "${podman[@]}" exec -t -e PYTHONUNBUFFERED=1 "$ONBOARDER_CONTAINER" "$script" "$@")"

ssh_opts=(
  -i "$KLM_SSH_KEY"
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=4
  -o LogLevel=ERROR
)
dest="${KLM_SSH_USER:+${KLM_SSH_USER}@}${KLM_HOST}"

# ---- preflight --------------------------------------------------------------
state=$(ssh "${ssh_opts[@]}" "$dest" "$check_cmd" 2>&1) || {
  echo "ERROR: could not inspect ${ONBOARDER_CONTAINER} on ${dest}: ${state}" >&2
  exit 1
}
[[ "$state" == "true" ]] || { echo "ERROR: ${ONBOARDER_CONTAINER} is not running (state: ${state})" >&2; exit 1; }

ssh "${ssh_opts[@]}" "$dest" "$exists_cmd" || {
  echo "ERROR: ${script} not found or not executable in ${ONBOARDER_CONTAINER}" >&2
  exit 1
}

# ---- run --------------------------------------------------------------------
echo ">>> ${dest}: ${ONBOARDER_CONTAINER} ${script} $*"
echo "------------------------------------------------------------------------"
set +e
ssh -tt "${ssh_opts[@]}" "$dest" "$run_cmd"   # -tt = live, line-buffered output
rc=$?
set -e
echo "------------------------------------------------------------------------"
echo ">>> ${CMD} finished with exit code ${rc}"
exit "$rc"