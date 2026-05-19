#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


def die(message: str, code: int = 1):
    print(f"[klm][ERROR] {message}", file=sys.stderr)
    sys.exit(code)


def run_capture(cmd, cwd=None, env=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def choose(title: str, options: list[str]) -> str:
    while True:
        print()
        print(title)
        print("=" * len(title))

        for index, option in enumerate(options, start=1):
            print(f"{index}) {option}")

        print("q) Quit")

        choice = input("\nSelect option: ").strip()

        if choice.lower() in {"q", "quit", "exit"}:
            sys.exit(0)

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(options):
                return options[index - 1]

        print("[klm] Invalid selection")


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        die(f"Missing required environment variable: {name}")
    return value


def discover_bundles(bundles_dir: Path) -> list[Path]:
    if not bundles_dir.exists():
        die(f"Bundles directory not found: {bundles_dir}")

    bundles = []

    for path in bundles_dir.iterdir():
        if not path.is_dir():
            continue

        if (path / "Taskfile.yml").exists():
            bundles.append(path)

    return sorted(bundles, key=lambda p: p.name.lower())


def build_runtime_env(env_dir: Path, bundles_dir: Path) -> dict:
    env = os.environ.copy()

    path_entries = []

    for bundle in bundles_dir.iterdir():
        if not bundle.is_dir():
            continue

        bundle_bin = bundle / "bin"
        if bundle_bin.exists():
            path_entries.append(str(bundle_bin))

    current_path = env.get("PATH", "")
    env["PATH"] = ":".join(path_entries + [current_path])

    env["KLM_ENV_DIR"] = str(env_dir)
    env["KLM_BUNDLES_DIR"] = str(bundles_dir)

    return env


def get_bundle_tasks(bundle_dir: Path, env: dict) -> list[dict]:
    taskfile = bundle_dir / "Taskfile.yml"

    result = run_capture(
        [
            "task",
            "--taskfile",
            str(taskfile),
            "--dir",
            str(bundle_dir),
            "--list",
        ],
        cwd=bundle_dir,
        env=env,
    )

    if result.returncode != 0:
        return []

    tasks = []

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()

        if not line.startswith("* "):
            continue

        line = line[2:].strip()

        if ":" in line:
            task_name, desc = line.split(":", 1)
        else:
            task_name = line
            desc = ""

        task_name = task_name.strip()
        desc = desc.strip()

        if not task_name:
            continue

        tasks.append(
            {
                "bundle": bundle_dir.name,
                "task": task_name,
                "desc": desc,
                "bundle_dir": bundle_dir,
                "taskfile": taskfile,
            }
        )

    return tasks


def build_task_menu(bundles_dir: Path, env: dict) -> list[dict]:
    all_tasks = []

    for bundle in discover_bundles(bundles_dir):
        all_tasks.extend(get_bundle_tasks(bundle, env))

    return all_tasks


def run_task(task: dict, env: dict) -> int:
    cmd = [
        "task",
        "--taskfile",
        str(task["taskfile"]),
        "--dir",
        str(task["bundle_dir"]),
        task["task"],
    ]

    print()
    print(f"[klm] Running {task['bundle']}:{task['task']}")
    print(f"[klm] Bundle: {task['bundle_dir']}")
    print()

    return subprocess.run(cmd, env=env).returncode


def direct_task_from_args(args: list[str], tasks: list[dict]) -> dict | None:
    if not args:
        return None

    requested = args[0]

    for task in tasks:
        full_name = f"{task['bundle']}:{task['task']}"

        if requested == full_name:
            return task

    for task in tasks:
        if requested == task["task"]:
            return task

    die(f"Task not found: {requested}")


def main():
    env_name = get_required_env("KLM_ENV_NAME")
    env_dir = Path(get_required_env("KLM_ENV_DIR"))
    bundles_dir = Path(get_required_env("KLM_BUNDLES_DIR"))

    runtime_env = build_runtime_env(env_dir, bundles_dir)

    tasks = build_task_menu(bundles_dir, runtime_env)

    if not tasks:
        die(f"No runnable tasks found in {bundles_dir}")

    selected_direct = direct_task_from_args(sys.argv[1:], tasks)

    if selected_direct:
        sys.exit(run_task(selected_direct, runtime_env))

    while True:
        labels = []

        for task in tasks:
            label = f"{task['bundle']}:{task['task']}"
            if task["desc"]:
                label += f" - {task['desc']}"
            labels.append(label)

        selected_label = choose(f"KLM Tasks for {env_name}", labels)
        selected_task = tasks[labels.index(selected_label)]

        rc = run_task(selected_task, runtime_env)

        print()
        print(f"[klm] Exit code: {rc}")

        again = input("\nReturn to task menu? [Y/n]: ").strip().lower()
        if again in {"n", "no"}:
            sys.exit(rc)


if __name__ == "__main__":
    main()