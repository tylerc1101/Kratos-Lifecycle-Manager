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
: "${KLM_OWNER:?KLM_OWNER is required}"
: "${KLM_GROUP:?KLM_GROUP is required}"

BUNDLES_DIR="$KLM_ENV_DIR/bundles"
TASKFILE_OUT="$KLM_ENV_DIR/Taskfile.yml"

[[ -d "$BUNDLES_DIR" ]] || die "Bundles directory not found: $BUNDLES_DIR"

log "Generating environment Taskfile: $TASKFILE_OUT"

python3 - "$BUNDLES_DIR" "$TASKFILE_OUT" <<'PY'
import sys
from pathlib import Path
import yaml

bundles_dir = Path(sys.argv[1])
taskfile_out = Path(sys.argv[2])

includes = {}

for manifest in sorted(bundles_dir.glob("*/manifest.yml")):
    bundle_dir = manifest.parent

    with manifest.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    name = data.get("name", bundle_dir.name)
    taskfile = data.get("taskfile", {})

    include_file = taskfile.get("include")
    namespace = taskfile.get("namespace", name)

    if not include_file:
        continue

    taskfile_path = bundle_dir / include_file

    if not taskfile_path.exists():
        raise SystemExit(f"Manifest references missing taskfile: {taskfile_path}")

    includes[namespace] = {
        "taskfile": f"./bundles/{bundle_dir.name}/{include_file}",
        "dir": f"./bundles/{bundle_dir.name}",
    }

output = {
    "version": "3",
    "includes": includes,
    "tasks": {
        "list": {
            "desc": "List available tasks",
            "cmds": [
                "task --list"
            ],
        }
    },
}

with taskfile_out.open("w", encoding="utf-8") as f:
    yaml.safe_dump(output, f, sort_keys=False)
PY

chown "$KLM_OWNER:$KLM_GROUP" "$TASKFILE_OUT"

log "Environment Taskfile generated"