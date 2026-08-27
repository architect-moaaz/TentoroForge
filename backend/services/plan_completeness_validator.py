"""Plan completeness validator — the deterministic gate that keeps
downstream authorities from having to guess.

Rationale
---------
Every failure mode we've been chasing (Status pollution, Based-At-as-date,
Schedule-Interview-with-one-field) traces back to the SAME shape: the
planner emitted a plan with fields missing, and downstream agents built
their best guess to fill the gap. Slices 1-5 taught the readers to
prefer plan declarations when present. This module closes the loop:
after the planner emits, we CHECK that the fields those readers need
ARE actually present. On miss we tell the planner exactly what to fix
and give it one focused REVISE turn.

Rules enforced
--------------
1. **enum_values on restricted-vocabulary columns.** If any workflow
   sets a column to a literal string value (``set: {status: "shortlisted"}``
   or ``values: {status: "shortlisted"}``), that column's ``enum_values``
   MUST include every such literal across the whole plan. Violation kills
   Bug 2 at the source.
2. **fk on non-primary uuid columns.** Any ``uuid`` field that isn't
   marked ``primaryKey: true`` MUST declare ``fk: {table, column}``. A
   bare uuid FK is what makes the harvester guess entity targets.
3. **inputs on user-triggered workflows.** Any workflow with
   ``trigger`` shape "manual" / "user"-style MUST declare an ``inputs``
   list covering the columns its entry-action writes that aren't
   session-derivable. Violation kills Bug 5.
4. **not_null declared on every field.** Absent ``not_null`` is
   ambiguous — the schema builder guesses False and required-marker
   pass has no signal to add red asterisks. Declaring the flag either
   way removes the ambiguity.

The validator is pure — takes a plan dict, returns a list of
`Violation`. Callers decide what to do (raise, revise, log). The
formatter turns violations into the "GAPS TO FIX:" block the planner's
REVISE MODE already understands, so we reuse that contract instead of
inventing a new one.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable


# ══════════════════════════════════════════════════════════════════
# Slice-2 strict-mode gate
# ══════════════════════════════════════════════════════════════════
#
# The 5 Slice-1 rules below are advisory by default (part of the same
# violation list every other rule uses; downstream reads and retries).
# Strict mode makes them a HARD gate: incomplete plan halts before any
# emitter runs. Env-gated so the flip is reviewable per environment.

# Rule slugs the Slice-1 additions produce. Keep in sync with the
# ``_check_*`` functions below.
SLICE1_EXECUTABILITY_RULES = frozenset({
    "page_data_source_declared",
    "page_actions_declared",
    "action_target_resolves",
    "workflow_has_step",
    "entity_has_surface",
})


def is_strict_plan_enabled() -> bool:
    """True when generation should halt if any Slice-1 executability rule
    fires. Default off; opt in per environment via ``FORGE_STRICT_PLAN``."""
    return os.getenv("FORGE_STRICT_PLAN", "").strip().lower() in (
        "1", "true", "yes", "on", "strict",
    )


def executability_violations(plan: dict) -> list[Violation]:
    """Return ONLY the Slice-1 executability violations for the plan.
    Same shape as :func:`validate_plan_completeness` — callers grepping
    for a specific rule get one authoritative list."""
    if not isinstance(plan, dict):
        return []
    return [v for v in validate_plan_completeness(plan)
            if v.rule in SLICE1_EXECUTABILITY_RULES]


class PlanNotExecutableError(RuntimeError):
    """Raised when strict mode is on AND the plan has Slice-1 violations.

    Carries the violation list so callers can render a REVISE prompt
    (via :func:`format_revise_gaps`) or surface it to the user."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        counts: dict[str, int] = {}
        for v in violations:
            counts[v.rule] = counts.get(v.rule, 0) + 1
        summary = ", ".join(f"{r}={c}" for r, c in sorted(counts.items()))
        super().__init__(
            f"plan is not executable: {summary}. "
            "Set FORGE_STRICT_PLAN=off to downgrade to warnings, or run the "
            "REVISE loop to have the planner fill the gaps."
        )


