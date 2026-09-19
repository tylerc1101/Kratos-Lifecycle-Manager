#!/usr/bin/env python3
"""KLM engine CLI: bundle validation and Semaphore reconciliation."""

import argparse
import logging
import os
import sys

import bundle_loader
import desired_state
import environment_selection
import inventories
import projects
import repositories
import settings as settings_module
import state as state_module
import templates
import views
import workflows
from client import DRY_RUN_ID, SemaphoreApiError, SemaphoreClient
from errors import ReconcileError

KLM_VERSION = "1.2.3"
LOG = logging.getLogger("klm")


def main():
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(getattr(args, "log_level", "INFO"))

    try:
        return args.func(args)
    except (
        bundle_loader.BundleError,
        desired_state.DesiredStateError,
        environment_selection.EnvironmentSelectionError,
        settings_module.SettingsError,
        state_module.StateError,
        SemaphoreApiError,
        ReconcileError,
    ) as error:
        LOG.error("%s", error)
        return 1


def command_version(_args):
    print("KLM Engine %s" % KLM_VERSION)
    return 0


def command_bundles_list(args):
    bundle_dir = args.bundle_dir or os.environ.get(
        "KLM_BUNDLE_DIR",
        settings_module.DEFAULT_BUNDLE_DIR,
    )
    environment_dir = os.environ.get(
        "KLM_ENVIRONMENT_DIR",
        settings_module.DEFAULT_ENVIRONMENT_DIR,
    )

    bundles = bundle_loader.discover_bundles(bundle_dir)
    environments = environment_selection.discover_environment_bundles(
        environment_dir
    )
    installed = sorted(
        bundles + environments,
        key=lambda item: item.name.lower(),
    )

    if not installed:
        print("No bundles installed.")
        return 0

    print("%-20s %-10s %-13s %s" % ("NAME", "VERSION", "TYPE", "STATUS"))

    for bundle in installed:
        enabled = "enabled" if bundle.enabled else "disabled"
        print(
            "%-20s %-10s %-13s %s"
            % (
                bundle.name,
                bundle.version,
                bundle.bundle_type,
                enabled,
            )
        )

        for index, system in enumerate(bundle.systems):
            system_state = "enabled" if system.enabled else "disabled"
            branch = "└─" if index == len(bundle.systems) - 1 else "├─"
            print("  %s %-36s %s" % (branch, system.name, system_state))

    return 0


def command_bundles_validate(args):
    bundle_dir = args.bundle_dir or os.environ.get(
        "KLM_BUNDLE_DIR",
        settings_module.DEFAULT_BUNDLE_DIR,
    )

    project_name = os.environ.get(
        "KLM_PROJECT_NAME",
        settings_module.DEFAULT_PROJECT_NAME,
    ).strip()

    bundles = bundle_loader.discover_bundles(bundle_dir)
    env_dir = os.environ.get(
        "KLM_ENVIRONMENT_DIR",
        settings_module.DEFAULT_ENVIRONMENT_DIR,
    )
    selection_file = os.environ.get(
        "KLM_ENVIRONMENT_SELECTION_FILE",
        settings_module.DEFAULT_ENVIRONMENT_SELECTION_FILE,
    )
    environments = environment_selection.discover_environment_bundles(env_dir)
    environment_bundle, selected_system = environment_selection.resolve_selection(
        env_dir, selection_file, required=False
    )
    wanted = desired_state.build_desired_state(
        bundles,
        project_name=project_name,
        environment_bundle=environment_bundle,
        selected_system=selected_system,
    )

    print("Bundle validation successful.")
    print("Project:      %s" % wanted.project.name)
    installed = bundles + environments
    print("Installed:    %d" % len(installed))
    print(
        "Enabled:      %d"
        % len([item for item in installed if item.enabled])
    )
    if environment_bundle is not None:
        print("Environment:  %s" % environment_bundle.name)
        print("System:       %s" % selected_system.name)
    else:
        print("Environment:  none selected")
    if environment_bundle is not None:
        print(
            "Systems:      1 selected / %d declared"
            % len(environment_bundle.systems)
        )
    else:
        print("Systems:      none selected")
    print("Repositories: %d" % len(wanted.repositories))
    print("Inventories:  %d" % len(wanted.inventories))
    print("Views:        %d" % len(wanted.views))
    print("Templates:    %d" % len(wanted.templates))
    print("Workflows:    %d" % len(wanted.workflows))
    print("View order:")

    for view in sorted(
        wanted.views,
        key=lambda item: item.position,
    ):
        print("  %3d  %s" % (view.position, view.name))

    return 0


