"""Reconcile KLM-owned Semaphore task-template views."""

import logging

from client import DRY_RUN_ID
from errors import ReconcileError

LOG = logging.getLogger(__name__)


def sync_views(client, desired_views, state):
    existing = client.list_views()
    ids_by_name = {}

    for desired in sorted(desired_views, key=lambda item: item.position):
        resource_id = _sync_one(client, desired, existing, state)
        ids_by_name[desired.name] = resource_id

    return ids_by_name


def _sync_one(client, desired, existing, state):
    owned_id = state.get_id("views", desired.state_key)
    current = None

    if owned_id is not None:
        current = next((item for item in existing if item.get("id") == owned_id), None)
        if current is None:
            LOG.warning("View '%s' id %s disappeared; recreating", desired.state_key, owned_id)
            state.forget("views", desired.state_key)

    if current is None:
        matches = [item for item in existing if item.get("title") == desired.name]
        if len(matches) > 1:
            raise ReconcileError("More than one Semaphore view titled '%s' exists" % desired.name)
        if matches:
            raise ReconcileError(
                "Semaphore view '%s' already exists with id %s, but KLM does not own it"
                % (desired.name, matches[0].get("id"))
            )

        payload = {
            "project_id": client.project_id,
            "title": desired.name,
            "position": desired.position,
        }
        LOG.info("Creating view '%s' at position %d", desired.name, desired.position)
        created = client.create_view(payload)
        resource_id = _created_id(created, desired.name)
        if resource_id != DRY_RUN_ID:
            state.record("views", desired.state_key, resource_id)
        return resource_id

    if current.get("title") != desired.name or current.get("position") != desired.position:
        payload = {
            "id": current["id"],
            "project_id": client.project_id,
            "title": desired.name,
            "position": desired.position,
            "type": current.get("type", ""),
            "hidden": current.get("hidden", False),
        }
        LOG.info("Updating view '%s' to position %d", desired.name, desired.position)
        client.update_view(current["id"], payload)

    return current["id"]


def prune_views(client, state, wanted_state_keys):
    for state_key in state.to_prune("views", wanted_state_keys):
        resource_id = state.get_id("views", state_key)
        LOG.info("Pruning KLM-owned view '%s' (id %s)", state_key, resource_id)
        client.delete_view(resource_id)
        state.forget("views", state_key)


def _created_id(created, name):
    if isinstance(created, dict) and "id" in created:
        return created["id"]
    raise ReconcileError("Semaphore did not return an id after creating view '%s'" % name)
