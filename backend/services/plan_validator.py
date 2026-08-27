"""Deterministic plan validator — the 8 cross-cutting rules from the
V2 spec, enforced in Python (not by asking the LLM to self-check).

Runs AFTER the planner returns, BEFORE the plan is committed to
downstream generation. Same shape as :mod:`services.patch_coherence`:
return a list of violations, empty on pass. The caller decides whether
to reject + retry or just log.

Design principle: check what the DOWNSTREAM PIPELINE CAN'T DO but the
planner might get away with. Things like "field name is valid" — the
LLM's own attention handles that. Things like "every foreign key
resolves to a real entity" — the LLM WILL slip and the pipeline WILL
blow up on it. Those go here.

The rules mirror §40 of the V2 spec, trimmed to the ones we've
watched fail in real generations this quarter:

1.  Every ``dataModels[].fields[].name`` is unique within its entity.
2.  Every ``relations[].from`` and ``relations[].to`` names an entity
    that exists in ``dataModels``.
3.  Every ``relations[].foreignKey`` names a field that exists on
    ``from`` (or is a plausible convention like ``entityId``).
4.  Every actor FK (``userId``, ``assigneeId``, ``createdById`` …) has
    a relation pointing at ``User``.
5.  Every ``pages[].entity`` names an entity that exists (or is
    ``null`` for entity-free pages like ``dashboard``).
6.  Every ``pages[].archetype`` is in the closed set the deterministic
    builder actually handles.
7.  Every workflow node's ``next`` / ``branches`` target a node that
    exists in the same workflow. Gateways use ``branches``, non-
    gateway/non-end nodes use ``next``. Every workflow has exactly
    one ``trigger`` and one ``end``.
8.  Every ``pages[].actions[].workflow`` names a workflow defined in
    ``workflows[]`` (when the plan carries workflows at all).

Not checked here (out of scope for THIS layer):

* Semantic correctness of a workflow's business logic.
* Field types match SQL constraints (schema_builder does that).
* Access-control coverage (a follow-up rule set — currently a warning
  in downstream guards, not a plan-level check).
"""
from __future__ import annotations

import re
from typing import Any


# The archetype set the deterministic builder actually handles today.
# Source of truth: services/deterministic_pages.py build_crud_page +
# build_dashboard_page. Everything else falls through to the LLM
# fallback and, empirically, misfires often enough to be worth
# flagging at plan time.
_VALID_ARCHETYPES: set[str] = {
    "list", "form", "create", "edit", "detail",
    "kanban", "calendar", "dashboard",
    # Archetype-specific page types the planner emits via page_type_templates.
    # Must stay in sync with _TEMPLATES in backend/services/page_type_templates.py
    # — a page type there that isn't here forces the REVISE loop to strip the
    # archetype label off the page, which then misses the template lookup.
    "auth", "error", "inbox", "report", "wizard",
    "audit-log", "timeline", "settings", "computational",
    "visual_scan", "retail_sources_admin",
}