def enforce_plan_executability(plan: dict) -> list[Violation]:
    """Return Slice-1 violations. Raise :class:`PlanNotExecutableError`
    when strict mode is on AND any violation exists — this is the seam
    every emitter (or the pipeline before it fans out) should call
    before touching the plan.

    Never raises when strict mode is off (default) — the returned list
    is the caller's cue to log / retry / carry on.
    """
    v = executability_violations(plan)
    if v and is_strict_plan_enabled():
        raise PlanNotExecutableError(v)
    return v


@dataclass(frozen=True)
class Violation:
    """One completeness gap. ``rule`` is a stable slug for tests; ``msg``
    is the human-readable line that lands in the REVISE prompt."""
    rule: str
    entity: str | None = None
    field: str | None = None
    workflow: str | None = None
    msg: str = ""


# ──────────────────────────────────────────────────────────────────
# Plan-shape helpers — support all plan flavours (dict/list/oneshot)
# ──────────────────────────────────────────────────────────────────

def _iter_entities(plan: dict) -> Iterable[tuple[str, dict]]:
    """Yield (name, entity_dict) across all plan shapes we accept."""
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for name, ent in ents.items():
            if isinstance(name, str) and isinstance(ent, dict):
                yield name, ent
    dm = plan.get("data_models") or plan.get("dataModels")
    if isinstance(dm, list):
        for ent in dm:
            if isinstance(ent, dict):
                name = ent.get("name")
                if isinstance(name, str):
                    yield name, ent


def _iter_fields(entity: dict) -> Iterable[dict]:
    fields = entity.get("fields")
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict) and f.get("name"):
                yield f
    elif isinstance(fields, dict):
        # {colname: {...meta}} — dict-of-fields shape
        for name, meta in fields.items():
            if isinstance(meta, dict):
                yield {"name": name, **meta}


def _iter_workflows(plan: dict) -> Iterable[dict]:
    wfs = plan.get("workflows")
    if isinstance(wfs, list):
        for w in wfs:
            if isinstance(w, dict) and w.get("name"):
                yield w


def _fold_col(name: str | None) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


# ──────────────────────────────────────────────────────────────────
# Rule 1 — enum_values on restricted-vocabulary columns
# ──────────────────────────────────────────────────────────────────

def _harvest_literal_writes(plan: dict) -> dict[str, set[str]]:
    """Return ``{column_name (folded): {literals}}`` for every string value
    the workflows write to a column. Only STRINGS count — a binding like
    ``{{userId}}`` is not a restricted vocabulary."""
    out: dict[str, set[str]] = {}

    def _visit(node):
        if isinstance(node, dict):
            # Common shapes: {"set": {col: value, ...}}, {"values": {...}},
            # or a step config {"actionType": "db_update", "values": {...}}.
            for key in ("set", "values", "fields"):
                v = node.get(key)
                if isinstance(v, dict):
                    for col, val in v.items():
                        if isinstance(val, str) and not (
                            val.startswith("{{") or val.startswith("$")
                        ):
                            out.setdefault(_fold_col(col), set()).add(val)
            for v in node.values():
                _visit(v)
        elif isinstance(node, list):
            for v in node:
                _visit(v)

    _visit(plan.get("workflows"))
    return out