def command_doctor(_args):
    settings = settings_module.load_settings()
    bundles = bundle_loader.discover_bundles(
        settings.bundle_dir
    )
    environment_bundle, selected_system = environment_selection.resolve_selection(
        settings.environment_dir,
        settings.environment_selection_file,
        required=False,
    )
    wanted = desired_state.build_desired_state(
        bundles,
        project_name=settings.project_name,
        environment_bundle=environment_bundle,
        selected_system=selected_system,
    )

    client = _client(settings)
    client.authenticate()
    pong = client.ping()

    print("KLM Engine Doctor")
    print("OK  Bundle directory: %s" % settings.bundle_dir)
    print(
        "OK  Enabled bundles:  %d"
        % len([item for item in bundles if item.enabled])
    )
    print("OK  Desired project:  %s" % wanted.project.name)
    if environment_bundle is not None:
        print("OK  Environment:      %s / %s" % (environment_bundle.name, selected_system.name))
    else:
        print("OK  Environment:      none selected")
    print(
        "OK  Semaphore API:    %s"
        % (pong or "reachable")
    )

    return 0


def command_env(args):
    environment_dir = os.environ.get(
        "KLM_ENVIRONMENT_DIR",
        settings_module.DEFAULT_ENVIRONMENT_DIR,
    )
    selection_file = os.environ.get(
        "KLM_ENVIRONMENT_SELECTION_FILE",
        settings_module.DEFAULT_ENVIRONMENT_SELECTION_FILE,
    )
    bundle_dir = os.environ.get(
        "KLM_BUNDLE_DIR",
        settings_module.DEFAULT_BUNDLE_DIR,
    )
    project_name = os.environ.get(
        "KLM_PROJECT_NAME",
        settings_module.DEFAULT_PROJECT_NAME,
    ).strip()

    requested_system = str(args.system or "").strip()

    if requested_system.lower() == "clear":
        previous = environment_selection.load_selection(
            selection_file, required=False
        )
        if previous is None:
            print("Environment selection is already clear.")
            return 0

        environment_selection.clear_selection(selection_file)
        print("Environment selection cleared.")
        print("Previous: %s / %s" % (previous.environment, previous.system))
        return 0

    environments = environment_selection.discover_environment_bundles(
        environment_dir
    )

    if not requested_system:
        current = environment_selection.load_selection(
            selection_file, required=False
        )
        if current is None:
            print("Selected environment: none")
        else:
            print(
                "Selected environment: %s / %s"
                % (current.environment, current.system)
            )

        print("Available systems:")
        if not environments:
            print("  None")
            return 0

        for bundle in environments:
            for system in bundle.systems:
                state = "enabled" if system.enabled else "disabled"
                print(
                    "  %-20s %-20s %s"
                    % (bundle.name, system.name, state)
                )
        return 0

    environment_bundle, selected_system = environment_selection.find_system(
        environments, requested_system
    )

    # Validate the complete dependency graph and every cross-bundle reference
    # before recording the selection. This makes a missing BaseKit/Onboarder/
    # OpenSpace dependency obvious before reconcile can touch Semaphore.
    bundles = bundle_loader.discover_bundles(bundle_dir)
    wanted = desired_state.build_desired_state(
        bundles,
        project_name=project_name,
        environment_bundle=environment_bundle,
        selected_system=selected_system,
    )

    environment_selection.save_selection(
        selection_file,
        environment_bundle.name,
        selected_system.name,
    )

    print("Environment selected.")
    print("Environment: %s" % environment_bundle.name)
    print("System:      %s" % selected_system.name)
    print("Dependencies and cross-bundle references validated.")

    requirements = _required_key_stores(wanted)
    print()
    print("Required Semaphore Key Store entries:")
    if not requirements:
        print("  None")
    else:
        for name, requirement in requirements:
            print("  %s" % name)
            print("      Type:    %s" % requirement["type"])
            print("      Purpose: %s" % ", ".join(requirement["purposes"]))

        print()
        print("Before running 'klm reconcile':")
        print("  1. Log in to Semaphore.")
        print("  2. Open project '%s'." % project_name)
        print("  3. Open Key Store.")
        print("  4. Create the Key Store entries listed above.")

    print()
    print("Then run:")
    print("  klm reconcile")
    return 0


