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

ALLOWED_SEMAPHORE_KEYS = RESOURCE_KEYS + ("profiles", "systems")
ALLOWED_BUNDLE_TYPES = ("capability", "architecture", "environment")


class BundleError(Exception):
    """Raised when an installed bundle is malformed."""


@dataclass(frozen=True)
class BundleRequirement:
    name: str
    version: str


@dataclass(frozen=True)
class BundleProfile:
    name: str
    description: str = ""
    requires: tuple = ()


@dataclass(frozen=True)
class BundleSystem:
    name: str
    enabled: bool = True
    description: str = ""
    profile: str = ""
    requires: tuple = ()


@dataclass
class Bundle:
    name: str
    version: str
    bundle_type: str
    description: str
    enabled: bool
    requires: list = field(default_factory=list)
    profiles: list = field(default_factory=list)
    systems: list = field(default_factory=list)
    directory: str = ""
    metadata_file: str = ""
    semaphore_file: str = ""
    metadata: dict = field(default_factory=dict)
    semaphore: dict = field(default_factory=dict)

    def enabled_systems(self):
        return [system for system in self.systems if system.enabled]

    def get_profile(self, name):
        if not name:
            return None
        return next((item for item in self.profiles if item.name == name), None)


def discover_bundles(bundle_dir):
    """Discover and validate installed bundles."""
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
    bundle_type = _required_string(metadata, "type", metadata_file).lower()
    description = str(metadata.get("description", ""))

    if bundle_type not in ALLOWED_BUNDLE_TYPES:
        raise BundleError(
            "%s: unsupported bundle type '%s'. Allowed: %s"
            % (metadata_file, bundle_type, ", ".join(ALLOWED_BUNDLE_TYPES))
        )

    enabled = metadata.get("enabled", True)
    if not isinstance(enabled, bool):
        raise BundleError("%s: 'enabled' must be true or false" % metadata_file)

    requires = _load_requirements(metadata.get("requires", []), metadata_file)
    profiles = _load_profiles(metadata.get("profiles", []), metadata_file)
    systems = _load_systems(metadata.get("systems", []), metadata_file)

    if (profiles or systems) and bundle_type != "environment":
        raise BundleError(
            "%s: 'profiles' and 'systems' are only valid for type: environment"
            % metadata_file
        )

    _validate_system_profile_references(systems, profiles, metadata_file)

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

    _validate_semaphore_profiles(
        semaphore.get("profiles", {}),
        profiles,
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
        profiles=profiles,
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


def _load_profiles(value, location):
    if value is None:
        return []

    if not isinstance(value, list):
        raise BundleError("%s: 'profiles' must be a list" % location)

    result = []
    seen = set()

    for index, raw in enumerate(value):
        item_location = "%s profiles[%d]" % (location, index)

        if not isinstance(raw, dict):
            raise BundleError("%s must be a mapping" % item_location)

        unknown = [
            key for key in raw
            if key not in ("name", "description", "requires")
        ]
        if unknown:
            raise BundleError(
                "%s has unknown key(s): %s"
                % (item_location, ", ".join(sorted(unknown)))
            )

        name = _required_string(raw, "name", item_location)
        if name in seen:
            raise BundleError("%s: duplicate profile '%s'" % (location, name))
        seen.add(name)

        result.append(
            BundleProfile(
                name=name,
                description=str(raw.get("description", "")),
                requires=tuple(_load_requirements(raw.get("requires", []), item_location)),
            )
        )

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
            if key not in ("name", "enabled", "description", "profile", "requires")
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

        profile = str(raw.get("profile", "")).strip()

        if name in seen:
            raise BundleError("%s: duplicate system '%s'" % (location, name))
        seen.add(name)

        result.append(
            BundleSystem(
                name=name,
                enabled=enabled,
                description=str(raw.get("description", "")),
                profile=profile,
                requires=tuple(_load_requirements(raw.get("requires", []), item_location)),
            )
        )

    return result


def _validate_system_profile_references(systems, profiles, location):
    profile_names = {profile.name for profile in profiles}

    for system in systems:
        if system.profile and system.profile not in profile_names:
            raise BundleError(
                "%s: system '%s' references unknown profile '%s'"
                % (location, system.name, system.profile)
            )


def _validate_resource_sections(value, declared_names, section_label, location):
    if value is None:
        value = {}

    if not isinstance(value, dict):
        raise BundleError("%s: '%s' must be a mapping" % (location, section_label))

    for item_name, section in value.items():
        if item_name not in declared_names:
            raise BundleError(
                "%s: Semaphore %s '%s' is not declared in bundle.yml"
                % (location, section_label[:-1], item_name)
            )

        if not isinstance(section, dict):
            raise BundleError(
                "%s: %s.%s must be a mapping"
                % (location, section_label, item_name)
            )

        for key in section:
            if key not in RESOURCE_KEYS:
                raise BundleError(
                    "%s: %s.%s has unknown key '%s'. Allowed: %s"
                    % (
                        location,
                        section_label,
                        item_name,
                        key,
                        ", ".join(RESOURCE_KEYS),
                    )
                )

        for field_name in RESOURCE_KEYS:
            _require_list_of_mappings(
                section.get(field_name, []),
                "%s.%s.%s" % (section_label, item_name, field_name),
                location,
            )


def _validate_semaphore_profiles(value, declared_profiles, location):
    _validate_resource_sections(
        value,
        {profile.name for profile in declared_profiles},
        "profiles",
        location,
    )


def _validate_semaphore_systems(value, declared_systems, location):
    _validate_resource_sections(
        value,
        {system.name for system in declared_systems},
        "systems",
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
