"""Reconcile the single Semaphore project used by installed KLM bundles."""

import logging

from client import DRY_RUN_ID
from errors import ReconcileError

LOG = logging.getLogger(__name__)


def sync_project(client, desired, state):
    existing_projects = client.list_projects()
    state_key = desired.name
    owned_id = state.get_id("projects", state_key)

    if owned_id is not None:
        for project in existing_projects:
            if project.get("id") == owned_id:
                if project.get("name") != desired.name:
                    raise ReconcileError(
                        "KLM-owned project id %s is now named '%s', expected '%s'"
                        % (owned_id, project.get("name"), desired.name)
                    )
                return owned_id

        LOG.warning("KLM-owned project id %s no longer exists; recreating", owned_id)
        state.forget("projects", state_key)

    for project in existing_projects:
        if project.get("name") == desired.name:
            raise ReconcileError(
                "Semaphore project '%s' already exists with id %s, but KLM does not own it"
                % (desired.name, project.get("id"))
            )

    LOG.info("Creating project '%s'", desired.name)
    created = client.create_project({"name": desired.name, "demo": False})
    project_id = _created_id(created, "project", desired.name)

    if project_id != DRY_RUN_ID:
        state.record("projects", state_key, project_id)

    return project_id


def _created_id(created, label, name):
    if isinstance(created, dict) and "id" in created:
        return created["id"]
    raise ReconcileError("Semaphore did not return an id after creating %s '%s'" % (label, name))