def command_bundle_validate_path(args):
    """Validate one extracted bundle and emit machine-readable metadata."""
    path = os.path.abspath(args.path)
    if not os.path.isdir(path):
        raise bundle_loader.BundleError(
            "Bundle path does not exist: %s" % path
        )

    bundle = bundle_loader.load_bundle(path, os.path.basename(path))
    print("%s\t%s\t%s" % (bundle.name, bundle.version, bundle.bundle_type))
    return 0



def command_env_validate_path(args):
    bundle = environment_selection.validate_environment_path(args.path)
    print("Environment bundle validation successful.")
    print("Name:    %s" % bundle.name)
    print("Version: %s" % bundle.version)
    print("Systems:")
    for system in bundle.systems:
        print("  %s" % system.name)
    return 0



def command_ensure_project(_args):
    """Ensure the installation-level Semaphore project exists.

    This command is used by the host-side `klm start` flow.  The KLM project is
    foundation state rather than bundle state, so an existing project with the
    configured installation name is accepted and recorded as KLM-owned.  Child
    resources are still subject to normal ownership rules during reconcile.
    """
    settings = settings_module.load_settings()
    settings.dry_run = False

    ownership = state_module.load_state(settings.state_file)
    client = _client(settings)
    client.authenticate()

    matches = [
        project
        for project in client.list_projects()
        if project.get("name") == settings.project_name
    ]

    if len(matches) > 1:
        raise ReconcileError(
            "More than one Semaphore project named '%s' exists"
            % settings.project_name
        )

    if matches:
        project_id = matches[0].get("id")
        if not project_id:
            raise ReconcileError(
                "Semaphore project '%s' does not have an id"
                % settings.project_name
            )
        ownership.record("projects", settings.project_name, project_id)
        state_module.save_state(settings.state_file, ownership, dry_run=False)
        print("Semaphore project '%s' already exists." % settings.project_name)
        return 0

    created = client.create_project({"name": settings.project_name, "demo": False})
    if not isinstance(created, dict) or not created.get("id"):
        raise ReconcileError(
            "Semaphore did not return an id after creating project '%s'"
            % settings.project_name
        )

    project_id = created["id"]
    ownership.record("projects", settings.project_name, project_id)
    state_module.save_state(settings.state_file, ownership, dry_run=False)
    print("Semaphore project '%s' created." % settings.project_name)
    return 0


def _required_key_stores(wanted):
    """Return human-readable Key Store requirements for the desired state."""
    requirements = {}

    def add(name, key_type, purpose):
        name = str(name or "").strip()
        if not name:
            return
        item = requirements.setdefault(
            name,
            {"type": key_type, "purposes": []},
        )
        if item["type"] != key_type:
            item["type"] = "Key Store entry"
        if purpose not in item["purposes"]:
            item["purposes"].append(purpose)

    for inventory in wanted.inventories:
        add(
            inventory.ssh_key_name,
            "Login with Password",
            "Ansible SSH authentication",
        )
        add(
            inventory.become_key_name,
            "Login with Password",
            "Ansible privilege escalation",
        )

    for template in wanted.templates:
        for vault in template.vaults:
            add(
                vault.key_store_name,
                "Key Store entry",
                "Ansible Vault for template '%s'" % template.name,
            )

    return sorted(requirements.items(), key=lambda item: item[0].lower())

