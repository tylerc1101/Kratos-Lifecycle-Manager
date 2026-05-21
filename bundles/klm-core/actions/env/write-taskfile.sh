#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  echo "[klm-core:env:taskfile][ERROR] $*" >&2
  exit 1
}

log() {
  echo "[klm-core:env:taskfile] $*" >&2
}

: "${KLM_ENV_DIR:?KLM_ENV_DIR is required}"
: "${KLM_BUNDLES_DIR:?KLM_BUNDLES_DIR is required}"
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

TASKFILE_OUT="$KLM_ENV_DIR/Taskfile.yml"

[[ -d "$KLM_BUNDLES_DIR" ]] || die "Bundles directory not found: $KLM_BUNDLES_DIR"

command -v python3 >/dev/null 2>&1 || die "python3 is required"

log "Generating environment Taskfile"
log "Bundles dir: $KLM_BUNDLES_DIR"
log "Output: $TASKFILE_OUT"

python3 - "$KLM_BUNDLES_DIR" "$TASKFILE_OUT" <<'PY'
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("Missing required Python module: yaml")

bundles_dir = Path(sys.argv[1]).resolve()
taskfile_out = Path(sys.argv[2]).resolve()

global_vars = {}
includes = {}


def resolve_value(value, bundle_context):
    """
    Resolves values from manifest.yml.

    Supported examples:
      "$KLM_HOME"          -> value of environment variable KLM_HOME
      "$KLM_ENV_DIR"       -> value of environment variable KLM_ENV_DIR
      "$BUNDLE_NAME"       -> bundle manifest name
      "$BUNDLE_VERSION"    -> bundle manifest version
      "$BUNDLE_DIR"        -> relative bundle directory path
      "static-value"       -> static-value
    """

    if not isinstance(value, str):
        return value

    if not value.startswith("$"):
        return value

    var_name = value[1:]

    if var_name in bundle_context:
        return bundle_context[var_name]

    return os.environ.get(var_name, "")


def merge_global_var(key, value, source):
    """
    Prevent silent conflicts if two bundles define the same global var differently.
    """

    if key in global_vars and global_vars[key] != value:
        raise SystemExit(
            f"Conflicting global var '{key}' from {source}. "
            f"Existing value='{global_vars[key]}', new value='{value}'"
        )

    global_vars[key] = value


for manifest_path in sorted(bundles_dir.glob("*/manifest.yml")):
    bundle_dir = manifest_path.parent
    bundle_dir_name = bundle_dir.name
    relative_bundle_dir = f"./bundles/{bundle_dir_name}"

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}

    bundle_name = str(manifest.get("name") or bundle_dir_name)
    bundle_version = str(manifest.get("version") or "")
    taskfile_cfg = manifest.get("taskfile") or {}

    include_file = taskfile_cfg.get("include")
    namespace = taskfile_cfg.get("namespace") or bundle_name
    flatten = bool(taskfile_cfg.get("flatten", False))

    if not include_file:
        continue

    bundle_taskfile = bundle_dir / include_file

    if not bundle_taskfile.exists():
        raise SystemExit(
            f"Manifest references missing taskfile: {bundle_taskfile}"
        )

    bundle_context = {
        "BUNDLE_NAME": bundle_name,
        "BUNDLE_VERSION": bundle_version,
        "BUNDLE_DIR": relative_bundle_dir,
        "BUNDLE_ABS_DIR": str(bundle_dir),
    }

    vars_cfg = taskfile_cfg.get("vars") or {}
    global_cfg = vars_cfg.get("global") or {}
    include_cfg = vars_cfg.get("include") or {}

    for key, value in global_cfg.items():
        resolved = resolve_value(value, bundle_context)
        merge_global_var(key, resolved, str(manifest_path))

    include_vars = {}

    for key, value in include_cfg.items():
        include_vars[key] = resolve_value(value, bundle_context)

    include_entry = {
        "taskfile": f"{relative_bundle_dir}/{include_file}",
        "dir": relative_bundle_dir,
    }

    if flatten:
        include_entry["flatten"] = True

    if include_vars:
        include_entry["vars"] = include_vars

    if namespace in includes:
        raise SystemExit(
            f"Duplicate taskfile namespace '{namespace}' found at {manifest_path}"
        )

    includes[namespace] = include_entry


output = {
    "version": "3",
}

if global_vars:
    output["vars"] = global_vars

output["includes"] = includes

output["tasks"] = {
    "list": {
        "desc": "List described tasks",
        "cmds": [
            "task --list"
        ],
    },
    "list-all": {
        "desc": "List all tasks",
        "cmds": [
            "task --list-all"
        ],
    },
}

taskfile_out.parent.mkdir(parents=True, exist_ok=True)

with taskfile_out.open("w", encoding="utf-8") as f:
    yaml.safe_dump(output, f, sort_keys=False)
PY

chown "$KLM_OWNER:$KLM_GROUP" "$TASKFILE_OUT"

log "Environment Taskfile generated: $TASKFILE_OUT"