# Column-name patterns that CONVENTIONALLY refer to a User row.
# Used by rule 4 to spot actor FKs that should relate to User.
_ACTOR_FK_RE = re.compile(
    r"^("
    r"(?:created|updated|submitted|approved|rejected|assigned|"
    r"reviewed|posted|uploaded)"
    r"By"
    r"|assignee|owner|manager|reporter|reviewer|approver|actor"
    r"|user"
    r")Id$",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def validate_plan(plan: dict | None) -> list[dict]:
    """Run every rule and return a flat list of violations.

    Each violation::

        {"rule":     "fk_target_missing" | ...,
         "severity": "error" | "warning",
         "message":  "<one-liner naming what's wrong and where>",
         "location": <plan JSONPath-ish string for the caller to grep>}

    Empty list = the plan passes every rule. Never raises; a
    malformed plan (wrong shape) still returns violations, not an
    exception, so callers can use the result to build a retry prompt.
    """
    if not isinstance(plan, dict):
        return [{
            "rule": "shape", "severity": "error",
            "message": "plan is not a JSON object",
            "location": "$",
        }]

    entities = _entities_by_name(plan)
    violations: list[dict] = []
    violations.extend(_rule_entity_lifecycle(plan, entities))
    violations.extend(_rule_unique_field_names(plan, entities))
    violations.extend(_rule_relation_endpoints(plan, entities))
    violations.extend(_rule_relation_fks(plan, entities))
    violations.extend(_rule_actor_fk_relations(plan, entities))
    violations.extend(_rule_page_entities(plan, entities))
    violations.extend(_rule_page_archetypes(plan))
    violations.extend(_rule_workflow_connectivity(plan))
    violations.extend(_rule_page_action_workflows(plan))
    violations.extend(_rule_workflow_input_coverage(plan))
    violations.extend(_rule_launcher_supplies_record_inputs(plan))
    violations.extend(_rule_workflow_entity_has_page(plan))
    violations.extend(_rule_actors(plan))
    # Completeness contract — the plan must be authoritative for downstream
    # construction. Warnings today (so existing plans don't break); flip to
    # errors once observed emission is reliable.
    violations.extend(_rule_field_completeness(plan, entities))
    violations.extend(_rule_money_currency_alias(plan, entities))
    violations.extend(_rule_sensitive_columns(plan, entities))
    violations.extend(_rule_search_columns(plan, entities))
    violations.extend(_rule_workflow_inputs_declared(plan))
    violations.extend(_rule_nav_completeness(plan))
    # Slice A T3 — SUBMIT-AUTHORITY rules. Warnings-only for now so
    # existing plans keep validating; flip severity to "error" once T2's
    # normalizer + prompt guidance land in enough live runs to trust
    # the LLM emits the contract shapes.
    violations.extend(_rule_forms_have_submit(plan, entities))
    violations.extend(_rule_workflows_have_source(plan))
    violations.extend(_rule_input_sources_resolve(plan))
    # Slice E T6 — workflow_resume submit kind (task-completion forms).
    violations.extend(_rule_workflow_resume_task_id(plan))
    return violations


def format_violations_for_retry(violations: list[dict]) -> str:
    """Render the violation list as an instruction Smith / the planner
    can read in a follow-up turn. Numbered, terse, actionable."""
    if not violations:
        return ""
    lines = [
        "The plan you produced has the following validation errors. "
        "Fix each one and produce a corrected plan. Do NOT invent "
        "new entities or fields — only edit or rename what's already "
        "there so the references resolve.",
        "",
    ]
    for i, v in enumerate(violations, 1):
        loc = v.get("location", "?")
        lines.append(f"  {i}. [{v['rule']}] {v['message']}  (at {loc})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers — normalize the plan shapes we see across full-mode + oneshot
# --------------------------------------------------------------------------- #

def _entities_by_name(plan: dict) -> dict[str, dict]:
    """Return ``{EntityName: entity_dict}`` normalized across the two
    plan flavours we support. The full-mode planner emits
    ``dataModels: [{name, fields, ...}]``; the oneshot emits
    ``entities: {Name: {table, fields, ...}}``. Both are common in
    the wild — accept either."""
    out: dict[str, dict] = {}
    dm = plan.get("dataModels") or plan.get("data_models")
    if isinstance(dm, list):
        for e in dm:
            if isinstance(e, dict) and isinstance(e.get("name"), str):
                out[e["name"]] = e
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for name, e in ents.items():
            if isinstance(e, dict):
                # Give the dict a `name` for downstream ergonomics.
                merged = {**e, "name": name}
                out[name] = merged
    return out


def _fields_of(entity: dict) -> list[dict]:
    """Iterate an entity's fields regardless of the two representations."""
    fields = entity.get("fields")
    if isinstance(fields, list):
        return [f for f in fields if isinstance(f, dict)]
    return []


def _field_name(field: dict) -> str | None:
    """Extract a field's business name from either `name` or `column`."""
    n = field.get("name")
    if isinstance(n, str) and n.strip():
        return n
    c = field.get("column")
    return c if isinstance(c, str) and c.strip() else None


def _pages(plan: dict) -> list[dict]:
    p = plan.get("pages")
    return [x for x in p if isinstance(x, dict)] if isinstance(p, list) else []


def _workflows(plan: dict) -> list[dict]:
    w = plan.get("workflows")
    return [x for x in w if isinstance(x, dict)] if isinstance(w, list) else []


def _workflow_steps(w: dict):
    """The canonical step view of a workflow, whichever shape it is written in.

    Two workflow shapes exist in this system and BOTH reach this validator:

    * **planner shape** — top-level ``steps``; connectivity lives on each
      step as ``next`` / ``branches``. This is what the planner emits.
    * **runtime shape** — ``definition.nodes`` + ``definition.edges``; the
      nodes carry NO ``next`` at all. This is what
      ``crud_workflow_generator.build_crud_workflow`` — the real product
      path — writes to ``workflows/*.json``.

    Reading only ``w["steps"] or w["nodes"]`` saw zero steps on every real
    product-generated file, so a structurally perfect workflow reported no
    trigger and no end (register S19-3). Reading only ``next`` would then
    report ``node_missing_next`` on every node of the ones it did find.

    This is the single place that knows about the two shapes. Every rule
    below reads the returned steps through ``next``/``branches`` and stays
    shape-agnostic — the same "one authority, no duplicate readers" fix
    applied to the seam's edit handlers.

    Returns the steps with connectivity always readable through
    ``next``/``branches``. A non-list is returned unchanged so callers keep
    reporting ``workflow_no_steps`` for genuinely malformed input.
    """
    container = w
    d = w.get("definition")
    if isinstance(d, dict) and ("nodes" in d or "steps" in d):
        container = d

    steps = container.get("steps")
    if steps is None:
        steps = container.get("nodes")
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        return steps  # caller raises workflow_no_steps

    edges = container.get("edges")
    if not isinstance(edges, list):
        return steps

    # Runtime shape: project `edges` back onto each node so the connectivity
    # rules below read one vocabulary. Shallow copies — a validator must not
    # mutate the plan it is handed.
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        src, tgt = e.get("source"), e.get("target")
        if isinstance(src, str) and src and isinstance(tgt, str) and tgt:
            label = e.get("label") or e.get("condition") or e.get("when") or ""
            adj.setdefault(src, []).append((str(label), tgt))

    projected: list = []
    for step in steps:
        if not isinstance(step, dict):
            projected.append(step)
            continue
        outgoing = adj.get(str(step.get("id") or ""), [])
        if not outgoing or step.get("next") or step.get("branches"):
            projected.append(step)
            continue
        s = dict(step)
        if len(outgoing) == 1:
            s["next"] = outgoing[0][1]
        else:
            s["branches"] = {
                (label or f"branch_{i}"): tgt
                for i, (label, tgt) in enumerate(outgoing)
            }
        projected.append(s)
    return projected


# --------------------------------------------------------------------------- #
# Rule 0 — entity `lifecycle` is a known value
# --------------------------------------------------------------------------- #
#
# ``lifecycle`` is an OPTIONAL per-entity flag that controls whether the emitted
# entity is a standard CRUD entity (the historical default, ``"crud"``) or an
# APPEND-ONLY LEDGER (``"append_only"``). The ledger contract is:
#   - schema_builder skips ``updatedAt``/``deletedAt``
#   - api_route_prune keeps the Data Engine catch-all which rejects PUT/DELETE
#     for entities listed in ``src/lib/append-only-entities.ts``
#   - form_scaffold / ensure_edit_routes skip edit forms for these entities
#   - apply_record_maquette forces ``view`` mode
#
# Every other value is a plan bug the planner should hear about, so this rule
# is an error (never a warning) — silently downgrading an unknown lifecycle to
# ``crud`` would let the LLM's "immutable" or "audit" or "read_only" slip
# through and quietly build a mutable table.
_KNOWN_LIFECYCLES = frozenset({"crud", "append_only"})


def _rule_entity_lifecycle(plan, entities) -> list[dict]:
    out: list[dict] = []
    for name, e in entities.items():
        lc = e.get("lifecycle")
        if lc is None or lc == "":
            continue  # optional; unset → treated as "crud" downstream
        if not isinstance(lc, str) or lc not in _KNOWN_LIFECYCLES:
            out.append({
                "rule": "entity_lifecycle_unknown",
                "severity": "error",
                "message": (
                    f"entity {name!r} declares lifecycle={lc!r} — must be one "
                    f"of {sorted(_KNOWN_LIFECYCLES)} or omitted"
                ),
                "location": f"$.entities.{name}.lifecycle",
            })
    return out


# --------------------------------------------------------------------------- #
# Rule 1 — unique field names per entity
# --------------------------------------------------------------------------- #

def _rule_unique_field_names(plan, entities) -> list[dict]:
    out: list[dict] = []
    for name, e in entities.items():
        seen: set[str] = set()
        for f in _fields_of(e):
            fname = _field_name(f)
            if not fname:
                continue
            if fname in seen:
                out.append({
                    "rule": "duplicate_field",
                    "severity": "error",
                    "message": f"entity {name!r} has duplicate field {fname!r}",
                    "location": f"$.entities.{name}.fields[?(@.name=={fname!r})]",
                })
            seen.add(fname)
    return out


# --------------------------------------------------------------------------- #
# Rule 2 — relation endpoints exist
# --------------------------------------------------------------------------- #

def _rule_relation_endpoints(plan, entities) -> list[dict]:
    out: list[dict] = []
    rels = plan.get("relations")
    if not isinstance(rels, list):
        return out
    ent_names = set(entities)
    for i, rel in enumerate(rels):
        if not isinstance(rel, dict):
            continue
        for endpoint in ("from", "to"):
            v = rel.get(endpoint)
            if not isinstance(v, str) or v not in ent_names:
                out.append({
                    "rule": "relation_endpoint_missing",
                    "severity": "error",
                    "message": (
                        f"relations[{i}].{endpoint}={v!r} is not an "
                        f"entity in dataModels/entities"
                    ),
                    "location": f"$.relations[{i}].{endpoint}",
                })
    return out


# --------------------------------------------------------------------------- #
# Rule 3 — relation FK exists on the `from` entity
# --------------------------------------------------------------------------- #

def _rule_relation_fks(plan, entities) -> list[dict]:
    out: list[dict] = []
    rels = plan.get("relations")
    if not isinstance(rels, list):
        return out
    for i, rel in enumerate(rels):
        if not isinstance(rel, dict):
            continue
        src_name = rel.get("from")
        fk = rel.get("foreignKey") or rel.get("foreign_key")
        if not isinstance(src_name, str) or src_name not in entities:
            continue  # already flagged by rule 2
        if not isinstance(fk, str) or not fk.strip():
            out.append({
                "rule": "relation_fk_missing",
                "severity": "error",
                "message": f"relations[{i}] ({src_name}→{rel.get('to')}) has no foreignKey",
                "location": f"$.relations[{i}].foreignKey",
            })
            continue
        field_names = {_field_name(f) for f in _fields_of(entities[src_name])}
        field_names.discard(None)
        if fk not in field_names:
            out.append({
                "rule": "relation_fk_not_on_source",
                "severity": "error",
                "message": (
                    f"relations[{i}] foreignKey {fk!r} does not exist "
                    f"as a field on {src_name!r}"
                ),
                "location": f"$.relations[{i}].foreignKey",
            })
    return out


# --------------------------------------------------------------------------- #
# Rule 4 — actor FK fields have a relation to User
# --------------------------------------------------------------------------- #

def _rule_actor_fk_relations(plan, entities) -> list[dict]:
    out: list[dict] = []
    if "User" not in entities:
        # Plan hasn't introduced a User model at all — a bigger design
        # issue but not this rule's responsibility to flag.
        return out
    rels = plan.get("relations") or []
    rel_index: dict[tuple[str, str], dict] = {}
    for r in rels:
        if isinstance(r, dict):
            key = (r.get("from"), r.get("foreignKey") or r.get("foreign_key"))
            rel_index[key] = r

    for ename, e in entities.items():
        for f in _fields_of(e):
            fname = _field_name(f)
            if not fname or not _ACTOR_FK_RE.match(fname):
                continue
            rel = rel_index.get((ename, fname))
            if rel is None:
                out.append({
                    "rule": "actor_fk_without_relation",
                    "severity": "error",
                    "message": (
                        f"{ename}.{fname} looks like an actor FK but no "
                        f"relation to User is declared"
                    ),
                    "location": f"$.entities.{ename}.fields[?(@.name=={fname!r})]",
                })
            elif rel.get("to") != "User":
                out.append({
                    "rule": "actor_fk_wrong_target",
                    "severity": "error",
                    "message": (
                        f"{ename}.{fname} looks like an actor FK but its "
                        f"relation points at {rel.get('to')!r}, not 'User'"
                    ),
                    "location": f"$.entities.{ename}.fields[?(@.name=={fname!r})]",
                })
    return out


# --------------------------------------------------------------------------- #
# Rule 5 — pages reference real entities
# --------------------------------------------------------------------------- #

def _rule_page_entities(plan, entities) -> list[dict]:
    out: list[dict] = []
    ent_names = set(entities)
    for i, p in enumerate(_pages(plan)):
        e = p.get("entity")
        if e in (None, "", "null"):
            continue  # entity-free pages are OK (dashboard, chat, etc.)
        if not isinstance(e, str) or e not in ent_names:
            out.append({
                "rule": "page_entity_missing",
                "severity": "error",
                "message": (
                    f"pages[{i}] ({p.get('name') or p.get('route')}) references "
                    f"entity={e!r} which is not defined"
                ),
                "location": f"$.pages[{i}].entity",
            })
    return out


# --------------------------------------------------------------------------- #
# Rule 6 — page archetype is in the builder's closed set
# --------------------------------------------------------------------------- #

def _rule_page_archetypes(plan) -> list[dict]:
    out: list[dict] = []
    for i, p in enumerate(_pages(plan)):
        a = p.get("archetype") or p.get("type")
        if a in (None, ""):
            continue  # some page shapes leave it implicit for the router
        if not isinstance(a, str) or a.lower() not in _VALID_ARCHETYPES:
            out.append({
                "rule": "unsupported_archetype",
                "severity": "error",
                "message": (
                    f"pages[{i}] ({p.get('name') or p.get('route')}) has "
                    f"archetype={a!r}; supported set is "
                    f"{sorted(_VALID_ARCHETYPES)}"
                ),
                "location": f"$.pages[{i}].archetype",
            })
    return out


# --------------------------------------------------------------------------- #
# Rule 7 — workflow connectivity
# --------------------------------------------------------------------------- #

def _rule_workflow_connectivity(plan) -> list[dict]:
    out: list[dict] = []
    for wi, w in enumerate(_workflows(plan)):
        name = w.get("name") or f"workflow[{wi}]"
        steps = _workflow_steps(w)
        if not isinstance(steps, list):
            out.append({
                "rule": "workflow_no_steps",
                "severity": "error",
                "message": f"{name} has no steps/nodes list",
                "location": f"$.workflows[{wi}].steps",
            })
            continue
        node_ids: dict[str, dict] = {}
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("id"), str):
                node_ids[step["id"]] = step

        triggers = [s for s in steps if isinstance(s, dict) and s.get("type") == "trigger"]
        ends = [s for s in steps if isinstance(s, dict) and s.get("type") == "end"]
        if len(triggers) != 1:
            out.append({
                "rule": "workflow_trigger_count",
                "severity": "error",
                "message": f"{name} must have exactly one 'trigger' node (found {len(triggers)})",
                "location": f"$.workflows[{wi}].steps",
            })
        if len(ends) != 1:
            out.append({
                "rule": "workflow_end_count",
                "severity": "error",
                "message": f"{name} must have exactly one 'end' node (found {len(ends)})",
                "location": f"$.workflows[{wi}].steps",
            })

        for step in steps:
            if not isinstance(step, dict):
                continue
            sid = step.get("id", "?")
            stype = step.get("type", "")
            is_gateway = "gateway" in str(stype).lower()
            has_next = "next" in step and step["next"] is not None
            has_branches = isinstance(step.get("branches"), dict) and step["branches"]

            # Gateway → branches, not next
            if is_gateway:
                if has_next and not has_branches:
                    out.append({
                        "rule": "gateway_uses_next",
                        "severity": "error",
                        "message": (
                            f"{name}.{sid} is a gateway; use 'branches', not "
                            f"'next'"
                        ),
                        "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})]",
                    })
                if not has_branches:
                    out.append({
                        "rule": "gateway_no_branches",
                        "severity": "error",
                        "message": f"{name}.{sid} is a gateway but has no 'branches'",
                        "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})]",
                    })

            # Non-gateway / non-end: must have next
            elif stype != "end" and stype:
                if not has_next:
                    out.append({
                        "rule": "node_missing_next",
                        "severity": "error",
                        "message": f"{name}.{sid} has no 'next' target",
                        "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})]",
                    })

            # Every next/branch target must exist as a node id
            for tgt in _next_targets(step):
                if tgt and tgt not in node_ids:
                    out.append({
                        "rule": "workflow_dangling_target",
                        "severity": "error",
                        "message": (
                            f"{name}.{sid} points at {tgt!r} which is not a "
                            f"node in this workflow"
                        ),
                        "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})]",
                    })
    return out


def _next_targets(step: dict) -> list[str]:
    out: list[str] = []
    n = step.get("next")
    if isinstance(n, str) and n:
        out.append(n)
    b = step.get("branches")
    if isinstance(b, dict):
        for v in b.values():
            if isinstance(v, str) and v:
                out.append(v)
    return out


# --------------------------------------------------------------------------- #
# Rule 8 — page.actions.workflow references a real workflow
# --------------------------------------------------------------------------- #

def _rule_page_action_workflows(plan) -> list[dict]:
    out: list[dict] = []
    workflows = _workflows(plan)
    if not workflows:
        return out  # no workflows declared → nothing to check
    wf_names = {w.get("name") for w in workflows if isinstance(w.get("name"), str)}
    for pi, p in enumerate(_pages(plan)):
        actions = p.get("actions") or []
        if not isinstance(actions, list):
            continue
        for ai, a in enumerate(actions):
            if not isinstance(a, dict):
                continue
            wref = a.get("workflow") or a.get("workflowId")
            if wref is None:
                continue  # navigation-only or nav-based actions are OK
            if not isinstance(wref, str) or wref not in wf_names:
                out.append({
                    "rule": "action_workflow_missing",
                    "severity": "error",
                    "message": (
                        f"pages[{pi}].actions[{ai}] ({a.get('label') or '?'}) "
                        f"references workflow={wref!r}, which is not defined "
                        f"in workflows[]"
                    ),
                    "location": f"$.pages[{pi}].actions[{ai}].workflow",
                })
    return out


# --------------------------------------------------------------------------- #
# Rule 9 — workflow input coverage
#
# For every workflow step config that references a binding via {{name}},
# `{{input.name}}`, `{{trigger.name}}`, or `{{steps.<id>.field}}`, prove
# the value has a source:
#
#   (a) the workflow's trigger declares an input of the same name
#       (`trigger.config.inputs` / `trigger.config.form.fields`), OR
#   (b) a prior step in the graph produces it (`steps.<earlierId>...`), OR
#   (c) the invoking page action supplies it via `action.input_map`, OR
#   (d) the ref uses a context/system binding (page/context/user/now/uuid)
#       which the dispatcher always provides.
#
# Without one of those, the ref resolves to `""` / `undefined` at runtime
# and `_buildWhere` throws "WHERE X is empty — trigger form is missing
# an input for this workflow node" (the exact class of the July-17 crash
# on UpdateAppointment). This rule catches it at plan time.
# --------------------------------------------------------------------------- #

# `{{ expr }}` (non-greedy) — same syntax the runtime resolver reads.
_BINDING_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

# Prefixes that always resolve via the dispatcher/context (rule 9d).
_ALWAYS_RESOLVED_PREFIXES: tuple[str, ...] = (
    "page.", "context.", "ctx.", "user.", "session.",
    "env.", "now", "today", "uuid(", "random(",
    "constants.", "app.",
)


def _extract_binding_names(config: Any) -> list[str]:
    """Walk a step config recursively and pull every `{{ … }}` ref out.
    Returns the *variable path* (`input.id`, `steps.n1.rowId`) — not the
    braces. Non-binding string values are ignored."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for m in _BINDING_RE.finditer(node):
                expr = m.group(1).strip()
                if expr:
                    found.append(expr)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(config)
    return found


def _trigger_input_names(trigger_step: dict | None) -> set[str]:
    """Union of every named input the trigger declares. Accepts both
    `config.inputs: [{name}]` and `config.form.fields: [{name}]` shapes."""
    if not isinstance(trigger_step, dict):
        return set()
    cfg = trigger_step.get("config") or {}
    if not isinstance(cfg, dict):
        return set()
    names: set[str] = set()
    for src in (cfg.get("inputs"), (cfg.get("form") or {}).get("fields")):
        if isinstance(src, list):
            for item in src:
                if isinstance(item, dict):
                    n = item.get("name") or item.get("id")
                    if isinstance(n, str) and n.strip():
                        names.add(n.strip())
    # Some planners emit a flat map: config.inputs = {"id": "uuid", …}.
    if isinstance(cfg.get("inputs"), dict):
        names.update(k for k in cfg["inputs"].keys() if isinstance(k, str))
    return names


def _action_input_map_names(plan: dict, workflow_name: str) -> set[str]:
    """Union of every key any page.action.input_map supplies to this
    workflow. If the action explicitly maps a key, the workflow can
    treat it as supplied even if the trigger doesn't declare it."""
    supplied: set[str] = set()
    for p in _pages(plan):
        for a in (p.get("actions") or []):
            if not isinstance(a, dict):
                continue
            wref = a.get("workflow") or a.get("workflowId")
            if wref != workflow_name:
                continue
            imap = a.get("input_map") or a.get("inputMap")
            if isinstance(imap, dict):
                supplied.update(k for k in imap.keys() if isinstance(k, str))
    return supplied


def _record_id_input_names(w: dict) -> set[str]:
    """Trigger inputs / where-vars of workflow ``w`` that name THE record.

    A workflow that filters ``where: {id: "{{documentId}}"}`` can only run
    with a record identity in hand. We call an input record-id-shaped
    when it is literally ``id`` / ``recordId``, or ``<entity>Id`` where
    <entity> matches (the singular of) any table the workflow touches.
    Other ``*Id`` inputs (``uploadedById``…) are actor/relation FKs
    supplied by different mechanisms and are NOT demanded here.
    """
    def _fold(s: str) -> str:
        return "".join(ch for ch in (s or "").lower() if ch.isalnum())

    steps = _workflow_steps(w) or []
    tables: set[str] = set()
    where_vars: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        cfg = step.get("config") or {}
        if isinstance(cfg.get("table"), str):
            tables.add(cfg["table"])
        where = cfg.get("where")
        if isinstance(where, dict):
            for v in where.values():
                if isinstance(v, str):
                    m = re.fullmatch(r"\{\{\s*([A-Za-z_]\w*)\s*\}\}", v.strip())
                    if m:
                        where_vars.add(m.group(1))

    stems = {_fold(t) for t in tables}
    stems |= {_fold(t[:-1]) for t in tables if t.endswith("s")}

    trigger = next((s for s in steps if isinstance(s, dict)
                    and s.get("type") == "trigger"), None)
    candidates = _trigger_input_names(trigger) | where_vars

    hits: set[str] = set()
    for name in candidates:
        f = _fold(name)
        if f in ("id", "recordid"):
            hits.add(name)
        elif f.endswith("id") and f[:-2] in stems:
            hits.add(name)
    return hits


def _rule_launcher_supplies_record_inputs(plan) -> list[dict]:
    """Every declared launcher of a record-scoped workflow must say
    where the record id comes from.

    The runtime crash this prevents: a bare Button dispatches the
    workflow with an empty payload, `{{documentId}}` resolves to
    nothing, and the engine throws "WHERE id is empty". The planner
    already declares the NEED (the workflow's where-clause); this rule
    forces it to also declare the SUPPLY on each launcher — either
    ``requires_record: true`` (the materializer then binds the hosting
    page's record id) or an explicit ``input_map`` entry.
    """
    out: list[dict] = []
    by_name: dict[str, set[str]] = {}
    for w in _workflows(plan):
        name = w.get("name")
        if isinstance(name, str) and name:
            needed = _record_id_input_names(w)
            if needed:
                by_name[name] = needed

    if not by_name:
        return out

    for pi, p in enumerate(_pages(plan)):
        page_label = p.get("name") or p.get("route") or f"pages[{pi}]"
        for ai, a in enumerate(p.get("actions") or []):
            if not isinstance(a, dict):
                continue
            wref = a.get("workflow") or a.get("workflowId")
            if not isinstance(wref, str) or wref not in by_name:
                continue
            imap = a.get("input_map") or a.get("inputMap")
            supplied = set(imap.keys()) if isinstance(imap, dict) else set()
            if a.get("requires_record") or a.get("requiresRecord"):
                continue  # materializer binds the page record's id
            missing = by_name[wref] - supplied
            if missing:
                label = a.get("label") or a.get("name") or f"actions[{ai}]"
                out.append({
                    "rule": "launcher_missing_record_input",
                    "severity": "error",
                    "message": (
                        f"page {page_label!r} action {label!r} launches "
                        f"{wref!r}, which filters records by "
                        f"{sorted(missing)} — but the action declares "
                        f"neither `requires_record: true` nor an "
                        f"`input_map` entry for it. The button would "
                        f"dispatch an empty payload and crash with "
                        f"'WHERE id is empty'. Add `requires_record: "
                        f"true` to this action."
                    ),
                    "location": f"$.pages[{pi}].actions[{ai}]",
                })
    return out


def _rule_workflow_input_coverage(plan) -> list[dict]:
    out: list[dict] = []
    for wi, w in enumerate(_workflows(plan)):
        name = w.get("name") or f"workflow[{wi}]"
        steps = _workflow_steps(w)
        if not isinstance(steps, list):
            continue

        # Index the trigger + a step-order map for reachability of
        # `steps.<id>` refs.
        trigger = next(
            (s for s in steps if isinstance(s, dict) and s.get("type") == "trigger"),
            None,
        )
        trigger_names = _trigger_input_names(trigger)
        action_supplied = _action_input_map_names(plan, name)

        # Names declared on the workflow itself (planner-authored process
        # variables). A read of `{{approvalDecision}}` is legitimate iff
        # the workflow declares it OR an earlier step writes it — see the
        # `process_vars` set that grows below.
        process_vars = {
            str(pv.get("name") or "")
            for pv in (w.get("processVariables") or [])
            if isinstance(pv, dict) and pv.get("name")
        }
        process_vars.discard("")

        prior_step_ids: set[str] = set()
        if isinstance(trigger, dict) and isinstance(trigger.get("id"), str):
            prior_step_ids.add(trigger["id"])

        # Walk steps in declared order. Ordering is approximate — the
        # runtime executes by graph traversal — but for coverage the
        # declared order is a safe upper bound (a ref satisfiable by ANY
        # earlier step in the graph is satisfiable here too).
        for step in steps:
            if not isinstance(step, dict) or step.get("type") == "trigger":
                continue
            sid = step.get("id", "?")
            cfg = step.get("config") or {}
            for expr in _extract_binding_names(cfg):
                # Ignore always-resolved prefixes/functions.
                if any(expr.startswith(p) or expr == p.rstrip(".")
                       for p in _ALWAYS_RESOLVED_PREFIXES):
                    continue

                # `input.NAME` / `trigger.NAME` → trigger form must supply.
                if expr.startswith("input.") or expr.startswith("trigger."):
                    key = expr.split(".", 1)[1].split(".")[0]
                    if key in trigger_names or key in action_supplied:
                        continue
                    out.append({
                        "rule": "workflow_input_uncovered",
                        "severity": "error",
                        "message": (
                            f"{name}.{sid} references {{{{{expr}}}}} but no "
                            f"trigger input named {key!r} exists and no page "
                            f"action.input_map supplies it — this crashes at "
                            f"runtime with 'WHERE X is empty'"
                        ),
                        "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})].config",
                    })
                    continue

                # `steps.EARLIER_ID.field` → the referenced step must
                # appear earlier in the graph.
                if expr.startswith("steps."):
                    parts = expr.split(".")
                    ref_sid = parts[1] if len(parts) > 1 else ""
                    if ref_sid and ref_sid not in prior_step_ids:
                        out.append({
                            "rule": "workflow_step_ref_not_reachable",
                            "severity": "error",
                            "message": (
                                f"{name}.{sid} references {{{{{expr}}}}} but "
                                f"step {ref_sid!r} does not appear earlier "
                                f"in the workflow — the value is undefined "
                                f"when this step runs"
                            ),
                            "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})].config",
                        })
                    continue

                # Bare name (`{{id}}`, `{{amount}}`) — treat like an
                # input reference, since the runtime resolver falls back
                # to the trigger inputs / variables map when no scope is
                # named. Same evidence + same failure mode.
                head = expr.split(".")[0]
                if head in trigger_names or head in action_supplied:
                    continue
                # Declared process variable (planner) or one an earlier
                # step wrote via set_variable / promoted output.
                if head in process_vars:
                    continue
                # Skip idiomatic FEEL functions and literals that fool the head.
                if head in {"true", "false", "null", "and", "or", "not", "if", "then", "else"}:
                    continue
                if head.isdigit() or (head.startswith('"') and head.endswith('"')):
                    continue
                out.append({
                    "rule": "workflow_input_uncovered",
                    "severity": "error",
                    "message": (
                        f"{name}.{sid} references {{{{{expr}}}}} but no "
                        f"trigger input, page action.input_map, or declared "
                        f"processVariable named {head!r} exists — this crashes "
                        f"at runtime with 'WHERE X is empty'. Declare it under "
                        f"`workflows[].processVariables[]` or write it earlier "
                        f"with a `set_variable` action."
                    ),
                    "location": f"$.workflows[{wi}].steps[?(@.id=={sid!r})].config",
                })

            # Register this step's id AFTER checking refs, so a step
            # doesn't accidentally satisfy its own binding. Also grow
            # `process_vars` from any set_variable this step writes and
            # any output-mapping it promotes — later steps then see them.
            if isinstance(sid, str):
                prior_step_ids.add(sid)
            if isinstance(cfg, dict):
                if cfg.get("actionType") == "set_variable":
                    vname = str(cfg.get("variableName") or "").strip()
                    if vname:
                        process_vars.add(vname)
                for m in (cfg.get("outputMappings") or []):
                    if isinstance(m, dict):
                        promoted = str(m.get("processVar") or "").strip()
                        if promoted:
                            process_vars.add(promoted)

    return out


# --------------------------------------------------------------------------- #
# Rule — authoritative inputs honored (JT-T2). When the planner ran with a
# StructuredBrief attached (discovery-driven flow), every commitment the brief
# made — actors, journey-referenced pages, journey-referenced workflows,
# User.role enum — MUST appear verbatim in the produced plan. Violations
# trigger a single REVISE-mode retry (wired at the router level).
#
# This rule is OPT-IN — callers pass the brief explicitly. The core
# validate_plan() intentionally doesn't take the brief, so pre-slice plans
# stay unchanged.
# --------------------------------------------------------------------------- #

def validate_plan_against_brief(plan: dict, brief: Any) -> list[dict]:
    """Same shape as :func:`validate_plan` but also checks the plan
    honored a :class:`services.structured_brief.StructuredBrief`.

    ``brief`` may be a dict (from the DB), a JSON string, or a parsed
    ``StructuredBrief`` object — we normalise. An empty brief (no
    actors + no journeys) validates as if it wasn't provided, so the
    caller can pass any brief without a nullness check.
    """
    core = validate_plan(plan)
    if brief is None:
        return core
    try:
        from services.structured_brief import StructuredBrief, BriefParseError
        if not hasattr(brief, "actors"):
            brief = StructuredBrief.parse(brief)
    except Exception as exc:  # noqa: BLE001
        core.append({
            "rule": "authoritative_brief_parse_failed",
            "severity": "warning",
            "message": (
                f"couldn't parse the attached structured brief "
                f"({type(exc).__name__}); skipping contract check"
            ),
            "location": "$.__meta.brief",
        })
        return core
    if getattr(brief, "is_empty", lambda: False)():
        return core
    core.extend(_rule_authoritative_inputs_honored(plan, brief))
    return core


def _rule_authoritative_inputs_honored(plan: dict, brief) -> list[dict]:
    """Walk the plan and confirm every brief commitment is met.

    Checks:
      * every brief actor appears in ``plan.actors[]`` with the same
        role + onboarding source (invited_by relationships mirrored);
      * every ``journey.steps[].page`` appears in ``plan.pages[]`` at
        the same route;
      * every ``journey.steps[].workflow`` appears in ``plan.workflows[]``;
      * every open_question has a corresponding ``plan.assumptions[]``
        entry so the planner's resolution is visible to the user;
      * ``User.role`` enum values cover every brief actor role.
    """
    out: list[dict] = []

    plan_actor_map = _plan_actor_map(plan)
    plan_pages_by_route = _plan_pages_by_route(plan)
    plan_workflow_names = _plan_workflow_names(plan)

    # --- actors ---------------------------------------------------------- #
    for i, a in enumerate(brief.actors):
        plan_actor = plan_actor_map.get(a.name)
        if plan_actor is None:
            out.append({
                "rule": "authoritative_actor_missing",
                "severity": "error",
                "message": (
                    f"brief specified actor {a.name!r} (role={a.role!r}); "
                    f"plan.actors[] has no entry with that name. Add it "
                    f"verbatim — do not rename or drop actors from the brief."
                ),
                "location": f"$.actors  ← missing {a.name!r}",
            })
            continue
        p_role = plan_actor.get("role") if isinstance(plan_actor, dict) else None
        if p_role != a.role:
            out.append({
                "rule": "authoritative_actor_role_mismatch",
                "severity": "error",
                "message": (
                    f"brief actor {a.name!r} has role {a.role!r}; plan "
                    f"emitted role={p_role!r}. Use the brief's role verbatim."
                ),
                "location": f"$.actors[?(@.name=={a.name!r})].role",
            })
        p_ob = (plan_actor.get("onboarding") or {}) if isinstance(plan_actor, dict) else {}
        p_source = p_ob.get("source") if isinstance(p_ob, dict) else None
        if a.onboarding.source and p_source != a.onboarding.source:
            out.append({
                "rule": "authoritative_actor_onboarding_mismatch",
                "severity": "error",
                "message": (
                    f"brief actor {a.name!r} has onboarding.source="
                    f"{a.onboarding.source!r}; plan emitted {p_source!r}"
                ),
                "location": f"$.actors[?(@.name=={a.name!r})].onboarding.source",
            })
        if a.onboarding.source == "invited_by":
            p_inv = p_ob.get("invited_by") if isinstance(p_ob, dict) else None
            if p_inv != a.onboarding.invited_by:
                out.append({
                    "rule": "authoritative_actor_inviter_mismatch",
                    "severity": "error",
                    "message": (
                        f"brief actor {a.name!r} is invited by "
                        f"{a.onboarding.invited_by!r}; plan emitted "
                        f"invited_by={p_inv!r}"
                    ),
                    "location": f"$.actors[?(@.name=={a.name!r})].onboarding.invited_by",
                })

    # --- journeys: pages + workflows exist ------------------------------- #
    for ji, j in enumerate(brief.user_journeys):
        for si, step in enumerate(j.steps):
            if step.page and step.page not in plan_pages_by_route:
                out.append({
                    "rule": "authoritative_journey_page_missing",
                    "severity": "error",
                    "message": (
                        f"journey {j.name!r} step {si + 1} references page "
                        f"{step.page!r}; plan.pages[] has no entry at that "
                        f"route. The planner MUST add a page for every "
                        f"journey step's `page` field."
                    ),
                    "location": (
                        f"$.user_journeys[{ji}].steps[{si}].page  ← "
                        f"missing route {step.page!r}"
                    ),
                })
            if step.workflow and step.workflow not in plan_workflow_names:
                out.append({
                    "rule": "authoritative_journey_workflow_missing",
                    "severity": "error",
                    "message": (
                        f"journey {j.name!r} step {si + 1} references "
                        f"workflow {step.workflow!r}; plan.workflows[] has "
                        f"no entry with that name."
                    ),
                    "location": (
                        f"$.user_journeys[{ji}].steps[{si}].workflow  ← "
                        f"missing workflow {step.workflow!r}"
                    ),
                })

    # --- open questions have assumption entries -------------------------- #
    if brief.open_questions:
        p_assumptions = plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else []
        blob = " | ".join(str(a) for a in p_assumptions).lower()
        for q in brief.open_questions:
            # A soft check — some fuzzy overlap between the question and an
            # assumption is enough. We're not requiring the LLM to copy the
            # question verbatim, only that it acknowledged it.
            key = _question_signal(q)
            if key and key not in blob:
                out.append({
                    "rule": "authoritative_open_question_unresolved",
                    "severity": "warning",
                    "message": (
                        f"brief listed open question {q!r}; plan.assumptions[] "
                        f"doesn't appear to address it. Every open question "
                        f"should be resolved with a note in assumptions[]."
                    ),
                    "location": f"$.assumptions  ← unresolved: {q[:80]!r}",
                })

    # --- User.role enum covers every actor role -------------------------- #
    user_roles = _user_role_enum(plan)
    brief_roles = [a.role for a in brief.actors if a.role]
    if user_roles is not None:
        for r in brief_roles:
            if r not in user_roles:
                out.append({
                    "rule": "authoritative_user_role_enum_missing",
                    "severity": "error",
                    "message": (
                        f"brief actor role {r!r} is not in User.role's "
                        f"enum_values (plan has {sorted(user_roles)}). The "
                        f"enum MUST cover every actor role verbatim."
                    ),
                    "location": (
                        "$.data_models[?(@.name=='User')].fields[?(@.name=='role')].enum_values"
                    ),
                })

    return out


def _plan_actor_map(plan: dict) -> dict[str, dict]:
    actors = plan.get("actors")
    if not isinstance(actors, list):
        return {}
    return {
        a["name"]: a for a in actors
        if isinstance(a, dict) and isinstance(a.get("name"), str)
    }


def _plan_pages_by_route(plan: dict) -> set[str]:
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return set()
    out: set[str] = set()
    for p in pages:
        if isinstance(p, dict) and isinstance(p.get("route"), str):
            out.add(p["route"])
    return out


def _plan_workflow_names(plan: dict) -> set[str]:
    wfs = plan.get("workflows")
    if not isinstance(wfs, list):
        return set()
    out: set[str] = set()
    for w in wfs:
        if isinstance(w, dict) and isinstance(w.get("name"), str):
            out.add(w["name"])
    return out


def _user_role_enum(plan: dict) -> set[str] | None:
    """Return the User.role enum values, or None if the plan doesn't
    yet declare a User entity (which means the enum check should just
    be skipped, not fail)."""
    for e in plan.get("data_models") or []:
        if not isinstance(e, dict) or e.get("name") != "User":
            continue
        for f in e.get("fields") or []:
            if not isinstance(f, dict):
                continue
            if f.get("name") == "role":
                vals = f.get("enum_values") or f.get("enum") or []
                if isinstance(vals, list):
                    return {str(v) for v in vals}
                return set()
    return None


def _question_signal(question: str) -> str:
    """Extract a low-noise substring to match against assumption blob.
    We drop stopwords and take the longest remaining token — usually
    the domain noun ("screening" in "is there a screening stage")."""
    import re
    words = re.findall(r"[a-zA-Z]{4,}", question.lower())
    stop = {"there", "should", "would", "will", "have", "with",
            "which", "when", "what", "does", "kind", "type", "into"}
    words = [w for w in words if w not in stop]
    return max(words, key=len) if words else ""


# --------------------------------------------------------------------------- #
# Rule — actors block (slice B): every actor names an onboarding source, so
# downstream generators know how each role gets provisioned. Missing / vague
# actors mean the app has no way to invite recruiters, no way for candidates
# to sign up, etc.
# --------------------------------------------------------------------------- #

_VALID_ONBOARDING_SOURCES = {"self_signup", "invited_by", "platform_org"}


def _rule_actors(plan: dict) -> list[dict]:
    out: list[dict] = []
    actors = plan.get("actors")
    if actors is None:
        # Not emitted at all — the planner prompt demands it, but the
        # downstream consumers all have a legacy fallback for pre-slice-B
        # plans. Skip silently so old fixtures still validate clean.
        return out
    if not isinstance(actors, list) or not actors:
        out.append({
            "rule": "actors_shape",
            "severity": "error",
            "message": "`actors` must be a non-empty list",
            "location": "$.actors",
        })
        return out

    names_seen: set[str] = set()
    roles_seen: set[str] = set()
    invited_by_targets: list[tuple[int, str]] = []

    for i, a in enumerate(actors):
        loc = f"$.actors[{i}]"
        if not isinstance(a, dict):
            out.append({
                "rule": "actor_shape", "severity": "error",
                "message": f"actor at index {i} is not an object",
                "location": loc,
            })
            continue

        name = a.get("name")
        role = a.get("role")
        if not (isinstance(name, str) and name.strip()):
            out.append({
                "rule": "actor_missing_name", "severity": "error",
                "message": f"actor at index {i} has no name",
                "location": loc,
            })
        else:
            if name in names_seen:
                out.append({
                    "rule": "actor_duplicate_name", "severity": "error",
                    "message": f"duplicate actor name {name!r}",
                    "location": loc,
                })
            names_seen.add(name)

        if not (isinstance(role, str) and role.strip()):
            out.append({
                "rule": "actor_missing_role", "severity": "error",
                "message": f"actor {name!r} has no role",
                "location": loc,
            })
        else:
            if role in roles_seen:
                out.append({
                    "rule": "actor_duplicate_role", "severity": "error",
                    "message": (
                        f"role {role!r} is used by more than one actor; "
                        f"roles must be unique (one User.role enum value each)"
                    ),
                    "location": loc,
                })
            roles_seen.add(role)

        onboarding = a.get("onboarding")
        if not isinstance(onboarding, dict):
            out.append({
                "rule": "actor_missing_onboarding", "severity": "error",
                "message": (
                    f"actor {name!r} has no onboarding block; every actor "
                    f"must specify how they get into the app "
                    f"({sorted(_VALID_ONBOARDING_SOURCES)})"
                ),
                "location": loc,
            })
            continue
        source = onboarding.get("source")
        if source not in _VALID_ONBOARDING_SOURCES:
            out.append({
                "rule": "actor_bad_onboarding_source", "severity": "error",
                "message": (
                    f"actor {name!r} onboarding.source={source!r} — "
                    f"must be one of {sorted(_VALID_ONBOARDING_SOURCES)}"
                ),
                "location": f"{loc}.onboarding.source",
            })
        elif source == "invited_by":
            inviter = onboarding.get("invited_by")
            if not (isinstance(inviter, str) and inviter.strip()):
                out.append({
                    "rule": "actor_invited_by_missing_inviter",
                    "severity": "error",
                    "message": (
                        f"actor {name!r} has onboarding.source='invited_by' "
                        f"but no invited_by naming which other actor does "
                        f"the inviting"
                    ),
                    "location": f"{loc}.onboarding.invited_by",
                })
            else:
                invited_by_targets.append((i, inviter))

    # Every invited_by target must itself be a named actor — else the invite
    # workflow has no one to attribute the invitation to.
    for i, inviter in invited_by_targets:
        if inviter not in names_seen:
            out.append({
                "rule": "actor_invited_by_unknown_inviter",
                "severity": "error",
                "message": (
                    f"actor at index {i} is invited_by={inviter!r}, but no "
                    f"actor with that name exists (known: {sorted(names_seen)})"
                ),
                "location": f"$.actors[{i}].onboarding.invited_by",
            })

    return out


# ────────────────────────────────────────────────────────────────────────
# Completeness contract — warns when the plan under-specifies fields the
# downstream pipeline would otherwise have to guess. Warnings today so
# existing plans still generate; flip to `error` once emission is reliable
# across 5+ apps.
# ────────────────────────────────────────────────────────────────────────


_KNOWN_ENUM_HINTS = ("status", "priority", "type", "stage", "kind", "state")


def _rule_field_completeness(plan, entities) -> list[dict]:
    """Every entity field should declare enough for downstream construction.

    * `type` is required — obvious, but plans sometimes omit it.
    * Any field the domain calls status/priority/type/stage MUST declare
      `enum_values`. If it doesn't, the enum harvester has to guess and
      pollutes downstream Select controls.
    * Any `uuid` field NOT declared as a primary key MUST declare `fk`
      (a foreign key). A bare uuid FK column tells downstream nothing
      about which entity a Select should fetch from.
    * Nullable state (`not_null`) MUST be present when the plan intends
      a NOT NULL column, so required-marker + form-scaffold agree.
    """
    out: list[dict] = []
    for ename, entity in entities.items():
        for fi, f in enumerate(_fields_of(entity)):
            if not isinstance(f, dict):
                continue
            name = _field_name(f) or f"field[{fi}]"
            loc  = f"$.entities[{ename}].fields[{name}]"

            if "type" not in f:
                out.append({
                    "rule": "field_type_missing", "severity": "warning",
                    "message": f"{ename}.{name} has no `type` — downstream cannot infer control",
                    "location": loc,
                })

            if any(h in name.lower() for h in _KNOWN_ENUM_HINTS):
                if not f.get("enum_values"):
                    out.append({
                        "rule": "field_enum_missing", "severity": "warning",
                        "message": (
                            f"{ename}.{name} looks like an enum-shaped field but "
                            "declares no `enum_values` — Select options will be "
                            "scraped/inferred, likely with wrong values"
                        ),
                        "location": loc,
                    })

            ftype = str(f.get("type") or "").lower()
            if ftype == "uuid" and not f.get("primaryKey") and not f.get("primary_key"):
                if not f.get("fk"):
                    out.append({
                        "rule": "field_fk_missing", "severity": "warning",
                        "message": (
                            f"{ename}.{name} is uuid but declares no `fk` — FK "
                            "target cannot be resolved for the Select control"
                        ),
                        "location": loc,
                    })

            if "not_null" not in f and "nullable" not in f:
                out.append({
                    "rule": "field_nullability_missing", "severity": "warning",
                    "message": f"{ename}.{name} declares neither `not_null` nor `nullable`",
                    "location": loc,
                })
    return out


def _rule_money_currency_alias(plan, entities) -> list[dict]:
    """A ``money``-typed column auto-emits a sibling ``<field>_currency`` (see
    schema_builder). If the plan also declares its OWN currency alias for the
    same money field under a DIFFERENT name (e.g. ``ccyCode``, ``fx_code``),
    the sibling and the alias would coexist as two different currency columns —
    ambiguous. Reject: pick one.

    A field named exactly the derived sibling name (``<amount>_currency`` /
    ``<amount>Currency``) is the schema builder's own sibling and is silently
    accepted (idempotent — the builder does not double-emit).
    """
    # Local import to avoid a hard dep from plan_validator on schema_builder;
    # keeps the validator standalone for tests / tooling.
    from services.schema_builder import _derive_currency_sibling_name

    out: list[dict] = []
    for ename, entity in entities.items():
        fields = _fields_of(entity)
        field_names = {(_field_name(f) or "").strip() for f in fields if _field_name(f)}
        for fi, f in enumerate(fields):
            ftype = str((f or {}).get("type") or "").lower().strip()
            if ftype not in ("money", "currency"):
                continue
            fname = _field_name(f) or f"field[{fi}]"
            sibling = _derive_currency_sibling_name(fname)
            # Any OTHER field on the same entity whose name reads as a currency
            # code alias for THIS amount → ambiguous.
            aliases = {"currency", fname + "Currency", fname + "_currency",
                       fname.rstrip("Amount") + "Currency" if fname.endswith("Amount") else "",
                       "ccy", "ccyCode", "fxCode", "fx_code", "currencyCode",
                       "currency_code"}
            aliases.discard("")
            aliases.discard(sibling)  # the builder's own sibling is fine
            aliases.discard(fname)     # the money column itself is not an alias
            collisions = sorted(field_names & aliases)
            if collisions:
                out.append({
                    "rule": "money_currency_ambiguous", "severity": "error",
                    "message": (
                        f"{ename}.{fname} is a `money` column — the schema builder "
                        f"auto-emits `{sibling}`. Field(s) {collisions} also declare "
                        "a currency code for the same amount; pick one (either rename "
                        f"the alias to `{sibling}` or drop the `money` type)."
                    ),
                    "location": f"$.entities[{ename}].fields[{fname}]",
                })
    return out


# Every mask kind the schema builder + runtime helper know how to render.
# `last4` (partial-reveal — the default for account/routing/card numbers),
# `email` (keep first char + domain), `phone` (last 4 digits), and `full`
# (fixed 8 bullets — nothing revealed, for secrets like SSNs). Extending the
# set requires a matching branch in the runtime `mask()` helper in
# templates/runtime/sensitive-crypto.ts — keep the two in sync.
_SENSITIVE_MASK_KINDS = frozenset({"last4", "email", "phone", "full"})

# Types the encrypt-at-rest path is defined for. Everything encrypts to a
# base64 AES-GCM blob stored in a `_encrypted text` column — non-string
# columns (`numeric`, `uuid`, `boolean`, `date`, `jsonb`) would need type-
# preserving encryption + would break every comparison predicate on the
# column, which is out of scope for Slice 4. Reject up-front rather than
# emit a schema the runtime can't service.
_SENSITIVE_SUPPORTED_TYPES = frozenset({
    "text", "varchar", "char", "string",
})


def _rule_sensitive_columns(plan, entities) -> list[dict]:
    """Slice-4 encrypt-at-rest contract.

    A column flagged ``sensitive: true`` is stored as an AES-GCM blob in
    ``<name>_encrypted``, with a pre-computed masked value in ``<name>_mask``
    for the default read path. This rule guards the plan-authoring surface:

      1. ``sensitive: true`` is only defined for string-shaped columns
         (``text``/``varchar``/``char``/``string``). Encrypting a
         ``numeric`` or ``uuid`` requires type-preserving encryption + would
         break every equality predicate on the column — out of scope for
         this slice. Reject rather than emit a schema the runtime can't
         service.
      2. If the entity declares no ``sensitiveReaders[]`` role list AND the
         field declares no explicit ``mask``, reject: the ambiguity is
         between "even admins see masked" (readers=[], mask="last4") and
         "any authenticated user can unmask" (readers=["*"], mask absent) —
         two very different security postures. Force the author to pick.
      3. ``mask`` (if set) must be one of the kinds the runtime helper
         supports; otherwise the mask column would hold garbage.
      4. Warn (do not reject) when ``sensitiveReaders`` names a role slug
         that isn't in ``plan.actors[].role`` — probably a typo, but not
         a security failure (an unknown reader just = nobody).
    """
    out: list[dict] = []

    known_roles = {
        (a.get("role") or "").strip()
        for a in (plan.get("actors") or [])
        if isinstance(a, dict) and (a.get("role") or "").strip()
    }

    for ename, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        readers = entity.get("sensitiveReaders")
        readers_list: list[str] = []
        if isinstance(readers, list):
            readers_list = [
                r.strip() for r in readers
                if isinstance(r, str) and r.strip()
            ]

        # (4) unknown-role warning is per-entity, not per-column.
        for r in readers_list:
            if r == "*":
                continue
            if known_roles and r not in known_roles:
                out.append({
                    "rule": "sensitive_readers_unknown_role",
                    "severity": "warning",
                    "message": (
                        f"{ename}.sensitiveReaders lists role {r!r} but no "
                        f"actor with that role is declared in plan.actors[]"
                    ),
                    "location": f"$.entities[{ename}].sensitiveReaders",
                })

        for fi, f in enumerate(_fields_of(entity)):
            if not isinstance(f, dict):
                continue
            if not f.get("sensitive"):
                continue
            name = _field_name(f) or f"field[{fi}]"
            loc = f"$.entities[{ename}].fields[{name}]"
            ftype = str(f.get("type") or "").lower().strip()

            # (1) type support
            if ftype not in _SENSITIVE_SUPPORTED_TYPES:
                out.append({
                    "rule": "sensitive_field_type_unsupported",
                    "severity": "error",
                    "message": (
                        f"{ename}.{name} declares `sensitive: true` on a "
                        f"{ftype!r} column; only string-shaped columns "
                        "(text/varchar/char) can be encrypted at rest in "
                        "this slice"
                    ),
                    "location": loc,
                })
                continue

            # (3) mask kind must be one the runtime knows how to render.
            mask = f.get("mask")
            if mask is not None:
                if not isinstance(mask, str) or mask not in _SENSITIVE_MASK_KINDS:
                    out.append({
                        "rule": "sensitive_mask_unknown",
                        "severity": "error",
                        "message": (
                            f"{ename}.{name}.mask={mask!r} is not one of "
                            f"{sorted(_SENSITIVE_MASK_KINDS)} — the runtime "
                            "helper wouldn't know how to render it"
                        ),
                        "location": loc,
                    })

            # (2) ambiguity gate — no readers AND no explicit mask kind.
            # "readers=[]" is authored intent ("even admins see masked");
            # a missing/undeclared list plus no mask is undeclared intent —
            # reject so the author has to pick a posture.
            if readers is None and mask is None:
                out.append({
                    "rule": "sensitive_readers_or_mask_required",
                    "severity": "error",
                    "message": (
                        f"{ename}.{name} is sensitive but {ename} declares "
                        "no `sensitiveReaders` and the field declares no "
                        "`mask` — pick one: set `sensitiveReaders: []` (nobody "
                        "unmasks; masked-only) and/or a `mask` kind, or list "
                        "the role slugs that may view the full value"
                    ),
                    "location": loc,
                })

    return out


# Types the tsvector/GIN full-text search path is defined for. Only string-shaped
# columns can be to_tsvector-lexed; numeric / uuid / boolean / jsonb / date columns
# would either fail the cast or produce nonsense tokens. Reject up-front rather
# than emit a schema Postgres won't accept.
_SEARCH_SUPPORTED_TYPES = frozenset({
    "text", "varchar", "char", "string",
})


def _rule_search_columns(plan, entities) -> list[dict]:
    """SEARCH-1 opt-in full-text search contract.

    A column flagged ``search: true`` gets a companion ``<name>_search`` column
    (Postgres ``tsvector``, ``GENERATED ALWAYS AS`` from the plaintext) + a GIN
    index. The Data Engine's ``op:"search"`` reads the manifest emitted by the
    schema builder and queries these columns with ``plainto_tsquery`` +
    ``ts_rank``. This rule guards the plan-authoring surface:

      1. ``search: true`` is only defined for string-shaped columns
         (``text``/``varchar``/``char``/``string``). ``to_tsvector`` requires
         text input; numeric/uuid/boolean/jsonb/date columns would either fail
         to cast or produce useless lexemes.
      2. A column MUST NOT be both ``sensitive: true`` AND ``search: true``.
         The plaintext lives in a ``_search`` tsvector column indexed by GIN;
         an attacker with SELECT on the entity can enumerate the plaintext via
         ``WHERE <col>_search @@ tsquery`` (each successful match narrows the
         string). This is a security invariant, not just a lint — the two
         flags are structurally incompatible.
    """
    out: list[dict] = []

    for ename, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        for fi, f in enumerate(_fields_of(entity)):
            if not isinstance(f, dict):
                continue
            if not f.get("search"):
                continue
            name = _field_name(f) or f"field[{fi}]"
            loc = f"$.entities[{ename}].fields[{name}]"
            ftype = str(f.get("type") or "").lower().strip()

            # (1) type support — only string-shaped columns can be indexed.
            if ftype not in _SEARCH_SUPPORTED_TYPES:
                out.append({
                    "rule": "search_field_type_unsupported",
                    "severity": "error",
                    "message": (
                        f"{ename}.{name} declares `search: true` on a {ftype!r} "
                        "column; only string-shaped columns (text/varchar/char) "
                        "can be indexed for full-text search"
                    ),
                    "location": loc,
                })
                continue

            # (2) sensitive + search is a leak. A GIN-indexed tsvector on the
            # plaintext lets any SELECT-holder enumerate the value with
            # narrowing tsquery matches, defeating encrypt-at-rest.
            if f.get("sensitive"):
                out.append({
                    "rule": "search_field_sensitive_conflict",
                    "severity": "error",
                    "message": (
                        f"{ename}.{name} is both `sensitive: true` and "
                        "`search: true` — a GIN-indexed tsvector on the "
                        "plaintext defeats encrypt-at-rest (an attacker with "
                        "SELECT can enumerate the value via narrowing "
                        "`WHERE <col>_search @@ tsquery` matches). Pick one."
                    ),
                    "location": loc,
                })

    return out


def _rule_workflow_inputs_declared(plan) -> list[dict]:
    """Every non-scheduled workflow MUST declare `inputs[]`.

    A user-triggered workflow with no declared inputs forces the
    workflow_launch_forms deriver to guess the trigger surface from the
    write set — which is what shipped the one-field Schedule Interview
    form in the cabin-crew app.
    """
    out: list[dict] = []
    for wi, w in enumerate(_workflows(plan)):
        if not isinstance(w, dict):
            continue
        trigger = str(w.get("trigger") or "").lower()
        if "schedule" in trigger or "cron" in trigger:
            # Scheduled workflows don't have a user trigger surface.
            continue
        name = w.get("name") or f"workflow[{wi}]"
        inputs = w.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            out.append({
                "rule": "workflow_inputs_missing", "severity": "warning",
                "message": (
                    f"workflow `{name}` has no declared `inputs[]` — its trigger "
                    "form will be under-specified"
                ),
                "location": f"$.workflows[{wi}].inputs",
            })
    return out


def _rule_nav_completeness(plan) -> list[dict]:
    """The `nav` block must exist and cover every actor role.

    Missing `initialFor` for an actor forces every session of that role
    to fall back to DEFAULT_INITIAL — which is usually wrong for at
    least one role. Missing `sidebar` forces the shell_menu_sync pass
    to derive one, which drops the plan's ordering + grouping intent.
    """
    out: list[dict] = []
    nav = plan.get("nav") or {}
    if not isinstance(nav, dict):
        out.append({
            "rule": "nav_missing", "severity": "warning",
            "message": "plan has no `nav` block — root redirect + sidebar will be inferred",
            "location": "$.nav",
        })
        return out

    actors = plan.get("actors") or []
    actor_roles = {a.get("role") for a in actors if isinstance(a, dict) and a.get("role")}

    initial_for = nav.get("initialFor") or {}
    if isinstance(initial_for, dict):
        for role in actor_roles:
            if role not in initial_for:
                out.append({
                    "rule": "nav_initial_missing", "severity": "warning",
                    "message": (
                        f"nav.initialFor has no entry for role `{role}` — that "
                        "actor will land on DEFAULT_INITIAL, likely wrong"
                    ),
                    "location": f"$.nav.initialFor.{role}",
                })

    sidebar = nav.get("sidebar")
    if not isinstance(sidebar, list) or not sidebar:
        out.append({
            "rule": "nav_sidebar_missing", "severity": "warning",
            "message": "nav.sidebar is empty — shell menu will be auto-derived",
            "location": "$.nav.sidebar",
        })
    else:
        # every listed route must exist in pages[]
        page_routes = {
            p.get("route") for p in _pages(plan)
            if isinstance(p, dict) and p.get("route")
        }
        for si, entry in enumerate(sidebar):
            if not isinstance(entry, dict):
                continue
            for ri, r in enumerate(entry.get("items") or []):
                if isinstance(r, str) and r not in page_routes:
                    out.append({
                        "rule": "nav_sidebar_orphan", "severity": "warning",
                        "message": (
                            f"nav.sidebar[{si}].items[{ri}] = `{r}` — not in "
                            "pages[]; sidebar link will 404"
                        ),
                        "location": f"$.nav.sidebar[{si}].items[{ri}]",
                    })

    return out


# --------------------------------------------------------------------------- #
# Slice A T3 — SUBMIT-AUTHORITY rules
# --------------------------------------------------------------------------- #

def _rule_forms_have_submit(plan: dict, entities: dict[str, dict]) -> list[dict]:
    """Every form-typed page must declare `submit.target`. When it
    does, the target must name a real workflow (for kind=workflow) or
    a real entity (for kind=data_api)."""
    out: list[dict] = []
    workflow_names = {
        w.get("name") for w in _workflows(plan)
        if isinstance(w, dict) and isinstance(w.get("name"), str)
    }
    for pi, page in enumerate(_pages(plan)):
        if str(page.get("type") or "").lower() != "form":
            continue
        submit = page.get("submit")
        if not isinstance(submit, dict) or not submit.get("target"):
            out.append({
                "rule": "form_missing_submit",
                "severity": "warning",
                "message": (
                    f"page `{page.get('name')}` is type=form but has no "
                    "`submit.target` — form will silently post nowhere or "
                    "default to /api/data/<entity>"
                ),
                "location": f"$.pages[{pi}]",
            })
            continue
        kind = str(submit.get("kind") or "data_api").lower()
        target = str(submit.get("target"))
        if kind == "workflow" and target not in workflow_names:
            out.append({
                "rule": "submit_target_missing",
                "severity": "warning",
                "message": (
                    f"page `{page.get('name')}`.submit.target = "
                    f"`{target}` — no workflow with that name in plan.workflows[]"
                ),
                "location": f"$.pages[{pi}].submit.target",
            })
        elif kind == "data_api" and target not in entities:
            out.append({
                "rule": "submit_target_missing",
                "severity": "warning",
                "message": (
                    f"page `{page.get('name')}`.submit.target = "
                    f"`{target}` — no entity with that name in data_models[]"
                ),
                "location": f"$.pages[{pi}].submit.target",
            })
    return out


def _rule_workflows_have_source(plan: dict) -> list[dict]:
    """Every workflow must declare `source.kind`. When kind is form/
    button, `source.page` must name a real page."""
    out: list[dict] = []
    page_names = {
        p.get("name") for p in _pages(plan)
        if isinstance(p, dict) and isinstance(p.get("name"), str)
    }
    for wi, wf in enumerate(_workflows(plan)):
        source = wf.get("source")
        if not isinstance(source, dict) or not source.get("kind"):
            out.append({
                "rule": "workflow_missing_source",
                "severity": "warning",
                "message": (
                    f"workflow `{wf.get('name')}` has no `source` — nothing "
                    "in the UI dispatches it (orphan). Add source.kind = "
                    "form|button|event|timer|webhook|cron."
                ),
                "location": f"$.workflows[{wi}]",
            })
            continue
        if source.get("kind") in ("form", "button"):
            page = source.get("page")
            if not isinstance(page, str) or page not in page_names:
                out.append({
                    "rule": "workflow_source_page_missing",
                    "severity": "warning",
                    "message": (
                        f"workflow `{wf.get('name')}`.source.page = "
                        f"`{page}` — no page with that name in plan.pages[]"
                    ),
                    "location": f"$.workflows[{wi}].source.page",
                })
    return out


def _rule_input_sources_resolve(plan: dict) -> list[dict]:
    """For every workflow input with a source, verify the source anchors
    into the plan: form_field must match a field on the source page,
    route param must appear in the source page's route, missing source
    on a required input is flagged."""
    out: list[dict] = []
    pages_by_name = {p.get("name"): p for p in _pages(plan)
                     if isinstance(p, dict) and isinstance(p.get("name"), str)}
    import re
    route_param_re = re.compile(
        r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]|:([a-zA-Z_][a-zA-Z0-9_]*)"
    )
    for wi, wf in enumerate(_workflows(plan)):
        source = wf.get("source") or {}
        source_page = None
        if isinstance(source, dict) and source.get("kind") in ("form", "button"):
            source_page = pages_by_name.get(source.get("page"))
        inputs = wf.get("inputs") or []
        if not isinstance(inputs, list):
            continue
        for ii, inp in enumerate(inputs):
            if not isinstance(inp, dict):
                continue
            src = inp.get("source")
            required = bool(inp.get("required"))
            if not isinstance(src, dict) or not src.get("kind"):
                if required:
                    out.append({
                        "rule": "input_missing_source",
                        "severity": "warning",
                        "message": (
                            f"workflow `{wf.get('name')}`.inputs[`{inp.get('name')}`] "
                            "is required but has no `source` — runtime "
                            "dispatcher cannot populate it"
                        ),
                        "location": f"$.workflows[{wi}].inputs[{ii}]",
                    })
                continue
            kind = src.get("kind")
            if kind == "form_field":
                field_name = src.get("field")
                if source_page is None:
                    continue  # source page unknown → workflow_source_page rule already flags
                form_field_names = _form_field_names(source_page)
                if field_name not in form_field_names:
                    out.append({
                        "rule": "input_source_form_field_missing",
                        "severity": "warning",
                        "message": (
                            f"workflow `{wf.get('name')}`.inputs[`{inp.get('name')}`]"
                            f".source.field=`{field_name}` — not a field on "
                            f"page `{source_page.get('name')}`"
                        ),
                        "location": f"$.workflows[{wi}].inputs[{ii}].source",
                    })
            elif kind == "route":
                param = src.get("param")
                if source_page is None:
                    continue
                route = str(source_page.get("route") or "")
                declared = {m.group(1) or m.group(2)
                            for m in route_param_re.finditer(route)}
                if param not in declared:
                    out.append({
                        "rule": "input_source_route_param_missing",
                        "severity": "warning",
                        "message": (
                            f"workflow `{wf.get('name')}`.inputs[`{inp.get('name')}`]"
                            f".source.param=`{param}` — not declared in "
                            f"page `{source_page.get('name')}`.route=`{route}`"
                        ),
                        "location": f"$.workflows[{wi}].inputs[{ii}].source",
                    })
    return out


