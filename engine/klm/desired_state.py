"""Build one validated desired Semaphore state from all enabled bundles."""

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)

VIEW_POSITION_START = 10
VIEW_POSITION_STEP = 10

VALID_NODE_TYPES = ("task", "approval", "note")
VALID_EDGE_CONDITIONS = ("on_success", "on_failure", "always")
VALID_CONVERGENCE = ("all", "any")

ALLOWED_REPOSITORY_KEYS = ("name", "url", "branch")
ALLOWED_INVENTORY_KEYS = (
    "name", "type", "inventory", "repository", "ssh_key", "become_key",
)
ALLOWED_VIEW_KEYS = ("name",)
ALLOWED_TEMPLATE_KEYS = (
    "name", "description", "playbook", "repository", "inventory", "environment",
    "view", "app", "git_branch", "arguments", "allow_override_args_in_task",
    "allow_override_branch_in_task", "allow_parallel_tasks",
    "suppress_success_alerts", "survey_vars", "vaults", "task_params", "type",
    "autorun",
)
ALLOWED_SURVEY_KEYS = (
    "name", "title", "description", "type", "required", "default", "values",
)
ALLOWED_VAULT_KEYS = ("name", "key", "type", "script")
ALLOWED_WORKFLOW_KEYS = (
    "name", "description", "start_version", "view", "nodes", "edges",
)
ALLOWED_NODE_KEYS = (
    "id", "type", "template", "convergence", "task_params",
    "approval_message", "approval_timeout", "note", "x", "y",
)
ALLOWED_EDGE_KEYS = ("from", "to", "condition")


class DesiredStateError(Exception):
    """Raised when bundle YAML is structurally valid but semantically invalid."""


@dataclass
class DesiredProject:
    name: str


@dataclass
class DesiredRepository:
    bundle_name: str
    system_name: str
    name: str
    url: str
    branch: str

    @property
    def state_key(self):
        return _resource_state_key(self.bundle_name, self.system_name, self.name)

    @property
    def semaphore_url(self):
        if self.url.startswith("file://"):
            return urlparse(self.url).path
        return self.url


@dataclass
class DesiredInventory:
    bundle_name: str
    system_name: str
    name: str
    inventory_type: str
    inventory: str
    repository_name: str
    ssh_key_name: str
    become_key_name: str

    @property
    def state_key(self):
        return _resource_state_key(self.bundle_name, self.system_name, self.name)


@dataclass
class DesiredView:
    bundle_name: str
    system_name: str
    name: str
    position: int = 0

    @property
    def state_key(self):
        return _resource_state_key(self.bundle_name, self.system_name, self.name)


@dataclass
class SurveyVariable:
    name: str
    title: str
    description: str
    var_type: str
    required: bool
    default_value: str
    values: list


@dataclass
class VaultReference:
    key_store_name: str
    vault_name: str
    vault_type: str
    script: str


@dataclass
class DesiredTemplate:
    bundle_name: str
    system_name: str
    view_name: str
    name: str
    description: str
    playbook: str
    repository_name: str
    inventory_name: str
    environment_name: str
    app: str
    git_branch: str
    arguments: list
    allow_override_args_in_task: bool
    allow_override_branch_in_task: bool
    allow_parallel_tasks: bool
    suppress_success_alerts: bool
    survey_vars: list
    vaults: list
    task_params: dict
    template_type: str
    autorun: bool

    @property
    def state_key(self):
        return _resource_state_key(self.bundle_name, self.system_name, self.name)


@dataclass
class DesiredNode:
    local_id: str
    node_type: str
    template_bundle: str
    template_system: str
    template_name: str
    convergence: str
    task_params: dict
    approval_message: str
    approval_timeout: int
    note: str
    x: int
    y: int

    @property
    def template_state_key(self):
        if self.node_type != "task":
            return ""
        return _resource_state_key(
            self.template_bundle,
            self.template_system,
            self.template_name,
        )