def _check_enum_values(plan: dict) -> list[Violation]:
    """A column that any workflow writes with literal strings MUST declare
    ``enum_values`` covering every observed literal.

    The intent: if the planner's OWN workflows write ``status: "shortlisted"``,
    the planner MUST tell downstream what the allowed status values are, or
    the harvester will invent them (Bug 2)."""
    literals = _harvest_literal_writes(plan)
    if not literals:
        return []
    out: list[Violation] = []
    for ent_name, ent in _iter_entities(plan):
        for f in _iter_fields(ent):
            col_name = f.get("name") or ""
            folded = _fold_col(col_name)
            observed = literals.get(folded)
            if not observed:
                continue
            # Spec B1: enum_values may be flat `[str]` or `[{key|value, label}]`.
            # Extract the key from either shape so the coverage check works both ways.
            declared_raw = f.get("enum_values")
            declared: set = set()
            if isinstance(declared_raw, list):
                for entry in declared_raw:
                    if isinstance(entry, str):
                        declared.add(entry)
                    elif isinstance(entry, dict):
                        k = entry.get("key") or entry.get("value")
                        if isinstance(k, str):
                            declared.add(k)
            missing = sorted(observed - declared)
            if missing:
                out.append(Violation(
                    rule="missing_enum_values",
                    entity=ent_name,
                    field=col_name,
                    msg=(
                        f"{ent_name}.{col_name} is written to literal string "
                        f"value(s) {sorted(observed)!r} by workflows, but its "
                        f"enum_values is missing/incomplete (declared: "
                        f"{sorted(declared)!r}; not covered: {missing!r}). "
                        "Add enum_values covering every literal the workflows write."
                    ),
                ))
    return out


# ──────────────────────────────────────────────────────────────────
# Rule 2 — fk on non-primary uuid columns
# ──────────────────────────────────────────────────────────────────

_UUID_TYPES = {"uuid", "guid"}


def _check_fk(plan: dict) -> list[Violation]:
    """Every non-primary-key uuid field MUST declare ``fk: {table, column}``.

    A bare uuid column with no fk is a foot-gun: the downstream FK
    resolver has to guess the target entity from the column name,
    which is how ``mismatched dropdowns`` happen."""
    out: list[Violation] = []
    for ent_name, ent in _iter_entities(plan):
        for f in _iter_fields(ent):
            typ = str(f.get("type") or "").lower()
            if typ not in _UUID_TYPES:
                continue
            if f.get("primaryKey") or f.get("primary_key"):
                continue
            if _fold_col(f.get("name")) == "id":
                continue  # tolerate bare `id` shorthand
            fk = f.get("fk")
            if isinstance(fk, dict) and fk.get("table") and fk.get("column"):
                continue
            out.append(Violation(
                rule="missing_fk",
                entity=ent_name,
                field=f.get("name"),
                msg=(
                    f"{ent_name}.{f.get('name')} is a uuid but declares no fk. "
                    "Add fk: {table, column} naming the referenced entity, or "
                    "mark this field primaryKey: true if it isn't a foreign key."
                ),
            ))
    return out


# ──────────────────────────────────────────────────────────────────
# Rule 3 — inputs on user-triggered workflows
# ──────────────────────────────────────────────────────────────────

_MANUAL_TRIGGER_TOKENS = ("manual", "user", "button")


def _is_user_triggered(wf: dict) -> bool:
    trig = wf.get("trigger")
    if isinstance(trig, str):
        return any(tok in trig.lower() for tok in _MANUAL_TRIGGER_TOKENS)
    if isinstance(trig, dict):
        t = str(trig.get("type") or trig.get("kind") or "").lower()
        return any(tok in t for tok in _MANUAL_TRIGGER_TOKENS)
    return False


def _check_workflow_inputs(plan: dict) -> list[Violation]:
    """User-triggered workflows MUST declare ``inputs``. Silence here is
    what causes bare-button launch forms to ship with one field (Bug 5).
    Empty list ``inputs: []`` is treated as ``missing`` — the writer must
    either populate it OR explicitly declare the trigger provides no
    user-collected inputs (which is rare and warrants re-examination)."""
    out: list[Violation] = []
    for w in _iter_workflows(plan):
        if not _is_user_triggered(w):
            continue
        raw = w.get("inputs") or w.get("trigger_inputs")
        if isinstance(raw, list) and any(r for r in raw):
            continue
        out.append(Violation(
            rule="missing_workflow_inputs",
            workflow=str(w.get("name")),
            msg=(
                f"Workflow {w.get('name')!r} is user-triggered but declares "
                "no inputs[]. List every column its entry-action writes that "
                "is not derivable from session/URL/defaults — the launch form "
                "collects exactly those fields."
            ),
        ))
    return out


