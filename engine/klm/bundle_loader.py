"""Discover and load KLM bundles from /opt/openspace/bundles."""

import logging
import os
from dataclasses import dataclass, field

import yaml

LOG = logging.getLogger(__name__)

BUNDLE_FILE_NAME = "bundle.yml"
SEMAPHORE_FILE_NAME = "semaphore.yml"

RESOURCE_KEYS = (
    "repositories",
    "inventories",
    "views",
    "templates",
    "workflows",
)

ALLOWED_SEMAPHORE_KEYS = RESOURCE_KEYS + ("systems",)


class BundleError(Exception):
    """Raised when an installed bundle is malformed."""


@dataclass(frozen=True)
class BundleRequirement:
    name: str
    version: str


@dataclass(frozen=True)
class BundleSystem:
    name: str
    enabled: bool = True
    description: str = ""
    requires: tuple = ()


@dataclass
class Bundle:
    name: str
    version: str
    bundle_type: str
    description: str
    enabled: bool
    requires: list = field(default_factory=list)
    systems: list = field(default_factory=list)
    directory: str = ""
    metadata_file: str = ""
    semaphore_file: str = ""
    metadata: dict = field(default_factory=dict)
    semaphore: dict = field(default_factory=dict)

    def enabled_systems(self):
        return [system for system in self.systems if system.enabled]


def discover_bundles(bundle_dir):
    """
    Discover installed bundles.

    Absence is meaningful: if a bundle directory is removed, it is no longer
    part of desired state and KLM will prune resources that it owns for it.

    Incomplete bundles fail closed. A directory containing only bundle.yml or
    only semaphore.yml is treated as a broken install and reconciliation stops
    before any Semaphore changes are made.
    """
    if not os.path.isdir(bundle_dir):
        raise BundleError("Bundle directory does not exist: %s" % bundle_dir)

    bundles = []

    for entry_name in sorted(os.listdir(bundle_dir)):
        if entry_name.startswith("."):
            continue

        directory = os.path.join(bundle_dir, entry_name)
        if not os.path.isdir(directory):
            continue

        metadata_file = os.path.join(directory, BUNDLE_FILE_NAME)
        semaphore_file = os.path.join(directory, SEMAPHORE_FILE_NAME)

        has_metadata = os.path.isfile(metadata_file)
        has_semaphore = os.path.isfile(semaphore_file)

        if not has_metadata and not has_semaphore:
            LOG.debug("Skipping %s: not a KLM bundle directory", entry_name)
            continue

        if has_metadata != has_semaphore:
            missing = SEMAPHORE_FILE_NAME if has_metadata else BUNDLE_FILE_NAME
            raise BundleError(
                "Bundle directory '%s' is incomplete: missing %s"
                % (directory, missing)
            )

        bundles.append(load_bundle(directory, entry_name))

    bundles.sort(key=lambda item: item.name.lower())
    _check_duplicate_bundle_names(bundles)
    return bundles


def load_bundle(directory, directory_name):
    metadata_file = os.path.join(directory, BUNDLE_FILE_NAME)
    semaphore_file = os.path.join(directory, SEMAPHORE_FILE_NAME)

    metadata = _load_yaml_mapping(metadata_file)
    semaphore = _load_yaml_mapping(semaphore_file)

    name = _required_string(metadata, "name", metadata_file)
    version = _required_string(metadata, "version", metadata_file)
    bundle_type = _required_string(metadata, "type", metadata_file)
    description = str(metadata.get("description", ""))

    enabled = metadata.get("enabled", True)
    if not isinstance(enabled, bool):
        raise BundleError("%s: 'enabled' must be true or false" % metadata_file)

    requires = _load_requirements(metadata.get("requires", []), metadata_file)
    systems = _load_systems(metadata.get("systems", []), metadata_file)

    if systems and bundle_type != "environment":
        raise BundleError(
            "%s: 'systems' is only valid for bundles with type: environment"
            % metadata_file
        )

    if name != directory_name:
        raise BundleError(
            "%s: bundle name '%s' must match directory name '%s'"
            % (metadata_file, name, directory_name)
        )

    for key in semaphore:
        if key not in ALLOWED_SEMAPHORE_KEYS:
            raise BundleError(
                "%s: unknown top-level key '%s'. Allowed: %s"
                % (semaphore_file, key, ", ".join(ALLOWED_SEMAPHORE_KEYS))
            )

    for field_name in RESOURCE_KEYS:
        _require_list_of_mappings(
            semaphore.get(field_name, []),
            field_name,
            semaphore_file,
        )

    _validate_semaphore_systems(
        semaphore.get("systems", {}),
        systems,
        semaphore_file,
    )

    return Bundle(
        name=name,
        version=version,
        bundle_type=bundle_type,
        description=description,
        enabled=enabled,
        requires=requires,
        systems=systems,
        directory=directory,
        metadata_file=metadata_file,
        semaphore_file=semaphore_file,
        metadata=metadata,
        semaphore=semaphore,
    )