def command_reconcile(args):
    settings = settings_module.load_settings()

    if args.bundle_dir:
        settings.bundle_dir = args.bundle_dir

    if args.dry_run:
        settings.dry_run = True

    # Everything under bundles is discovered and validated before the first
    # Semaphore API mutation. A removed bundle is a valid desired-state change;
    # an incomplete/malformed bundle is a hard error and prevents pruning.
    bundles = bundle_loader.discover_bundles(
        settings.bundle_dir
    )
    environment_bundle, selected_system = environment_selection.resolve_selection(
        settings.environment_dir,
        settings.environment_selection_file,
        required=False,
    )
    wanted = desired_state.build_desired_state(
        bundles,
        project_name=settings.project_name,
        environment_bundle=environment_bundle,
        selected_system=selected_system,
    )
    ownership = state_module.load_state(
        settings.state_file
    )

    LOG.info(
        "Desired state: project=%s repositories=%d inventories=%d "
        "views=%d templates=%d workflows=%d",
        wanted.project.name,
        len(wanted.repositories),
        len(wanted.inventories),
        len(wanted.views),
        len(wanted.templates),
        len(wanted.workflows),
    )
    if environment_bundle is not None:
        LOG.info(
            "Selected environment: %s / %s",
            environment_bundle.name,
            selected_system.name,
        )

    if settings.dry_run:
        LOG.info("Running in dry-run mode")

    client = _client(settings)
    client.authenticate()

    try:
        project_id = projects.sync_project(
            client,
            wanted.project,
            ownership,
        )
        _checkpoint(settings, ownership)

        if project_id == DRY_RUN_ID:
            LOG.info(
                "[dry-run] Project does not exist yet; child resources "
                "would be created after project creation"
            )
            _log_initial_children(wanted)
            return 0

        client.set_project_id(project_id)

        # Resolve every template inventory before any child resources are
        # created or updated. Reusable templates inherit the selected system's
        # single inventory. Without an environment, one unambiguous operator-
        # created Semaphore inventory may act as the default. KLM never guesses
        # when more than one candidate exists.
        templates.resolve_template_inventories(
            client,
            wanted.templates,
            wanted.inventories,
            ownership,
            environment_bundle=environment_bundle,
            selected_system=selected_system,
        )

        repository_ids = repositories.sync_repositories(
            client,
            wanted.repositories,
            ownership,
        )
        _checkpoint(settings, ownership)

        inventory_ids = inventories.sync_inventories(
            client,
            wanted.inventories,
            repository_ids,
            ownership,
        )
        _checkpoint(settings, ownership)

        view_ids = views.sync_views(
            client,
            wanted.views,
            ownership,
        )
        _checkpoint(settings, ownership)

        template_ids = templates.sync_templates(
            client,
            wanted.templates,
            repository_ids,
            inventory_ids,
            view_ids,
            ownership,
        )
        _checkpoint(settings, ownership)

        workflows.sync_workflows(
            client,
            wanted.workflows,
            template_ids,
            ownership,
        )
        _checkpoint(settings, ownership)

        # Automatic convergence is intentional. If an installed bundle is
        # removed or disabled, resources that KLM owns for it are removed.
        # Operator-created resources are never in ownership state and are not
        # pruned.
        workflows.prune_workflows(
            client,
            ownership,
            [item.state_key for item in wanted.workflows],
        )
        _checkpoint(settings, ownership)

        templates.prune_templates(
            client,
            ownership,
            [item.state_key for item in wanted.templates],
        )
        _checkpoint(settings, ownership)

        views.prune_views(
            client,
            ownership,
            [item.state_key for item in wanted.views],
        )
        _checkpoint(settings, ownership)

        inventories.prune_inventories(
            client,
            ownership,
            [item.state_key for item in wanted.inventories],
        )
        _checkpoint(settings, ownership)

        repositories.prune_repositories(
            client,
            ownership,
            [item.state_key for item in wanted.repositories],
        )
        _checkpoint(settings, ownership)

        LOG.info("Reconcile complete")
        return 0

    finally:
        # Sync functions record/forget ownership immediately after each
        # successful API mutation. Saving here makes a partially successful
        # reconcile recoverable if a later resource fails.
        state_module.save_state(
            settings.state_file,
            ownership,
            dry_run=settings.dry_run,
        )