@dataclass
class DesiredEdge:
    source_local_id: str
    target_local_id: str
    condition: str


@dataclass
class DesiredWorkflow:
    bundle_name: str
    system_name: str
    view_name: str
    name: str
    description: str
    start_version: str
    nodes: list
    edges: list

    @property
    def state_key(self):
        return _resource_state_key(self.bundle_name, self.system_name, self.name)

    @property
    def live_name(self):
        return "%s - %s" % (self.view_name, self.name)


@dataclass
class DesiredState:
    project: DesiredProject = None
    repositories: list = field(default_factory=list)
    inventories: list = field(default_factory=list)
    views: list = field(default_factory=list)
    templates: list = field(default_factory=list)
    workflows: list = field(default_factory=list)


def build_desired_state(
    bundles,
    project_name="KLM",
    environment_bundle=None,
    selected_system=None,
):
    """
    Merge enabled capability/architecture bundles plus one selected environment
    system into one desired Semaphore state.

    Import order is irrelevant. The entire dependency graph and every
    cross-bundle reference are validated before reconciliation starts.
    """
    state = DesiredState(project=DesiredProject(name=project_name))

    normal_bundles = list(bundles)
    for bundle in normal_bundles:
        if bundle.bundle_type == "environment":
            raise DesiredStateError(
                "Environment bundle '%s' is installed in the normal bundle directory. "
                "Import environment bundles with: klm env import" % bundle.name
            )

    active_bundles = [bundle for bundle in normal_bundles if bundle.enabled]

    if environment_bundle is not None:
        if environment_bundle.bundle_type != "environment":
            raise DesiredStateError(
                "Selected environment '%s' is type '%s', expected type: environment"
                % (environment_bundle.name, environment_bundle.bundle_type)
            )
        if not environment_bundle.enabled:
            raise DesiredStateError(
                "Selected environment '%s' is disabled" % environment_bundle.name
            )
        if selected_system is None:
            raise DesiredStateError(
                "Environment '%s' requires a selected system" % environment_bundle.name
            )
        if not selected_system.enabled:
            raise DesiredStateError(
                "Selected system '%s' in environment '%s' is disabled"
                % (selected_system.name, environment_bundle.name)
            )

    _check_bundle_requirements(
        normal_bundles,
        environment_bundle=environment_bundle,
        selected_system=selected_system,
    )

    for bundle in active_bundles:
        _append_resource_section(
            state,
            bundle,
            bundle.semaphore,
            system_name="",
        )

    if environment_bundle is not None:
        # Contract-level resources, such as the local environment repository,
        # apply to whichever system from that contract is selected.
        _append_resource_section(
            state,
            environment_bundle,
            environment_bundle.semaphore,
            system_name="",
        )

        semaphore_systems = environment_bundle.semaphore.get("systems", {})
        _append_resource_section(
            state,
            environment_bundle,
            semaphore_systems.get(selected_system.name, {}),
            system_name=selected_system.name,
        )

    _check_unique_live_names(state.repositories, "repository")
    _check_unique_live_names(state.inventories, "inventory")
    _check_unique_live_names(state.views, "view")
    _check_template_identities(state)
    _check_workflow_names(state)
    _check_references(state)
    assign_view_positions(state)
    return state

def _append_resource_section(state, bundle, section, system_name):
    for raw in section.get("repositories", []):
        state.repositories.append(_build_repository(bundle, raw, system_name))

    for raw in section.get("inventories", []):
        state.inventories.append(_build_inventory(bundle, raw, system_name))

    for raw in section.get("views", []):
        state.views.append(_build_view(bundle, raw, system_name))

    for raw in section.get("templates", []):
        state.templates.append(_build_template(bundle, raw, system_name))

    for raw in section.get("workflows", []):
        state.workflows.append(_build_workflow(bundle, raw, system_name))


def _resource_state_key(bundle_name, system_name, resource_name):
    if system_name:
        return "%s::%s::%s" % (bundle_name, system_name, resource_name)
    return "%s::%s" % (bundle_name, resource_name)


