
import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    import yaml
except Exception as exc:
    print("[klm][ERROR] PyYAML is required by KLM core.", file=sys.stderr)
    print(f"[klm][ERROR] {exc}", file=sys.stderr)
    sys.exit(1)


def log(message: str) -> None:
    print(f"[klm] {message}", file=sys.stderr)


def warn(message: str) -> None:
    print(f"[klm][WARN] {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    print(f"[klm][ERROR] {message}", file=sys.stderr)
    sys.exit(code)


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def klm_home() -> Path:
    return Path(os.environ.get("KLM_HOME", "/opt/klm")).resolve()


def env_root() -> Path:
    return klm_home() / "env"


def current_link() -> Path:
    return env_root() / "current"


def current_env_dir() -> Path:
    link = current_link()
    if not link.is_symlink():
        die("No current environment is set. Run: klm env use <env_name> or klm init --config deployment.yml")
    target = link.resolve()
    if not target.exists():
        die(f"Current environment target does not exist: {target}")
    return target


def ensure_env_dirs(env_dir: Path) -> None:
    for name in ["bundles", "artifacts", "generated", "inventory", "logs", "state", "backups"]:
        (env_dir / name).mkdir(parents=True, exist_ok=True)


def task_binary() -> str:
    found = shutil.which("task")
    if found:
        return found
    candidate = klm_home() / "bin" / "task"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    die("Go Task binary not found. Install 'task' or place it at $KLM_HOME/bin/task")


def resolve_relative(base_dir: Path, value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def config_env_name(config: dict, fallback: str | None = None) -> str:
    metadata = config.get("metadata") or {}
    return str(metadata.get("name") or config.get("env_name") or fallback or "").strip()


def deployment_bundle_root(config_path: Path, config: dict, override: str | None = None) -> Path:
    if override:
        return resolve_relative(Path.cwd(), override)
    klm = config.get("klm") or {}
    value = klm.get("bundle_root") or "bundles"
    return resolve_relative(config_path.parent, str(value))


def deployment_bundle_entries(config: dict) -> list[dict]:
    klm = config.get("klm") or {}
    entries = klm.get("bundles") or []
    if not isinstance(entries, list):
        die("deployment.yml field klm.bundles must be a list")
    return entries


def enabled(value) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"false", "no", "0", "off", "disabled"}


def unpack_bundle(archive: Path, dest_root: Path) -> str:
    if not archive.exists():
        die(f"Bundle archive not found: {archive}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            with tarfile.open(archive, "r:*") as tf:
                tf.extractall(tmp_path)
        except tarfile.TarError as exc:
            die(f"Failed to unpack bundle {archive}: {exc}")

        candidates = []
        if (tmp_path / "klm-bundle.yml").exists():
            candidates.append(tmp_path)
        candidates.extend(p.parent for p in tmp_path.glob("*/klm-bundle.yml"))

        if not candidates:
            die(f"Bundle archive does not contain klm-bundle.yml: {archive}")

        bundle_root = candidates[0]
        manifest = load_yaml(bundle_root / "klm-bundle.yml")
        metadata = manifest.get("metadata") or {}
        bundle_name = str(metadata.get("name") or archive.stem.replace(".tar", "")).strip()

        if not bundle_name:
            die(f"Bundle name could not be determined: {archive}")

        dest = dest_root / bundle_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(bundle_root, dest)

        return bundle_name


def init_cmd(args) -> None:
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        die(f"Deployment config not found: {config_path}")

    config = load_yaml(config_path)
    env_name = args.env_name or config_env_name(config)

    if not env_name:
        die("Environment name not found. Add metadata.name to deployment.yml or pass --name <env_name>.")

    root = env_root()
    env_dir = root / env_name

    root.mkdir(parents=True, exist_ok=True)
    env_dir.mkdir(parents=True, exist_ok=True)
    ensure_env_dirs(env_dir)

    shutil.copy2(config_path, env_dir / "deployment.yml")

    bundle_root = deployment_bundle_root(config_path, config, args.bundle_root)

    entries = deployment_bundle_entries(config)
    if not entries:
        warn("No klm.bundles entries found in deployment.yml.")

    for entry in entries:
        if not isinstance(entry, dict):
            die("Each klm.bundles entry must be an object")

        if not enabled(entry.get("enabled", True)):
            continue

        name = entry.get("name", "")
        file_name = entry.get("file") or entry.get("source")
        if not file_name:
            die(f"Bundle entry is missing file/source: {entry}")

        archive = resolve_relative(bundle_root, str(file_name))
        staged_name = unpack_bundle(archive, env_dir / "bundles")

        expected_version = entry.get("version")
        staged_manifest = load_yaml(env_dir / "bundles" / staged_name / "klm-bundle.yml")
        staged_meta = staged_manifest.get("metadata") or {}

        if name and str(staged_meta.get("name")) != str(name):
            die(f"Bundle name mismatch for {archive}: deployment.yml wants {name}, bundle says {staged_meta.get('name')}")

        if expected_version and str(staged_meta.get("version")) != str(expected_version):
            die(f"Bundle version mismatch for {name}: deployment.yml wants {expected_version}, bundle says {staged_meta.get('version')}")

        log(f"Staged bundle: {staged_name}")

    if current_link().exists() or current_link().is_symlink():
        current_link().unlink()
    current_link().symlink_to(env_dir)

    log(f"Initialized environment: {env_name}")
    log(f"Current environment: {current_link()} -> {env_dir}")


def env_current(args) -> None:
    env_dir = current_env_dir()
    print(f"Current environment: {env_dir.name}")
    print(f"Path: {env_dir}")


def env_list(args) -> None:
    root = env_root()
    print("Available environments:")
    if not root.exists():
        print("  none")
        return
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir() and p.name != "current":
            marker = ""
            try:
                if current_link().is_symlink() and current_link().resolve() == p.resolve():
                    marker = " *"
            except Exception:
                pass
            print(f"  - {p.name}{marker}")


def env_use(args) -> None:
    env_dir = env_root() / args.name
    if not env_dir.exists():
        die(f"Environment does not exist: {args.name}")
    if current_link().exists() or current_link().is_symlink():
        current_link().unlink()
    current_link().symlink_to(env_dir)
    print(f"Current environment is now: {args.name}")


def bundle_manifests() -> list[Path]:
    bundles_dir = current_env_dir() / "bundles"
    if not bundles_dir.exists():
        return []
    return sorted(bundles_dir.glob("*/klm-bundle.yml"), key=lambda p: p.parent.name.lower())


GROUP_MAP = {
    "infrastructure": "Infrastructure",
    "architecture": "Infrastructure",
    "platform": "Infrastructure",
    "application": "Applications",
    "applications": "Applications",
    "app": "Applications",
    "operations": "Operations",
    "troubleshooting": "Troubleshooting",
}


def normalize_task(entry):
    if isinstance(entry, str):
        return {
            "id": entry,
            "task": entry,
            "label": entry,
            "description": "",
            "interactive": False,
            "dangerous": False,
            "confirm": "",
            "hidden": False,
        }
    if not isinstance(entry, dict):
        return None
    task_id = str(entry.get("id", "")).strip()
    if not task_id:
        return None
    return {
        "id": task_id,
        "task": str(entry.get("task") or task_id).strip(),
        "label": str(entry.get("label") or task_id).strip(),
        "description": str(entry.get("description") or "").strip(),
        "interactive": bool(entry.get("interactive", False)),
        "dangerous": bool(entry.get("dangerous", False)),
        "confirm": str(entry.get("confirm") or "").strip(),
        "hidden": bool(entry.get("hidden", False)),
    }


def task_records() -> list[dict]:
    records = []
    for manifest_path in bundle_manifests():
        data = load_yaml(manifest_path)
        meta = data.get("metadata") or {}
        bundle = str(meta.get("name") or manifest_path.parent.name)
        display = str(meta.get("displayName") or meta.get("display_name") or bundle)
        bundle_type = str(data.get("type") or "other").lower()
        group = str(data.get("group") or GROUP_MAP.get(bundle_type, "Other"))

        for entry in data.get("tasks") or []:
            item = normalize_task(entry)
            if not item or item["hidden"]:
                continue
            records.append({
                "group": group,
                "bundle": bundle,
                "display": display,
                "bundle_dir": manifest_path.parent,
                **item,
            })
    return records


def print_tasks(args=None) -> None:
    env_dir = current_env_dir()
    records = task_records()

    print("KLM Task Menu")
    print(f"Environment: {env_dir.name}")
    print()

    if not records:
        print("No published bundle tasks found.")
        return

    current_group = None
    current_bundle = None
    count = 1

    for r in records:
        if r["group"] != current_group:
            current_group = r["group"]
            current_bundle = None
            print(f"[{current_group}]")
            print()

        if r["display"] != current_bundle:
            current_bundle = r["display"]
            print(f"  {current_bundle}")

        suffix = ""
        if r["interactive"]:
            suffix += " [interactive]"
        if r["dangerous"]:
            suffix += " [dangerous]"

        print(f"    {count}) {r['label']}{suffix}")
        if r["description"]:
            print(f"       {r['description']}")
        count += 1

    print()


def resolve_command(command_or_number: str) -> dict:
    records = task_records()
    if command_or_number.isdigit():
        idx = int(command_or_number)
        if idx < 1 or idx > len(records):
            die(f"Task selection out of range: {idx}")
        return records[idx - 1]

    if ":" not in command_or_number:
        die("Task command must be <bundle>:<task>, for example onboarder:apply")

    bundle, task_id = command_or_number.split(":", 1)
    for r in records:
        if r["bundle"] == bundle and r["id"] == task_id:
            return r

    die(f"Task not found: {command_or_number}")


def run_record(r: dict) -> None:
    env_dir = current_env_dir()
    bundle_dir = Path(r["bundle_dir"])
    taskfile = bundle_dir / "Taskfile.yml"

    if not taskfile.exists():
        die(f"Bundle is missing Taskfile.yml: {bundle_dir}")

    if r["dangerous"]:
        expected = r["confirm"] or "YES"
        answer = input(f"This task is dangerous. Type '{expected}' to continue: ")
        if answer != expected:
            die("Cancelled.")

    env = os.environ.copy()
    env.update({
        "KLM_HOME": str(klm_home()),
        "KLM_ENV_NAME": env_dir.name,
        "KLM_ENV_DIR": str(env_dir),
        "KLM_CONFIG": str(env_dir / "deployment.yml"),
        "KLM_BUNDLES_DIR": str(env_dir / "bundles"),
        "KLM_BUNDLE_DIR": str(bundle_dir),
        "KLM_ARTIFACTS_DIR": str(env_dir / "artifacts"),
        "KLM_GENERATED_DIR": str(env_dir / "generated"),
        "KLM_INVENTORY_DIR": str(env_dir / "inventory"),
        "KLM_LOGS_DIR": str(env_dir / "logs"),
        "KLM_STATE_DIR": str(env_dir / "state"),
    })

    cmd = [task_binary(), "-t", str(taskfile), r["task"]]

    print()
    log(f"Environment: {env_dir.name}")
    log(f"Running: {r['bundle']}:{r['id']}")
    log(f"Taskfile task: {r['task']}")
    print()

    subprocess.run(cmd, cwd=bundle_dir, env=env, check=True)


def run_cmd(args) -> None:
    run_record(resolve_command(args.task))


def menu_cmd(args) -> None:
    records = task_records()
    print_tasks()
    if not records:
        return
    selection = input("Select task number, command, or q to quit: ").strip()
    if selection.lower() == "q":
        return
    if not selection:
        die("No selection provided")
    run_record(resolve_command(selection))


def plan_cmd(args) -> None:
    env_dir = current_env_dir()
    print("KLM execution plan")
    print(f"Environment: {env_dir.name}")
    print()
    for r in task_records():
        if r["id"] == "apply":
            print(f"  - {r['bundle']}:{r['id']} ({r['label']})")


def apply_cmd(args) -> None:
    for r in task_records():
        if r["id"] == "apply":
            run_record(r)


def validate_cmd(args) -> None:
    env_dir = current_env_dir()
    errors = []

    if not (env_dir / "deployment.yml").exists():
        errors.append("Missing deployment.yml")

    for manifest_path in bundle_manifests():
        data = load_yaml(manifest_path)
        meta = data.get("metadata") or {}
        name = meta.get("name") or manifest_path.parent.name
        if not (manifest_path.parent / "Taskfile.yml").exists():
            errors.append(f"{name}: missing Taskfile.yml")
        if not isinstance(data.get("tasks") or [], list):
            errors.append(f"{name}: tasks must be a list")

    print("KLM validation")
    print(f"Environment: {env_dir.name}")
    print()

    if errors:
        print("Errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("Validation passed.")


def status_cmd(args) -> None:
    print("KLM status")
    print("----------")
    print(f"KLM_HOME: {klm_home()}")
    try:
        env_dir = current_env_dir()
        print(f"Current environment: {env_dir.name}")
        print(f"Current path: {env_dir}")
    except SystemExit:
        print("Current environment: not set")
    print(f"Core path: {Path(__file__).resolve().parents[1]}")


def bundle_list_cmd(args) -> None:
    env_dir = current_env_dir()
    print("Bundles")
    print(f"Environment: {env_dir.name}")
    print()
    for manifest_path in bundle_manifests():
        data = load_yaml(manifest_path)
        meta = data.get("metadata") or {}
        name = meta.get("name") or manifest_path.parent.name
        display = meta.get("displayName") or name
        version = meta.get("version") or ""
        print(f"  - {display}" + (f" ({version})" if version else ""))
        print(f"    name: {name}")
        print(f"    path: {manifest_path.parent}")
        print()


def bundle_add_cmd(args) -> None:
    env_dir = current_env_dir()
    name = unpack_bundle(Path(args.archive).resolve(), env_dir / "bundles")
    print(f"Added bundle: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="klm")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init")
    p.add_argument("--config", required=True)
    p.add_argument("--name", dest="env_name")
    p.add_argument("--bundle-root")
    p.set_defaults(func=init_cmd)

    p = sub.add_parser("menu")
    p.set_defaults(func=menu_cmd)

    p = sub.add_parser("tasks")
    p.set_defaults(func=print_tasks)

    p = sub.add_parser("run")
    p.add_argument("task")
    p.set_defaults(func=run_cmd)

    p = sub.add_parser("plan")
    p.set_defaults(func=plan_cmd)

    p = sub.add_parser("apply")
    p.set_defaults(func=apply_cmd)

    p = sub.add_parser("validate")
    p.set_defaults(func=validate_cmd)

    p = sub.add_parser("status")
    p.set_defaults(func=status_cmd)

    env = sub.add_parser("env")
    env_sub = env.add_subparsers(dest="env_command")
    p = env_sub.add_parser("current")
    p.set_defaults(func=env_current)
    p = env_sub.add_parser("list")
    p.set_defaults(func=env_list)
    p = env_sub.add_parser("use")
    p.add_argument("name")
    p.set_defaults(func=env_use)

    bundle = sub.add_parser("bundle")
    bundle_sub = bundle.add_subparsers(dest="bundle_command")
    p = bundle_sub.add_parser("list")
    p.set_defaults(func=bundle_list_cmd)
    p = bundle_sub.add_parser("add")
    p.add_argument("archive")
    p.set_defaults(func=bundle_add_cmd)

    args = parser.parse_args()

    if not args.command:
        args = parser.parse_args(["menu"])

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)
