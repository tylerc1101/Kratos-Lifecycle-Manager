"""Reconcile KLM-owned Semaphore task templates."""

import json
import logging

from client import DRY_RUN_ID
from errors import ReconcileError

LOG = logging.getLogger(__name__)

MANAGED_FIELDS = (
    "name", "description", "playbook", "app", "git_branch", "arguments",
    "allow_override_args_in_task", "allow_override_branch_in_task",
    "allow_parallel_tasks", "suppress_success_alerts", "inventory_id",
    "repository_id", "environment_ids", "view_id", "survey_vars", "vaults",
    "task_params", "type", "autorun",
)


def resolve_template_inventories(
    client,
    desired_templates,
    desired_inventories,
    state,
    environment_bundle=None,
    selected_system=None,
):
    """Resolve and validate template inventories before child mutations.

    Only Ansible templates require an inventory. Other Semaphore apps may
    omit inventory entirely.

    Resolution order for an Ansible template that omits ``inventory``:

    1. If an environment/system is selected and that system defines exactly
       one KLM-managed inventory, use it.
    2. Without an environment, if desired state defines exactly one managed
       inventory, use it.
    3. Otherwise, if exactly one operator-created Semaphore inventory exists,
       use it.
    4. Never guess when more than one candidate exists.

    Explicit inventory names may point either to a desired KLM-managed
    inventory or to an operator-created Semaphore inventory. KLM does not adopt
    or prune operator-created inventories.
    """
    if not desired_templates:
        return

    desired_by_name = {item.name: item for item in desired_inventories}
    live_inventories = client.list_inventories()

    # Anything recorded in ownership state belongs to KLM. If it is no longer
    # part of desired state, it may be pruned later and must not become the
    # implicit operator default.
    owned_ids = {
        resource_id
        for resource_id in state.inventories.values()
        if resource_id is not None
    }
    operator_inventories = [
        item
        for item in live_inventories
        if item.get("id") not in owned_ids
    ]

    _validate_explicit_inventory_references(
        desired_templates,
        desired_by_name,
        operator_inventories,
    )

    # Semaphore requires an inventory for Ansible templates. Other apps
    # (bash, python, terraform, etc.) can legitimately run without one.
    unresolved = [
        item
        for item in desired_templates
        if item.app == "ansible" and not item.inventory_name
    ]
    if not unresolved:
        return

    default_name = ""
    default_reason = ""

    if environment_bundle is not None and selected_system is not None:
        system_inventories = [
            item
            for item in desired_inventories
            if item.bundle_name == environment_bundle.name
            and item.system_name == selected_system.name
        ]

        if len(system_inventories) == 1:
            default_name = system_inventories[0].name
            default_reason = "selected environment/system"
        elif len(system_inventories) > 1:
            names = ", ".join(sorted(item.name for item in system_inventories))
            raise ReconcileError(
                "Selected environment '%s' system '%s' defines more than one "
                "inventory (%s), so KLM cannot choose a default for templates "
                "that omit inventory. Set inventory explicitly on those "
                "templates."
                % (environment_bundle.name, selected_system.name, names)
            )
    else:
        if len(desired_inventories) == 1:
            default_name = desired_inventories[0].name
            default_reason = "single KLM-managed inventory"
        elif len(desired_inventories) > 1:
            names = ", ".join(sorted(item.name for item in desired_inventories))
            raise ReconcileError(
                "No environment is selected and desired state defines more "
                "than one inventory (%s). KLM cannot choose a default for "
                "templates that omit inventory. Set inventory explicitly on "
                "those templates or select an environment/system." % names
            )

    if not default_name:
        if len(operator_inventories) == 1:
            default_name = str(operator_inventories[0].get("name") or "").strip()
            if not default_name:
                raise ReconcileError(
                    "The only operator-created Semaphore inventory has no name"
                )
            default_reason = "single operator-created Semaphore inventory"
        elif len(operator_inventories) == 0:
            names = ", ".join(
                sorted("%s / %s" % (item.view_name, item.name) for item in unresolved)
            )
            raise ReconcileError(
                "Templates without an inventory cannot be reconciled because "
                "no default inventory is available. Affected templates: %s. "
                "Create one inventory in Semaphore, set inventory explicitly "
                "in the bundle, or select an environment/system that defines "
                "an inventory." % names
            )
        else:
            choices = ", ".join(
                "%s (id %s)" % (item.get("name", ""), item.get("id"))
                for item in sorted(
                    operator_inventories,
                    key=lambda item: str(item.get("name", "")).lower(),
                )
            )
            raise ReconcileError(
                "More than one operator-created Semaphore inventory exists "
                "(%s), so KLM cannot choose a default for templates that omit "
                "inventory. Set inventory explicitly in the bundle or select "
                "an environment/system." % choices
            )

    for item in unresolved:
        item.inventory_name = default_name

    LOG.info(
        "Default inventory for templates without one: %s (%s)",
        default_name,
        default_reason,
    )