def _rule_workflow_resume_task_id(plan: dict) -> list[dict]:
    """Slice E T6: a page whose submit.kind is ``workflow_resume``
    must:
      - name a real workflow via ``submit.target``
      - carry a ``task_id`` spec whose ``kind`` is ``route`` (the
        /tasks/[id] page reads the id from the URL — no other source
        makes sense for this shape)
      - the ``task_id.param`` must appear in the page's own route.
    """
    import re
    param_re = re.compile(
        r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]|:([a-zA-Z_][a-zA-Z0-9_]*)"
    )
    workflow_names = {
        w.get("name") for w in _workflows(plan)
        if isinstance(w, dict) and isinstance(w.get("name"), str)
    }
    out: list[dict] = []
    for pi, page in enumerate(_pages(plan)):
        submit = page.get("submit")
        if not isinstance(submit, dict):
            continue
        if str(submit.get("kind") or "").strip() != "workflow_resume":
            continue

        loc = f"$.pages[{pi}].submit"
        target = submit.get("target")
        if not isinstance(target, str) or target not in workflow_names:
            out.append({
                "rule":     "workflow_resume_unknown_target",
                "severity": "warning",
                "message":  (
                    f"page `{page.get('name')}`.submit.target="
                    f"`{target}` — no workflow with that name"
                ),
                "location": loc,
            })
            continue  # subsequent checks assume target valid

        task_id = submit.get("task_id") or {"kind": "route", "param": "id"}
        if not isinstance(task_id, dict):
            out.append({
                "rule":     "workflow_resume_task_id_missing",
                "severity": "warning",
                "message":  (
                    f"page `{page.get('name')}`.submit.task_id is missing "
                    "or not an object — must be `{kind: 'route', param: '...'}`"
                ),
                "location": loc,
            })
            continue

        kind = task_id.get("kind")
        if kind != "route":
            out.append({
                "rule":     "workflow_resume_task_id_kind",
                "severity": "warning",
                "message":  (
                    f"page `{page.get('name')}`.submit.task_id.kind="
                    f"`{kind}` — workflow_resume requires kind='route' "
                    "(the /tasks/[id] page reads the id from the URL)"
                ),
                "location": f"{loc}.task_id",
            })
            continue

        param = task_id.get("param")
        route = str(page.get("route") or "")
        route_params = {
            m.group(1) or m.group(2) for m in param_re.finditer(route)
        }
        if not isinstance(param, str) or param not in route_params:
            out.append({
                "rule":     "workflow_resume_task_id_param",
                "severity": "warning",
                "message":  (
                    f"page `{page.get('name')}`.submit.task_id.param=`{param}` "
                    f"— not declared in route `{route}`"
                ),
                "location": f"{loc}.task_id",
            })

    return out


