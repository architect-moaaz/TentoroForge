"""ComponentContract — the 5W+H envelope self-verify checks against.

Pure module. Reads the same four contract files the interaction
extractor reads (nav-flow / plan / per-page schemas / registry) and
emits one :class:`ComponentContract` per generated node (Page /
Button / Form / Table / Workflow / Entity / Detail).

Each contract carries six named slots:

  what   — the promise the component makes ("Books a class")
  who    — actor / role that can use it (auth + RBAC)
  where  — route + placement (nav location)
  when   — the trigger (click / submit / navigate / render / …)
  how    — the mechanism (workflow name, dataSource + entity, action)
  why    — the user job it fulfills (empty here; Slice 4 fills from
           BLUEPRINT.md)

Every slot is a :class:`WSlot` with:

  slot        — one of the six names (redundant with dict key; kept
                so the WSlot itself is self-describing when serialized)
  value       — human-readable claim
  verifiable  — can a probe mechanically decide pass/fail?
  source      — where the value came from
                ('schema' | 'plan' | 'nav-flow' | 'registry' |
                'blueprint' | '' for unfilled)

Slot presence is the contract. Runtime verification (Slice 2) turns
each verifiable slot into one probe.

Design principles
-----------------
* Pure function — no I/O beyond reading contract files.
* Best-effort — missing files degrade cleanly (module never raises).
* Deterministic — same input tree → same output list (sorted by
  (component_type, id)).
* Slot vocabulary is CLOSED. Adding a slot is a schema change, not a
  freeform extension.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal

logger = logging.getLogger(__name__)


# ── Types ────────────────────────────────────────────────────────────────


SlotName = Literal["what", "who", "where", "when", "how", "why"]
ComponentType = Literal[
    "page", "button", "form", "table",
    "workflow", "entity", "detail",
]
SlotSource = Literal[
    "schema", "plan", "nav-flow", "registry", "blueprint", "",
]


_SLOT_NAMES: tuple[SlotName, ...] = ("what", "who", "where", "when", "how", "why")


@dataclass(frozen=True)
class WSlot:
    """One filled (or empty) slot of a ComponentContract."""

    slot: SlotName
    value: str = ""
    verifiable: bool = False
    source: SlotSource = ""


@dataclass(frozen=True)
class ComponentContract:
    """The 5W+H contract for one generated node.

    ``route`` and ``node_selector`` are None for non-visual components
    (Workflow, Entity) — they don't live at a URL and have no DOM anchor.
    """

    id: str
    component_type: ComponentType
    label: str
    slots: dict[str, WSlot]
    route: str | None = None
    node_selector: str | None = None


# ── Public entry ─────────────────────────────────────────────────────────


def extract_component_contracts(output_dir: str | Path) -> list[ComponentContract]:
    """Read all four contract files and return the contract list.

    Missing files degrade to empty sub-lists (no pages, no workflows,
    no entities) — the caller always gets a well-typed list back.

    When ``product-brief.json`` / ``plan.json`` describe promises
    (persona jobs, page purposes, workflow purposes), the ``why`` slot
    on each affected contract is filled from
    :mod:`services.blueprint_promises`. SV-STRICT-4.
    """
    root = Path(output_dir)
    if not root.exists():
        return []

    nav = _read_json(root / "src" / "contracts" / "nav-flow.json")
    plan = _read_json(root / "src" / "contracts" / "plan.json")
    registry = _read_json(root / "registry.json")

    contracts: list[ComponentContract] = []
    contracts.extend(_pages_from_nav(nav))
    contracts.extend(_details_from_nav(nav))
    contracts.extend(_workflows_from_plan(plan))
    contracts.extend(_entities_from_registry(registry))
    contracts.extend(_widgets_from_schemas(root, nav))

    # SV-STRICT-4: fill `why` slots from the Promises set. Fail-open on
    # any error so the contract list itself always returns.
    try:
        from services.blueprint_promises import load_promises
        promises = load_promises(root)
        contracts = _fill_why_slots(contracts, promises)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[component_contract] why-slot fill skipped: %s", exc)

    contracts.sort(key=lambda c: (c.component_type, c.id))
    return contracts


def _fill_why_slots(contracts: list[ComponentContract],
                     promises: Any) -> list[ComponentContract]:
    """Return a new contract list with ``slots["why"]`` populated per Promises.

    Rules (deterministic):
      * ``page`` / ``detail`` contract → page_purposes[route]
      * ``workflow`` contract → workflow_purposes[label]
      * ``entity`` contract → any persona-job that names it in
        primary_entities (joined "; ")
    """
    page_purposes = promises.page_purposes or {}
    workflow_purposes = promises.workflow_purposes or {}
    persona_jobs = promises.persona_jobs or []

    # entity name → list of "persona: job" strings
    jobs_by_entity: dict[str, list[str]] = {}
    for j in persona_jobs:
        for ent in j.primary_entities:
            jobs_by_entity.setdefault(ent, []).append(
                f"{j.persona_name}: {j.job_label}"
            )

    updated: list[ComponentContract] = []
    for c in contracts:
        why_value = ""
        if c.component_type in ("page", "detail") and c.route:
            why_value = page_purposes.get(c.route, "")
        elif c.component_type == "workflow":
            why_value = workflow_purposes.get(c.label, "")
        elif c.component_type == "entity":
            lines = jobs_by_entity.get(c.label, [])
            why_value = "; ".join(lines)

        if not why_value:
            updated.append(c)
            continue

        new_slots = dict(c.slots)
        new_slots["why"] = WSlot(
            slot="why", value=why_value,
            verifiable=True, source="blueprint",
        )
        # ComponentContract is frozen — rebuild.
        from dataclasses import replace
        updated.append(replace(c, slots=new_slots))
    return updated


def to_dict(contract: ComponentContract) -> dict[str, Any]:
    """JSON-serializable dict — slots come out as nested dicts."""
    d = asdict(contract)
    # asdict already recurses; slot dict is already dict[str, dict].
    return d


# ── Helpers ──────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
        logger.warning("[component_contract] bad JSON at %s: %s", path, exc)
        return {}


def _empty_slots() -> dict[str, WSlot]:
    """Six empty slots; specific factories overwrite the ones they know."""
    return {name: WSlot(slot=name) for name in _SLOT_NAMES}


def _walk_nodes(node: Any) -> Iterator[dict]:
    """Yield every node dict in a schema tree."""
    if isinstance(node, list):
        for n in node:
            yield from _walk_nodes(n)
        return
    if not isinstance(node, dict):
        return
    yield node
    for v in node.values():
        yield from _walk_nodes(v)


def _route_requires_auth(nav: dict, route: str, shell: bool) -> bool:
    """Same rule as the interaction extractor: authGated + shell=True and
    not in the ``auth_routes`` allowlist."""
    if not nav.get("authGated"):
        return False
    if not shell:
        return False
    if route in set(nav.get("auth_routes") or []):
        return False
    return True


def _who_line(requires_auth: bool) -> str:
    return "signed-in users" if requires_auth else "public — any visitor"


# ── Factories ────────────────────────────────────────────────────────────


def _pages_from_nav(nav: dict) -> Iterator[ComponentContract]:
    for page in nav.get("pages") or []:
        route = page.get("route")
        if not route:
            continue
        shell = bool(page.get("shell", True))
        requires_auth = _route_requires_auth(nav, route, shell)
        title = page.get("title") or page.get("id") or route

        slots = _empty_slots()
        slots["what"] = WSlot("what",
                              f"Renders the {title} page.",
                              verifiable=True, source="nav-flow")
        slots["who"] = WSlot("who", _who_line(requires_auth),
                             verifiable=True, source="nav-flow")
        slots["where"] = WSlot("where",
                               f"lives at {route}",
                               verifiable=True, source="nav-flow")
        slots["when"] = WSlot("when",
                              "on_navigate — when the user visits the route",
                              verifiable=True, source="nav-flow")
        slots["how"] = WSlot("how",
                             f"schema file: {page.get('schemaFile') or '(none)'}",
                             verifiable=True, source="schema")
        # why remains empty until Slice 4 wires BLUEPRINT.

        yield ComponentContract(
            id=f"page:{route}",
            component_type="page",
            label=title,
            slots=slots,
            route=route,
            node_selector=None,
        )


def _details_from_nav(nav: dict) -> Iterator[ComponentContract]:
    """Any route containing a bracket param is also a `detail` contract.

    The `page` contract already covers "route reachable + auth OK". The
    detail contract carries the stricter promise: "given a valid :id in
    the URL, the page renders that record's data." Slice 2 turns that
    into a probe against a seeded row.
    """
    for page in nav.get("pages") or []:
        route = page.get("route") or ""
        if "[" not in route or "]" not in route:
            continue
        shell = bool(page.get("shell", True))
        requires_auth = _route_requires_auth(nav, route, shell)

        slots = _empty_slots()
        slots["what"] = WSlot("what",
                              f"Renders one record's detail view at {route}.",
                              verifiable=True, source="nav-flow")
        slots["who"] = WSlot("who", _who_line(requires_auth),
                             verifiable=True, source="nav-flow")
        slots["where"] = WSlot("where", f"lives at {route}",
                               verifiable=True, source="nav-flow")
        slots["when"] = WSlot("when",
                              "on_navigate — visited with a real id in the URL",
                              verifiable=True, source="nav-flow")
        slots["how"] = WSlot("how",
                             "resolves the id parameter and loads the record",
                             verifiable=True, source="schema")

        yield ComponentContract(
            id=f"detail:{route}",
            component_type="detail",
            label=page.get("title") or route,
            slots=slots,
            route=route,
            node_selector=None,
        )


def _workflows_from_plan(plan: dict) -> Iterator[ComponentContract]:
    for wf in plan.get("workflows") or []:
        name = wf.get("name")
        if not name:
            continue
        # Trigger can be dict ({"kind": "..."}) or a bare string ("form"/"manual"/…).
        raw_trigger = wf.get("trigger") or {}
        if isinstance(raw_trigger, dict):
            trigger = raw_trigger.get("kind") or "manual"
        elif isinstance(raw_trigger, str):
            trigger = raw_trigger or "manual"
        else:
            trigger = "manual"
        inputs = wf.get("inputs") or []
        input_summary = ", ".join(
            f"{i.get('name')}:{i.get('type')}" for i in inputs
        ) or "(no inputs)"

        slots = _empty_slots()
        slots["what"] = WSlot("what", f"Workflow {name} — runs a business process.",
                              verifiable=True, source="plan")
        # `who` is not typed in the plan schema yet — leave as verifiable=False
        # for now; the workflow contract's real access-control check
        # happens through the launching form/button's own contract.
        slots["who"] = WSlot("who",
                             "callable by any actor that can reach a launcher",
                             verifiable=False, source="plan")
        # Workflows aren't rendered anywhere — they're mechanism.
        slots["where"] = WSlot("where",
                               "not visual — dispatched from a form / button / event",
                               verifiable=False, source="plan")
        slots["when"] = WSlot("when",
                              f"trigger kind: {trigger}",
                              verifiable=True, source="plan")
        slots["how"] = WSlot("how",
                             f"inputs: {input_summary}",
                             verifiable=True, source="plan")

        yield ComponentContract(
            id=f"workflow:{name}",
            component_type="workflow",
            label=name,
            slots=slots,
            route=None,
            node_selector=None,
        )


def _entities_from_registry(registry: dict) -> Iterator[ComponentContract]:
    for entity_name, entity in (registry.get("entities") or {}).items():
        fields_dict = entity.get("fields") or {}
        field_count = len(fields_dict)

        slots = _empty_slots()
        slots["what"] = WSlot("what",
                              f"Data entity {entity_name} — a table in the database.",
                              verifiable=True, source="registry")
        slots["who"] = WSlot("who",
                             "readable/writable per the app's RBAC rules",
                             verifiable=False, source="registry")
        slots["where"] = WSlot("where",
                               "not visual — persisted in the database",
                               verifiable=False, source="registry")
        slots["when"] = WSlot("when",
                              "queried on page load; mutated by workflows",
                              verifiable=False, source="registry")
        slots["how"] = WSlot("how",
                             f"table with {field_count} columns",
                             verifiable=True, source="registry")

        yield ComponentContract(
            id=f"entity:{entity_name}",
            component_type="entity",
            label=entity_name,
            slots=slots,
            route=None,
            node_selector=None,
        )


def _widgets_from_schemas(root: Path, nav: dict) -> Iterator[ComponentContract]:
    """Walk every page schema and emit Button/Form/Table contracts."""
    for page in nav.get("pages") or []:
        route = page.get("route")
        if not route:
            continue
        schema_path = _resolve_schema_path(root, page)
        if not schema_path or not schema_path.exists():
            continue
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        shell = bool(page.get("shell", True))
        requires_auth = _route_requires_auth(nav, route, shell)
        page_who = _who_line(requires_auth)

        # dataSources index for Table `how` resolution
        ds_by_name = {
            (ds.get("name") or ""): ds
            for ds in (schema.get("dataSources") or [])
        }

        for node in _walk_nodes(schema.get("root") or {}):
            node_type = node.get("type")
            props = node.get("props") or {}

            if node_type == "Button":
                yield _button_contract(route, page_who, requires_auth, props)
            elif node_type == "Form":
                yield _form_contract(route, page_who, requires_auth, node)
            elif node_type == "Table":
                yield _table_contract(route, page_who, requires_auth,
                                       props, ds_by_name)


def _resolve_schema_path(root: Path, page: dict) -> Path | None:
    rel = page.get("schemaFile")
    if not rel:
        return None
    # `schemaFile` is always relative to output root.
    return root / rel


def _button_contract(route: str, page_who: str, requires_auth: bool,
                     props: dict) -> ComponentContract:
    label = props.get("label") or "(unlabeled button)"
    # Nav-action alias chain (matches Button.tsx).
    nav_target = (props.get("navigate") or props.get("trigger")
                  or props.get("to") or props.get("route")
                  or props.get("target") or props.get("href")
                  or props.get("path"))
    workflow_target = props.get("workflow")
    is_submit = bool(props.get("submit"))

    if workflow_target:
        how_line = f"dispatches workflow: {workflow_target}"
        what_line = f"'{label}' — starts the {workflow_target} workflow"
    elif nav_target:
        how_line = f"navigates to: {nav_target}"
        what_line = f"'{label}' — navigates to {nav_target}"
    elif is_submit:
        how_line = "submits the enclosing form"
        what_line = f"'{label}' — submits the form"
    else:
        how_line = "no action declared"
        what_line = f"'{label}' — no declared action"

    slots = _empty_slots()
    slots["what"] = WSlot("what", what_line, verifiable=True, source="schema")
    slots["who"] = WSlot("who", page_who,
                         verifiable=True, source="nav-flow")
    slots["where"] = WSlot("where", f"button on {route}",
                           verifiable=True, source="schema")
    slots["when"] = WSlot("when", "on_click — when the user clicks",
                          verifiable=True, source="schema")
    slots["how"] = WSlot("how", how_line, verifiable=True, source="schema")

    # A stable, route-scoped, label-scoped id so probes can join to it.
    slug = _slugify(label)
    return ComponentContract(
        id=f"button:{route}:{slug}",
        component_type="button",
        label=label,
        slots=slots,
        route=route,
        node_selector=f"[data-testid='button-{slug}']",
    )


def _form_contract(route: str, page_who: str, requires_auth: bool,
                   node: dict) -> ComponentContract:
    props = node.get("props") or {}
    label = props.get("title") or props.get("submitLabel") or "Form"
    workflow_target = props.get("workflow")
    ds_target = props.get("dataSource")

    if workflow_target:
        how_line = f"dispatches workflow: {workflow_target}"
        what_line = f"submits inputs to the {workflow_target} workflow"
    elif ds_target:
        how_line = f"writes to dataSource: {ds_target}"
        what_line = f"submits inputs to the {ds_target} data source"
    else:
        how_line = "no submit target declared"
        what_line = "form with no declared submit target"

    slots = _empty_slots()
    slots["what"] = WSlot("what", what_line, verifiable=True, source="schema")
    slots["who"] = WSlot("who", page_who, verifiable=True, source="nav-flow")
    slots["where"] = WSlot("where", f"form on {route}",
                           verifiable=True, source="schema")
    slots["when"] = WSlot("when", "on_submit — when the user submits",
                          verifiable=True, source="schema")
    slots["how"] = WSlot("how", how_line, verifiable=True, source="schema")

    slug = _slugify(label)
    return ComponentContract(
        id=f"form:{route}:{slug}",
        component_type="form",
        label=label,
        slots=slots,
        route=route,
        node_selector=f"[data-testid='form-{slug}']",
    )


def _table_contract(route: str, page_who: str, requires_auth: bool,
                    props: dict, ds_by_name: dict[str, dict]) -> ComponentContract:
    label = props.get("title") or "Table"
    rows_binding = props.get("rows") or ""
    ds_name = ""
    if isinstance(rows_binding, str) and rows_binding.startswith("{{"):
        # {{name}} or {{name.x[0]}} — take the head.
        head = rows_binding.strip("{}").strip()
        ds_name = head.split(".")[0].split("[")[0]
    ds = ds_by_name.get(ds_name) if ds_name else None
    entity = (ds or {}).get("entity") if ds else None

    if ds_name and entity:
        how_line = f"binds to dataSource '{ds_name}' (entity: {entity})"
        what_line = f"renders rows from {entity} via '{ds_name}'"
    elif ds_name:
        how_line = f"binds to dataSource '{ds_name}' (entity unresolved)"
        what_line = f"renders rows from '{ds_name}'"
    else:
        how_line = "no dataSource binding"
        what_line = "table with no data binding"

    slots = _empty_slots()
    slots["what"] = WSlot("what", what_line, verifiable=True, source="schema")
    slots["who"] = WSlot("who", page_who, verifiable=True, source="nav-flow")
    slots["where"] = WSlot("where", f"table on {route}",
                           verifiable=True, source="schema")
    slots["when"] = WSlot("when",
                          "on_render — populated when the page loads",
                          verifiable=True, source="schema")
    slots["how"] = WSlot("how", how_line, verifiable=True, source="schema")

    slug = _slugify(ds_name or label)
    return ComponentContract(
        id=f"table:{route}:{slug}",
        component_type="table",
        label=label,
        slots=slots,
        route=route,
        node_selector=f"[data-testid='table-{slug}']",
    )


# ── Small utility ────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    return (
        "".join(c.lower() if c.isalnum() else "-" for c in (text or ""))
        .strip("-")
        .replace("--", "-")
    ) or "unlabeled"
