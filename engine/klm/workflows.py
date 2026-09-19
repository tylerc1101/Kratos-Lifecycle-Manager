"""
Reconcile Semaphore 2.19.12 workflows.

Bundle authors use friendly node IDs, but Semaphore stores numeric IDs.
Friendly IDs exist only in bundle YAML. They are NOT sent as a fake "name"
field because Semaphore 2.19.12 workflow nodes do not have one.

Semaphore 2.19.12 fields used here:
    kind
    template_id
    convergence_mode
    approval_timeout
    approval_message
    task_params
    note
    position_x
    position_y

Edge fields:
    source_node_id
    destination_node_id
    condition

Supported node kinds in 2.19.12:
    task
    approval
    note
"""

import logging

from client import DRY_RUN_ID
from errors import ReconcileError

LOG = logging.getLogger(__name__)

LAYOUT_X_START = 80
LAYOUT_Y_START = 80
LAYOUT_X_SPACING = 300
LAYOUT_Y_SPACING = 160


def sync_workflows(client, desired_workflows, template_ids_by_state_key, state):
    existing_workflows = client.list_workflows()

    for desired in desired_workflows:
        _sync_one_workflow(
            client,
            desired,
            template_ids_by_state_key,
            existing_workflows,
            state,
        )


def _sync_one_workflow(
    client,
    desired,
    template_ids_by_state_key,
    existing_workflows,
    state,
):
    existing = _find_existing_workflow(
        client,
        desired,
        existing_workflows,
        state,
    )

    positions = _calculate_positions(desired)

    nodes = _build_nodes(
        desired,
        template_ids_by_state_key,
        positions,
    )

    if nodes is None:
        LOG.warning(
            "Skipping workflow '%s': task templates do not have real IDs "
            "during dry-run creation.",
            desired.live_name,
        )
        return

    edges = _build_edges(
        desired,
        nodes,
    )

    payload = {
        "project_id": client.project_id,
        "name": desired.live_name,
        "description": desired.description,
        "nodes": nodes,
        "edges": edges,
    }

    if desired.start_version:
        payload["start_version"] = desired.start_version

    if existing is None:
        _create_workflow(
            client,
            desired,
            payload,
            state,
        )
        return

    _update_workflow_if_changed(
        client,
        desired,
        payload,
        existing,
    )


def _find_existing_workflow(client, desired, existing_workflows, state):
    owned_id = state.get_id("workflows", desired.state_key)

    if owned_id is not None:
        for workflow in existing_workflows:
            if workflow.get("id") == owned_id:
                return client.get_workflow(owned_id)

        LOG.warning(
            "Workflow '%s' (id %d) is in KLM state but no longer exists. "
            "Recreating it.",
            desired.state_key,
            owned_id,
        )

        state.forget("workflows", desired.state_key)
        return None

    for workflow in existing_workflows:
        if workflow.get("name") == desired.live_name:
            raise ReconcileError(
                "Semaphore workflow '%s' already exists with id %s, but "
                "KLM does not own it. Rename/remove the existing workflow "
                "or explicitly add it to KLM ownership state before reconciling."
                % (
                    desired.live_name,
                    workflow.get("id"),
                )
            )

    return None


def _calculate_positions(desired):
    levels = _calculate_levels(desired)
    nodes_at_level = {}

    for node in desired.nodes:
        level = levels[node.local_id]
        nodes_at_level.setdefault(level, []).append(node.local_id)

    positions = {}

    for level in sorted(nodes_at_level.keys()):
        for row, local_id in enumerate(nodes_at_level[level]):
            positions[local_id] = (
                LAYOUT_X_START + (level * LAYOUT_X_SPACING),
                LAYOUT_Y_START + (row * LAYOUT_Y_SPACING),
            )

    for node in desired.nodes:
        automatic_x, automatic_y = positions[node.local_id]

        chosen_x = node.x if node.x >= 0 else automatic_x
        chosen_y = node.y if node.y >= 0 else automatic_y

        positions[node.local_id] = (
            chosen_x,
            chosen_y,
        )

    return positions


def _calculate_levels(desired):
    levels = {
        node.local_id: 0
        for node in desired.nodes
    }

    outgoing = {
        node.local_id: []
        for node in desired.nodes
    }

    for edge in desired.edges:
        outgoing[edge.source_local_id].append(
            edge.target_local_id
        )

    changed = True

    while changed:
        changed = False

        for source_id, target_ids in outgoing.items():
            for target_id in target_ids:
                wanted_level = levels[source_id] + 1

                if levels[target_id] < wanted_level:
                    levels[target_id] = wanted_level
                    changed = True

    return levels


