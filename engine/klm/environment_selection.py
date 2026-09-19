"""Environment bundle discovery and active system selection."""

import os
from dataclasses import dataclass

import yaml

import bundle_loader


class EnvironmentSelectionError(Exception):
    """Raised when an environment/system selection is invalid."""


@dataclass(frozen=True)
class EnvironmentSelection:
    environment: str
    system: str


def discover_environment_bundles(environment_dir):
    bundles = bundle_loader.discover_bundles(environment_dir)

    for bundle in bundles:
        if bundle.bundle_type != "environment":
            raise EnvironmentSelectionError(
                "Environment directory contains non-environment bundle '%s' (type: %s)"
                % (bundle.name, bundle.bundle_type)
            )

    return bundles


def validate_environment_path(path):
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise EnvironmentSelectionError(
            "Environment bundle path does not exist: %s" % path
        )

    bundle = bundle_loader.load_bundle(path, os.path.basename(path))
    if bundle.bundle_type != "environment":
        raise EnvironmentSelectionError(
            "Bundle '%s' has type '%s'; bundle path must have type: environment"
            % (bundle.name, bundle.bundle_type)
        )
    return bundle


def find_system(environment_bundles, requested_system):
    requested = requested_system.strip().lower()
    matches = []

    for bundle in environment_bundles:
        if not bundle.enabled:
            continue
        for system in bundle.systems:
            if system.name.lower() == requested:
                matches.append((bundle, system))

    if not matches:
        available = []
        for bundle in environment_bundles:
            if not bundle.enabled:
                continue
            for system in bundle.systems:
                available.append("%s/%s" % (bundle.name, system.name))

        message = "No installed environment defines system '%s'." % requested_system
        if available:
            message += " Available systems: %s" % ", ".join(sorted(available))
        raise EnvironmentSelectionError(message)

    if len(matches) > 1:
        owners = ["%s/%s" % (bundle.name, system.name) for bundle, system in matches]
        raise EnvironmentSelectionError(
            "System '%s' is defined by more than one installed environment: %s"
            % (requested_system, ", ".join(sorted(owners)))
        )

    bundle, system = matches[0]
    if not system.enabled:
        raise EnvironmentSelectionError(
            "System '%s' in environment '%s' is disabled"
            % (system.name, bundle.name)
        )

    return bundle, system


def save_selection(path, bundle_name, system_name):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_path = path + ".tmp"
    document = {
        "environment": bundle_name,
        "system": system_name,
    }

    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(document, handle, default_flow_style=False, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except OSError as error:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        raise EnvironmentSelectionError(
            "Could not save environment selection %s: %s" % (path, error)
        ) from error


def clear_selection(path):
    """Clear the active environment/system selection if one exists."""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError as error:
        raise EnvironmentSelectionError(
            "Could not clear environment selection %s: %s" % (path, error)
        ) from error


def load_selection(path, required=False):
    if not os.path.isfile(path):
        if required:
            raise EnvironmentSelectionError(
                "No system is selected. Run: klm env <system>"
            )
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as error:
        raise EnvironmentSelectionError(
            "Could not read environment selection %s: %s" % (path, error)
        ) from error

    environment = str(document.get("environment", "")).strip()
    system = str(document.get("system", "")).strip()
    if not environment or not system:
        raise EnvironmentSelectionError(
            "Environment selection %s is invalid" % path
        )

    return EnvironmentSelection(environment=environment, system=system)


def resolve_selection(environment_dir, selection_file, required=False):
    selection = load_selection(selection_file, required=required)
    if selection is None:
        return None, None

    bundles = discover_environment_bundles(environment_dir)
    bundle = next(
        (item for item in bundles if item.name == selection.environment),
        None,
    )
    if bundle is None:
        raise EnvironmentSelectionError(
            "Selected environment '%s' is not installed in %s"
            % (selection.environment, environment_dir)
        )

    system = next(
        (item for item in bundle.systems if item.name == selection.system),
        None,
    )
    if system is None:
        raise EnvironmentSelectionError(
            "Selected system '%s' no longer exists in environment '%s'"
            % (selection.system, bundle.name)
        )
    if not bundle.enabled:
        raise EnvironmentSelectionError(
            "Selected environment '%s' is disabled" % bundle.name
        )
    if not system.enabled:
        raise EnvironmentSelectionError(
            "Selected system '%s' in environment '%s' is disabled"
            % (system.name, bundle.name)
        )

    return bundle, system