# ──────────────────────────────────────────────────────────────────
# Rule 4 — not_null on every field
# ──────────────────────────────────────────────────────────────────

def _check_not_null(plan: dict) -> list[Violation]:
    """Absent ``not_null`` on a field is ambiguous. The plan must declare
    it either True or False so the required-marker pass has an authority
    to read from (not a guess)."""
    out: list[Violation] = []
    for ent_name, ent in _iter_entities(plan):
        for f in _iter_fields(ent):
            if "not_null" in f or "notNull" in f or "nullable" in f:
                continue
            if f.get("primaryKey") or f.get("primary_key"):
                continue  # PK is not-null by convention
            out.append(Violation(
                rule="missing_not_null",
                entity=ent_name,
                field=f.get("name"),
                msg=(
                    f"{ent_name}.{f.get('name')} is missing ``not_null``. "
                    "Set it to true or false — never leave it unspecified."
                ),
            ))
    return out


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def validate_plan_completeness(plan: dict) -> list[Violation]:
    """Run all rules against a plan. Empty list = complete.

    Order matters only for readability of the REVISE output: enum before
    fk before workflow inputs before not_null. The planner sees them in
    that order and works top-down.
    """
    if not isinstance(plan, dict):
        return []
    out: list[Violation] = []
    out.extend(_check_enum_values(plan))
    out.extend(_check_fk(plan))
    out.extend(_check_workflow_inputs(plan))
    out.extend(_check_not_null(plan))
    out.extend(_check_action_targets(plan))
    # Slice-1 executability rules — the "plan must be executable, not
    # interpretable" contract. Each one closes a class of downstream
    # guessing (dataSource entity mis-binding, unattached buttons,
    # phantom workflows, planned-but-no-page entities).
    out.extend(_check_page_data_source_declared(plan))
    out.extend(_check_page_actions_declared(plan))
    out.extend(_check_action_target_resolves(plan))
    out.extend(_check_workflow_has_step(plan))
    out.extend(_check_entity_has_surface(plan))
    out.extend(_check_field_interactions_resolve(plan))
    # Spec D Wave 1 — page.ux_hint shape check. Rule fires ONLY when
    # the field is present (opt-in field); absence is legal.
    out.extend(_check_page_ux_hint_shape(plan))
    return out


# ══════════════════════════════════════════════════════════════════
# Spec D Wave 1 — page.ux_hint shape validator
# ══════════════════════════════════════════════════════════════════
#
# The planner MAY attach ``ux_hint`` per page (see PLANNER_SYSTEM_PROMPT
# / Spec D Wave 1 block). Downstream page-builders will prefer these
# hints over ``services/domain_ux_specs.py``'s hardcoded per-industry
# playbook once the consumer-side migration lands. For now we only
# validate SHAPE: absence is legal (old plans stay valid); when
# present, the block must have known field types + string sizes.


_UX_HINT_HERO_FIELDS_MAX = 6
_UX_HINT_KEY_WIDGETS_MAX = 5
_UX_HINT_EMPTY_STATE_MAX = 160
_UX_HINT_INFO_HIERARCHY_MAX = 80

_UX_HINT_ALLOWED_KEYS: frozenset[str] = frozenset({
    "hero_fields", "key_widgets", "empty_state", "info_hierarchy",
})