def _validate_explicit_inventory_references(
    desired_templates,
    desired_by_name,
    operator_inventories,
):
    by_name = {}
    for item in operator_inventories:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        by_name.setdefault(name, []).append(item)

    for template in desired_templates:
        name = template.inventory_name
        if not name or name in desired_by_name:
            continue

        matches = by_name.get(name, [])
        if len(matches) == 1:
            continue

        if not matches:
            available = ", ".join(sorted(by_name)) or "(none)"
            raise ReconcileError(
                "Template '%s / %s' references inventory '%s', but no desired "
                "KLM inventory or operator-created Semaphore inventory with "
                "that name exists. Operator inventories: %s"
                % (template.view_name, template.name, name, available)
            )

        ids = ", ".join(str(item.get("id")) for item in matches)
        raise ReconcileError(
            "Template '%s / %s' references inventory '%s', but more than one "
            "operator-created Semaphore inventory has that name (ids: %s)"
            % (template.view_name, template.name, name, ids)
        )


def sync_templates(client, desired_templates, repository_ids, inventory_ids,
                   view_ids, state):
    existing = client.list_templates()
    ids_by_state_key = {}

    for desired in desired_templates:
        repo_id = repository_ids[desired.repository_name]
        view_id = view_ids[desired.view_name]
        inventory_id = _resolve_inventory_id(
            client,
            desired.inventory_name,
            inventory_ids,
        )

        dependency_ids = [repo_id, view_id]
        if inventory_id is not None:
            dependency_ids.append(inventory_id)

        if DRY_RUN_ID in dependency_ids:
            LOG.info(
                "[dry-run] Would reconcile template '%s / %s' after its dependencies are created",
                desired.view_name,
                desired.name,
            )
            ids_by_state_key[desired.state_key] = DRY_RUN_ID
            continue

        template_id = _sync_one(
            client, desired, repo_id, inventory_id, view_id, existing, state
        )
        ids_by_state_key[desired.state_key] = template_id

    return ids_by_state_key


def _resolve_inventory_id(client, inventory_name, inventory_ids):
    """
    Resolve a template inventory without claiming ownership of operator data.

    - If an enabled bundle defines the inventory, use the KLM-managed ID.
    - If a name is supplied but no bundle defines it, resolve an existing
      Semaphore inventory by name and leave it operator-owned.
    - Inventory omission must already have been resolved by preflight.
    """
    if not inventory_name:
        return None

    managed_id = inventory_ids.get(inventory_name)
    if managed_id is not None:
        return managed_id

    return client.find_inventory_id(inventory_name)


def _sync_one(client, desired, repo_id, inventory_id, view_id, existing, state):
    desired_fields = _build_managed_fields(
        client, desired, repo_id, inventory_id, view_id
    )

    owned_id = state.get_id("templates", desired.state_key)
    current = None

    if owned_id is not None:
        summary = next((item for item in existing if item.get("id") == owned_id), None)
        if summary is not None:
            current = client.get_template(owned_id)
        else:
            LOG.warning("Template '%s' id %s disappeared; recreating", desired.state_key, owned_id)
            state.forget("templates", desired.state_key)

    if current is None:
        matches = [
            item for item in existing
            if item.get("name") == desired.name and item.get("view_id") == view_id
        ]
        if len(matches) > 1:
            raise ReconcileError(
                "More than one Semaphore template '%s / %s' exists"
                % (desired.view_name, desired.name)
            )
        if matches:
            raise ReconcileError(
                "Semaphore template '%s / %s' already exists with id %s, but KLM does not own it"
                % (desired.view_name, desired.name, matches[0].get("id"))
            )

        payload = dict(desired_fields)
        payload["project_id"] = client.project_id
        LOG.info("Creating template '%s / %s'", desired.view_name, desired.name)
        created = client.create_template(payload)
        template_id = _created_id(created, desired.name)
        if template_id != DRY_RUN_ID:
            state.record("templates", desired.state_key, template_id)
        return template_id

    changed = _find_changed_fields(current, desired_fields)
    if changed:
        payload = dict(desired_fields)
        payload["id"] = current["id"]
        payload["project_id"] = client.project_id
        payload["vaults"] = _carry_over_vault_ids(
            current.get("vaults") or [], desired_fields["vaults"], current["id"]
        )
        LOG.info(
            "Updating template '%s': changed fields: %s",
            desired.state_key,
            ", ".join(changed),
        )
        client.update_template(current["id"], payload)

    return current["id"]