def _checkpoint(settings, ownership):
    if settings.dry_run:
        return

    state_module.save_state(
        settings.state_file,
        ownership,
        dry_run=False,
    )


def _client(settings):
    return SemaphoreClient(
        base_url=settings.base_url,
        api_token=settings.api_token,
        username=settings.username,
        password=settings.password,
        timeout_seconds=settings.timeout_seconds,
        verify_tls=settings.verify_tls,
        dry_run=settings.dry_run,
    )


def _log_initial_children(wanted):
    for item in wanted.repositories:
        LOG.info(
            "[dry-run] Would create repository '%s'",
            item.name,
        )

    for item in wanted.inventories:
        LOG.info(
            "[dry-run] Would create inventory '%s'",
            item.name,
        )

    for item in wanted.views:
        LOG.info(
            "[dry-run] Would create view '%s' at position %d",
            item.name,
            item.position,
        )

    for item in wanted.templates:
        LOG.info(
            "[dry-run] Would create template '%s / %s'",
            item.view_name,
            item.name,
        )

    for item in wanted.workflows:
        LOG.info(
            "[dry-run] Would create workflow '%s'",
            item.live_name,
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Kratos Lifecycle Manager engine",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=(
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
        ),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    version = sub.add_parser(
        "version",
        help="Show KLM engine version",
    )
    version.set_defaults(
        func=command_version,
    )

    doctor = sub.add_parser(
        "doctor",
        help="Validate KLM and Semaphore connectivity",
    )
    doctor.set_defaults(
        func=command_doctor,
    )

    bundles = sub.add_parser(
        "bundles",
        help="Bundle commands",
    )
    bundle_sub = bundles.add_subparsers(
        dest="bundle_command",
        required=True,
    )

    bundle_list = bundle_sub.add_parser(
        "list",
        help="List installed bundles",
    )
    bundle_list.add_argument(
        "--bundle-dir",
        default="",
    )
    bundle_list.set_defaults(
        func=command_bundles_list,
    )

    bundle_validate = bundle_sub.add_parser(
        "validate",
        help="Validate all installed bundles",
    )
    bundle_validate.add_argument(
        "--bundle-dir",
        default="",
    )
    bundle_validate.set_defaults(
        func=command_bundles_validate,
    )

    bundle_validate_path = sub.add_parser(
        "bundle-validate-path",
        help=argparse.SUPPRESS,
    )
    bundle_validate_path.add_argument("path")
    bundle_validate_path.set_defaults(
        func=command_bundle_validate_path,
    )

    env = sub.add_parser(
        "env",
        help="Show or select the active environment system",
    )
    env.add_argument(
        "system",
        nargs="?",
        default="",
        help="System to select, for example: SKCT2, or 'clear' to clear selection",
    )
    env.set_defaults(
        func=command_env,
    )

    env_validate = sub.add_parser(
        "env-validate-path",
        help=argparse.SUPPRESS,
    )
    env_validate.add_argument("path")
    env_validate.set_defaults(
        func=command_env_validate_path,
    )

    ensure_project = sub.add_parser(
        "ensure-project",
        help=argparse.SUPPRESS,
    )
    ensure_project.set_defaults(
        func=command_ensure_project,
    )

    reconcile = sub.add_parser(
        "reconcile",
        help="Reconcile installed bundles into Semaphore",
    )
    reconcile.add_argument(
        "--dry-run",
        action="store_true",
    )
    reconcile.add_argument(
        "--bundle-dir",
        default="",
    )
    reconcile.set_defaults(
        func=command_reconcile,
    )

    return parser


def configure_logging(level):
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":
    sys.exit(main())