def _check_page_ux_hint_shape(plan: dict) -> list[Violation]:
    """Rule ``page_ux_hint_invalid`` — every page whose ``ux_hint`` is
    present must be a dict with the four known keys (any subset) and
    correctly-typed values within size bounds.

    Absence of ``ux_hint`` is always fine. Extra keys are a soft error
    that surfaces so the planner learns which keys are meaningful.
    """
    out: list[Violation] = []
    for p in _iter_pages(plan):
        if "ux_hint" not in p:
            continue
        pid = p.get("id") or p.get("route") or "(unknown)"
        hint = p.get("ux_hint")
        if not isinstance(hint, dict):
            out.append(Violation(
                rule="page_ux_hint_invalid",
                msg=(f"page {pid!r} ``ux_hint`` must be a JSON object "
                     f"with keys {sorted(_UX_HINT_ALLOWED_KEYS)}, "
                     f"got {type(hint).__name__}."),
            ))
            continue
        unknown = [k for k in hint.keys() if k not in _UX_HINT_ALLOWED_KEYS]
        if unknown:
            out.append(Violation(
                rule="page_ux_hint_invalid",
                msg=(f"page {pid!r} ``ux_hint`` has unknown key(s) "
                     f"{unknown}. Allowed: {sorted(_UX_HINT_ALLOWED_KEYS)}."),
            ))
            # keep validating the known keys we did find
        # hero_fields
        if "hero_fields" in hint:
            v = hint["hero_fields"]
            if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=f"page {pid!r} ``ux_hint.hero_fields`` must be list[str].",
                ))
            elif len(v) > _UX_HINT_HERO_FIELDS_MAX:
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=(f"page {pid!r} ``ux_hint.hero_fields`` has {len(v)} "
                         f"entries; max {_UX_HINT_HERO_FIELDS_MAX}."),
                ))
        # key_widgets
        if "key_widgets" in hint:
            v = hint["key_widgets"]
            if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=f"page {pid!r} ``ux_hint.key_widgets`` must be list[str].",
                ))
            elif len(v) > _UX_HINT_KEY_WIDGETS_MAX:
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=(f"page {pid!r} ``ux_hint.key_widgets`` has {len(v)} "
                         f"entries; max {_UX_HINT_KEY_WIDGETS_MAX}."),
                ))
        # empty_state
        if "empty_state" in hint:
            v = hint["empty_state"]
            if not isinstance(v, str):
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=f"page {pid!r} ``ux_hint.empty_state`` must be a string.",
                ))
            elif len(v) > _UX_HINT_EMPTY_STATE_MAX:
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=(f"page {pid!r} ``ux_hint.empty_state`` is "
                         f"{len(v)} chars; max {_UX_HINT_EMPTY_STATE_MAX}."),
                ))
        # info_hierarchy
        if "info_hierarchy" in hint:
            v = hint["info_hierarchy"]
            if not isinstance(v, str):
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=f"page {pid!r} ``ux_hint.info_hierarchy`` must be a string.",
                ))
            elif len(v) > _UX_HINT_INFO_HIERARCHY_MAX:
                out.append(Violation(
                    rule="page_ux_hint_invalid",
                    msg=(f"page {pid!r} ``ux_hint.info_hierarchy`` is "
                         f"{len(v)} chars; max {_UX_HINT_INFO_HIERARCHY_MAX}."),
                ))
    return out


def _check_field_interactions_resolve(plan: dict) -> list[Violation]:
    """Field-Interaction Authoring — every ``interaction`` block the LLM
    (or auto-derive) put on a field must validate against
    :mod:`services.interaction_spec`. Catches unknown-function typos,
    dangling sibling refs, invalid resource slugs, and cycles before
    they reach the runtime hooks.

    Rule name: ``field_interaction_invalid``. Adds one violation per
    field whose interaction fails validation, with the first error
    message from the validator as the human-readable hint.
    """
    try:
        from services.interaction_spec import validate_interaction
    except Exception:  # noqa: BLE001 — validator missing → no-op
        return []

    pages = plan.get("pages")
    if not isinstance(pages, list):
        return []

    out: list[Violation] = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        fields = p.get("fields")
        if not isinstance(fields, list):
            continue
        page_id = str(p.get("id") or p.get("route") or "?")
        for f in fields:
            if not isinstance(f, dict):
                continue
            inter = f.get("interaction")
            if not isinstance(inter, dict):
                continue
            r = validate_interaction(inter, f, fields, registry=None)
            if r.ok:
                continue
            hint = r.errors[0] if r.errors else "invalid interaction shape"
            out.append(Violation(
                rule="field_interaction_invalid",
                field=f.get("name") or None,
                msg=f"page='{page_id}' field='{f.get('name', '?')}': {hint}",
            ))
    return out


