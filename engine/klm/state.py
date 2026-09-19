"""Persistent KLM ownership state used for safe update/prune behavior."""

import json
import logging
import os
import time

LOG = logging.getLogger(__name__)
STATE_VERSION = 2
STATE_FILE_MODE = 0o600


class StateError(Exception):
    pass


class OwnershipState:
    def __init__(
        self,
        projects=None,
        repositories=None,
        inventories=None,
        views=None,
        templates=None,
        workflows=None,
    ):
        self.projects = dict(projects or {})
        self.repositories = dict(repositories or {})
        self.inventories = dict(inventories or {})
        self.views = dict(views or {})
        self.templates = dict(templates or {})
        self.workflows = dict(workflows or {})

    def _group(self, name):
        return getattr(self, name)

    def get_id(self, group, key):
        return self._group(group).get(key)

    def record(self, group, key, resource_id):
        self._group(group)[key] = resource_id

    def forget(self, group, key):
        self._group(group).pop(key, None)

    def to_prune(self, group, wanted_keys):
        wanted = set(wanted_keys)
        return [
            key
            for key in sorted(self._group(group))
            if key not in wanted
        ]

    def to_dict(self):
        return {
            "version": STATE_VERSION,
            "updated_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            ),
            "projects": self.projects,
            "repositories": self.repositories,
            "inventories": self.inventories,
            "views": self.views,
            "templates": self.templates,
            "workflows": self.workflows,
        }


def load_state(path):
    if not os.path.isfile(path):
        LOG.info("No ownership state at %s yet", path)
        return OwnershipState()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as error:
        raise StateError(
            "Could not read ownership state %s: %s"
            % (path, error)
        )

    version = document.get("version")

    if version != STATE_VERSION:
        raise StateError(
            "Ownership state %s has version %s; this engine expects version %d."
            % (path, version, STATE_VERSION)
        )

    return OwnershipState(
        projects=document.get("projects", {}),
        repositories=document.get("repositories", {}),
        inventories=document.get("inventories", {}),
        views=document.get("views", {}),
        templates=document.get("templates", {}),
        workflows=document.get("workflows", {}),
    )


def save_state(path, state, dry_run=False):
    if dry_run:
        LOG.info(
            "[dry-run] Would save ownership state to %s",
            path,
        )
        return

    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    temporary = path + ".tmp"

    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(
            state.to_dict(),
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.chmod(temporary, STATE_FILE_MODE)
    os.replace(temporary, path)

    LOG.info(
        "Saved ownership state to %s",
        path,
    )