def _load_requirements(value, location):
    if value is None:
        return []

    if not isinstance(value, list):
        raise BundleError("%s: 'requires' must be a list" % location)

    result = []
    seen = set()

    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise BundleError("%s: requires[%d] must be a mapping" % (location, index))

        unknown = [key for key in raw if key not in ("name", "version")]
        if unknown:
            raise BundleError(
                "%s: requires[%d] has unknown key(s): %s"
                % (location, index, ", ".join(sorted(unknown)))
            )

        name = _required_string(raw, "name", "%s requires[%d]" % (location, index))
        version = _required_string(raw, "version", "%s requires[%d]" % (location, index))

        if name in seen:
            raise BundleError("%s: duplicate requirement for bundle '%s'" % (location, name))
        seen.add(name)

        result.append(BundleRequirement(name=name, version=version))

    return result


def _load_systems(value, location):
    if value is None:
        return []

    if not isinstance(value, list):
        raise BundleError("%s: 'systems' must be a list" % location)

    result = []
    seen = set()

    for index, raw in enumerate(value):
        item_location = "%s systems[%d]" % (location, index)

        if not isinstance(raw, dict):
            raise BundleError("%s must be a mapping" % item_location)

        unknown = [
            key for key in raw
            if key not in ("name", "enabled", "description", "requires")
        ]
        if unknown:
            raise BundleError(
                "%s has unknown key(s): %s"
                % (item_location, ", ".join(sorted(unknown)))
            )

        name = _required_string(raw, "name", item_location)
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise BundleError("%s: 'enabled' must be true or false" % item_location)

        if name in seen:
            raise BundleError("%s: duplicate system '%s'" % (location, name))
        seen.add(name)

        result.append(
            BundleSystem(
                name=name,
                enabled=enabled,
                description=str(raw.get("description", "")),
                requires=tuple(_load_requirements(raw.get("requires", []), item_location)),
            )
        )

    return result


def _validate_semaphore_systems(value, declared_systems, location):
    if value is None:
        value = {}

    if not isinstance(value, dict):
        raise BundleError("%s: 'systems' must be a mapping" % location)

    declared_names = {system.name for system in declared_systems}

    for system_name, section in value.items():
        if system_name not in declared_names:
            raise BundleError(
                "%s: Semaphore system '%s' is not declared in bundle.yml systems"
                % (location, system_name)
            )

        if not isinstance(section, dict):
            raise BundleError(
                "%s: systems.%s must be a mapping"
                % (location, system_name)
            )

        for key in section:
            if key not in RESOURCE_KEYS:
                raise BundleError(
                    "%s: systems.%s has unknown key '%s'. Allowed: %s"
                    % (location, system_name, key, ", ".join(RESOURCE_KEYS))
                )

        for field_name in RESOURCE_KEYS:
            _require_list_of_mappings(
                section.get(field_name, []),
                "systems.%s.%s" % (system_name, field_name),
                location,
            )


def _check_duplicate_bundle_names(bundles):
    seen = {}
    for bundle in bundles:
        if bundle.name in seen:
            raise BundleError(
                "Bundles '%s' and '%s' both declare name '%s'"
                % (seen[bundle.name], bundle.directory, bundle.name)
            )
        seen[bundle.name] = bundle.directory


def _load_yaml_mapping(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except yaml.YAMLError as error:
        raise BundleError("%s is not valid YAML: %s" % (path, error))
    except OSError as error:
        raise BundleError("Could not read %s: %s" % (path, error))

    if document is None:
        return {}
    if not isinstance(document, dict):
        raise BundleError("%s must contain a YAML mapping" % path)
    return document


def _required_string(mapping, key, location):
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BundleError("%s: '%s' must be a non-empty string" % (location, key))
    return value.strip()


def _require_list_of_mappings(value, field_name, location):
    if not isinstance(value, list):
        raise BundleError("%s: '%s' must be a list" % (location, field_name))
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise BundleError(
                "%s: '%s[%d]' must be a mapping" % (location, field_name, index)
            )