def _check_bundle_requirements(
    bundles,
    environment_bundle=None,
    selected_system=None,
):
    """Validate exact bundle dependencies and report all missing/mismatched items."""
    installed = {bundle.name: bundle for bundle in bundles}
    if environment_bundle is not None:
        installed[environment_bundle.name] = environment_bundle

    requirements = []

    for bundle in bundles:
        if not bundle.enabled:
            continue
        for requirement in bundle.requires:
            requirements.append((
                "bundle '%s'" % bundle.name,
                requirement,
            ))

    if environment_bundle is not None:
        for requirement in environment_bundle.requires:
            requirements.append((
                "environment '%s'" % environment_bundle.name,
                requirement,
            ))

        if selected_system is not None:
            for requirement in selected_system.requires:
                requirements.append((
                    "environment '%s' system '%s'"
                    % (environment_bundle.name, selected_system.name),
                    requirement,
                ))

    errors = []
    for owner, requirement in requirements:
        required = installed.get(requirement.name)

        if required is None:
            errors.append(
                "%s requires bundle '%s' version %s, but it is not installed"
                % (owner, requirement.name, requirement.version)
            )
            continue

        if not required.enabled:
            errors.append(
                "%s requires bundle '%s' version %s, but it is disabled"
                % (owner, requirement.name, requirement.version)
            )
            continue

        if required.version != requirement.version:
            errors.append(
                "%s requires bundle '%s' version %s, but version %s is installed"
                % (
                    owner,
                    requirement.name,
                    requirement.version,
                    required.version,
                )
            )

    if errors:
        raise DesiredStateError(
            "Bundle dependency validation failed:\n  - " + "\n  - ".join(errors)
        )

def assign_view_positions(state):
    for index, view in enumerate(
        sorted(state.views, key=lambda item: natural_sort_key(item.name)),
        start=1,
    ):
        view.position = VIEW_POSITION_START + ((index - 1) * VIEW_POSITION_STEP)


def natural_sort_key(text):
    key = []
    for part in re.split(r"(\d+)", text.lower()):
        if part.isdigit():
            key.append((1, int(part)))
        elif part:
            key.append((0, part))
    return key


def _build_repository(bundle, raw, system_name=""):
    location = "%s (repository)" % bundle.semaphore_file
    _reject_unknown_keys(raw, ALLOWED_REPOSITORY_KEYS, location)
    name = _require_string(raw, "name", location)
    url = _require_string(raw, "url", location)
    branch = str(raw.get("branch", "main"))
    return DesiredRepository(bundle.name, system_name, name, url, branch)


def _build_inventory(bundle, raw, system_name=""):
    location = "%s (inventory)" % bundle.semaphore_file
    _reject_unknown_keys(raw, ALLOWED_INVENTORY_KEYS, location)

    name = _require_string(raw, "name", location)
    inventory_type = str(raw.get("type", "static"))

    if inventory_type not in ("static", "static-yaml", "file"):
        raise DesiredStateError(
            "%s: inventory '%s' has unsupported type '%s'"
            % (location, name, inventory_type)
        )

    return DesiredInventory(
        bundle_name=bundle.name,
        system_name=system_name,
        name=name,
        inventory_type=inventory_type,
        inventory=str(raw.get("inventory", "")),
        repository_name=str(raw.get("repository", "")).strip(),
        ssh_key_name=str(raw.get("ssh_key", "")).strip(),
        become_key_name=str(raw.get("become_key", "")).strip(),
    )


def _build_view(bundle, raw, system_name=""):
    location = "%s (view)" % bundle.semaphore_file
    _reject_unknown_keys(raw, ALLOWED_VIEW_KEYS, location)
    return DesiredView(bundle.name, system_name, _require_string(raw, "name", location))


