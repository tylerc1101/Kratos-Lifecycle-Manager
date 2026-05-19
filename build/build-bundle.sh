#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_DIR="${1:-}"
DIST_DIR="${DIST_DIR:-dist}"

die() {
  echo "[build][ERROR] $*" >&2
  exit 1
}

log() {
  echo "[build] $*"
}

usage() {
  cat <<EOF
Usage:
  ./scripts/build-bundle.sh <bundle_dir>

Example:
  ./scripts/build-bundle.sh bundles/klm-core

Optional:
  DIST_DIR=./dist ./scripts/build-bundle.sh bundles/klm-core
EOF
}

[[ -n "$BUNDLE_DIR" ]] || {
  usage
  exit 1
}

[[ -d "$BUNDLE_DIR" ]] || die "Bundle directory not found: $BUNDLE_DIR"

BUNDLE_DIR="$(cd "$BUNDLE_DIR" && pwd)"
REPO_ROOT="$(cd "$BUNDLE_DIR/../.." && pwd)"
DIST_DIR="$REPO_ROOT/$DIST_DIR"

RUNTIME_MANIFEST="$BUNDLE_DIR/manifest.yml"
BUILD_MANIFEST="$BUNDLE_DIR/build-manifest.yml"

[[ -f "$RUNTIME_MANIFEST" ]] || die "Missing runtime manifest: $RUNTIME_MANIFEST"
[[ -f "$BUILD_MANIFEST" ]] || die "Missing build manifest: $BUILD_MANIFEST"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

need_cmd python3
need_cmd tar
need_cmd mkdir
need_cmd chmod

yaml_get() {
  local file="$1"
  local key="$2"

  python3 - "$file" "$key" <<'PY'
import sys
import yaml

file_path = sys.argv[1]
key_path = sys.argv[2].split(".")

with open(file_path, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

cur = data

for part in key_path:
    if not isinstance(cur, dict) or part not in cur:
        print("")
        sys.exit(0)
    cur = cur[part]

if isinstance(cur, (list, dict)):
    print("")
else:
    print(cur if cur is not None else "")
PY
}

yaml_list() {
  local file="$1"
  local key="$2"

  python3 - "$file" "$key" <<'PY'
import sys
import yaml

file_path = sys.argv[1]
key_path = sys.argv[2].split(".")

with open(file_path, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

cur = data

for part in key_path:
    if not isinstance(cur, dict) or part not in cur:
        sys.exit(0)
    cur = cur[part]

if isinstance(cur, list):
    for item in cur:
        print(item)
PY
}

safe_name_check() {
  local name="$1"

  [[ -n "$name" ]] || die "Name is empty"
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || die "Unsafe name: $name"
  [[ "$name" != "." ]] || die "Invalid name"
  [[ "$name" != ".." ]] || die "Invalid name"
}

NAME="$(yaml_get "$RUNTIME_MANIFEST" "name")"
VERSION="$(yaml_get "$RUNTIME_MANIFEST" "version")"

[[ -n "$NAME" ]] || die "manifest.yml missing name"
[[ -n "$VERSION" ]] || die "manifest.yml missing version"

safe_name_check "$NAME"
safe_name_check "$VERSION"

log "Building bundle"
log "  Name: $NAME"
log "  Version: $VERSION"
log "  Source: $BUNDLE_DIR"

mkdir -p "$DIST_DIR"

log "Validating required files"

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  [[ -f "$BUNDLE_DIR/$file" ]] || die "Required file missing: $file"
done < <(yaml_list "$BUILD_MANIFEST" "required_files")

log "Validating required directories"

while IFS= read -r dir; do
  [[ -z "$dir" ]] && continue
  [[ -d "$BUNDLE_DIR/$dir" ]] || die "Required directory missing: $dir"
done < <(yaml_list "$BUILD_MANIFEST" "required_dirs")

log "Running pre-build commands"

while IFS= read -r cmd; do
  [[ -z "$cmd" ]] && continue
  log "  $cmd"
  bash -lc "cd '$BUNDLE_DIR' && $cmd"
done < <(yaml_list "$BUILD_MANIFEST" "pre_build")

log "Setting executable permissions"

while IFS= read -r exe; do
  [[ -z "$exe" ]] && continue

  if [[ ! -f "$BUNDLE_DIR/$exe" ]]; then
    die "Executable listed but file not found: $exe"
  fi

  chmod +x "$BUNDLE_DIR/$exe"
  log "  chmod +x $exe"
done < <(yaml_list "$BUILD_MANIFEST" "executables")

OUT_FILE="$DIST_DIR/${NAME}-${VERSION}.bundle"

TAR_EXCLUDES=(
  "--exclude=./.git"
  "--exclude=./.gitignore"
  "--exclude=./*.bundle"
  "--exclude=./tmp"
  "--exclude=./logs"
  "--exclude=./.task"
  "--exclude=./.venv"
  "--exclude=./__pycache__"
)

while IFS= read -r exclude; do
  [[ -z "$exclude" ]] && continue
  TAR_EXCLUDES+=("--exclude=./$exclude")
done < <(yaml_list "$BUILD_MANIFEST" "exclude")

log "Creating bundle artifact"
log "  Output: $OUT_FILE"

tar -czf "$OUT_FILE" \
  -C "$BUNDLE_DIR" \
  "${TAR_EXCLUDES[@]}" \
  .

log "Bundle created: $OUT_FILE"