def _check_action_targets(plan: dict) -> list[Violation]:
    """Slice B — page.actions[] targets and input-map sources must
    resolve against real workflows/routes. Adapts the flat error dicts
    from :func:`services.action_authority.validate_action_targets` to
    the REVISE-loop Violation shape."""
    try:
        from services.action_authority import validate_action_targets
    except Exception:  # noqa: BLE001
        return []
    errs = validate_action_targets(plan)
    out: list[Violation] = []
    for e in errs:
        # Rule slug prefixed so tests can grep and the REVISE prompt
        # groups these together visibly.
        rule = f"action_{e.get('kind') or 'unknown'}"
        label = e.get("label") or "(unlabeled)"
        page = e.get("page") or "(unknown)"
        detail = e.get("detail") or ""
        msg = f"page {page!r} action {label!r}: {detail}"
        out.append(Violation(rule=rule, msg=msg))
    return out


# ══════════════════════════════════════════════════════════════════
# Slice-1 executability rules
# ══════════════════════════════════════════════════════════════════
#
# The "plan must be executable, not interpretable" contract. Each rule
# closes one class of downstream stages guessing — every mechanical bug
# recently fixed by a post-gen guard corresponds to one of these gaps
# in the plan. Making the planner author these facts up-front means the
# guards become retrofit-only for pre-strict apps.


_LIST_ARCHETYPES = {"list", "table", "kanban", "board", "grid", "calendar"}


def _iter_pages(plan: dict) -> Iterable[dict]:
    for p in plan.get("pages") or []:
        if isinstance(p, dict):
            yield p