def _build_template(bundle, raw, system_name=""):
    location = "%s (template)" % bundle.semaphore_file
    _reject_unknown_keys(raw, ALLOWED_TEMPLATE_KEYS, location)

    name = _require_string(raw, "name", location)
    playbook = _require_string(raw, "playbook", location)
    repository = _require_string(raw, "repository", location)
    inventory = str(raw.get("inventory", "")).strip()
    view = _require_string(raw, "view", location)

    arguments = raw.get("arguments", [])
    if not isinstance(arguments, list):
        raise DesiredStateError(
            "%s: template '%s' arguments must be a list" % (location, name)
        )

    task_params = raw.get("task_params", {})
    if not isinstance(task_params, dict):
        raise DesiredStateError(
            "%s: template '%s' task_params must be a mapping" % (location, name)
        )
    task_params = dict(task_params)

    # A tool template may intentionally have no default inventory. In that
    # case the operator chooses any Semaphore inventory at launch time.
    if not inventory and str(raw.get("app", "ansible")) == "ansible":
        task_params.setdefault("allow_override_inventory", True)

    return DesiredTemplate(
        bundle_name=bundle.name,
        system_name=system_name,
        view_name=view,
        name=name,
        description=str(raw.get("description", "")),
        playbook=playbook,
        repository_name=repository,
        inventory_name=inventory,
        environment_name=str(raw.get("environment", "")).strip(),
        app=str(raw.get("app", "ansible")),
        git_branch=str(raw.get("git_branch", "")),
        arguments=[str(value) for value in arguments],
        allow_override_args_in_task=_bool(
            raw, "allow_override_args_in_task", False, location, name
        ),
        allow_override_branch_in_task=_bool(
            raw, "allow_override_branch_in_task", False, location, name
        ),
        allow_parallel_tasks=_bool(
            raw, "allow_parallel_tasks", False, location, name
        ),
        suppress_success_alerts=_bool(
            raw, "suppress_success_alerts", False, location, name
        ),
        survey_vars=_build_survey_vars(raw.get("survey_vars", []), name, location),
        vaults=_build_vaults(raw.get("vaults", []), name, location),
        task_params=task_params,
        template_type=str(raw.get("type", "")),
        autorun=_bool(raw, "autorun", False, location, name),
    )


def _build_survey_vars(raw_vars, template_name, location):
    if not isinstance(raw_vars, list):
        raise DesiredStateError(
            "%s: template '%s' survey_vars must be a list"
            % (location, template_name)
        )

    result = []

    for index, raw in enumerate(raw_vars):
        if not isinstance(raw, dict):
            raise DesiredStateError(
                "%s: survey_vars[%d] must be a mapping" % (location, index)
            )

        _reject_unknown_keys(raw, ALLOWED_SURVEY_KEYS, location)

        name = _require_string(raw, "name", location)
        required = raw.get("required", False)

        if not isinstance(required, bool):
            raise DesiredStateError(
                "%s: survey '%s' required must be true or false"
                % (location, name)
            )

        values = raw.get("values", [])
        if not isinstance(values, list):
            raise DesiredStateError(
                "%s: survey '%s' values must be a list" % (location, name)
            )

        normalized_values = []
        for value in values:
            if isinstance(value, dict):
                if "value" not in value:
                    raise DesiredStateError(
                        "%s: survey '%s' value mapping needs 'value'"
                        % (location, name)
                    )
                item_value = str(value["value"])
                normalized_values.append(
                    {
                        "name": str(value.get("name", item_value)),
                        "value": item_value,
                    }
                )
            else:
                item_value = str(value)
                normalized_values.append(
                    {"name": item_value, "value": item_value}
                )

        result.append(
            SurveyVariable(
                name=name,
                title=str(raw.get("title", name)),
                description=str(raw.get("description", "")),
                var_type=str(raw.get("type", "")),
                required=required,
                default_value=str(raw.get("default", "")),
                values=normalized_values,
            )
        )

    return result


