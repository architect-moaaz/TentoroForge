"""Walk a generated Forge app's contracts and emit a typed Interaction list.

The Self-Verify Pass runner (`forge-verify` Playwright service) drives one
click / one HTTP call per Interaction and asserts a proof envelope per §5.4
of `docs/superpowers/specs/2026-08-01-self-verify-pass-design.md`.

This module is pure: (output_dir, scope) → Interaction[]. No I/O beyond
reading the four contract files that are always present after a successful
generation. No LLM. Deterministic ordering — same contracts always emit the
same list, sorted stably by `(route, path)` so `id`s are reproducible across
runs (regression-detection needs this).

## Inputs read

- `<output>/src/contracts/nav-flow.json`   — the closed set of routes + auth
- `<output>/src/schemas/**/*.json`         — per-page component trees
- `<output>/src/contracts/plan.json`       — workflow trigger inputs (types)
- `<output>/registry.json`                 — entity columns, FK targets

## Outputs (Interaction union — spec §5.3)

- ``RouteInteraction``   — every ``pages[].route``
- ``ButtonInteraction``  — every ``Button`` node with an action shape
- ``FormInteraction``    — every ``Form`` node (fields harvested from descendants)
- ``ListInteraction``    — every ``Table`` bound to a ``dataSources[]`` entry
- ``DetailInteraction``  — every route with a bracket param (``/x/[id]``)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal


# ── Skip set: config files that live under src/schemas but aren't pages ──
# Mirrors backend/services/nav_flow_from_schemas.py:25 — keep in sync there.
_SCHEMA_SKIP_NAMES = {"registry.json", "load.json", "nav-flow.json", "shell.json"}


# ── Types ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldSpec:
    """One field the runner has to fill for a Form submission."""

    name: str
    type: str  # 'text' | 'email' | 'uuid' | 'number' | 'date' | 'timestamp' | 'select' | 'file' | ...
    required: bool = False
    options: tuple[str, ...] = ()  # enum values / select options; empty if free-form
    fk_entity: str | None = None   # if this field is a foreign key, the target entity slug


@dataclass(frozen=True)
class WorkflowInput:
    """One input the runner has to fill for a workflow-backed Form."""

    name: str
    type: str
    required: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteInteraction:
    id: str
    kind: Literal["route"]
    route: str
    requires_auth: bool
    # Optional display label — real routes rarely carry one, but synthetic
    # promise-gate faults reuse this shape and need it to reach the narrator.
    label: str = ""


@dataclass(frozen=True)
class ButtonAction:
    """Discriminated action union — exactly one of the *_target keys is set."""

    kind: Literal["workflow", "navigate", "compute", "submit", "none"]
    workflow_target: str | None = None   # workflow name (for kind='workflow')
    navigate_target: str | None = None   # /path (for kind='navigate')
    compute_target: str | None = None    # field name (for kind='compute')
    compute_formula: str | None = None   # formula string (for kind='compute')


@dataclass(frozen=True)
class ButtonInteraction:
    id: str
    kind: Literal["button"]
    route: str
    selector: str          # DOM selector the runner uses to find the button
    label: str             # display text (for logs)
    action: ButtonAction


@dataclass(frozen=True)
class FormSubmit:
    """Discriminated submit target — exactly one of *_target keys is set."""

    kind: Literal["workflow", "dataSource", "none"]
    workflow_target: str | None = None    # workflow name
    workflow_inputs: tuple[WorkflowInput, ...] = ()  # from plan.workflows[].inputs
    dataSource_target: str | None = None  # dataSources[].name


@dataclass(frozen=True)
class FormInteraction:
    id: str
    kind: Literal["form"]
    route: str
    selector: str
    fields: tuple[FieldSpec, ...]         # harvested from descendant field nodes
    submit: FormSubmit


@dataclass(frozen=True)
class ListInteraction:
    id: str
    kind: Literal["list"]
    route: str
    selector: str
    dataSource: str          # dataSources[].name
    entity: str | None       # dataSources[].entity — nullable if unresolved
    seed_min_rows: int       # 1 by default; SEED-1 guarantees this


@dataclass(frozen=True)
class DetailInteraction:
    id: str
    kind: Literal["detail"]
    route: str               # e.g. /candidates/[id]
    entity: str | None       # inferred from parent list's dataSource entity, else None
    param_name: str          # the bracket param name (e.g. "id")


Interaction = (
    RouteInteraction
    | ButtonInteraction
    | FormInteraction
    | ListInteraction
    | DetailInteraction
)


# ── Field-node types the runner knows how to fill ────────────────────────
# These match the components emitted by build_form_page + workflow_launch_forms.
_FIELD_NODE_TYPES = {
    "Input",
    "Textarea",
    "Select",
    "NumberInput",
    "DatePicker",
    "TimePicker",
    "FileUpload",
    "Switch",
    "Combobox",
    "RadioGroup",
    "Checkbox",
    "KeyValueInput",
    "Slider",
    "Rating",
    "ColorPicker",
    "MaskedInput",
    "InputOTP",
}


# ── Walker ───────────────────────────────────────────────────────────────


def _walk_nodes(node: Any) -> Iterator[dict]:
    """Yield every node dict in a schema tree.

    Copies the pattern from nav_flow_emitter._walk_nodes so the top-level
    envelope (with 'root' key) is fully traversed as well as nested
    component trees.
    """
    if isinstance(node, list):
        for n in node:
            yield from _walk_nodes(n)
        return
    if not isinstance(node, dict):
        return
    yield node
    for v in node.values():
        if isinstance(v, (dict, list)):
            yield from _walk_nodes(v)


def _walk_nodes_with_path(
    node: Any, path: str = "root",
) -> Iterator[tuple[dict, str]]:
    """Yield (node, path) pairs so we can build stable per-interaction ids.

    Path form: 'root', 'root.children[0]', 'root.children[0].children[2]',
    'root.props.onClick' (structural keys skipped in favour of children
    indexing since children is the load-bearing tree shape).
    """
    if isinstance(node, dict):
        yield node, path
        children = node.get("children")
        if isinstance(children, list):
            for i, child in enumerate(children):
                yield from _walk_nodes_with_path(child, f"{path}.children[{i}]")
        # Also descend into props to catch e.g. Form.props.title being a nested node
        # in some schema flavours — keeps the walker complete.
        props = node.get("props")
        if isinstance(props, dict):
            for k, v in props.items():
                if isinstance(v, (dict, list)):
                    yield from _walk_nodes_with_path(v, f"{path}.props.{k}")


def _iter_schema_files(schemas_dir: Path) -> Iterator[Path]:
    for p in sorted(schemas_dir.rglob("*.json")):
        if p.name in _SCHEMA_SKIP_NAMES:
            continue
        yield p


# ── Loaders (defensive — every contract may be missing on partial gen) ──


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_nav_flow(output_dir: Path) -> dict:
    return _load_json(output_dir / "src" / "contracts" / "nav-flow.json") or {}


def _load_plan(output_dir: Path) -> dict:
    return _load_json(output_dir / "src" / "contracts" / "plan.json") or {}


def _load_registry(output_dir: Path) -> dict:
    return _load_json(output_dir / "registry.json") or {}


# ── Plan / registry helpers ──────────────────────────────────────────────


def _workflow_inputs(plan: dict, name: str) -> tuple[WorkflowInput, ...]:
    """Look up trigger inputs for a workflow by name in plan.json.

    Accepts both `inputs` and `trigger_inputs` — planner emits `inputs` but
    older fixtures / some downstream serializers use `trigger_inputs`. See
    plan_completeness_validator.py:310 for the same alias.
    """
    if not name:
        return ()
    for w in plan.get("workflows", []) or []:
        if (w.get("name") or "") != name:
            continue
        raw = w.get("inputs") or w.get("trigger_inputs") or []
        out: list[WorkflowInput] = []
        for f in raw:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            out.append(WorkflowInput(
                name=str(f["name"]),
                type=str(f.get("type") or "text"),
                required=bool(f.get("required", False)),
                options=tuple(str(v) for v in (f.get("enum") or f.get("enum_values") or [])),
            ))
        return tuple(out)
    return ()


def _fk_lookup(registry: dict, entity: str, column: str) -> str | None:
    """Return the FK target entity slug for entity.column, else None.

    Registry stores relations at top level as
    ``{from_entity, to_entity, type}``; the exact FK column isn't always
    named there so we fall back to a name-heuristic (column ending in
    ``_id`` maps to an entity whose slug matches the stem).
    """
    for rel in registry.get("relations", []) or []:
        if rel.get("from_entity") == entity:
            fk_col = rel.get("foreignKey") or ""
            # Column-exact match, or a naming convention match
            if fk_col == column or column.endswith("_id"):
                return rel.get("to_entity")
    return None


# ── Interaction builders ─────────────────────────────────────────────────


def _button_action(props: dict) -> ButtonAction:
    """Classify a Button's action from its props.

    Handles four flavours:
      - props.workflow           → workflow dispatch
      - props.onClick = {action:"navigate", to}  → navigate
      - props.navigate           → navigate (simple)
      - props.submit = true      → form submit sentinel
    Any Button without one of these lands as kind='none' — the runner
    treats that as a fault (a button with no action is broken).
    """
    workflow = props.get("workflow")
    if workflow:
        return ButtonAction(kind="workflow", workflow_target=str(workflow))
    on_click = props.get("onClick")
    if isinstance(on_click, dict):
        if on_click.get("action") == "navigate":
            to = on_click.get("to") or on_click.get("trigger")
            if to:
                return ButtonAction(kind="navigate", navigate_target=str(to))
        if on_click.get("action") == "compute" or on_click.get("kind") == "compute":
            return ButtonAction(
                kind="compute",
                compute_target=str(on_click.get("target") or ""),
                compute_formula=str(on_click.get("formula") or ""),
            )
        if on_click.get("action") == "workflow":
            wf = on_click.get("workflow") or on_click.get("target")
            if wf:
                return ButtonAction(kind="workflow", workflow_target=str(wf))
    navigate = props.get("navigate")
    if navigate:
        return ButtonAction(kind="navigate", navigate_target=str(navigate))
    if props.get("submit") is True:
        return ButtonAction(kind="submit")
    return ButtonAction(kind="none")


def _field_from_node(node: dict, registry: dict, entity: str | None) -> FieldSpec | None:
    """Turn a field-node (Input/Select/etc.) into a typed FieldSpec.

    Returns None for nodes that aren't fields or lack a `name` prop —
    labels, decorative Inputs, etc.
    """
    if node.get("type") not in _FIELD_NODE_TYPES:
        return None
    props = node.get("props") or {}
    name = props.get("name")
    if not name:
        return None
    # Derive the value type from either an explicit props.type
    # (kind hint) or the node type itself (Select→select, DatePicker→date).
    node_type = node.get("type") or ""
    props_type = props.get("type") or props.get("kind") or ""
    resolved_type = props_type or {
        "Input": "text",
        "Textarea": "text",
        "Select": "select",
        "Combobox": "select",
        "NumberInput": "number",
        "Slider": "number",
        "Rating": "number",
        "DatePicker": "date",
        "TimePicker": "time",
        "FileUpload": "file",
        "Switch": "boolean",
        "Checkbox": "boolean",
        "RadioGroup": "select",
        "KeyValueInput": "keyvalue",
        "ColorPicker": "color",
        "MaskedInput": "text",
        "InputOTP": "text",
    }.get(node_type, "text")
    # Required — check validators + top-level required prop
    validators = props.get("validators") or {}
    required = bool(
        props.get("required") or validators.get("required") is True
        or validators.get("required") == "required"
    )
    # Enum options — Select/Combobox/RadioGroup carry props.options: [{value,label}] or [str,...]
    raw_options = props.get("options") or []
    options: list[str] = []
    for o in raw_options:
        if isinstance(o, dict) and "value" in o:
            options.append(str(o["value"]))
        elif isinstance(o, (str, int, float)):
            options.append(str(o))
    # FK detection — if registry marks this column as an FK, override the type
    # so the runner picks a real FK value at fill-time instead of synthesizing junk.
    fk_entity = _fk_lookup(registry, entity, str(name)) if entity else None
    if fk_entity:
        resolved_type = "uuid"  # runner will pluck from GET /api/data/<fk_entity>?limit=1
    return FieldSpec(
        name=str(name),
        type=str(resolved_type),
        required=required,
        options=tuple(options),
        fk_entity=fk_entity,
    )


def _collect_form_fields(
    form_node: dict, registry: dict, entity: str | None,
) -> tuple[FieldSpec, ...]:
    """Walk a Form subtree, collecting every descendant field-node."""
    out: list[FieldSpec] = []
    seen_names: set[str] = set()
    for descendant in _walk_nodes(form_node):
        # Don't count the Form itself
        if descendant is form_node:
            continue
        f = _field_from_node(descendant, registry, entity)
        if f is None or f.name in seen_names:
            continue
        seen_names.add(f.name)
        out.append(f)
    return tuple(out)


def _button_selector(label: str, path: str) -> str:
    """Best-guess DOM selector for a Button.

    Runner prefers text match (Playwright: `role=button[name="Label"]`) but
    falls back to a data-testid stamped by the renderer (path-derived).
    """
    if label:
        return f'role=button[name="{label}"]'
    return f"[data-forge-path=\"{path}\"]"


def _form_selector(path: str) -> str:
    """Forms are hard to text-select; use a positional selector."""
    return f"form[data-forge-path=\"{path}\"], form:nth-of-type(1)"


def _list_selector(path: str) -> str:
    return f'[data-forge-path="{path}"], table'


def _extract_binding_name(rows: Any) -> str | None:
    """Pull `foo` out of `{{foo}}` or `{{foo[0].bar}}`.

    Tables carry `props.rows = "{{candidates}}"` where the identifier
    references a dataSources[] entry name.
    """
    if not isinstance(rows, str):
        return None
    m = re.match(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)", rows)
    return m.group(1) if m else None


# ── Public entry point ───────────────────────────────────────────────────


def extract_interactions(
    output_dir: str | Path,
    scope: str = "*",
) -> list[Interaction]:
    """Emit the full Interaction[] for a generated app.

    ``scope`` filters by route:
      - ``"*"`` — everything
      - ``"/dashboard"`` — exact route match
      - ``"/candidates/*"`` — prefix (any sub-path)

    Returns interactions sorted deterministically by (route, kind, path)
    so ids are reproducible across runs.
    """
    root = Path(output_dir)
    nav_flow = _load_nav_flow(root)
    plan = _load_plan(root)
    registry = _load_registry(root)

    interactions: list[Interaction] = []

    # 1. Routes from nav-flow.pages
    pages = nav_flow.get("pages", []) or []
    auth_routes = set(nav_flow.get("auth_routes") or [])
    global_auth = bool(nav_flow.get("authGated", False))
    for page in pages:
        route = page.get("route")
        if not route:
            continue
        if not _route_in_scope(route, scope):
            continue
        # Auth-gated computation:
        # - shell:false OR in auth_routes[]  → THIS IS the login/signup page itself,
        #   so it never requires auth to reach.
        # - has a `guard` string             → explicitly gated.
        # - global `authGated:true`          → every non-auth page requires auth.
        if page.get("shell") is False or route in auth_routes:
            requires_auth = False
        elif page.get("guard"):
            requires_auth = True
        elif global_auth:
            requires_auth = True
        else:
            requires_auth = False

        interactions.append(RouteInteraction(
            id=f"route:{route}",
            kind="route",
            route=route,
            requires_auth=requires_auth,
        ))

    # 2/3/4/5. Buttons, Forms, Lists, Details — walk schemas
    schemas_dir = root / "src" / "schemas"
    if schemas_dir.exists():
        for schema_path in _iter_schema_files(schemas_dir):
            schema = _load_json(schema_path)
            if not schema:
                continue
            page_route = schema.get("route") or ""
            if not _route_in_scope(page_route, scope):
                continue
            data_sources = {
                str(ds.get("name")): ds
                for ds in (schema.get("dataSources") or [])
                if isinstance(ds, dict) and ds.get("name")
            }
            # Primary entity for FK resolution on this page
            primary_entity: str | None = None
            for ds in data_sources.values():
                if ds.get("entity"):
                    primary_entity = str(ds["entity"])
                    break

            for node, path in _walk_nodes_with_path(schema.get("root") or schema):
                ntype = node.get("type")
                props = node.get("props") or {}
                if ntype == "Button":
                    label = str(props.get("label") or "")
                    action = _button_action(props)
                    interactions.append(ButtonInteraction(
                        id=f"button:{page_route}:{path}",
                        kind="button",
                        route=page_route,
                        selector=_button_selector(label, path),
                        label=label,
                        action=action,
                    ))
                elif ntype == "Form":
                    fields = _collect_form_fields(node, registry, primary_entity)
                    submit = _form_submit(props, plan, data_sources)
                    interactions.append(FormInteraction(
                        id=f"form:{page_route}:{path}",
                        kind="form",
                        route=page_route,
                        selector=_form_selector(path),
                        fields=fields,
                        submit=submit,
                    ))
                elif ntype == "Table":
                    binding = _extract_binding_name(props.get("rows"))
                    if not binding:
                        continue
                    ds = data_sources.get(binding)
                    interactions.append(ListInteraction(
                        id=f"list:{page_route}:{path}",
                        kind="list",
                        route=page_route,
                        selector=_list_selector(path),
                        dataSource=binding,
                        entity=str(ds.get("entity")) if ds and ds.get("entity") else None,
                        seed_min_rows=1,
                    ))

    # 5. Detail interactions — every route with a [param]
    for page in pages:
        route = page.get("route") or ""
        if not route or "[" not in route or not _route_in_scope(route, scope):
            continue
        m = re.search(r"\[(\w+)\]", route)
        if not m:
            continue
        # Try to infer entity from the parent list route's dataSource
        parent_route = re.sub(r"/\[[^/]+\]", "", route) or "/"
        entity = _entity_for_route(interactions, parent_route)
        interactions.append(DetailInteraction(
            id=f"detail:{route}",
            kind="detail",
            route=route,
            entity=entity,
            param_name=m.group(1),
        ))

    return sorted(interactions, key=_sort_key)


def _entity_for_route(interactions: list[Interaction], route: str) -> str | None:
    for it in interactions:
        if isinstance(it, ListInteraction) and it.route == route:
            return it.entity
    return None


def _route_in_scope(route: str, scope: str) -> bool:
    if scope == "*" or scope == "":
        return True
    if scope.endswith("/*"):
        prefix = scope[:-2]
        return route == prefix or route.startswith(prefix + "/")
    return route == scope


_KIND_ORDER = {"route": 0, "list": 1, "detail": 2, "form": 3, "button": 4}


def _sort_key(it: Interaction) -> tuple:
    return (it.route, _KIND_ORDER.get(it.kind, 99), it.id)


def _form_submit(props: dict, plan: dict, data_sources: dict) -> FormSubmit:
    """Classify a Form's submit target: workflow, dataSource, or none."""
    wf = props.get("workflow")
    if wf:
        return FormSubmit(
            kind="workflow",
            workflow_target=str(wf),
            workflow_inputs=_workflow_inputs(plan, str(wf)),
        )
    # Some Forms carry props.dataSource for a direct POST to /api/data/<slug>
    ds = props.get("dataSource")
    if ds:
        return FormSubmit(kind="dataSource", dataSource_target=str(ds))
    submit = props.get("submit")
    if isinstance(submit, dict) and submit.get("target"):
        target = str(submit["target"])
        if submit.get("kind") == "workflow":
            return FormSubmit(
                kind="workflow",
                workflow_target=target,
                workflow_inputs=_workflow_inputs(plan, target),
            )
        return FormSubmit(kind="dataSource", dataSource_target=target)
    return FormSubmit(kind="none")


# ── Convenience for callers that need dicts (e.g. runner service HTTP) ──


def to_dict(interaction: Interaction) -> dict:
    """Serialize an Interaction to a JSON-safe dict (for the runner API)."""
    return asdict(interaction)
