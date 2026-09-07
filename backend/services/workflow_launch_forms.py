"""Trigger-input-form generator for BARE-button workflow launchers.

Problem
-------
A manual-triggered domain workflow (e.g. `InterviewSchedulingWorkflow`) whose
ENTRY action is a `db_insert` can be launched by a BARE Button
(`props.workflow=<slug>`, NOT inside a Form). A bare Button dispatches with an
EMPTY payload, so the insert's `{{applicationId}}`/`{{scheduledAt}}` bindings
resolve to null → NOT-NULL violation at runtime.

Fix
---
For every such launcher we generate a small "trigger input form" page that
collects the workflow's required inputs (the insert's columns, mapped to the same
inputs the deterministic CRUD form uses — FK→Select, date→DatePicker, required→
validators) and repoint the launcher button to NAVIGATE to that form. A
`<Form workflow="X">` collects its named field values and dispatches
`dispatch("X", values)`; the engine seeds those into `ctx.variables` so `{{col}}`
resolves. The dispatch mechanism already works — we only add the input form.

Public API: `ensure_workflow_launch_forms(output_dir, registry) -> list[str]`,
returning the run-page routes created/updated. Idempotent (a launcher already
carrying `props.navigate` is left alone).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from services.deterministic_pages import (
    _SYSTEM,
    _editable_columns,
    _gap,
    _input_for,
    _resolve_target,
)
from services.fk_semantics import default_hidden_fk_norms
from services.plan_field_lookup import load_plan


def _plan_workflow_inputs(plan: dict | None, wf_name: str) -> list[str] | None:
    """Return the plan's declared trigger `inputs` for a workflow, or None.

    Match on the workflow's `name` case-insensitively across
    ``plan.workflows`` (both dict and list flavours). ``None`` means the
    plan is silent — caller must fall through to insert-value derivation.
    An empty list is treated as None (a mis-emitted `inputs: []` shouldn't
    strip the form to zero fields — that's clearly a plan defect).
    """
    if not isinstance(plan, dict) or not wf_name:
        return None
    wfs = plan.get("workflows")
    target = wf_name.strip().lower()

    def _pick(entry: dict) -> list[str] | None:
        if not isinstance(entry, dict):
            return None
        n = str(entry.get("name") or "").strip().lower()
        if n != target:
            return None
        raw = entry.get("inputs") or entry.get("trigger_inputs")
        if not isinstance(raw, list) or not raw:
            return None
        cols: list[str] = []
        for r in raw:
            if isinstance(r, str) and r.strip():
                cols.append(r.strip())
            elif isinstance(r, dict):
                nm = r.get("name") or r.get("column")
                if isinstance(nm, str) and nm.strip():
                    cols.append(nm.strip())
        return cols or None

    if isinstance(wfs, list):
        for e in wfs:
            v = _pick(e)
            if v:
                return v
    if isinstance(wfs, dict):
        for e in wfs.values():
            v = _pick(e)
            if v:
                return v
    return None

# Conservative name-based hidden-FK default (actor/tenancy). A launch form collects
# user-supplied inputs, so these server-filled FKs are never fields. Domain FKs are not
# in this set and are kept (the CRUD editable-column filter handles them).
_DEFAULT_HIDDEN_FK = default_hidden_fk_norms()

_CRUD_NAME_RE = re.compile(r"^(create|update|delete)", re.I)
_PAYLOAD_REF_RE = re.compile(r"^\s*\{\{\s*([A-Za-z0-9_]+)\s*\}\}\s*$")


def _is_payload_ref(binding, col: str) -> bool:
    """True when the insert binds `col` to its OWN dispatch-payload variable, i.e.
    `"{{col}}"` — meaning the workflow REQUIRES the user to supply this value (as
    opposed to `{{currentUser.id}}`/`{{now}}`, which the engine provides). Such a
    column must be collected on the launch form even if a generic CRUD filter would
    drop it (e.g. a NOT-NULL `scheduledAt` timestamp)."""
    if not isinstance(binding, str):
        return False
    m = _PAYLOAD_REF_RE.match(binding)
    return bool(m) and m.group(1).lower() == col.lower()


def _keep_input_col(col: str, meta: dict, binding) -> bool:
    """Whether an insert column becomes a launch-form field. Drops PK/system/owner-FK
    always; otherwise keeps anything the CRUD editable-column filter keeps, PLUS
    self-referential `{{col}}` payload bindings the filter would drop only because
    they look like a lifecycle timestamp (the workflow still needs them seeded)."""
    low = col.lower()
    if meta.get("primaryKey") or low in _SYSTEM or _norm(col) in _DEFAULT_HIDDEN_FK:
        return False
    if _editable_columns({col: meta}):
        return True
    return _is_payload_ref(binding, col)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ── workflow loading / lookup ────────────────────────────────────────────────

def _load_workflows(output_dir: Path) -> dict:
    """Map every workflow by BOTH its `id` (slug) and a slug of its `name`, so a
    button's `props.workflow` (usually the slug like `interviewschedulingworkflow`)
    resolves regardless of which identifier the launcher used."""
    wf_dir = output_dir / "workflows"
    out: dict[str, dict] = {}
    if not wf_dir.is_dir():
        return out
    for fn in sorted(wf_dir.glob("*.json")):
        try:
            wf = json.loads(fn.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a bad file must not break the pass
            continue
        if not isinstance(wf, dict):
            continue
        for key in (wf.get("id"), wf.get("name"), fn.stem):
            if isinstance(key, str) and key:
                out.setdefault(_norm(key), wf)
    return out


def _node_config(node: dict) -> dict:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else node.get("config")
    return config if isinstance(config, dict) else {}


def _entry_action_node(wf: dict) -> dict | None:
    """The workflow's ENTRY action node — the FIRST node of type `action` reached by
    walking from the trigger along outgoing default/then edges (skipping the trigger
    and any gateways). This is the action that runs first on dispatch.

    Falls back to the first `action` node in `definition.nodes` only when the graph
    can't be walked (no trigger or no usable edges), so a downstream db_insert (audit
    log / notification) is never mistaken for the entry action."""
    definition = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
    nodes = definition.get("nodes") or wf.get("nodes") or []
    node_by_id = {n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")}
    edges = definition.get("edges") or wf.get("edges") or []

    out_edges: dict[str, list[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        src, tgt = e.get("source"), e.get("target")
        etype = str((e.get("data") or {}).get("edgeType") or "default")
        if src and tgt and etype in ("default", "then"):
            out_edges.setdefault(src, []).append(tgt)

    trigger = next((n for n in nodes
                    if isinstance(n, dict) and n.get("type") == "trigger"), None)
    if trigger and out_edges:
        cur = trigger.get("id")
        visited: set[str] = set()
        while cur and cur not in visited:
            visited.add(cur)
            node = node_by_id.get(cur)
            if node is not None and node.get("type") == "action":
                return node  # authoritative: first action reachable from the trigger
            nxts = out_edges.get(cur) or []
            cur = nxts[0] if nxts else None

    # Graph not walkable — fall back to declaration order.
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "action":
            return n
    return None


def _entry_insert_config(wf: dict) -> dict | None:
    """The entry action's config IF it is a `db_insert`, else None. A workflow whose
    entry action is a db_update/ai_*/etc. is NOT a launch-form candidate — repointing
    it would destroy its real dispatch (e.g. an approval acting on an existing row)."""
    node = _entry_action_node(wf)
    if node is None:
        return None
    config = _node_config(node)
    if str(config.get("actionType")) == "db_insert":
        return config
    return None


# ── entity resolution ────────────────────────────────────────────────────────

def _resolve_entity(sql_table: str, entities: dict) -> tuple[str | None, dict]:
    """Map an insert's `table` (SQL table) → (entity name, fields dict). Prefer an
    entity whose `table` matches exactly, else match by snake/plural of the name."""
    want = _norm(sql_table)
    for name, info in (entities or {}).items():
        info = info or {}
        if _norm(info.get("table") or "") == want:
            return name, (info.get("fields") or {})
    for name, info in (entities or {}).items():
        n = _norm(name)
        if want in (n, n + "s", want.rstrip("s")) or n == want.rstrip("s"):
            return name, ((info or {}).get("fields") or {})
    return None, {}


# ── route / verb derivation ──────────────────────────────────────────────────

def _launch_verb(name: str, wf_slug: str) -> str:
    """A deterministic launch verb from the workflow name."""
    low = (name or "").lower()
    for kill in ("workflow", "process", "flow"):
        low = low.replace(kill, "")
    if "schedul" in low:
        return "schedule"
    if "assign" in low:
        return "assign"
    if "approv" in low:
        return "approve"
    if "review" in low:
        return "review"
    if "generat" in low:
        return "generate"
    return wf_slug


def _seg_for(schema_slug: str, entity: str, sql_table: str) -> str:
    """The list segment to root the run-page under: the launcher schema's own first
    segment when it maps to the target entity, else the (already-plural) SQL table."""
    first = (schema_slug or "").split("/")[0]
    if first:
        want = {_norm(entity), _norm(entity) + "s", _norm(sql_table)}
        if _norm(first) in want:
            return first
    return sql_table


def _humanize_wf(name: str) -> str:
    s = re.sub(r"(?i)workflow$", "", name or "").strip()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s).strip()
    return s or (name or "Run")


# ── run-page builder ─────────────────────────────────────────────────────────

def _build_run_page(*, workflow_slug: str, wf_name: str, route: str, seg: str,
                    verb: str, field_nodes: list[dict], entities: dict) -> dict:
    gap = _gap(None)
    # FK option sources — one list dataSource per Select(optionsFrom.source).
    sources: list[dict] = []
    for node in field_nodes:
        of = node["props"].get("optionsFrom") if node.get("type") == "Select" else None
        if isinstance(of, dict) and of.get("source"):
            src = of["source"]
            if not any(s["name"] == src for s in sources):
                ent = _resolve_target(src, entities)[0] or (
                    src[:-1].capitalize() if src.endswith("s") else src.capitalize())
                sources.append({"name": src, "entity": ent, "op": "list"})

    submit_label = verb[:1].upper() + verb[1:]
    body: dict
    if len(field_nodes) >= 7 and gap != "tokens.spacing.2":
        body = {"type": "Grid", "props": {"columns": 2, "gap": gap}, "children": field_nodes}
    else:
        body = {"type": "Stack", "props": {"gap": gap}, "children": field_nodes}

    buttons = {"type": "Row", "props": {"gap": "tokens.spacing.2", "justify": "end"}, "children": [
        {"type": "Button", "props": {"label": "Cancel", "variant": "ghost", "navigate": f"/{seg}"}},
        {"type": "Button", "props": {"label": submit_label, "variant": "primary", "submit": True}},
    ]}

    # Post-dispatch UX: success → toast + navigate to the parent list;
    # failure → toast + stay on the form so the user can retry. Both
    # match the runtime defaults in packages/library Form.tsx; setting
    # them explicitly here means the schema is self-documenting and any
    # editor session that touches the schema sees what will happen.
    parent_route = f"/{seg}"
    success_msg = f"{_humanize_wf(wf_name)} — done"
    failure_msg = f"Couldn't {verb.lower()} — please try again"

    page = {
        "schemaVersion": "2",
        "id": f"{seg}-{verb}",
        "route": route,
        "layout": "main",
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": [
            {"type": "Heading", "props": {"content": _humanize_wf(wf_name), "level": 1}},
            {"type": "Card", "children": [
                {"type": "Form", "props": {
                    "workflow": workflow_slug,
                    "submitLabel": submit_label,
                    "onSuccess": {"toast": success_msg, "navigate": parent_route},
                    "onError":   {"toast": failure_msg},
                },
                 "children": [{"type": "Stack", "props": {"gap": gap}, "children": [body, buttons]}]},
            ]},
        ]},
    }
    if sources:
        page["dataSources"] = sources
    return page


# ── launcher discovery ───────────────────────────────────────────────────────

def _collect_launchers(schema: dict) -> list[dict]:
    """Every bare workflow-launcher Button node in a page: a Button carrying
    `props.workflow`, NOT inside a Form, and not already repointed (`props.navigate`).
    Returns the mutable node dicts so callers can repoint them in place."""
    found: list[dict] = []

    def walk(node, in_form: bool) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, in_form)
            return
        if not isinstance(node, dict):
            return
        here_form = in_form or node.get("type") == "Form"
        if node.get("type") == "Button" and not in_form:
            p = node.get("props")
            if isinstance(p, dict) and p.get("workflow") and not p.get("navigate"):
                found.append(node)
        # Walk EVERY nested value, not just `children` / `root`.
        #
        # Real schemas nest components under many keys — a Table's
        # `rowActions`, a column `cell`, `items`, `slots`, `props.actions`. The
        # walker only descended `children` and `root`, so a launcher button in
        # any of those was never discovered and never repointed at its form:
        # the button stayed bare and dispatching it did nothing (register
        # LF-1). Skipping only `props` scalars keeps this cheap.
        for key, val in node.items():
            if key in ("children", "root"):
                continue
            if isinstance(val, (dict, list)):
                walk(val, here_form)
        for c in node.get("children") or []:
            walk(c, here_form)
        if "root" in node:
            walk(node["root"], here_form)

    root = schema.get("root") if isinstance(schema, dict) and "root" in schema else schema
    walk(root, False)
    return found


# ── public API ───────────────────────────────────────────────────────────────

def ensure_workflow_launch_forms(output_dir: str, registry: dict) -> list[str]:
    """Generate trigger-input-form pages for bare-button workflow launchers whose
    entry action is a db_insert, and repoint each launcher to navigate to its form.
    Returns the list of run-page routes created/updated. Idempotent."""
    out = Path(output_dir)
    schemas_root = out / "src" / "schemas"
    if not schemas_root.exists():
        return []
    workflows = _load_workflows(out)
    entities = (registry or {}).get("entities") or {}
    plan = load_plan(str(out))

    created: list[str] = []
    # route -> the workflow slug that owns it (for uniqueness against DIFFERENT wfs)
    route_owner: dict[str, str] = {}
    # each launch form's incoming edge (for the nav-flow registration below):
    # (form_route, source_page_route, button_label). Multiple entries may share
    # form_route when TWO launchers on different pages point at the same form.
    launcher_edges: list[tuple[str, str, str]] = []
    for existing in schemas_root.rglob("*.json"):
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        r = data.get("route")
        wf = None
        forms = []
        _find(data.get("root"), "Form", forms)
        if forms:
            wf = forms[0].get("props", {}).get("workflow")
        if isinstance(r, str):
            route_owner[r] = _norm(wf) if isinstance(wf, str) else route_owner.get(r, "")

    for schema_file in sorted(schemas_root.rglob("*.json")):
        try:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        launchers = _collect_launchers(schema)
        if not launchers:
            continue
        schema_slug = str(schema_file.relative_to(schemas_root).with_suffix("")).replace("\\", "/")
        modified = False

        for node in launchers:
            props = node["props"]
            wf_slug_raw = props.get("workflow")
            wf = workflows.get(_norm(wf_slug_raw))
            if not wf:
                continue
            wf_name = str(wf.get("name") or "")
            if _CRUD_NAME_RE.match(wf_name.strip()):
                continue
            insert = _entry_insert_config(wf)
            # Slice A T6: when the workflow has no db_insert entry step,
            # fall back to plan-declared workflow inputs. Previously
            # skipped, which meant domain workflows (parseCV, submitFeedback,
            # anything with an ai_extract or external-api entry) never got
            # a launcher form despite having a full input contract.
            if not insert:
                plan_inputs = _plan_workflow_inputs(plan, wf_name)
                if not plan_inputs:
                    continue   # nothing to build a form from — genuinely skip
                sql_table = ""
                entity, fields = "", {}
            else:
                sql_table = str(insert.get("table") or "")
                entity, fields = _resolve_entity(sql_table, entities)
                # Slice A T6: when the entity resolves to None (e.g. the
                # workflow inserts into a domain-owned side table not in
                # our registry), still try to build the form from plan
                # inputs before falling out.
                if not entity or not isinstance(fields, dict):
                    plan_inputs = _plan_workflow_inputs(plan, wf_name)
                    if not plan_inputs:
                        continue
                    entity, fields = "", {}

            # Column-source order:
            #   0. Plan-declared workflows[].inputs — authoritative when present.
            #      When the plan lists trigger inputs, THAT set drives the form
            #      (verbatim, in order). Kills Bug 5: Schedule Interview shipped
            #      with only Status because the workflow's `insert.values` merely
            #      referenced `{{applicationId}}` while its actual required
            #      inputs (interviewer, time, location) lived in the plan.
            #   1. insert.values keys — the workflow's declared writes, filtered
            #      by editable-column rules (drops PK/system/owner-FK/lifecycle).
            values = insert.get("values") or {}
            plan_cols = _plan_workflow_inputs(plan, wf_name)
            source_cols: list[str] = list(plan_cols) if plan_cols else list(values.keys())

            kept: list[tuple[str, dict]] = []
            for col in source_cols:
                meta = fields.get(col)
                if meta is None:
                    continue
                meta = meta if isinstance(meta, dict) else {}
                # When the plan owns the column list, we trust it entirely —
                # skipping only obviously system columns. Legacy path keeps the
                # full editable-column filter over insert.values.
                if plan_cols:
                    if _norm(col) in _SYSTEM:
                        continue
                    kept.append((col, meta))
                elif _keep_input_col(col, meta, values.get(col)):
                    kept.append((col, meta))
            if not kept:
                continue
            field_nodes = [_input_for(c, m, entities) for c, m in kept]

            seg = _seg_for(schema_slug, entity, sql_table or entity.lower())
            verb = _launch_verb(wf_name, _norm(wf_slug_raw) or "run")
            # SINGLE-segment route (no second `/`). A 2-segment `/seg/verb` route is
            # captured by the entity's `/[id]` detail pattern on CLIENT navigation
            # (id="verb") and opens a phantom-record detail drawer instead of the form.
            # A one-segment route is served by `[entity]/page.tsx` (the list route), which
            # has no `[id]` sub-pattern, so client navigation renders the form. `seg` is
            # still used for the form's Cancel/back link to the entity list.
            base_route = f"/{verb}-{entity.lower()}"
            route = base_route
            n = 2
            wf_key = _norm(wf_slug_raw)
            # A route is reusable ONLY when THIS workflow already owns it (two launchers
            # → one workflow → one shared form). An empty-owner route is a pre-existing
            # NON-workflow page and a different-workflow owner is someone else's form —
            # both are occupied, so never overwrite them: pick the next suffixed route.
            while route in route_owner and route_owner[route] != wf_key:
                route = f"{base_route}-{n}"
                n += 1
            slug_path = route.lstrip("/")

            page = _build_run_page(
                workflow_slug=wf_slug_raw, wf_name=wf_name, route=route,
                seg=seg, verb=verb, field_nodes=field_nodes, entities=entities)
            page_file = schemas_root / f"{slug_path}.json"
            page_file.parent.mkdir(parents=True, exist_ok=True)
            page_file.write_text(json.dumps(page, indent=2), encoding="utf-8")
            route_owner[route] = wf_key
            created.append(route)

            # Repoint the launcher IN PLACE: drop the dispatch, navigate to the form.
            btn_label = str(props.get("label") or props.get("children") or "").strip()
            props.pop("workflow", None)
            props.pop("args", None)
            props["navigate"] = route
            modified = True

            # Record the incoming edge for the nav-flow registration below. The
            # source page's route is whatever the schema declares; fall back to
            # deriving it from the schema slug when absent (shouldn't happen for
            # real pages but keeps the recorder defensive).
            src_route = schema.get("route") if isinstance(schema.get("route"), str) else f"/{schema_slug}"
            launcher_edges.append((route, src_route, btn_label or _launch_verb(wf_name, _norm(wf_slug_raw) or "run").title()))

        if modified:
            schema_file.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    if created:
        # Guarded: this import pulls in the whole schema pipeline, and it runs
        # AFTER the writes above (register LF-2). An ImportError here — a
        # circular import, a missing optional dep — would abort the function
        # with the new pages already on disk but the route registry never
        # regenerated, leaving the app half-wired with no explanation.
        try:
            from services.schema_pipeline import _regenerate_route_registry
            _regenerate_route_registry(str(out))
        except Exception as e:  # noqa: BLE001
            logger.error(
                "workflow_launch_forms: created %d launch page(s) but could NOT "
                "regenerate the route registry (%s). The pages exist on disk and "
                "are not yet routable — re-run the route registry step.",
                len(created), e,
            )

    # Register launch-form pages + incoming button-edges in nav-flow.json so the
    # editor graph, the launcher button, and the schema on disk all agree. Runs
    # even when nothing new was created this pass — a launcher repointed on an
    # EARLIER run leaves nav-flow out of sync, and the reconcile step below finds
    # those retroactively. Never crashes.
    try:
        edges = list(launcher_edges)
        edges.extend(_reconcile_existing_launch_form_edges(out, schemas_root, launcher_edges))
        if edges:
            _register_launch_forms_in_nav_flow(out, edges)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("nav-flow launch-form registration skipped: %s", e)
    # Dedupe (two launchers → one shared form route) while preserving order, so a
    # caller counting `applied` doesn't double-count a single generated page.
    return list(dict.fromkeys(created))


def _iter_buttons(schema: dict):
    """Walk every Button node in a schema and yield its props dict."""
    def walk(n):
        if isinstance(n, list):
            for x in n: yield from walk(x)
        elif isinstance(n, dict):
            if n.get("type") == "Button" and isinstance(n.get("props"), dict):
                yield n["props"]
            for v in n.values(): yield from walk(v)
    yield from walk(schema)


def _reconcile_existing_launch_form_edges(
    out_dir: Path, schemas_root: Path, already_recorded: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Find launch-form navigations that a PREVIOUS run of this pass already made
    but never registered in nav-flow.json. A button whose ``props.navigate`` points
    at an app-local route that has a schema file — and whose target route isn't
    already in nav-flow's pages — is a retroactive launcher edge. Idempotent."""
    nav_path = out_dir / "src" / "contracts" / "nav-flow.json"
    known_routes: set[str] = set()
    if nav_path.exists():
        try:
            nav = json.loads(nav_path.read_text(encoding="utf-8"))
            for p in (nav.get("pages") or []):
                if isinstance(p, dict) and p.get("route"):
                    known_routes.add(str(p["route"]))
        except (OSError, ValueError):
            pass

    seen = {(f, s, l) for (f, s, l) in already_recorded}
    extras: list[tuple[str, str, str]] = []
    for schema_file in sorted(schemas_root.rglob("*.json")):
        try:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src_route = schema.get("route") if isinstance(schema.get("route"), str) else None
        if not src_route:
            continue
        for props in _iter_buttons(schema):
            nav = props.get("navigate")
            if not isinstance(nav, str) or not nav.startswith("/"):
                continue
            # Route stem (ignore /{{...}} params) → mapped to a schema file we can find on disk.
            stem = nav.split("/{{", 1)[0].split("/[", 1)[0].rstrip("/")
            if not stem or stem in known_routes:
                continue
            target_slug = stem.lstrip("/")
            target_file = schemas_root / f"{target_slug}.json"
            if not target_file.exists():
                continue
            # It's a real page, missing from nav-flow → record the edge.
            label = str(props.get("label") or props.get("children") or "").strip() or "launch"
            key = (stem, src_route, label)
            if key in seen:
                continue
            seen.add(key)
            extras.append(key)
    return extras