def _build_vaults(raw_vaults, template_name, location):
    if not isinstance(raw_vaults, list):
        raise DesiredStateError(
            "%s: template '%s' vaults must be a list"
            % (location, template_name)
        )

    result = []

    for raw in raw_vaults:
        if not isinstance(raw, dict):
            raise DesiredStateError(
                "%s: template '%s' vault entry must be a mapping"
                % (location, template_name)
            )

        _reject_unknown_keys(raw, ALLOWED_VAULT_KEYS, location)

        result.append(
            VaultReference(
                key_store_name=_require_string(raw, "key", location),
                vault_name=str(raw.get("name", "")),
                vault_type=str(raw.get("type", "password")),
                script=str(raw.get("script", "")),
            )
        )

    return result


def _build_workflow(bundle, raw, system_name=""):
    location = "%s (workflow)" % bundle.semaphore_file
    _reject_unknown_keys(raw, ALLOWED_WORKFLOW_KEYS, location)

    name = _require_string(raw, "name", location)
    view_name = _require_string(raw, "view", location)
    raw_nodes = raw.get("nodes", [])
    raw_edges = raw.get("edges", [])

    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise DesiredStateError(
            "%s: workflow '%s' must contain at least one node"
            % (location, name)
        )

    if not isinstance(raw_edges, list):
        raise DesiredStateError(
            "%s: workflow '%s' edges must be a list" % (location, name)
        )

    nodes = []
    seen = set()

    for raw_node in raw_nodes:
        node = _build_workflow_node(
            raw_node,
            workflow_name=name,
            location=location,
            default_bundle_name=bundle.name,
            default_system_name=system_name,
        )

        if node.local_id in seen:
            raise DesiredStateError(
                "%s: workflow '%s' repeats node id '%s'"
                % (location, name, node.local_id)
            )

        seen.add(node.local_id)
        nodes.append(node)

    node_by_id = {node.local_id: node for node in nodes}
    edges = []

    for raw_edge in raw_edges:
        edge = _build_workflow_edge(raw_edge, name, location)

        if (
            edge.source_local_id not in node_by_id
            or edge.target_local_id not in node_by_id
        ):
            raise DesiredStateError(
                "%s: workflow '%s' edge references an unknown node"
                % (location, name)
            )

        if (
            node_by_id[edge.source_local_id].node_type == "note"
            or node_by_id[edge.target_local_id].node_type == "note"
        ):
            raise DesiredStateError(
                "%s: workflow '%s' note nodes cannot be connected"
                % (location, name)
            )

        edges.append(edge)

    _check_for_cycle(nodes, edges, name, location)

    return DesiredWorkflow(
        bundle_name=bundle.name,
        system_name=system_name,
        view_name=view_name,
        name=name,
        description=str(raw.get("description", "")),
        start_version=str(raw.get("start_version", "")),
        nodes=nodes,
        edges=edges,
    )


