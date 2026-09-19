"""Reconcile KLM-owned Semaphore repositories."""

import logging

from client import DRY_RUN_ID
from errors import ReconcileError

LOG = logging.getLogger(__name__)

MANAGED_FIELDS = ("name", "git_url", "git_branch", "ssh_key_id")


def sync_repositories(client, desired_repositories, state):
    existing = client.list_repositories()
    ids_by_name = {}

    if not desired_repositories:
        return ids_by_name

    none_key_id = client.find_key_id("None")

    for desired in desired_repositories:
        resource_id = _sync_one(
            client,
            desired,
            existing,
            none_key_id,
            state,
        )
        ids_by_name[desired.name] = resource_id

    client.clear_lookup_cache()
    return ids_by_name


def _sync_one(client, desired, existing, none_key_id, state):
    owned_id = state.get_id("repositories", desired.state_key)
    current = None

    if owned_id is not None:
        current = _find_by_id(existing, owned_id)
        if current is None:
            LOG.warning(
                "Repository '%s' id %s disappeared; recreating",
                desired.state_key,
                owned_id,
            )
            state.forget("repositories", desired.state_key)

    if current is None:
        conflict = _find_by_name(existing, desired.name)
        if conflict is not None:
            raise ReconcileError(
                "Semaphore repository '%s' already exists with id %s, "
                "but KLM does not own it"
                % (desired.name, conflict.get("id"))
            )

        payload = _payload(client, desired, none_key_id)
        LOG.info("Creating repository '%s'", desired.name)
        created = client.create_repository(payload)
        resource_id = _created_id(created, desired.name)

        if resource_id != DRY_RUN_ID:
            state.record("repositories", desired.state_key, resource_id)

        return resource_id

    payload = _payload(client, desired, none_key_id)

    if _changed(current, payload):
        payload["id"] = current["id"]
        LOG.info("Updating repository '%s'", desired.name)
        client.update_repository(current["id"], payload)

    return current["id"]


def prune_repositories(client, state, wanted_state_keys):
    for state_key in state.to_prune("repositories", wanted_state_keys):
        resource_id = state.get_id("repositories", state_key)
        LOG.info(
            "Pruning KLM-owned repository '%s' (id %s)",
            state_key,
            resource_id,
        )
        client.delete_repository(resource_id)
        state.forget("repositories", state_key)


def _payload(client, desired, none_key_id):
    return {
        "project_id": client.project_id,
        "name": desired.name,
        "git_url": desired.semaphore_url,
        "git_branch": desired.branch,
        "ssh_key_id": none_key_id,
    }


def _normalize(value):
    if value in (None, False, 0, "", [], {}):
        return None
    return value


def _changed(existing, payload):
    return any(
        _normalize(existing.get(field)) != _normalize(payload.get(field))
        for field in MANAGED_FIELDS
    )


def _find_by_id(items, resource_id):
    return next(
        (item for item in items if item.get("id") == resource_id),
        None,
    )


def _find_by_name(items, name):
    matches = [
        item
        for item in items
        if item.get("name") == name
    ]

    if len(matches) > 1:
        raise ReconcileError(
            "More than one Semaphore repository named '%s' exists" % name
        )

    return matches[0] if matches else None


def _created_id(created, name):
    if isinstance(created, dict) and "id" in created:
        return created["id"]

    raise ReconcileError(
        "Semaphore did not return an id after creating repository '%s'" % name
    )