def _register_launch_forms_in_nav_flow(out_dir: Path, edges: list[tuple[str, str, str]]) -> None:
    """Upsert a page node + an incoming button-edge for each launch form into
    ``src/contracts/nav-flow.json``. Idempotent: existing nodes/edges (same id or
    same (from,trigger,to)) are not duplicated. If nav-flow.json doesn't exist, we
    synthesize it from schemas first so no consumer sees a partial graph."""
    if not edges:
        return
    from services.nav_flow_from_schemas import ensure_nav_flow
    from services.nav_flow_from_plan import _slug_from_route, _schema_file_from_route, _humanize

    ensure_nav_flow(out_dir)  # create-if-missing, idempotent
    nav_path = out_dir / "src" / "contracts" / "nav-flow.json"
    if not nav_path.exists():
        return  # no schemas at all — nothing to register against
    try:
        nav = json.loads(nav_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    pages = nav.setdefault("pages", [])
    transitions = nav.setdefault("transitions", [])

    # Existing indices for idempotency.
    by_route: dict[str, dict] = {str(p.get("route")): p for p in pages if isinstance(p, dict)}
    edge_keys: set[tuple[str, str, str]] = set()
    for t in transitions:
        if isinstance(t, dict):
            edge_keys.add((str(t.get("from") or ""), str(t.get("trigger") or ""), str(t.get("to") or "")))

    def _next_edge_id() -> str:
        n = len(transitions) + 1
        while any(isinstance(t, dict) and t.get("id") == f"t-{n}" for t in transitions):
            n += 1
        return f"t-{n}"

    for form_route, src_route, btn_label in edges:
        # Upsert the launch-form page node (idempotent on route).
        if form_route not in by_route:
            slug = _slug_from_route(form_route)
            node = {
                "id": slug,
                "route": form_route,
                "title": _humanize(slug),
                "schemaFile": _schema_file_from_route(form_route),
                "layout": None,
                "guard": None,
                "params": [],
                "shell": True,
            }
            pages.append(node)
            by_route[form_route] = node
        target_id = by_route[form_route].get("id") or _slug_from_route(form_route)

        # Find the source page's node id — bail on the edge if the source isn't
        # in the graph (a shell-only or synthetic source would confuse consumers).
        src_node = by_route.get(src_route)
        if not src_node:
            continue
        source_id = src_node.get("id") or _slug_from_route(src_route)

        trigger = f"button:{btn_label}" if btn_label else "button:launch"
        key = (source_id, trigger, target_id)
        if key in edge_keys:
            continue
        transitions.append({
            "id": _next_edge_id(),
            "from": source_id,
            "trigger": trigger,
            "to": target_id,
            "navType": "link",
        })
        edge_keys.add(key)

    nav_path.write_text(json.dumps(nav, indent=2), encoding="utf-8")


def _find(node, typ, acc):
    if isinstance(node, list):
        for n in node:
            _find(n, typ, acc)
    elif isinstance(node, dict):
        if node.get("type") == typ:
            acc.append(node)
        for c in node.get("children") or []:
            _find(c, typ, acc)
        if "root" in node:
            _find(node["root"], typ, acc)
    return acc