def _build_workflow_node(
    raw,
    workflow_name,
    location,
    default_bundle_name,
    default_system_name,
):
    if not isinstance(raw, dict):
        raise DesiredStateError(
            "%s: workflow '%s' node must be a mapping"
            % (location, workflow_name)
        )

    _reject_unknown_keys(raw, ALLOWED_NODE_KEYS, location)

    local_id = _require_string(raw, "id", location)
    node_type = str(raw.get("type", "task"))

    if node_type not in VALID_NODE_TYPES:
        raise DesiredStateError(
            "%s: workflow '%s' node '%s' unsupported type '%s'"
            % (location, workflow_name, local_id, node_type)
        )

    convergence = str(raw.get("convergence", "all"))
    if convergence not in VALID_CONVERGENCE:
        raise DesiredStateError(
            "%s: workflow '%s' node '%s' invalid convergence '%s'"
            % (location, workflow_name, local_id, convergence)
        )

    template_bundle = ""
    template_system = ""
    template_name = ""

    if node_type == "task":
        template_reference = _require_string(raw, "template", location)
        parts = [part.strip() for part in template_reference.split("::")]

        if len(parts) == 1:
            template_bundle = default_bundle_name
            template_system = default_system_name
            template_name = parts[0]
        elif len(parts) == 2:
            template_bundle, template_name = parts
            template_system = ""
        elif len(parts) == 3:
            template_bundle, template_system, template_name = parts
        else:
            template_bundle = ""
            template_name = ""

        if not template_bundle or not template_name or (len(parts) == 3 and not template_system):
            raise DesiredStateError(
                "%s: workflow '%s' node '%s' has invalid template reference '%s'"
                % (
                    location,
                    workflow_name,
                    local_id,
                    template_reference,
                )
            )

    task_params = raw.get("task_params", {})
    if not isinstance(task_params, dict):
        raise DesiredStateError(
            "%s: workflow '%s' node '%s' task_params must be mapping"
            % (location, workflow_name, local_id)
        )

    approval_timeout = raw.get("approval_timeout", 0)
    if not isinstance(approval_timeout, int) or approval_timeout < 0:
        raise DesiredStateError(
            "%s: workflow '%s' node '%s' approval_timeout must be non-negative integer"
            % (location, workflow_name, local_id)
        )

    x = raw.get("x", -1)
    y = raw.get("y", -1)
    if not isinstance(x, int) or not isinstance(y, int):
        raise DesiredStateError(
            "%s: workflow '%s' node '%s' x/y must be integers"
            % (location, workflow_name, local_id)
        )

    return DesiredNode(
        local_id=local_id,
        node_type=node_type,
        template_bundle=template_bundle,
        template_system=template_system,
        template_name=template_name,
        convergence=convergence,
        task_params=task_params,
        approval_message=str(raw.get("approval_message", "")),
        approval_timeout=approval_timeout,
        note=str(raw.get("note", "")),
        x=x,
        y=y,
    )


def _build_workflow_edge(raw, workflow_name, location):
    if not isinstance(raw, dict):
        raise DesiredStateError(
            "%s: workflow '%s' edge must be a mapping"
            % (location, workflow_name)
        )

    _reject_unknown_keys(raw, ALLOWED_EDGE_KEYS, location)

    source = _require_string(raw, "from", location)
    target = _require_string(raw, "to", location)
    condition = str(raw.get("condition", "on_success"))

    if condition not in VALID_EDGE_CONDITIONS:
        raise DesiredStateError(
            "%s: workflow '%s' invalid edge condition '%s'"
            % (location, workflow_name, condition)
        )

    return DesiredEdge(source, target, condition)


def _check_for_cycle(nodes, edges, workflow_name, location):
    runnable = [node.local_id for node in nodes if node.node_type != "note"]
    outgoing = {node_id: [] for node_id in runnable}

    for edge in edges:
        outgoing[edge.source_local_id].append(edge.target_local_id)

    visiting = set()
    visited = set()

    def visit(node_id):
        if node_id in visiting:
            raise DesiredStateError(
                "%s: workflow '%s' contains a cycle"
                % (location, workflow_name)
            )

        if node_id in visited:
            return

        visiting.add(node_id)

        for next_id in outgoing[node_id]:
            visit(next_id)

        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in runnable:
        visit(node_id)


def _check_unique_live_names(resources, label):
    seen = {}

    for resource in resources:
        owner = _resource_owner_label(resource)

        if resource.name in seen:
            raise DesiredStateError(
                "Bundle scopes '%s' and '%s' both define Semaphore %s '%s'"
                % (
                    seen[resource.name],
                    owner,
                    label,
                    resource.name,
                )
            )

        seen[resource.name] = owner


def _resource_owner_label(resource):
    if getattr(resource, "system_name", ""):
        return "%s/%s" % (resource.bundle_name, resource.system_name)
    return resource.bundle_name


def _check_template_identities(state):
    seen_live = set()
    seen_state = set()

    for template in state.templates:
        live_key = (template.view_name, template.name)

        if live_key in seen_live:
            raise DesiredStateError(
                "More than one template resolves to view '%s' / template '%s'"
                % live_key
            )

        if template.state_key in seen_state:
            raise DesiredStateError(
                "Bundle scope '%s' defines template name '%s' more than once. "
                "Template names must be unique within a bundle/system scope."
                % (_resource_owner_label(template), template.name)
            )

        seen_live.add(live_key)
        seen_state.add(template.state_key)


