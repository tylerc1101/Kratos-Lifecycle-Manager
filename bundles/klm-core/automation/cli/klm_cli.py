#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path


def die(message, code=1):
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


def choose(title, options):
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


def get_required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        die(f"Missing required environment variable: {name}")
    return value


def discover_bundles(bundles_dir):
    if not bundles_dir.exists():
        die(f"Bundles directory not found: {bundles_dir}")

    return sorted(
        [
            path
            for path in bundles_dir.iterdir()
            if path.is_dir() and (path / "Taskfile.yml").exists()
        ],
        key=lambda p: p.name.lower(),
    )


def build_runtime_env(env_dir, bundles_dir):
    env = os.environ.copy()

    path_entries = []

    for bundle in bundles_dir.iterdir():
        if not bundle.is_dir():
            continue

        bundle_bin = bundle / "bin"
        if bundle_bin.exists():
            path_entries.append(str(bundle_bin))

    env["PATH"] = ":".join(path_entries + [env.get("PATH", "")])
    env["KLM_ENV_DIR"] = str(env_dir)
    env["KLM_BUNDLES_DIR"] = str(bundles_dir)

    return env


def get_bundle_tasks(bundle_dir, env):
    taskfile = bundle_dir / "Taskfile.yml"

    result = run_capture(
        [
            "task",
            "--taskfile",
            str(taskfile),
            "--dir",
            str(bundle_dir),
            "--json",
            "--list-all",
        ],
        cwd=bundle_dir,
        env=env,
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return []

    try:
        data = json.loads(result.stdout)
    except Exception as exc:
        print(f"[klm][WARN] Failed to parse task JSON for {bundle_dir.name}: {exc}", file=sys.stderr)
        return []

    tasks = []

    for item in data.get("tasks", []):
        task_name = str(item.get("name", "")).strip()
        desc = str(item.get("desc", "") or "").strip()

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


def build_task_menu(bundles_dir, env):
    all_tasks = []

    for bundle in discover_bundles(bundles_dir):
        all_tasks.extend(get_bundle_tasks(bundle, env))

    return all_tasks


def run_task(task, env):
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


def direct_task_from_args(args, tasks):
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
        indexed_tasks = []
        counter = 1

        print()
        print(f"KLM Tasks for {env_name}")
        print("=" * (14 + len(env_name)))

        current_bundle = None

        for task in tasks:
            if task["bundle"] != current_bundle:
                current_bundle = task["bundle"]
                print()
                print(current_bundle)
                print("=" * len(current_bundle))

            desc = f" - {task['desc']}" if task["desc"] else ""
            print(f"{counter}) {task['task']}{desc}")

            indexed_tasks.append(task)
            counter += 1

        print()
        print("q) Quit")

        choice = input("\nSelect task: ").strip()

        if choice.lower() in {"q", "quit", "exit"}:
            sys.exit(0)

        if not choice.isdigit():
            print("[klm] Invalid selection")
            continue

        selected_index = int(choice)

        if selected_index < 1 or selected_index > len(indexed_tasks):
            print("[klm] Invalid selection")
            continue

        selected_task = indexed_tasks[selected_index - 1]

        rc = run_task(selected_task, runtime_env)

        print()
        print(f"[klm] Exit code: {rc}")

        again = input("\nReturn to task menu? [Y/n]: ").strip().lower()

        if again in {"n", "no"}:
            sys.exit(rc)


if __name__ == "__main__":
    main()