def _build_nodes(desired, template_ids_by_state_key, positions):
    nodes = []

    # These IDs are only temporary IDs for the POST/PUT payload.
    # Semaphore remaps them when the workflow is saved.
    temporary_id_by_local_id = {}

    for index, node in enumerate(desired.nodes, start=1):
        temporary_id_by_local_id[node.local_id] = index

    for node in desired.nodes:
        position_x, position_y = positions[node.local_id]

        payload = {
            "id": temporary_id_by_local_id[node.local_id],
            "kind": node.node_type,
            "position_x": position_x,
            "position_y": position_y,
        }

        if node.node_type != "note":
            payload["convergence_mode"] = node.convergence

        if node.node_type == "task":
            template_id = template_ids_by_state_key.get(
                node.template_state_key
            )

            if template_id is None or template_id == DRY_RUN_ID:
                return None

            payload["template_id"] = template_id
            payload["task_params"] = node.task_params

        elif node.node_type == "approval":
            if node.approval_message:
                payload["approval_message"] = node.approval_message

            if node.approval_timeout > 0:
                payload["approval_timeout"] = node.approval_timeout

        elif node.node_type == "note":
            payload["note"] = node.note

        nodes.append(payload)

    return nodes


def _build_edges(desired, nodes):
    node_id_by_position = {}
    desired_node_by_local_id = {
        node.local_id: node
        for node in desired.nodes
    }

    # Node order is the same in _build_nodes and desired.nodes.
    for desired_node, payload_node in zip(desired.nodes, nodes):
        node_id_by_position[desired_node.local_id] = payload_node["id"]

    edges = []

    for edge in desired.edges:
        edges.append({
            "source_node_id": node_id_by_position[edge.source_local_id],
            "destination_node_id": node_id_by_position[edge.target_local_id],
            "condition": edge.condition,
        })

    return edges


def _create_workflow(client, desired, payload, state):
    LOG.info(
        "Creating workflow '%s' (%d nodes, %d edges)",
        desired.live_name,
        len(payload["nodes"]),
        len(payload["edges"]),
    )

    created = client.create_workflow(payload)
    workflow_id = _read_created_id(
        created,
        desired.live_name,
    )

    if workflow_id != DRY_RUN_ID:
        state.record(
            "workflows",
            desired.state_key,
            workflow_id,
        )


def _update_workflow_if_changed(client, desired, payload, existing):
    workflow_id = existing["id"]

    if not _workflow_changed(existing, payload):
        LOG.debug(
            "Workflow '%s' (id %d) is already up to date",
            desired.live_name,
            workflow_id,
        )
        return

    LOG.info(
        "Updating workflow '%s' (id %d)",
        desired.live_name,
        workflow_id,
    )

    update_payload = dict(payload)
    update_payload["id"] = workflow_id

    client.update_workflow(
        workflow_id,
        update_payload,
    )


def _workflow_changed(existing, desired):
    return _normalize_workflow(existing) != _normalize_workflow(desired)


def _normalize_workflow(workflow):
    workflow = workflow or {}

    node_position_by_id = {}
    normalized_nodes = []

    for node in workflow.get("nodes") or []:
        position = (
            int(node.get("position_x", 0)),
            int(node.get("position_y", 0)),
        )

        node_position_by_id[node.get("id")] = position

        kind = str(node.get("kind") or "task")

        normalized_nodes.append({
            "kind": kind,
            "template_id": node.get("template_id") or None,
            "convergence_mode": (
                str(node.get("convergence_mode") or "all")
                if kind != "note"
                else ""
            ),
            "approval_timeout": node.get("approval_timeout") or 0,
            "approval_message": str(node.get("approval_message") or ""),
            "task_params": (
                node.get("task_params") or {}
                if kind == "task"
                else {}
            ),
            "note": str(node.get("note") or ""),
            "position_x": position[0],
            "position_y": position[1],
        })

    normalized_nodes.sort(
        key=lambda item: (
            item["position_x"],
            item["position_y"],
            item["kind"],
            item["template_id"] or 0,
        )
    )

    normalized_edges = []

    for edge in workflow.get("edges") or []:
        normalized_edges.append({
            "source_position": node_position_by_id.get(
                edge.get("source_node_id")
            ),
            "destination_position": node_position_by_id.get(
                edge.get("destination_node_id")
            ),
            "condition": str(
                edge.get("condition") or "on_success"
            ),
        })

    normalized_edges.sort(
        key=lambda item: (
            item["source_position"] or (0, 0),
            item["destination_position"] or (0, 0),
            item["condition"],
        )
    )

    return {
        "name": str(workflow.get("name") or ""),
        "description": str(workflow.get("description") or ""),
        "start_version": str(workflow.get("start_version") or ""),
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def prune_workflows(client, state, wanted_state_keys):
    for state_key in state.to_prune("workflows", wanted_state_keys):
        workflow_id = state.get_id("workflows", state_key)

        LOG.info(
            "Pruning KLM-owned workflow '%s' (id %d)",
            state_key,
            workflow_id,
        )

        client.delete_workflow(workflow_id)
        state.forget("workflows", state_key)


def _read_created_id(created, workflow_name):
    if isinstance(created, dict) and "id" in created:
        return created["id"]

    raise ReconcileError(
        "Semaphore did not return an id after creating workflow '%s'. "
        "Response: %r" % (workflow_name, created)
    )