def _build_managed_fields(client, desired, repo_id, inventory_id, view_id):
    environment_ids = []
    if desired.environment_name:
        environment_ids = [client.find_environment_id(desired.environment_name)]

    return {
        "name": desired.name,
        "description": desired.description,
        "playbook": desired.playbook,
        "app": desired.app,
        "git_branch": desired.git_branch or None,
        "arguments": json.dumps(desired.arguments),
        "allow_override_args_in_task": desired.allow_override_args_in_task,
        "allow_override_branch_in_task": desired.allow_override_branch_in_task,
        "allow_parallel_tasks": desired.allow_parallel_tasks,
        "suppress_success_alerts": desired.suppress_success_alerts,
        "repository_id": repo_id,
        "inventory_id": inventory_id,
        "environment_ids": environment_ids,
        "view_id": view_id,
        "survey_vars": _build_survey_vars(desired),
        "vaults": _build_vaults(client, desired),
        "task_params": desired.task_params,
        "type": desired.template_type,
        "autorun": desired.autorun,
    }


def _build_survey_vars(desired):
    return [
        {
            "name": item.name,
            "title": item.title,
            "description": item.description,
            "type": item.var_type,
            "required": item.required,
            "default_value": item.default_value,
            "values": item.values,
        }
        for item in desired.survey_vars
    ]


def _build_vaults(client, desired):
    result = []
    for item in desired.vaults:
        result.append({
            "vault_key_id": client.find_key_id(item.key_store_name),
            "name": item.vault_name,
            "type": item.vault_type,
            "script": item.script or None,
        })
    return result


def _find_changed_fields(existing, desired):
    changed = []
    for field in MANAGED_FIELDS:
        left = existing.get(field)
        right = desired.get(field)
        if field == "arguments":
            left = _normalize_arguments(left)
            right = _normalize_arguments(right)
        elif field == "survey_vars":
            left = _normalize_survey_vars(left)
            right = _normalize_survey_vars(right)
        elif field == "vaults":
            left = _normalize_vaults(left)
            right = _normalize_vaults(right)
        else:
            left = _normalize(left)
            right = _normalize(right)
        if left != right:
            changed.append(field)
    return changed


def _normalize(value):
    if value in (None, False, 0, "", [], {}):
        return None
    return value


def _normalize_arguments(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [value]
    return parsed if isinstance(parsed, list) else [parsed]


def _normalize_survey_vars(items):
    if not items:
        return []
    normalized = []
    for item in items:
        values = []
        for option in item.get("values") or []:
            if isinstance(option, dict):
                values.append((str(option.get("name", "")), str(option.get("value", ""))))
            else:
                values.append((str(option), str(option)))
        normalized.append((
            str(item.get("name", "")), str(item.get("title", "")),
            str(item.get("description", "")), str(item.get("type", "")),
            bool(item.get("required", False)), str(item.get("default_value", "")),
            tuple(values),
        ))
    normalized.sort()
    return normalized


def _normalize_vaults(items):
    if not items:
        return []
    result = [
        (
            item.get("vault_key_id"), str(item.get("name") or ""),
            str(item.get("type") or "password"), str(item.get("script") or ""),
        )
        for item in items
    ]
    result.sort(key=lambda item: (item[0] or 0, item[1]))
    return result


def _carry_over_vault_ids(existing_vaults, desired_vaults, template_id):
    existing_by_key = {
        (item.get("vault_key_id"), item.get("name") or ""): item
        for item in existing_vaults
    }
    result = []
    for desired in desired_vaults:
        item = dict(desired)
        item["template_id"] = template_id
        old = existing_by_key.get((desired.get("vault_key_id"), desired.get("name") or ""))
        if old is not None and old.get("id") is not None:
            item["id"] = old["id"]
        result.append(item)
    return result


def prune_templates(client, state, wanted_state_keys):
    for state_key in state.to_prune("templates", wanted_state_keys):
        resource_id = state.get_id("templates", state_key)
        LOG.info("Pruning KLM-owned template '%s' (id %s)", state_key, resource_id)
        client.delete_template(resource_id)
        state.forget("templates", state_key)


def _created_id(created, name):
    if isinstance(created, dict) and "id" in created:
        return created["id"]
    raise ReconcileError("Semaphore did not return an id after creating template '%s'" % name)