def _check_workflow_names(state):
    seen = set()

    for workflow in state.workflows:
        if workflow.live_name in seen:
            raise DesiredStateError(
                "More than one workflow resolves to '%s'" % workflow.live_name
            )

        seen.add(workflow.live_name)


def _check_references(state):
    repo_names = {item.name: item for item in state.repositories}
    inventory_names = {item.name: item for item in state.inventories}
    view_names = {item.name: item for item in state.views}
    templates_by_state_key = {
        item.state_key: item
        for item in state.templates
    }

    for inventory in state.inventories:
        if inventory.repository_name:
            if inventory.repository_name not in repo_names:
                raise DesiredStateError(
                    "Inventory '%s' references unknown repository '%s'. "
                    "Inventories stored in a bundle must reference a repository "
                    "declared by an enabled bundle."
                    % (inventory.name, inventory.repository_name)
                )

            repository = repo_names[inventory.repository_name]
            local_path = repository.semaphore_url

            if (
                inventory.inventory_type == "file"
                and local_path.startswith("/")
                and inventory.inventory
            ):
                inventory_path = os.path.join(local_path, inventory.inventory)
                if not os.path.isfile(inventory_path):
                    raise DesiredStateError(
                        "Inventory '%s' file does not exist: %s"
                        % (inventory.name, inventory_path)
                    )

    for template in state.templates:
        if template.repository_name not in repo_names:
            raise DesiredStateError(
                "Template '%s' references unknown repository '%s'"
                % (template.name, template.repository_name)
            )

        if template.view_name not in view_names:
            raise DesiredStateError(
                "Template '%s' references unknown view '%s'"
                % (template.name, template.view_name)
            )

        # Inventory is intentionally different from repository/view.
        # A template may reference an inventory managed by an environment
        # bundle OR an operator-created inventory already present in Semaphore.
        # If omitted entirely, the template is created without a default
        # inventory and allow_override_inventory defaults to true.
        if template.inventory_name and template.inventory_name in inventory_names:
            pass

        repository = repo_names[template.repository_name]
        local_path = repository.semaphore_url

        if local_path.startswith("/"):
            playbook_path = os.path.join(local_path, template.playbook)
            if not os.path.isfile(playbook_path):
                raise DesiredStateError(
                    "Template '%s' playbook does not exist: %s"
                    % (template.name, playbook_path)
                )

    for workflow in state.workflows:
        if workflow.view_name not in view_names:
            raise DesiredStateError(
                "Workflow '%s' references unknown view '%s'"
                % (workflow.name, workflow.view_name)
            )

        for node in workflow.nodes:
            if (
                node.node_type == "task"
                and node.template_state_key not in templates_by_state_key
            ):
                raise DesiredStateError(
                    "Workflow '%s' references template '%s', but no enabled "
                    "bundle defines state key '%s'"
                    % (
                        workflow.name,
                        node.template_name,
                        node.template_state_key,
                    )
                )


def _bool(mapping, key, default, location, item_name):
    value = mapping.get(key, default)

    if not isinstance(value, bool):
        raise DesiredStateError(
            "%s: '%s' on '%s' must be true or false"
            % (location, key, item_name)
        )

    return value


def _require_string(mapping, key, location):
    value = mapping.get(key)

    if not isinstance(value, str) or not value.strip():
        raise DesiredStateError(
            "%s: '%s' must be a non-empty string" % (location, key)
        )

    return value.strip()


def _reject_unknown_keys(mapping, allowed, location):
    for key in mapping:
        if key not in allowed:
            raise DesiredStateError(
                "%s: unknown key '%s'. Allowed: %s"
                % (location, key, ", ".join(allowed))
            )
