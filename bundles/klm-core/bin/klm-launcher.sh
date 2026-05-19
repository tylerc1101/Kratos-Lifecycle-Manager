#!/usr/bin/env bash
set -Eeuo pipefail

# KLM lightweight launcher
# Installed to:
#   $KLM_HOME/bin/klm
#
# Purpose:
#   - discover available KLM environments
#   - allow env selection
#   - run the selected env's compatible klm_cli.py

KLM_GLOBAL_ENV="/etc/klm/klm.env"

die() {
  printf '[klm][ERROR] %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[klm] %s\n' "$*" >&2
}

load_global_env() {
  if [[ -f "$KLM_GLOBAL_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$KLM_GLOBAL_ENV"
  fi

  KLM_HOME="${KLM_HOME:-/opt/openspace}"
  KLM_ENV_ROOT="$KLM_HOME/env"
}

usage() {
  cat <<EOF
KLM Launcher

Usage:
  klm
  klm --env <env_name>
  klm --env <env_name> <args>

Examples:
  klm
  klm --env GEP2
  klm --env GEP2 onboarder:deploy

EOF
}

discover_envs() {
  [[ -d "$KLM_ENV_ROOT" ]] || die "KLM env directory not found: $KLM_ENV_ROOT"

  find "$KLM_ENV_ROOT" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -printf '%f\n' | sort
}

select_env() {
  local envs=()
  local env
  local choice
  local index

  while IFS= read -r env; do
    [[ -n "$env" ]] && envs+=("$env")
  done < <(discover_envs)

  [[ "${#envs[@]}" -gt 0 ]] || die "No KLM environments found in $KLM_ENV_ROOT"

  echo
  echo "Select KLM Environment"
  echo "======================"

  for index in "${!envs[@]}"; do
    printf '%s) %s\n' "$((index + 1))" "${envs[$index]}"
  done

  echo "q) Quit"
  echo

  read -rp "Select option: " choice

  if [[ "$choice" =~ ^[Qq]$ ]]; then
    exit 0
  fi

  [[ "$choice" =~ ^[0-9]+$ ]] || die "Invalid selection: $choice"

  index="$((choice - 1))"

  [[ "$index" -ge 0 && "$index" -lt "${#envs[@]}" ]] || die "Invalid selection: $choice"

  printf '%s\n' "${envs[$index]}"
}

load_env_file() {
  local env_file="$1"

  [[ -f "$env_file" ]] || die "Environment file not found: $env_file"

  # shellcheck disable=SC1090
  source "$env_file"
}

main() {
  local env_name=""
  local env_dir=""
  local env_file=""
  local env_cli=""

  load_global_env

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env)
        env_name="${2:-}"
        [[ -n "$env_name" ]] || die "Missing value for --env"
        shift 2
        ;;
      --env=*)
        env_name="${1#--env=}"
        shift
        ;;
      -h|--help|help)
        usage
        exit 0
        ;;
      *)
        break
        ;;
    esac
  done

  if [[ -z "$env_name" ]]; then
    env_name="$(select_env)"
  fi

  env_dir="$KLM_ENV_ROOT/$env_name"
  env_file="$env_dir/klm.env"
  env_cli="$env_dir/bundles/klm-core/automation/cli/klm_cli.py"

  [[ -d "$env_dir" ]] || die "Environment not found: $env_dir"

  load_env_file "$env_file"

  export KLM_HOME
  export KLM_ENV_NAME="${KLM_ENV_NAME:-$env_name}"
  export KLM_ENV_DIR="${KLM_ENV_DIR:-$env_dir}"
  export KLM_BUNDLES_DIR="${KLM_BUNDLES_DIR:-$env_dir/bundles}"
  export KLM_DEPLOYMENT_FILE="${KLM_DEPLOYMENT_FILE:-$env_dir/deployment.yml}"

  if [[ -d "$KLM_BUNDLES_DIR/klm-core/bin" ]]; then
    export PATH="$KLM_BUNDLES_DIR/klm-core/bin:$PATH"
  fi

  [[ -f "$env_cli" ]] || die "Environment CLI not found: $env_cli"

  exec python3 "$env_cli" "$@"
}

main "$@"