def _norm_route(route: str) -> str:
    """Normalize route so `:id` and `[id]` compare equal — the planner
    uses either convention and the emitter accepts both."""
    if not isinstance(route, str):
        return ""
    # Convert `[id]` → `:id`
    import re as _re
    r = _re.sub(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", r":\1", route.strip())
    # Strip trailing slash for consistency
    return r.rstrip("/") or "/"


def _plan_entity_names(plan: dict) -> set[str]:
    return {name for name, _ in _iter_entities(plan)}


def _plan_page_routes(plan: dict) -> set[str]:
    return {_norm_route(p.get("route") or "") for p in _iter_pages(plan) if p.get("route")}


def _plan_workflow_names(plan: dict) -> set[str]:
    return {str(w.get("name")) for w in _iter_workflows(plan) if w.get("name")}


def _check_page_data_source_declared(plan: dict) -> list[Violation]:
    """R1 — every list-shaped page must declare `dataSource` with an
    entity that exists in the plan. Closes the "Carer page shows all
    users" class where the LLM reuses `users` as the dataSource on
    every persona page."""
    out: list[Violation] = []
    ent_names = _plan_entity_names(plan)
    for p in _iter_pages(plan):
        archetype = str(p.get("archetype") or "").lower()
        if archetype not in _LIST_ARCHETYPES:
            continue
        pid = p.get("id") or p.get("route") or "(unknown)"
        ds = p.get("dataSource")
        if not isinstance(ds, dict):
            out.append(Violation(
                rule="page_data_source_declared",
                msg=(
                    f"page {pid!r} is a {archetype} page but declares no "
                    "``dataSource``. Add ``dataSource: {entity, op}`` naming "
                    "the entity whose rows this page displays."
                ),
            ))
            continue
        ds_entity = ds.get("entity")
        if not isinstance(ds_entity, str) or not ds_entity:
            out.append(Violation(
                rule="page_data_source_declared",
                msg=(
                    f"page {pid!r} has ``dataSource`` but no ``entity`` field. "
                    "Name the entity whose rows this page displays."
                ),
            ))
            continue
        if ds_entity not in ent_names:
            out.append(Violation(
                rule="page_data_source_declared",
                msg=(
                    f"page {pid!r} dataSource entity {ds_entity!r} is not a "
                    "planned entity. Either add the entity to ``entities`` or "
                    "point the dataSource at one that exists."
                ),
            ))
    return out


_VALID_ACTION_KINDS = {"workflow", "navigate", "external", "none"}


def _check_page_actions_declared(plan: dict) -> list[Violation]:
    """R2 — every page must declare ``actions`` (possibly empty). Each
    action must have ``label``, ``kind``, and (unless kind=='none') a
    ``target``. This closes the "unattached button" class: the schema
    emitter no longer has to invent action wiring because the plan
    already enumerates the interactive surfaces."""
    out: list[Violation] = []
    for p in _iter_pages(plan):
        pid = p.get("id") or p.get("route") or "(unknown)"
        if "actions" not in p:
            out.append(Violation(
                rule="page_actions_declared",
                msg=(
                    f"page {pid!r} is missing ``actions``. Declare every "
                    "user-triggered control on the page as an entry in "
                    "``actions[]`` with ``{label, kind, target?}``. Empty list "
                    "is fine for view-only pages — the field being absent is "
                    "not (silently no actions => downstream invents them)."
                ),
            ))
            continue
        actions = p.get("actions")
        if not isinstance(actions, list):
            out.append(Violation(
                rule="page_actions_declared",
                msg=(
                    f"page {pid!r} ``actions`` must be a list (was "
                    f"{type(actions).__name__})."
                ),
            ))
            continue
        for i, a in enumerate(actions):
            if not isinstance(a, dict):
                out.append(Violation(
                    rule="page_actions_declared",
                    msg=f"page {pid!r} actions[{i}] must be an object.",
                ))
                continue
            kind = a.get("kind")
            if not isinstance(kind, str) or kind not in _VALID_ACTION_KINDS:
                label = a.get("label") or f"actions[{i}]"
                out.append(Violation(
                    rule="page_actions_declared",
                    msg=(
                        f"page {pid!r} action {label!r} must declare "
                        f"``kind`` (one of {sorted(_VALID_ACTION_KINDS)}). "
                        "Use ``kind: \"none\"`` for decorative/view-only "
                        "controls — leaving it out lets downstream guess."
                    ),
                ))
                continue
            if kind == "none":
                continue
            target = a.get("target")
            if not isinstance(target, str) or not target:
                label = a.get("label") or f"actions[{i}]"
                out.append(Violation(
                    rule="page_actions_declared",
                    msg=(
                        f"page {pid!r} action {label!r} has kind={kind!r} but "
                        "no ``target``. Name the workflow, route, or URL."
                    ),
                ))
    return out


def _check_action_target_resolves(plan: dict) -> list[Violation]:
    """R3 — every action.target must resolve against the plan. Closes
    the "phantom workflow" class (``workflow: 'CreateUser'`` with no
    workflow file) and the "navigate: /nowhere" class."""
    out: list[Violation] = []
    wf_names = _plan_workflow_names(plan)
    routes = _plan_page_routes(plan)
    for p in _iter_pages(plan):
        pid = p.get("id") or p.get("route") or "(unknown)"
        for a in p.get("actions") or []:
            if not isinstance(a, dict):
                continue
            kind = a.get("kind")
            target = a.get("target")
            if kind not in ("workflow", "navigate"):
                continue  # external / none don't resolve against the plan
            if not isinstance(target, str) or not target:
                continue  # covered by R2
            if kind == "workflow" and target not in wf_names:
                label = a.get("label") or "(unlabeled)"
                out.append(Violation(
                    rule="action_target_resolves",
                    msg=(
                        f"page {pid!r} action {label!r} dispatches workflow "
                        f"{target!r} which is not in ``workflows[]``. Add the "
                        "workflow OR pick an existing name."
                    ),
                ))
            elif kind == "navigate" and _norm_route(target) not in routes:
                label = a.get("label") or "(unlabeled)"
                out.append(Violation(
                    rule="action_target_resolves",
                    msg=(
                        f"page {pid!r} action {label!r} navigates to {target!r} "
                        "which is not a planned page route. Add the destination "
                        "page OR pick an existing route."
                    ),
                ))
    return out


def _check_workflow_has_step(plan: dict) -> list[Violation]:
    """R4 — every workflow that any action dispatches must have at least
    one step. Empty workflows silently drop the click; the runtime shows
    no error."""
    out: list[Violation] = []
    referenced: set[str] = set()
    for p in _iter_pages(plan):
        for a in p.get("actions") or []:
            if isinstance(a, dict) and a.get("kind") == "workflow":
                target = a.get("target")
                if isinstance(target, str) and target:
                    referenced.add(target)

    for w in _iter_workflows(plan):
        name = w.get("name")
        if name not in referenced:
            continue  # orphan workflows are a separate concern (warning class)
        steps = w.get("steps") or w.get("definition", {}).get("nodes")
        if not isinstance(steps, list) or not steps:
            out.append(Violation(
                rule="workflow_has_step",
                workflow=str(name),
                msg=(
                    f"workflow {name!r} is referenced by a page action but has "
                    "no ``steps``. Add at least one action step (e.g. "
                    "``{actionType: 'db_insert', table, values}``)."
                ),
            ))
    return out


def _check_entity_has_surface(plan: dict) -> list[Violation]:
    """R5 — every non-internal entity must be surfaced on at least one
    page. Closes the "PaymentMethod planned but no UI" class. Entities
    flagged ``internal: True`` are exempt (audit logs, join tables,
    system bookkeeping)."""
    out: list[Violation] = []
    surface_entities: set[str] = set()
    for p in _iter_pages(plan):
        ds = p.get("dataSource")
        if isinstance(ds, dict):
            e = ds.get("entity")
            if isinstance(e, str) and e:
                surface_entities.add(e)
        e = p.get("entity")
        if isinstance(e, str) and e:
            surface_entities.add(e)

    for name, ent in _iter_entities(plan):
        if ent.get("internal") is True:
            continue
        if name in surface_entities:
            continue
        out.append(Violation(
            rule="entity_has_surface",
            entity=name,
            msg=(
                f"entity {name!r} has no user-facing page. Either add a page "
                f"with ``dataSource.entity: '{name}'`` (or ``entity: '{name}'``) "
                "OR mark the entity ``internal: true`` if it is not meant to "
                "surface (audit log, join table, etc.)."
            ),
        ))
    return out


def format_revise_gaps(violations: list[Violation]) -> str:
    """Render violations as a "GAPS TO FIX:" block that the planner's
    REVISE MODE already understands. Each gap is [BLOCKER] because
    downstream authorities need it — leaving them unaddressed is what
    causes the observed bugs."""
    if not violations:
        return ""
    lines = ["GAPS TO FIX:"]
    for i, v in enumerate(violations, 1):
        anchor = ""
        if v.entity and v.field:
            anchor = f"data_models[{v.entity}].fields[{v.field}]"
        elif v.entity:
            anchor = f"data_models[{v.entity}]"
        elif v.workflow:
            anchor = f"workflows[{v.workflow}]"
        anchor_str = f"  evidence: {anchor}\n" if anchor else ""
        lines.append(
            f"{i}. [BLOCKER] [architecture] {v.msg}\n{anchor_str}"
        )
    return "\n".join(lines)
