"""Reconcile KLM-owned Semaphore inventories."""

import logging

from client import DRY_RUN_ID
from errors import ReconcileError

LOG = logging.getLogger(__name__)

MANAGED_FIELDS = (
    "name",
    "inventory",
    "type",
    "ssh_key_id",
    "become_key_id",
    "repository_id",
)


def sync_inventories(client, desired_inventories, repository_ids, state):
    existing = client.list_inventories()
    ids_by_name = {}

    for desired in desired_inventories:
        resource_id = _sync_one(
            client,
            desired,
            existing,
            repository_ids,
            state,
        )
        ids_by_name[desired.name] = resource_id

    client.clear_lookup_cache()
    return ids_by_name


def _sync_one(client, desired, existing, repository_ids, state):
    owned_id = state.get_id("inventories", desired.state_key)
    current = None

    if owned_id is not None:
        current = _find_by_id(existing, owned_id)

        if current is None:
            LOG.warning(
                "Inventory '%s' id %s disappeared; recreating",
                desired.state_key,
                owned_id,
            )
            state.forget("inventories", desired.state_key)

    if current is None:
        conflict = _find_by_name(existing, desired.name)

        if conflict is not None:
            raise ReconcileError(
                "Semaphore inventory '%s' already exists with id %s, "
                "but KLM does not own it"
                % (desired.name, conflict.get("id"))
            )

        payload = _payload(
            client,
            desired,
            repository_ids,
        )

        LOG.info("Creating inventory '%s'", desired.name)
        created = client.create_inventory(payload)
        resource_id = _created_id(created, desired.name)

        if resource_id != DRY_RUN_ID:
            state.record("inventories", desired.state_key, resource_id)

        return resource_id

    payload = _payload(
        client,
        desired,
        repository_ids,
    )

    if _changed(current, payload):
        payload["id"] = current["id"]
        LOG.info("Updating inventory '%s'", desired.name)
        client.update_inventory(current["id"], payload)

    return current["id"]


def prune_inventories(client, state, wanted_state_keys):
    for state_key in state.to_prune("inventories", wanted_state_keys):
        resource_id = state.get_id("inventories", state_key)
        LOG.info(
            "Pruning KLM-owned inventory '%s' (id %s)",
            state_key,
            resource_id,
        )
        client.delete_inventory(resource_id)
        state.forget("inventories", state_key)


def _payload(client, desired, repository_ids):
    repository_id = None

    if desired.repository_name:
        repository_id = repository_ids.get(desired.repository_name)

        if repository_id is None:
            repository_id = client.find_repository_id(
                desired.repository_name
            )

    ssh_key_id = _resolve_ssh_key_id(
        client,
        desired.ssh_key_name,
    )

    become_key_id = _resolve_become_key_id(
        client,
        desired.become_key_name,
    )

    return {
        "project_id": client.project_id,
        "name": desired.name,
        "inventory": desired.inventory,
        "type": desired.inventory_type,
        "ssh_key_id": ssh_key_id,
        "become_key_id": become_key_id,
        "repository_id": repository_id,
    }


def _resolve_ssh_key_id(client, key_name):
    # KLM never creates credentials. SSH user credentials remain operator-owned
    # in Semaphore Key Store. Username/password (login_password) and SSH-key
    # entries are both valid for an inventory SSH credential.
    key = client.find_key(key_name or "None")
    key_type = key.get("type")

    if key_type not in ("none", "login_password", "ssh"):
        raise ReconcileError(
            "Key Store entry '%s' has type '%s'; inventory SSH credentials "
            "must be Login with Password or SSH Key"
            % (key.get("name"), key_type)
        )

    return key["id"]


def _resolve_become_key_id(client, key_name):
    # Semaphore 2.19.12 uses a Login with Password entry as Ansible's become
    # credential. The login becomes --become-user and the password is supplied
    # through --ask-become-pass. For `su`, set ansible_become_method: su in the
    # inventory and use `become: true` in the play/task that needs elevation.
    key = client.find_key(key_name or "None")
    key_type = key.get("type")

    if key_type not in ("none", "login_password"):
        raise ReconcileError(
            "Key Store entry '%s' has type '%s'; inventory become credentials "
            "must be Login with Password"
            % (key.get("name"), key_type)
        )

    return key["id"]


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
            "More than one Semaphore inventory named '%s' exists" % name
        )

    return matches[0] if matches else None


def _created_id(created, name):
    if isinstance(created, dict) and "id" in created:
        return created["id"]

    raise ReconcileError(
        "Semaphore did not return an id after creating inventory '%s'" % name
    )