def _form_field_names(page: dict) -> set[str]:
    """Every field name declared on ``page.fields[]`` — the planner-
    authored field spec. Doesn't attempt to introspect a materialized
    page schema (that's what the post-generate guards do)."""
    out: set[str] = set()
    fields = page.get("fields")
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                n = f.get("name")
                if isinstance(n, str) and n:
                    out.add(n)
    return out

def _rule_workflow_entity_has_page(plan) -> list[dict]:
    """Every UI-triggered workflow needs SOMEWHERE to live: at least one
    plan page must resolve for its subject entity (or its trigger page).
    A workflow whose entity has no page ships as an unreachable feature —
    the fleet's yoga fixture lost 15+ delivery points to exactly this.
    Feeds the planner REVISE loop so new plans fix it at the source; the
    transition materializer's landing-page fallback is the backstop for
    plans that ship anyway.
    """
    from services.transition_materializer import (
        _entity_page_candidates,
        _resolve_page_route,
    )
    out: list[dict] = []
    if not isinstance(plan, dict):
        return out
    for wf in plan.get("workflows") or []:
        if not isinstance(wf, dict) or not wf.get("name"):
            continue
        trigger = wf.get("trigger")
        t = (trigger if isinstance(trigger, str)
             else str((trigger or {}).get("type") or "")).strip().lower()
        if not t.startswith(("manual", "button", "user", "form")):
            continue
        # An "on <Page>" clause that resolves is sufficient.
        import re as _re
        m = _re.search(r"\bon\s+(.+)$", t, _re.IGNORECASE)
        resolved = False
        if m:
            for cand in _re.split(r"\s+or\s+|,", m.group(1)):
                cand = cand.strip().split()[0] if cand.strip() else ""
                if cand and _resolve_page_route(cand, plan):
                    resolved = True
                    break
        if not resolved:
            for cand in _entity_page_candidates(wf):
                if _resolve_page_route(cand, plan):
                    resolved = True
                    break
        if not resolved:
            out.append({
                "rule": "workflow_entity_has_page",
                "severity": "error",
                "subject": str(wf["name"]),
                "message": (
                    f"workflow {wf['name']!r} (trigger {t!r}) has no page "
                    "for its entity — add a list or detail page for the "
                    "entity this workflow operates on, or name an existing "
                    "page in the trigger"),
            })
    return out

