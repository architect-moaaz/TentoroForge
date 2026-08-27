"""Deterministic builders for routine CRUD page schemas (list / form / detail / edit).

A CRUD page is a pure function of the entity's real columns + a few design-spec
parameters (density, form layout) — no LLM. It emits the SAME Page schema
(schemaVersion "2") the renderer consumes, so the output drops into the existing
pipeline (binding pass, validator, app_emitter) unchanged.

Inputs:  entity name, its columns (registry fields), the page archetype + route,
         and the design spec (for density / layout variety + tokens).
Output:  a Page schema dict — type-mapped inputs (Input/NumberInput/Select/DatePicker/
         Switch/Textarea), FK columns as Select+optionsFrom, PK/owner-FK/system columns
         dropped, required columns covered, submit wired to the Create/Update workflow.

The LLM is reserved for non-routine pages (dashboards, landing, custom analytics);
this handles the routine 80%. Design varies by tokens + density/layout, not per-app
LLM guesses — consistent, correct, responsive, and still editable Page-schema data.

Only the prop names that appear in the live component contracts are emitted, so the
renderer's validateProps never strips anything.
"""
from __future__ import annotations

import logging
import os
import re

from services.field_controls import resolve_control
from services.fk_semantics import default_hidden_fk_norms, hidden_fk_columns
from services.page_polish import (
    compose_card_actions,
    compose_features,
    compose_header_actions,
    parse_description_hints,
    pick_card_props,
)

logger = logging.getLogger(__name__)

# Conservative name-based hidden-FK default (actor/tenancy) — used ONLY when a caller
# has no registry to classify roles from. The PRIMARY path threads a role-based `hidden`
# set (computed via fk_semantics.hidden_fk_columns) so a real DOMAIN FK (pets.ownerId →
# owners) is NO LONGER excluded — it becomes an editable Select.
_DEFAULT_HIDDEN = default_hidden_fk_norms()
_SYSTEM = {"id", "createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"}
# Lifecycle timestamps a WORKFLOW sets (shortlistedAt, rejectedAt, approvedAt, …) — a
# user creating/editing a row should never hand-enter these. createdAt/updatedAt are
# already covered by _SYSTEM; this catches the domain-specific *At columns.
_LIFECYCLE_AT = re.compile(r"(?:^|_)[a-z0-9]+_?at$", re.I)


def _is_lifecycle_timestamp(name: str, meta: dict) -> bool:
    low = name.lower()
    if low in _SYSTEM:
        return True
    typ = str((meta or {}).get("type", "")).lower()
    return typ.startswith(("timestamp", "date", "time")) and bool(_LIFECYCLE_AT.search(name)) \
        and low not in ("date",)  # a column literally named "date" is user data, keep it
_NUMERIC = {"integer", "int", "int4", "int8", "serial", "bigserial", "smallint", "bigint",
            "numeric", "decimal", "real", "double", "double precision", "float", "money"}
_DATE = {"date", "timestamp", "timestamptz", "timestamp with time zone", "datetime", "time"}
_JSON = {"json", "jsonb"}
_LONG_TEXT = ("description", "notes", "note", "bio", "content", "address", "comment",
              "summary", "details", "detail", "message", "body", "about")
_ROUTINE = {"list", "form", "create", "detail", "edit"}


def is_routine_archetype(archetype: str | None, page_type: str | None = None) -> bool:
    a = (archetype or "").strip().lower()
    t = (page_type or "").strip().lower()
    return a in _ROUTINE or t in _ROUTINE


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def effective_archetype(route: str, *hints: str | None) -> str | None:
    """The routine CRUD archetype for a page, inferred from the ROUTE shape first (most
    reliable) then the planner's archetype/type hints. Returns None for non-routine pages.
    Route shape wins: `/x/new`→form, `/x/[id]/edit`→edit, `/x/[id]`→detail, `/x`→list."""
    r = (route or "").rstrip("/")
    if re.search(r"/(edit)$", r):
        return "edit"
    if r.endswith("/new"):
        return "form"
    if re.search(r"/(\[id\]|:id|\{id\}|\[\.\.\..*\])$", r):
        return "detail"
    for h in hints:
        a = (h or "").strip().lower()
        # Non-CRUD archetypes with first-class deterministic builders — recognised from
        # the planner's type/archetype hint (a bare route like `/pipeline` gives no shape).
        if a in ("kanban", "board"):
            return "kanban"
        if a in ("calendar", "schedule"):
            return "calendar"
        if a in ("list", "form", "create", "edit", "detail"):
            return a
        if a in ("wizard",):
            # NOT "a create wizard is still a create form". A wizard is a
            # multi-step flow with accumulated values and a review pane —
            # the library ships a Wizard component that does exactly that.
            # Collapsing it here erased the archetype before wizard_page_pass
            # could act, so the Receive Stock Wizard shipped as a flat form.
            # Route shape still wins above: /x/new stays a create form.
            return "wizard"
    # A bare single-segment route (`/reservations`) with a list-ish hint is a list.
    segs = [s for s in r.split("/") if s]
    if len(segs) == 1:
        a = (hints[0] or "").strip().lower() if hints else ""
        if a in ("list", "table", "grid", "index", ""):
            return "list"
    return None


def resolve_entity(route: str, entity_hint: str | None, entity_names) -> str | None:
    """The entity a routine page is about. Prefer an explicit hint; otherwise infer from
    the route's first segment, matched against the registry's entity names (singular or
    plural). Prefers the singular form so it lines up with Create<Entity> workflow names."""
    names = list(entity_names or [])
    if entity_hint and entity_hint in names:
        return entity_hint
    segs = [s for s in (route or "").split("/")
            if s and not s.startswith("[") and s not in ("new", "edit", ":id")]
    if not segs:
        return None
    target = _norm(segs[0])
    singular = target[:-1] if target.endswith("s") else target
    by_norm = {_norm(n): n for n in names}
    for key in (singular, target, target + "s"):  # singular first
        if key in by_norm:
            return by_norm[key]
    return None


# ── small helpers ───────────────────────────────────────────────────────────

def _label(col: str) -> str:
    s = re.sub(r"[_\-]+", " ", col)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"\bId\b", "", s).strip()
    return s[:1].upper() + s[1:] if s else col


def _humanize_entity(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).strip() or name


def _entity_heading_plural(entity: str) -> str:
    """List-page heading form of an entity — humanized THEN pluralized.

    Replaces the previous naive ``_humanize_entity(entity) + "s"`` pattern
    which produced "Propertys" / "Personys" / "Categorys". Sprint 5 of
    Forge Great Again.
    """
    from services.humanize import pluralize
    human = _humanize_entity(entity)
    if not human:
        return human
    # Pluralize each word-part in the humanized string is overkill; the
    # LAST word is what carries the noun ("Membership Plan" → "Membership
    # Plans"). Split on space, pluralize the tail, rejoin.
    parts = human.split(" ")
    parts[-1] = pluralize(parts[-1])
    return " ".join(parts)


def _table_from_route(route: str, fallback: str) -> str:
    segs = [s for s in (route or "").split("/") if s and not s.startswith("[") and s != "new"]
    return segs[0] if segs else fallback


def _is_fk(col: str, hidden: set[str] | None = None) -> bool:
    # Case-sensitive so a real FK (`roomId`, `room_id`) matches but a word that merely
    # ends in "id" (`isPaid`, `valid`, `grid`) does not. `hidden` is the role-based
    # actor/tenancy set (server-filled columns that must not become a Select); a domain
    # FK is absent from it and correctly treated as a real FK.
    hid = hidden if hidden is not None else _DEFAULT_HIDDEN
    if col.lower() in _SYSTEM or _norm(col) in hid:
        return False
    return col.endswith("Id") or col.endswith("_id")


def _fk_slug(col: str) -> str:
    stem = re.sub(r"(_id|Id)$", "", col)
    stem = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stem).lower().replace("_", "-")
    return stem + ("" if stem.endswith("s") else "s")


def _fk_target_slug(col: str, meta: dict | None, entities: dict | None) -> str:
    """The dataSource name a FK Select should bind to. Prefer the column's REAL fk
    target (from `meta['fk']`, resolved to the target entity's slug) over a name guess
    — so `assigneeId → users` (not `assignees`) and `vetId → staff` (not `vets`). Falls
    back to the name-derived slug only when no FK metadata is available."""
    fk = (meta or {}).get("fk")
    if fk and isinstance(entities, dict):
        want = _norm_col(fk)
        for name, e in entities.items():
            if not isinstance(e, dict):
                continue
            for form in (name, e.get("name"), e.get("slug"), e.get("table"),
                         e.get("camel"), e.get("id"), e.get("singular")):
                if form and _norm_col(form) == want:
                    return e.get("slug") or e.get("table") or _fk_slug(col)
    return _fk_slug(col)


# Column-name hints for a human-friendly Select label (the target entity's display field).
_LABEL_PREFER = ("name", "title", "label", "displayname", "fullname", "username",
                 "email", "code", "number", "roomnumber", "sku", "reference", "slug")


def _norm_col(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _as_field_dict(columns) -> dict:
    """Coerce an entity's fields into the {name: {meta}} dict this module expects.

    The registry stores fields as a dict, but a plan may carry them as a LIST of
    {name/key, type, nullable, …} objects (or bare strings). Normalising here keeps
    the deterministic builder from throwing ('list' object has no attribute 'items')
    and falling back to the LLM — the whole point of the deterministic path is to
    work WITHOUT a model call."""
    if isinstance(columns, dict):
        return {k: (v if isinstance(v, dict) else {}) for k, v in columns.items()}
    if isinstance(columns, list):
        out: dict = {}
        for f in columns:
            if isinstance(f, dict):
                name = f.get("name") or f.get("key") or f.get("column") or f.get("field")
                if name:
                    out[str(name)] = {k: v for k, v in f.items() if k not in ("name", "key", "column", "field")}
            elif isinstance(f, str):
                out[f] = {}
        return out
    return {}


def _resolve_target(slug: str, entities: dict | None) -> tuple[str | None, dict]:
    """Map an optionsFrom slug ('guests') back to its target entity (name, columns)."""
    if not entities:
        return (None, {})
    want = _norm_col(slug)
    for name, info in entities.items():
        n = _norm_col(name)
        if n == want or n + "s" == want or n == want.rstrip("s"):
            return (name, _as_field_dict((info or {}).get("fields")))
    return (None, {})


def _label_field(cols: dict) -> str:
    """Pick the best human-readable label column from a target entity's columns.
    Falls back to 'name' — the renderer then falls back to showing the id value."""
    cand = [
        c for c in (cols or {})
        if not (cols[c] or {}).get("primaryKey")
        and not _is_fk(c) and c.lower() not in _SYSTEM and _norm(c) not in _DEFAULT_HIDDEN
    ]
    for pref in _LABEL_PREFER:
        for c in cand:
            if _norm_col(c) == pref:
                return c
    for c in cand:
        t = str((cols[c] or {}).get("type", "")).lower()
        if t.startswith("varchar") or t.startswith("char") or t in ("text", "string"):
            return c
    return cand[0] if cand else "name"


def _gap(design_spec: dict | None, default: int = 4) -> str:
    d = (((design_spec or {}).get("visualLanguage") or {}).get("densityPreference")
         or (design_spec or {}).get("density") or "comfortable")
    return {"compact": "tokens.spacing.2", "comfortable": "tokens.spacing.4",
            "spacious": "tokens.spacing.6"}.get(str(d).lower(), f"tokens.spacing.{default}")


# ── archetype-builder column detectors (kanban / calendar) ───────────────────
# Column names that hold a record's pipeline stage — a Kanban groups columns by
# one of these (prefer an enum so the columns are the enum's allowed values).
_STATUS_NAMES = ("status", "stage", "state", "phase", "pipelinestage",
                 "kanbanstatus", "workflowstate", "column", "swimlane")
# Column names / suffixes that hold the (start) date a Calendar plots an event on.
_DATE_FIELD_PREFER = ("scheduledat", "scheduleddate", "startat", "startdate", "starttime",
                      "eventdate", "eventat", "appointmentat", "appointmentdate", "dueat",
                      "duedate", "date", "occursat", "happensat", "beginsat", "when")


def _entity_list_source(entity: str) -> str:
    """The list-dataSource / binding name for an entity. Delegates to
    :func:`services.entity_names.derive_names` — the canonical naming
    authority — so `AssessmentDay → assessmentDays` (never `assessmentDaies`
    or `assessment-days`) matches what every other builder in the pipeline
    emits for the same entity."""
    from services.entity_names import derive_names
    return derive_names(entity).sourceName


def _enum_values(meta: dict) -> list[str]:
    """The declared enum values for a column, ignoring jsonb array-type markers
    (e.g. ['string[]']) which are NOT selectable enum options."""
    typ = str((meta or {}).get("type", "")).lower()
    if typ in _JSON or typ.startswith("json"):
        return []
    raw = (meta or {}).get("enum_values") or (meta or {}).get("enumValues")
    if not isinstance(raw, list):
        return []
    return [str(v) for v in raw if v not in (None, "") and not str(v).endswith("[]")]


def _is_enum(meta: dict) -> bool:
    typ = str((meta or {}).get("type", "")).lower()
    return bool(_enum_values(meta)) or typ.startswith("enum") or "enum" in typ


def _status_column(columns: dict) -> str | None:
    """The column a Kanban groups by / a Calendar colours by. Detect a named
    status/stage column; PREFER one that is an enum; else the first named one;
    else the first enum column anywhere. None when nothing categorical exists."""
    named = [(n, m if isinstance(m, dict) else {})
             for n, m in (columns or {}).items() if _norm_col(n) in _STATUS_NAMES]
    for n, m in named:
        if _is_enum(m):
            return n
    if named:
        return named[0][0]
    for n, m in (columns or {}).items():
        if _is_enum(m if isinstance(m, dict) else {}):
            return n
    return None


def _is_date_col(meta: dict) -> bool:
    typ = str((meta or {}).get("type", "")).lower()
    return typ in _DATE or typ.startswith(("timestamp", "date", "time"))


def _date_field(columns: dict) -> str | None:
    """The primary date column a Calendar plots events on. Prefer a well-known
    scheduling name (scheduledAt/startAt/dueAt/date/…), then any *At/*Date/*Time
    column, then the first date/timestamp column — always excluding system audit
    timestamps (createdAt/updatedAt/deletedAt)."""
    date_cols = [(n, m if isinstance(m, dict) else {})
                 for n, m in (columns or {}).items()
                 if _is_date_col(m if isinstance(m, dict) else {}) and n.lower() not in _SYSTEM]
    for pref in _DATE_FIELD_PREFER:
        for n, _ in date_cols:
            if _norm_col(n) == pref:
                return n
    for n, _ in date_cols:
        if re.search(r"(at|date|time|on)$", n, re.I):
            return n
    return date_cols[0][0] if date_cols else None


def _editable_columns(
    columns: dict,
    hidden: set[str] | None = None,
    *,
    plan: dict | None = None,
    entity_name: str | None = None,
    form_mode: str = "create",
) -> list[tuple[str, dict]]:
    """Columns that get an editable input. `hidden` is the role-based actor/tenancy FK set
    (server-filled) to exclude; when absent, the conservative name-based default is used.
    Domain FKs are NOT in `hidden`, so they survive and become relational Selects.

    Spec B7: on ``create`` forms, columns with plan flag ``lifecycle_status: true``
    are hidden — recording state on create is a mode question best handled by
    the workflow, not a user-chosen dropdown. On ``edit`` forms they surface
    normally (as status pickers)."""
    hid = hidden if hidden is not None else _DEFAULT_HIDDEN
    # Lazy import — plan lookups are optional; older callers pass no plan.
    _get_lifecycle_status = None
    if plan is not None and entity_name and form_mode == "create":
        try:
            from services.plan_field_lookup import get_lifecycle_status as _gls
            _get_lifecycle_status = _gls
        except Exception:  # noqa: BLE001
            _get_lifecycle_status = None
    out = []
    for name, meta in (columns or {}).items():
        meta = meta if isinstance(meta, dict) else {}
        low = name.lower()
        if meta.get("primaryKey") or low in _SYSTEM or _norm(name) in hid \
                or _is_lifecycle_timestamp(name, meta):
            continue
        if _get_lifecycle_status is not None and _get_lifecycle_status(
            plan, entity_name, name,
        ):
            continue
        out.append((name, meta))
    return out


def _is_required(meta: dict) -> bool:
    """A column must be filled on a create form when it's NOT NULL and has no DB
    default. (PK/owner-FK/system columns are excluded upstream by _editable_columns.)
    Relies on accurate registry metadata — see registry.reconcile_entities."""
    if not isinstance(meta, dict):
        return False
    not_null = meta.get("nullable") is False or meta.get("notNull") is True
    return bool(not_null) and not meta.get("hasDefault")


def _resolve_field_control(col: str, meta: dict, entities: dict | None,
                           *, semantic_type: str | None = None,
                           enum_override: list[str] | None = None,
                           hidden: set[str] | None = None) -> tuple[str, dict]:
    """The single control authority for a form field: (control, props).

    Delegates the control TYPE to `services.field_controls.resolve_control` — the ONE
    place that decides Input/Select/NumberInput/DatePicker/Switch/Textarea from the
    column's SQL type, FK target, enum values, and an optional semantic hint — so the
    deterministic builder and the post-generation re-typing pass can never diverge.

    Two things resolve_control does NOT own (they are display/config, not control TYPE):
      * jsonb columns render as a KeyValueInput editable map (not a plain text input);
      * an FK Select's `optionsFrom.label` is the target entity's best display column,
        resolved here from the registry (resolve_control returns a generic "name").
    Props never include name/label/validators — the caller owns those.
    """
    typ = str((meta or {}).get("type", "")).lower()
    # jsonb config column (e.g. "criteriaConfig", "settings") — an editable key→value
    # map. resolve_control has no json concept, so this stays owned by the builder.
    if typ in _JSON or typ.startswith("json"):
        return "KeyValueInput", {}
    meta_enum = meta.get("enum_values") or meta.get("enumValues")
    enum = enum_override or ([str(v) for v in meta_enum if v not in (None, "")]
                             if isinstance(meta_enum, list) else None) or None
    is_fk = _is_fk(col, hidden)
    control, props = resolve_control(
        name=col, sql_type=typ,
        fk_target=(_fk_target_slug(col, meta, entities) if is_fk else None),
        options=enum, semantic_type=semantic_type,
    )
    # Patch the FK Select's display label to the target entity's best label column.
    of = props.get("optionsFrom")
    if isinstance(of, dict) and of.get("source"):
        of = dict(of)
        of["label"] = _label_field(_resolve_target(of["source"], entities)[1])
        props = {**props, "optionsFrom": of}
    return control, props


def _input_for(col: str, meta: dict, entities: dict | None = None,
               hidden: set[str] | None = None) -> dict:
    """Map a column to the right input component via the shared control authority
    (`_resolve_field_control` → `resolve_control`), emitting only valid props.
    Required (NOT NULL, no default) fields get `validators.required` so the browser
    blocks empty submission instead of the insert hitting a null-violation."""
    label = _label(col)
    req = _is_required(meta)
    control, props = _resolve_field_control(col, meta, entities, hidden=hidden)
    if control == "KeyValueInput":
        # `required` doesn't apply — the control always submits at least `{}`.
        return {"type": "KeyValueInput", "props": {"name": col, "label": label}}
    node_props = {"name": col, "label": label, **props}
    if req:
        node_props["validators"] = {"required": True}
    return {"type": control, "props": node_props}


def _display_columns(columns: dict, limit: int = 6, hidden: set[str] | None = None) -> list[str]:
    hid = hidden if hidden is not None else _DEFAULT_HIDDEN
    cols = []
    for name, meta in (columns or {}).items():
        meta = meta if isinstance(meta, dict) else {}
        low = name.lower()
        if low in _SYSTEM and low != "id":
            continue
        if _norm(name) in hid:
            continue
        if any(h in low for h in _LONG_TEXT):
            continue
        cols.append(name)
    return cols[:limit]


# ── planner per-field spec merge ────────────────────────────────────────────
# The planner may author a per-field form spec carrying only JUDGMENT the registry
# can't derive: semanticType (currency vs count, email vs plain string), enum (the
# literal Select values), required, label, order. The CONTROL TYPE is NEVER authored
# by the planner — it is ALWAYS derived by the shared authority (`resolve_control`,
# via `_resolve_field_control`) from the real SQL column + the semanticType hint. A
# planner-supplied `control` key (from an older plan) is ignored. label/required/enum/
# order override the registry default; any real column the planner OMITTED is still
# built from the registry (backstop → a partial spec is a full form). A spec naming a
# non-existent column is never matched, so it's simply dropped.


def _merge_field_node(col: str, meta: dict, spec: dict | None, entities: dict | None,
                      hidden: set[str] | None = None) -> dict:
    """Merge the planner's field-spec JUDGMENT OVER the registry-derived default for one
    column. The control type is DERIVED (never taken from the spec); the spec only
    supplies semanticType/enum/required/label."""
    if not isinstance(spec, dict):
        return _input_for(col, meta, entities, hidden)

    req = _is_required(meta)
    if isinstance(spec.get("required"), bool):
        req = spec["required"]

    raw_enum = spec.get("enum")
    enum_override = ([str(v) for v in raw_enum if v not in (None, "")]
                     if isinstance(raw_enum, list) else None) or None

    sem = spec.get("semanticType")
    sem = sem if isinstance(sem, str) and sem.strip() else None

    # Control ALWAYS from the shared authority — a planner `control` key is ignored.
    control, props = _resolve_field_control(
        col, meta, entities, semantic_type=sem, enum_override=enum_override, hidden=hidden)

    lbl = spec.get("label")
    label = lbl.strip() if isinstance(lbl, str) and lbl.strip() else _label(col)

    if control == "KeyValueInput":
        # jsonb key→value map; `required` doesn't apply (always submits at least {}).
        return {"type": "KeyValueInput", "props": {"name": col, "label": label}}
    node_props = {"name": col, "label": label, **props}
    if req:
        node_props["validators"] = {"required": True}
    return {"type": control, "props": node_props}


def _field_specs_by_col(field_specs) -> dict:
    """{norm_col -> spec} from a plan page's `fields` list (last-wins on dup names)."""
    out: dict = {}
    for s in field_specs or []:
        if isinstance(s, dict):
            nm = s.get("name")
            if isinstance(nm, str) and nm.strip():
                out[_norm_col(nm)] = s
    return out


# ── page builders ─────────────────────────────────────────────────────────

_WIDE_INPUT_TYPES = {"Textarea", "KeyValueInput"}


def build_form_page(entity: str, columns: dict, route: str, design_spec: dict | None,
                    op: str = "create", entities: dict | None = None,
                    modal: bool = False, field_specs: list | None = None,
                    registry: dict | None = None, output_dir: str | None = None,
                    submit_target: str | None = None,
                    plan: dict | None = None) -> dict:
    """Build a deterministic form page.

    IRF-M4-T2: when ``plan`` is supplied, the form's submit UX honors the
    effective shape at ``route``. ``workflows.executionMode`` from
    ``resolve_shape(plan, route)`` maps via ``form_submit_pattern`` into one of:
    ``fire-and-forget-with-toast-nav`` | ``await-with-spinner`` |
    ``in-place-progress`` | ``background-with-notification``. That value is
    emitted as ``props.submitMode`` on the ``Form`` node so the runtime
    dispatcher and library Form component behave coherently with the workflow
    translator (T3) — both read the same substrate primitive.
    """
    table = _table_from_route(route, entity.lower())
    gap = _gap(design_spec)
    # Role-based hidden set: actor/tenancy FKs are server-filled (excluded); a domain FK is
    # NOT hidden and becomes an editable relational Select. Threaded from the registry's
    # real FK targets (with a schema `.references()` fallback via output_dir); when no
    # registry is available it falls back to the conservative name-based default.
    reg = registry if isinstance(registry, dict) and registry.get("entities") else {"entities": entities or {}}
    hidden = hidden_fk_columns(entity, reg, output_dir)
    editable = _editable_columns(columns, hidden)
    if field_specs:
        # Plan is AUTHORITATIVE for the field set. When the planner authored
        # `page.fields`, the form emits EXACTLY those fields — no registry
        # backstop appending columns the plan didn't declare. Registry cols
        # are used only as a lookup for types + FK targets when a spec
        # names a real column. A spec naming an unknown column is dropped
        # (silent) so a typo can't fabricate a phantom input.
        #
        # Rationale: the previous "registry-backstop" merge let unrelated-
        # entity columns leak into a form when the caller passed a wider
        # `editable` set — e.g. auth columns (email/password/isActive)
        # showing up on a rent-payment form. Plan-first eliminates that
        # entire class of cross-entity bleed and makes the planner's field
        # list a hard contract.
        editable_by_col = {_norm_col(c): (c, m) for c, m in editable}
        spec_by_col = _field_specs_by_col(field_specs)
        _LARGE = 10 ** 6
        ranked: list[tuple[int, int, dict]] = []
        for idx, fs in enumerate(field_specs):
            if not isinstance(fs, dict):
                continue
            name = fs.get("name")
            key = _norm_col(name) if name else None
            if not key:
                continue
            found = editable_by_col.get(key)
            if not found:
                # Plan named a column that isn't in this entity's registry
                # (typo, wrong entity, stale plan). Skip silently — never
                # fabricate an input for an undeclared column.
                continue
            c, m = found
            spec = spec_by_col.get(key)
            node = _merge_field_node(c, m, spec, entities, hidden)
            order = spec.get("order") if spec and isinstance(spec.get("order"), int) \
                and not isinstance(spec.get("order"), bool) else None
            rank = order if order is not None else _LARGE + idx
            ranked.append((rank, idx, node))
        ranked.sort(key=lambda t: (t[0], t[1]))
        inputs = [n for _, _, n in ranked]
    else:
        # No plan spec — legacy behaviour: emit every editable registry column.
        # This path stays for the small set of pages the planner doesn't author
        # (deprecated as callers migrate to plan-first).
        inputs = [_input_for(c, m, entities, hidden) for c, m in editable]
    # FK option sources — one list dataSource per Select(optionsFrom). optionsFrom is the
    # object form {source, value, label}; read its `source` for the dataSource name.
    sources = []
    for node in inputs:
        of = node["props"].get("optionsFrom") if node["type"] == "Select" else None
        if isinstance(of, dict) and of.get("source"):
            src = of["source"]
            if not any(s["name"] == src for s in sources):
                ent = _resolve_target(src, entities)[0] or (
                    src[:-1].capitalize() if src.endswith("s") else src.capitalize())
                sources.append({"name": src, "entity": ent, "op": "list"})

    verb = "Edit" if op == "edit" else "Add"
    # Slice A T5: submit_target from page.submit.target overrides the
    # CRUD-derived default. Preserves existing behaviour when the caller
    # doesn't pass submit_target (all data_api forms + legacy pipeline).
    workflow = (
        submit_target.strip() if isinstance(submit_target, str) and submit_target.strip()
        else f"{'Update' if op == 'edit' else 'Create'}{entity}"
    )
    submit_label = f"{'Save changes' if op == 'edit' else 'Create ' + _humanize_entity(entity)}"

    # Spec C3 — voice-tuned CTA verb from brief.content_bank when present.
    # cta_verbs["save"] wins on edit; cta_verbs["create"] on create; "primary"
    # is the last-resort override for both. Silent fallback keeps the generic
    # label above when the brief is absent or the key missing.
    if output_dir:
        try:
            from services.design_brief_editor import read_brief
            from services.content_bank_reader import cta_verb as _bank_cta
            _brief = read_brief(output_dir)
            _bank = getattr(_brief, "content_bank", None) if _brief is not None else None
            if _bank is not None:
                if op == "edit":
                    _verb = _bank_cta(_bank, "save", "")
                    if _verb:
                        submit_label = _verb
                else:
                    _verb = _bank_cta(_bank, "create", "") or _bank_cta(_bank, "primary", "")
                    if _verb:
                        submit_label = f"{_verb} {_humanize_entity(entity)}"
        except Exception:
            pass

    # Layout DNA (spec.layout.form): the form's structure varies per app —
    # single-column | two-column | sectioned | side-summary. Structured fields
    # (Textarea/KeyValueInput) always span full width. Pre-DNA specs keep the
    # historical behaviour (auto 2-col + auto-sectioning on large forms).
    form_comp = str(((design_spec or {}).get("layout") or {}).get("form") or "").lower()
    compact = [n for n in inputs if n["type"] not in _WIDE_INPUT_TYPES]
    wide = [n for n in inputs if n["type"] in _WIDE_INPUT_TYPES]

    two_col = (form_comp == "two-column") or (
        form_comp not in ("single-column", "sectioned", "side-summary")
        and len(compact) >= 4 and gap != "tokens.spacing.2")
    if two_col and len(compact) >= 2:
        compact_group = {"type": "Grid", "props": {"columns": 2, "gap": gap}, "children": compact}
    else:
        compact_group = {"type": "Stack", "props": {"gap": gap}, "children": compact}

    # Sectioned: forced by DNA, else the historical auto rule. The section
    # voice differs between the two so no two apps share the exact headings.
    sectioned = form_comp == "sectioned" or (
        form_comp != "single-column" and bool(wide) and len(inputs) >= 6)
    sec_titles = ("Basics", "More detail") if form_comp == "sectioned" \
        else ("Details", "Additional information")
    body_children: list[dict] = []
    if sectioned and (compact and (wide or form_comp == "sectioned")):
        body_children.append({"type": "Heading", "props": {"content": sec_titles[0], "level": 3}})
        body_children.append(compact_group)
        if wide:
            body_children.append({"type": "Heading", "props": {"content": sec_titles[1], "level": 3}})
            body_children.extend(wide)
    else:
        if compact:
            body_children.append(compact_group)
        body_children.extend(wide)
    body = {"type": "Stack", "props": {"gap": gap}, "children": body_children}

    # dataJourney: stable identifier for the journey verifier's Playwright
    # driver — survives label drift (LLM might rename "Create" → "Save" on
    # a re-emit). Deterministic emitter → deterministic locator.
    buttons = {"type": "Row", "props": {"gap": "tokens.spacing.2", "justify": "end"}, "children": [
        {"type": "Button", "props": {"label": "Cancel", "variant": "ghost", "navigate": f"/{table}",
                                     "dataJourney": "form-cancel"}},
        {"type": "Button", "props": {"label": submit_label, "variant": "primary", "submit": True,
                                     "dataJourney": "form-submit"}},
    ]}

    # IRF-M4-T2: submit UX from the effective shape at this route. Silent
    # skip when plan absent / no shape / no workflows primitive — historic
    # behavior preserved.
    form_props: dict = {"workflow": workflow, "submitLabel": submit_label}
    if isinstance(plan, dict):
        try:
            from services.shape_profile_derived import (
                form_submit_pattern as _pattern,
                resolve_shape as _resolve,
            )
            _shape = _resolve(plan, route)
            if isinstance(_shape, dict) and (_shape.get("workflows") or {}).get("executionMode"):
                form_props["submitMode"] = _pattern(_shape)
        except Exception:
            pass

    form_card = {"type": "Card", "children": [
        {"type": "Form", "props": form_props,
         "children": [{"type": "Stack", "props": {"gap": gap}, "children": [body, buttons]}]},
    ]}
    if form_comp == "side-summary" and not modal and len(inputs) >= 3:
        # Form beside a context rail — the record's purpose and requirements.
        required = [n["props"].get("label") or _label(n["props"].get("name", ""))
                    for n in inputs if n.get("props", {}).get("required")]
        rail_children: list[dict] = [
            {"type": "Text", "props": {
                "content": f"{'Update this' if op == 'edit' else 'Add a new'} "
                           f"{_humanize_entity(entity).lower()} record. "
                           "Changes save when you submit.",
                "as": "p", "className": "text-sm text-muted-foreground"}}]
        if required:
            rail_children.append({"type": "Text", "props": {
                "content": "Required: " + ", ".join(str(r) for r in required[:5]),
                "as": "p", "className": "text-xs text-muted-foreground"}})
        card = {"type": "Split", "props": {"ratio": "2:1"}, "children": [
            form_card,
            {"type": "Card", "props": {"title": _humanize_entity(entity)},
             "children": [{"type": "Stack", "props": {"gap": gap}, "children": rail_children}]},
        ]}
    else:
        card = form_card
    # Inside a modal the dialog supplies the title — skip the inner level:1 heading and
    # the page envelope's top-level heading so the title isn't shown twice.
    root_children: list[dict] = []
    if not modal:
        root_children.append(
            {"type": "Heading", "props": {"content": f"{verb} {_humanize_entity(entity)}", "level": 1}})
    root_children.append(card)

    page = {
        "schemaVersion": "2",
        "id": f"{table}-{op}",
        "route": route,
        "layout": "main",
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": root_children},
    }
    if sources:
        page["dataSources"] = sources
    return page


def _voice(design_spec: dict | None) -> dict:
    """Per-app action-verb microcopy from the design DNA (spec.voice).

    Kills the identical "New X" / "View details" formula that repeated
    verbatim on every collection page of every generated app.
    """
    v = (design_spec or {}).get("voice") or {}
    return {"create": str(v.get("create") or "New"),
            "view": str(v.get("view") or "View details")}


def _detail_composition(design_spec: dict | None) -> str:
    """The app's detail-page shape from Layout DNA (spec.layout.detail)."""
    layout = (design_spec or {}).get("layout") or {}
    return str(layout.get("detail") or "stack").lower()


def _field_rows(var: str, cols: list[str]) -> list[dict]:
    return [{"type": "Row", "props": {"justify": "between"}, "children": [
        {"type": "Text", "props": {"content": _label(c)}},
        {"type": "Text", "props": {"content": f"{{{{{var}.{c}}}}}", "weight": "medium"}},
    ]} for c in cols]


def build_detail_page(
    entity: str, columns: dict, route: str, design_spec: dict | None,
    page_hint: dict | None = None,
) -> dict:
    """Assemble a detail-view page schema for ``entity``.

    ``page_hint`` is the planner's per-page dict; when it carries
    ``actions`` (Slice B ACTION-AUTHORITY contract), those buttons are
    appended to the header verbatim via
    :func:`services.action_authority.derive_button_props`. The stock
    Back / Edit buttons stay in place — they're generic navigation the
    contract explicitly excludes.
    """
    table = _table_from_route(route, entity.lower())
    var = re.sub(r"([a-z0-9])([A-Z])", r"\1", entity)[:1].lower() + entity[1:] if entity else "item"
    gap = _gap(design_spec)
    columns_dict = _as_field_dict(columns)
    display = _display_columns(columns, limit=12)
    label = _label_field(columns_dict)
    status = _status_column(columns_dict)

    header_btns: list[dict] = [
        {"type": "Button", "props": {"label": "Back", "variant": "ghost", "navigate": f"/{table}"}},
        {"type": "Button", "props": {"label": "Edit", "variant": "primary", "navigate": f"/{table}/{{{{{var}.id}}}}/edit"}},
    ]
    # Slice B: append planner-declared action buttons AFTER the generic
    # nav (so primary domain actions read as the rightmost, strongest
    # CTA on the row). We normalize via _normalize_actions to drop any
    # malformed entries defensively — the validator surfaced those as
    # gaps upstream; here we just want a clean render.
    if isinstance(page_hint, dict) and page_hint.get("actions"):
        try:
            from services.action_authority import (
                _normalize_actions, derive_button_props,
            )
            for action in _normalize_actions(page_hint.get("actions")):
                props = derive_button_props(action)
                if props:
                    header_btns.append({"type": "Button", "props": props})
        except Exception:  # noqa: BLE001 — never block page build on the extension
            pass

    header = {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
        {"type": "Heading", "props": {"content": _humanize_entity(entity), "level": 1}},
        {"type": "Row", "props": {"gap": "tokens.spacing.2"}, "children": header_btns},
    ]}

    # Layout DNA: the SAME validated field bindings, arranged into structurally
    # different detail pages per app (DETAIL_LAYOUTS finally has consumers).
    composition = _detail_composition(design_spec)

    # Split fields: identity/primary first, bookkeeping (dates, FKs) as meta.
    meta_cols = [c for c in display
                 if c.endswith("_at") or c.endswith("_id") or c in ("id", "createdAt", "updatedAt")]
    primary_cols = [c for c in display if c not in meta_cols] or display[:1]

    if composition == "split-detail" and len(display) >= 4:
        # Work surface beside a meta rail — 2:1.
        body: list[dict] = [{"type": "Split", "props": {"ratio": "2:1"}, "children": [
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": gap}, "children": _field_rows(var, primary_cols)}]},
            {"type": "Card", "props": {"title": "Record info"}, "children": [
                {"type": "Stack", "props": {"gap": gap},
                 "children": _field_rows(var, meta_cols or display[-3:])}]},
        ]}]
    elif composition == "profile-detail":
        # Identity band (avatar + name + status badge), then the facts.
        band_children: list[dict] = [
            {"type": "Avatar", "props": {"name": f"{{{{{var}.{label}}}}}", "size": "lg"}},
            {"type": "Stack", "props": {"gap": "tokens.spacing.1"}, "children": [
                {"type": "Heading", "props": {"content": f"{{{{{var}.{label}}}}}", "level": 2}},
                {"type": "Text", "props": {"content": _humanize_entity(entity),
                                           "className": "text-sm text-muted-foreground"}},
            ]},
        ]
        if status:
            band_children.append({"type": "Badge", "props": {
                "content": f"{{{{{var}.{status}}}}}", "variant": "primary"}})
        rest = [c for c in display if c != label]
        body = [
            {"type": "Card", "children": [
                {"type": "Row", "props": {"gap": gap, "align": "center"}, "children": band_children}]},
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": gap}, "children": _field_rows(var, rest)}]},
        ]
    elif composition == "timeline-detail" and len(display) >= 4:
        # Key facts as a summary strip, then the full record.
        strip = [{"type": "Card", "children": [
            {"type": "Stack", "props": {"gap": "tokens.spacing.1"}, "children": [
                {"type": "Text", "props": {"content": _label(c),
                                           "className": "text-xs uppercase tracking-wide text-muted-foreground"}},
                {"type": "Text", "props": {"content": f"{{{{{var}.{c}}}}}", "weight": "medium"}},
            ]}]} for c in primary_cols[:3]]
        body = [
            {"type": "Grid", "props": {"columns": min(3, len(strip)), "gap": gap}, "children": strip},
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": gap},
                 "children": _field_rows(var, [c for c in display if c not in primary_cols[:3]])}]},
        ]
    elif composition == "tabbed-hero":
        # Title hero band, then the record card — an editorial read.
        body = [
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": "tokens.spacing.1"}, "children": [
                    {"type": "Heading", "props": {"content": f"{{{{{var}.{label}}}}}", "level": 2}},
                    *([{"type": "Badge", "props": {"content": f"{{{{{var}.{status}}}}}",
                                                   "variant": "neutral"}}] if status else []),
                ]}]},
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": gap},
                 "children": _field_rows(var, [c for c in display if c != label])}]},
        ]
    else:  # historical single-card stack — pre-DNA apps keep their exact shape
        body = [{"type": "Card", "children": [
            {"type": "Stack", "props": {"gap": gap}, "children": _field_rows(var, display)}]}]

    return {
        "schemaVersion": "2",
        "id": f"{table}-detail",
        "route": route,
        "layout": "main",
        "dataSources": [{"name": var, "entity": entity, "op": "get"}],
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"},
                 "children": [header, *body]},
    }


def _list_composition(design_spec: dict | None) -> str:
    """The app's list-page shape from Layout DNA (spec.layout.list).

    Vocabulary: table | card-grid | board | timeline | split-list.
    Unknown / absent → "table" so pre-DNA specs keep their exact output.
    """
    layout = (design_spec or {}).get("layout") or {}
    return str(layout.get("list") or "table").lower()


def _card_grid_collection(table: str, columns_dict: dict, desc_hints: dict,
                          view_label: str = "View details") -> dict:
    """A Grid→Repeat→Card collection bound to the entity list — the card-grid
    alternative to the default Table. Uses the same {{item.field}} convention
    as schema_binding.apply_list_binding, so the runtime binds it identically."""
    card_props = pick_card_props(columns_dict, hints=desc_hints)
    title_field = card_props.get("cardTitle") or _label_field(columns_dict)
    subtitle = card_props.get("cardSubtitle")
    badge = (card_props.get("cardBadges") or [None])[0]

    card_children: list[dict] = []
    if badge and badge != title_field:
        card_children.append({"type": "Badge", "props": {
            "content": f"{{{{item.{badge}}}}}", "variant": "neutral"}})
    if subtitle and subtitle not in (title_field, badge):
        card_children.append({"type": "Text", "props": {
            "content": f"{{{{item.{subtitle}}}}}",
            "as": "p", "className": "text-sm text-muted-foreground"}})
    card_children.append({"type": "Link", "props": {
        "label": view_label, "navigate": f"/{table}/{{{{item.id}}}}"}})

    return {"type": "Grid", "props": {"columns": 3, "gap": "tokens.spacing.4"}, "children": [
        {"type": "Repeat", "bind": table, "children": [
            {"type": "Card",
             "props": {"title": f"{{{{item.{title_field}}}}}", "elevation": "sm"},
             "children": card_children},
        ]},
    ]}


def _timeline_date(columns_dict: dict) -> str | None:
    """Date anchor for a TIMELINE feed. Unlike _date_field (calendar
    semantics), audit timestamps are perfectly good anchors here — an
    activity feed ordered by created_at is the natural reading."""
    d = _date_field(columns_dict)
    if d:
        return d
    for cand in ("created_at", "createdAt", "updated_at", "updatedAt"):
        if cand in (columns_dict or {}):
            return cand
    return None


def _timeline_collection(table: str, columns_dict: dict, desc_hints: dict,
                         view_label: str = "Open") -> dict:
    """A date-anchored feed: Repeat rows of [date rail | record card].

    The timeline alternative for chronology-heavy apps (activity logs,
    bookings, filings). The caller guards on _timeline_date first.
    """
    card_props = pick_card_props(columns_dict, hints=desc_hints)
    title_field = card_props.get("cardTitle") or _label_field(columns_dict)
    badge = (card_props.get("cardBadges") or [None])[0]
    date = _timeline_date(columns_dict) or "created_at"

    card_children: list[dict] = []
    if badge and badge != title_field:
        card_children.append({"type": "Badge", "props": {
            "content": f"{{{{item.{badge}}}}}", "variant": "neutral"}})
    card_children.append({"type": "Link", "props": {
        "label": view_label, "navigate": f"/{table}/{{{{item.id}}}}"}})

    return {"type": "Stack", "props": {"gap": "tokens.spacing.3"}, "children": [
        {"type": "Repeat", "bind": table, "children": [
            {"type": "Row", "props": {"gap": "tokens.spacing.4", "align": "start"}, "children": [
                {"type": "Text", "props": {
                    "content": f"{{{{item.{date}}}}}",
                    "className": "w-28 shrink-0 pt-4 text-xs text-muted-foreground"}},
                {"type": "Card",
                 "props": {"title": f"{{{{item.{title_field}}}}}", "elevation": "sm"},
                 "children": card_children},
            ]},
        ]},
    ]}


def build_list_page(entity: str, columns: dict, route: str, design_spec: dict | None,
                    page_hint: dict | None = None) -> dict:
    # Layout DNA: a "board" app renders its lists as kanban wherever the
    # entity has a status-like column — the strongest structural signal a
    # list page can carry. Falls through to the standard builder otherwise.
    if _list_composition(design_spec) == "board" and _status_column(_as_field_dict(columns)):
        return build_kanban_page(entity, columns, route,
                                 design_spec=design_spec, page_hint=page_hint)

    table = _table_from_route(route, entity.lower())
    # The row already links to the detail page (rowHref), so a raw leading
    # "Id" column is pure machine noise — 18 of 26 audited tables led with it.
    display = [c for c in _display_columns(columns, limit=7)
               if c.lower() not in ("id", "uuid")][:6] \
        or _display_columns(columns, limit=6)
    columns_dict = _as_field_dict(columns)
    # Slice-3: `type:"money"` columns default to Table's currency formatter
    # (right-aligned Intl.NumberFormat) so amounts read as $1,234.56 instead
    # of raw "1234.56". Per-row currency (from the sibling _currency column)
    # is a Table-schema limitation left to a follow-on slice — the column-def
    # `format:"currency"` prop is a static formatter, no per-row currency key.
    cols = []
    for c in display:
        meta = columns_dict.get(c) or {}
        col_def: dict = {"key": c, "label": _label(c)}
        if str(meta.get("type", "")).lower() in ("money", "currency"):
            col_def["format"] = "currency"
            col_def["align"] = "right"
        cols.append(col_def)

    hint = page_hint or {}
    desc_hints = parse_description_hints(hint.get("description") or "", columns_dict)
    voice = _voice(design_spec)
    feat = compose_features(
        hint.get("features") or [],
        columns=columns_dict,
        entity=entity,
        data_source=table,
    )
    row_actions = _to_table_row_actions(compose_card_actions(hint.get("actions") or []))
    header_actions = compose_header_actions(hint.get("actions") or [])

    hum = _humanize_entity(entity)
    default_new_btn = {"type": "Button", "props": {
        "label": f"{voice['create']} {hum}", "variant": "primary",
        "navigate": f"/{table}/new"}}
    header_btns = [{"type": "Button", "props": _button_props(a)} for a in header_actions] or [default_new_btn]

    table_props: dict = {
        "columns": cols,
        "rows": f"{{{{{table}}}}}",
        "rowHref": f"/{table}/{{id}}",
        # Per-entity empty state — "No records yet." repeated across every
        # table of every app was a same-generator tell.
        "emptyText": f"No {hum.lower()}s yet",
        # FIX-4 wired at source (was per-app on tr7rfk34): the library's Table
        # renders a CTA when emptyAction is set. Every list page already knows
        # its create route (default_new_btn.navigate), so wire it here instead
        # of stamping "Nothing here yet" dead-ends. Description carries the
        # domain voice ("Add one to get started" / "Create one to get started").
        "emptyDescription": f"{voice['create']} one to get started.",
        "emptyAction": {
            "label": f"{voice['create']} {hum}",
            "navigate": f"/{table}/new",
        },
    }
    if row_actions:
        table_props["rowActions"] = row_actions

    data_sources = [{"name": table, "entity": entity, "op": "list"}]
    for ds in feat["extra_ds"]:
        data_sources.append(ds)

    heading_row = {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
        {"type": "Heading", "props": {"content": _entity_heading_plural(entity), "level": 1}},
        {"type": "Row", "props": {"gap": "tokens.spacing.2"}, "children": header_btns},
    ]}
    # Layout DNA: card-grid apps browse records as cards, timeline apps as a
    # date-anchored feed (when the entity has a date column); the rest keep
    # the proven Table.
    list_comp = _list_composition(design_spec)
    if list_comp == "card-grid":
        collection_node = _card_grid_collection(table, columns_dict, desc_hints,
                                                view_label=voice["view"])
    elif list_comp == "timeline" and _timeline_date(columns_dict):
        collection_node = _timeline_collection(table, columns_dict, desc_hints,
                                               view_label=voice["view"])
    else:
        collection_node = {"type": "Table", "props": table_props}
    root_children = [
        heading_row,
        *feat["header_nodes"],
        collection_node,
        *feat["footer_nodes"],
    ]

    return {
        "schemaVersion": "2",
        "id": f"{table}-list",
        "route": route,
        "layout": "main",
        "dataSources": data_sources,
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": root_children},
    }


# ── kanban builder (pipeline / board pages) ─────────────────────────────────
# A kanban page is a pure function of the entity's columns: a Kanban node bound to
# the entity's list dataSource, grouped by its status/stage column, cards titled by
# the entity's label field. Built deterministically so a "pipeline" page can never
# silently become a Table (the LLM never authors it). Only Kanban.schema.ts props
# are emitted (data/groupBy/columnOrder/cardTitle/cardHref), so validateProps never
# strips anything.

def build_kanban_page(entity: str, columns: dict, route: str,
                      design_spec: dict | None = None, entities: dict | None = None,
                      registry: dict | None = None, output_dir: str | None = None,
                      page_hint: dict | None = None) -> dict:
    columns = _as_field_dict(columns)
    source = _entity_list_source(entity)
    # Detail routes on disk are kebab-case (see build_list_page:644), but
    # `source` is the camelCase dataSource variable name. Using `source`
    # as the route slug generates URLs like /assessmentDays/<id> that 404
    # because the real route file is /assessment-days/[id].
    table = _table_from_route(route, entity.lower())
    status = _status_column(columns)
    label = _label_field(columns)
    section_gap = "tokens.spacing.semantic.section"

    # Polish levers — extract hints from the planner's per-page dict.
    hint = page_hint or {}
    desc_hints = parse_description_hints(hint.get("description") or "", columns)
    # Prose-parser groupBy overrides the naive first-enum column, but only
    # when it's a real column and the naive picker actually chose something
    # different (protects "grouped by status" prose against a wrong enum).
    if desc_hints.get("groupBy") and desc_hints["groupBy"] in columns:
        status = desc_hints["groupBy"]

    kanban_props: dict = {
        "data": "{{%s}}" % source,
        "cardTitle": label,
        "cardHref": f"/{table}/{{id}}",
    }
    if status:
        kanban_props["groupBy"] = status
        enum = _enum_values(columns.get(status) or {})
        if enum:
            kanban_props["columnOrder"] = enum
    kanban_props["emptyText"] = f"No {_humanize_entity(entity).lower()}s yet"

    # LEVER 1 — smart card props (title/subtitle/image/badges) with prose hints.
    # pick_card_props emits SEMANTIC keys; map to Kanban's schema (cardTitle,
    # cardDescription, cardBadge — no cardImage/cardBadges/cardSubtitle).
    card_props = pick_card_props(columns, hints=desc_hints)
    if card_props.get("cardTitle"):
        kanban_props["cardTitle"] = card_props["cardTitle"]
    if card_props.get("cardSubtitle"):
        kanban_props["cardDescription"] = card_props["cardSubtitle"]
    if card_props.get("cardBadges"):
        # Kanban's cardBadge is a single string — first badge column wins.
        kanban_props["cardBadge"] = card_props["cardBadges"][0]

    # LEVER 2 — planner's row_action list. Kanban.schema does NOT yet accept
    # cardActions; per-card action buttons come with a future library seam. For
    # now the planner's row_actions surface via the LIST view (Table.rowActions)
    # so the intent isn't lost — we intentionally omit cardActions on Kanban
    # rather than emit props the renderer's validateProps would strip.

    # LEVER 3 — features (approval, filterable, metrics, timeline, search).
    feat = compose_features(
        hint.get("features") or [],
        columns=columns,
        entity=entity,
        data_source=source,
    )

    header_actions = compose_header_actions(hint.get("actions") or [])

    heading_row = {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
        {"type": "Heading", "props": {"content": _entity_heading_plural(entity), "level": 1}},
    ]}
    if header_actions:
        heading_row["children"].append({
            "type": "Row", "props": {"gap": "tokens.spacing.2"},
            "children": [{"type": "Button", "props": _button_props(a)} for a in header_actions],
        })

    kanban = {"type": "Kanban", "props": kanban_props}
    root_children = [heading_row, *feat["header_nodes"], kanban, *feat["footer_nodes"]]

    data_sources = [{"name": source, "entity": entity, "op": "list"}]
    for ds in feat["extra_ds"]:
        data_sources.append(ds)

    return {
        "schemaVersion": "2",
        "id": f"{_table_from_route(route, entity.lower())}-kanban",
        "route": route,
        "layout": "main",
        "dataSources": data_sources,
        "root": {"type": "Stack", "props": {"gap": section_gap}, "children": root_children},
    }


def _to_table_row_actions(actions: list[dict]) -> list[dict]:
    """Table.RowAction is `.strict()` and accepts only
    {label, icon?, navigate?, workflow?, variant?} — normalize the
    planner-derived shape (which may carry input_map / non-Table variants)
    to what Table.schema will actually keep. input_map is dropped here
    with a comment on the planner-side: revisit once Table's schema
    supports parameterized workflow dispatch."""
    out: list[dict] = []
    for a in actions or []:
        if not isinstance(a, dict) or not a.get("label"):
            continue
        entry: dict = {"label": a["label"]}
        if a.get("workflow"):
            entry["workflow"] = a["workflow"]
        if a.get("navigate"):
            entry["navigate"] = a["navigate"]
        # Table only allows "default" | "danger". Map our polish output
        # (which may say "primary"): reject → danger, everything else → default.
        raw_variant = str(a.get("variant") or "").lower()
        if raw_variant == "danger" or a["label"].lower() in ("reject", "delete", "remove"):
            entry["variant"] = "danger"
        out.append(entry)
    return out


def _button_props(action: dict) -> dict:
    """Map a composed header-action dict → renderer Button props."""
    p: dict = {"label": action.get("label") or "Action"}
    if action.get("workflow"):
        p["workflow"] = action["workflow"]
    if action.get("navigate"):
        p["navigate"] = action["navigate"]
    variant = action.get("variant") or "primary"
    p["variant"] = variant
    return p


# ── calendar builder (schedule pages) ───────────────────────────────────────
# A calendar page binds a Calendar in EVENT mode: `events` is the {{listDataSource}}
# binding (NOT `bind`, NOT a bare name), `dateField` is the entity's primary date
# column, `titleField` its label, `colorField` its status. Built deterministically so
# the calendar always gets the correct `events` contract. Only Calendar.schema.ts
# event-mode props are emitted.

def build_calendar_page(entity: str, columns: dict, route: str,
                        design_spec: dict | None = None, entities: dict | None = None,
                        registry: dict | None = None, output_dir: str | None = None) -> dict:
    columns = _as_field_dict(columns)
    source = _entity_list_source(entity)
    # Detail routes on disk are kebab-case (see build_list_page:644), but
    # `source` is the camelCase dataSource variable name. Using `source`
    # as the route slug generates URLs like /assessmentDays/<id> that 404
    # because the real route file is /assessment-days/[id]. Route from the
    # same helper the list/detail pages use.
    table = _table_from_route(route, entity.lower())
    date_field = _date_field(columns)
    label = _label_field(columns)
    status = _status_column(columns)
    section_gap = "tokens.spacing.semantic.section"

    cal_props: dict = {
        "events": "{{%s}}" % source,
        "titleField": label,
        "view": "month",
        "eventHref": f"/{table}/{{id}}",
        "emptyText": f"No {_humanize_entity(entity).lower()}s scheduled",
    }
    if date_field:
        cal_props["dateField"] = date_field
    if status:
        cal_props["colorField"] = status

    heading = {"type": "Heading",
               "props": {"content": _humanize_entity(entity) + " Calendar", "level": 1}}
    calendar = {"type": "Calendar", "props": cal_props}
    return {
        "schemaVersion": "2",
        "id": f"{_table_from_route(route, entity.lower())}-calendar",
        "route": route,
        "layout": "main",
        "dataSources": [{"name": source, "entity": entity, "op": "list"}],
        "root": {"type": "Stack", "props": {"gap": section_gap}, "children": [heading, calendar]},
    }


# ── dashboard builder (planner-authored widgets) ────────────────────────────
# A report/dashboard page may carry a planner-authored `widgets[]` — the JUDGMENT
# the registry can't derive (which entity to count, what to group a chart by, which
# table to list). Each widget is rendered DETERMINISTICALLY from the registry into
# the exact aggregate/series/list dataSource shapes the runtime already resolves
# (reused verbatim from widget_data_source_guard / chart_data_source_guard), so the
# LLM never guesses a dashboard's data. Every widget's entity + referenced columns
# are validated against the registry; a widget naming a non-existent entity/column
# is DROPPED (never invented). Returns None when no widget is valid → the caller
# keeps the LLM path for genuinely bespoke dashboards (no regression).

_METRIC_FNS = {"count", "sum", "avg", "min", "max"}
_SERIES_BUCKETS = {"day", "week", "month"}


def _lower1(s: str) -> str:
    return (s[:1].lower() + s[1:]) if s else s


def _cap1(s: str) -> str:
    return (s[:1].upper() + s[1:]) if s else s


def _real_col(cols: dict, name) -> str | None:
    """The real column name matching `name` (normalised), or None."""
    if not isinstance(name, str) or not name.strip():
        return None
    want = _norm_col(name)
    for c in (cols or {}):
        if _norm_col(c) == want:
            return c
    return None


def _valid_filter(filt, cols: dict):
    """({realCol: value}, ok). ok=False when a filter key names a non-existent
    column (→ drop the widget). An absent/empty filter is ({}, True)."""
    if filt in (None, {}):
        return {}, True
    if not isinstance(filt, dict):
        return {}, True
    out: dict = {}
    for k, v in filt.items():
        real = _real_col(cols, k)
        if not real:
            return {}, False
        out[real] = v
    return out, True


def _dash_card(title: str | None, node: dict, gap: str) -> dict:
    children: list[dict] = []
    if title:
        children.append({"type": "Heading", "props": {"content": title, "level": 3}})
    children.append(node)
    return {"type": "Card", "children": [{"type": "Stack", "props": {"gap": gap}, "children": children}]}


def _dashboard_composition(design_spec: dict | None) -> str:
    """The dashboard SHAPE chosen by this project's design DNA.

    Falls back to "stat-grid" (the historical skeleton) so any app generated
    without a DNA keeps its previous, known-good layout.
    """
    if isinstance(design_spec, dict):
        for path in (("layout", "dashboard"), ("designDna", "layout", "dashboard")):
            node: object = design_spec
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, str) and node:
                return node
    return "stat-grid"


def _compose_dashboard(composition: str, heading: str, stat_nodes: list[dict],
                       block_nodes: list[dict], card_gap: str) -> list[dict]:
    """Arrange the SAME resolved widgets into structurally different dashboards.

    Every branch uses only already-validated nodes (bindings/dataSources are
    untouched), so composition can vary freely without risking broken data.
    """
    head = {"type": "Heading", "props": {"content": heading, "level": 1}}

    def tiles(cols: int | None = None) -> list[dict]:
        if not stat_nodes:
            return []
        n = cols or len(stat_nodes)
        return [{"type": "Grid",
                 "props": {"columns": max(1, min(n, len(stat_nodes))), "gap": card_gap,
                           "equalCols": True, "equalRows": True},
                 "children": stat_nodes}]

    def blocks(cols: int = 2) -> list[dict]:
        if not block_nodes:
            return []
        if len(block_nodes) >= 2:
            return [{"type": "Grid", "props": {"columns": cols, "gap": card_gap},
                     "children": block_nodes}]
        return list(block_nodes)

    # --- stat-strip: a thin full-width KPI band, then a wide primary block ---
    if composition == "stat-strip":
        out = [head]
        if stat_nodes:
            out.append({"type": "Row", "props": {"gap": card_gap, "align": "stretch"},
                        "children": stat_nodes})
        out.extend(blocks(cols=1) if len(block_nodes) <= 2 else blocks(cols=2))
        return out

    # --- hero-led: a greeting band leads, KPIs support, one focus block ---
    if composition == "hero-led":
        # Hero.schema props are headline/subhead/ctas — "subheadline" doesn't
        # exist, and the component indexes ctas.length, so ctas must be [].
        out: list[dict] = [{
            "type": "Hero",
            "props": {"headline": heading,
                      "subhead": "Your day at a glance",
                      "ctas": []}}]
        out.extend(tiles())
        out.extend(blocks(cols=1 if len(block_nodes) <= 2 else 2))
        return out

    # --- feed-led: the activity/table block is the hero; KPIs demoted below ---
    if composition == "feed-led":
        out = [head]
        if block_nodes:
            out.append(block_nodes[0])
        out.extend(tiles(cols=min(4, len(stat_nodes) or 1)))
        if len(block_nodes) > 1:
            rest = block_nodes[1:]
            out.append({"type": "Grid", "props": {"columns": 2, "gap": card_gap},
                        "children": rest} if len(rest) >= 2 else rest[0])
        return out

    # --- split-focus: 60/40 — primary work surface beside a KPI rail ---
    if composition == "split-focus" and stat_nodes and block_nodes:
        left = {"type": "Stack", "props": {"gap": card_gap},
                "children": block_nodes}
        right = {"type": "Stack", "props": {"gap": card_gap},
                 "children": stat_nodes}
        return [head, {"type": "Row", "props": {"gap": card_gap, "align": "start"},
                       "children": [left, right]}]

    # --- board-first: blocks lead in a wide grid, compact metrics underneath ---
    if composition == "board-first":
        out = [head]
        out.extend(blocks(cols=2))
        out.extend(tiles(cols=min(4, len(stat_nodes) or 1)))
        return out

    # --- stat-grid (default / historical): tiles grid → block grid ---
    out = [head]
    out.extend(tiles())
    out.extend(blocks(cols=2))
    return out


def _polish_dashboard_on() -> bool:
    """Spec C Slice 1 — planner-authored `dashboard_composition` gate.

    Default off (opt-in). When on, dashboards with a page-level
    `dashboard_composition` dict compile through `compose_dashboard`
    (validates every ref against entity/component registries; falls back
    to labeled placeholders on unresolved refs). The legacy widgets[]
    path stays for pages that don't emit composition, so this flag is
    safe to flip without regenerating apps.
    """
    return os.getenv("FORGE_POLISH_DASHBOARD", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def build_dashboard_page(page: dict, registry: dict | None,
                         design_spec: dict | None = None) -> dict | None:
    """Render a report/dashboard page's planner-authored `widgets[]` into a real Page
    schema — deterministically, from the registry (0 LLM). Returns None when the page
    carries no widgets or none of them resolve to a real entity/column (LLM fallback)."""
    # Spec C Slice 1 — composition path. When the planner emits a
    # `dashboard_composition` block AND the flag is on, we compile
    # through the composer instead of the widgets[] path. Composer
    # validates every reference against the entity/component registries
    # + never crashes on unresolvable refs (labeled placeholder swap).
    composition = page.get("dashboard_composition")
    if _polish_dashboard_on() and isinstance(composition, dict) and composition:
        from services.dashboard_composer import compose_dashboard, CompositionError
        entities = registry or {}
        # Component names come from the same starter manifest the
        # planner sees in its C6 catalog injection — kept lazy to avoid
        # loading the manifest for every non-composition page.
        try:
            from services.library_manifest import load_component_catalog
            component_names = set((load_component_catalog() or {}).keys())
        except Exception:
            component_names = set()
        try:
            root = compose_dashboard(
                composition,
                entities=entities,
                component_names=component_names,
            )
        except CompositionError as exc:
            logger.warning(
                "[c1] dashboard composition rejected — falling back to "
                "widgets[] path: %s", exc,
            )
            root = None
        if isinstance(root, dict) and root:
            route = page.get("route") or "/dashboard"
            table = _table_from_route(route, "dashboard")
            return {
                "schemaVersion": "2",
                "id": table,
                "route": route,
                "layout": "main",
                "dataSources": [],  # composer nodes carry their own binds
                "root": root,
            }

    widgets = page.get("widgets")
    if not isinstance(widgets, list) or not widgets:
        return None
    entities = registry or {}
    gap = _gap(design_spec)
    route = page.get("route") or "/dashboard"
    table = _table_from_route(route, "dashboard")

    data_sources: list[dict] = []
    stat_nodes: list[dict] = []
    block_nodes: list[dict] = []  # charts + tables, each in its own Card
    used_names: set[str] = set()

    def _uniq(base: str) -> str:
        base = base or "widget"
        name = base
        i = 2
        while name in used_names:
            name = f"{base}{i}"
            i += 1
        used_names.add(name)
        return name

    for w in widgets:
        if not isinstance(w, dict):
            continue
        wtype = str(w.get("type") or "").strip().lower()
        real_ent, cols = _resolve_target(str(w.get("entity") or ""), entities)
        if not real_ent:
            continue  # entity not in the registry → drop (never invent)
        raw_title = w.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None

        if wtype == "stat":
            metric = w.get("metric") if isinstance(w.get("metric"), dict) else {}
            fn = str(metric.get("fn") or "count").strip().lower()
            if fn not in _METRIC_FNS:
                continue
            m: dict = {"fn": fn}
            if fn != "count":
                field = _real_col(cols, metric.get("field"))
                if not field:
                    continue  # sum/avg/… needs a real column
                m["field"] = field
            filt, ok = _valid_filter(metric.get("filter"), cols)
            if not ok:
                continue
            if filt:
                m["filter"] = filt
            name = _uniq(f"{_lower1(real_ent)}Stat")
            data_sources.append({"name": name, "entity": real_ent, "op": "aggregate",
                                 "metrics": {"value": m}})
            label = title or f"{_humanize_entity(real_ent)} {fn}".strip()
            stat_nodes.append({"type": "MetricTile", "props": {
                "label": label, "value": "{{%s.value}}" % name, "format": "number"}})

        elif wtype == "chart":
            group_by = _real_col(cols, w.get("groupBy"))
            if not group_by:
                continue  # groupBy must be a real column
            src: dict = {"entity": real_ent, "op": "series", "groupBy": group_by}
            agg = w.get("agg") if isinstance(w.get("agg"), dict) else None
            if agg:
                afn = str(agg.get("fn") or "count").strip().lower()
                if afn not in _METRIC_FNS:
                    afn = "count"
                a: dict = {"fn": afn}
                if afn != "count":
                    afield = _real_col(cols, agg.get("field"))
                    if not afield:
                        continue
                    a["field"] = afield
                src["agg"] = a
            bucket = w.get("bucket")
            if isinstance(bucket, str) and bucket.strip().lower() in _SERIES_BUCKETS:
                src["bucket"] = bucket.strip().lower()
            filt, ok = _valid_filter(w.get("filter"), cols)
            if not ok:
                continue
            if filt:
                src["filter"] = filt
            if "bucket" in src:
                src["sort"] = "label"
                src["limit"] = 12
            else:
                src["sort"] = "value"
                src["limit"] = 8
            name = _uniq(f"{_lower1(real_ent)}By{_cap1(group_by)}")
            src["name"] = name
            data_sources.append(src)
            chart_node = {"type": "Chart", "props": {
                "data": "{{%s}}" % name, "xKey": "label",
                "series": [{"name": title or "Count", "dataKey": "value"}]}}
            block_nodes.append(_dash_card(title, chart_node, gap))

        elif wtype == "table":
            filt, ok = _valid_filter(w.get("filter"), cols)
            if not ok:
                continue
            src = {"entity": real_ent, "op": "list"}
            limit = w.get("limit")
            if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
                src["limit"] = limit
            if filt:
                src["filter"] = filt
            name = _uniq(f"{_lower1(real_ent)}Rows")
            src["name"] = name
            data_sources.append(src)
            raw_cols = w.get("columns")
            display: list[str] = []
            if isinstance(raw_cols, list):
                for rc in raw_cols:
                    real = _real_col(cols, rc)
                    if real and real not in display:
                        display.append(real)
            if not display:
                display = _display_columns(cols, limit=6)
            # Raw leading "Id" columns + the stock "No records yet." empty
            # state were top same-generator tells in the audit.
            display = [c for c in display if c.lower() not in ("id", "uuid")] or display
            table_cols = [{"key": c, "label": _label(c)} for c in display]
            # FIX-4 wired at source: every dashboard list Table gets an
            # empty-state CTA that navigates to the entity's create route
            # (`/{entity_slug}/new` — matches build_list_page's convention).
            # The library renders the CTA button when emptyAction is present.
            _ent_slug = _table_from_route("/" + real_ent, real_ent.lower())
            _ent_hum = _humanize_entity(real_ent)
            table_node = {"type": "Table", "props": {
                "columns": table_cols, "rows": "{{%s}}" % name,
                "emptyText": f"No {_ent_hum.lower()}s yet",
                "emptyDescription": "Get started by adding your first record.",
                "emptyAction": {
                    "label": f"Add {_ent_hum}",
                    "navigate": f"/{_ent_slug}/new",
                },
            }}
            block_nodes.append(_dash_card(title, table_node, gap))

    if not data_sources:
        return None  # nothing valid → LLM authors the bespoke dashboard

    heading = page.get("name") or page.get("title") or "Dashboard"
    if isinstance(heading, str):
        heading = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", heading).strip() or "Dashboard"
    # Semantic spacing tokens (same scale the LLM pages + design system use) — the root
    # Stack separates sections; the grids space equal-weight cards/tiles.
    section_gap = "tokens.spacing.semantic.section"
    card_gap = "tokens.spacing.semantic.card"

    # COMPOSITION — the app's design DNA decides the dashboard's SHAPE, not just
    # its colors. Without this every generated app shipped the identical
    # "tiles row → chart grid → table" skeleton and looked like the same product.
    composition = _dashboard_composition(design_spec)
    root_children = _compose_dashboard(
        composition, heading, stat_nodes, block_nodes, card_gap)

    return {
        "schemaVersion": "2",
        "id": table,
        "route": route,
        "layout": "main",
        "dataSources": data_sources,
        "root": {"type": "Stack", "props": {"gap": section_gap}, "children": root_children},
    }


def build_crud_page(archetype: str, entity: str, columns: dict, route: str,
                    design_spec: dict | None = None, entities: dict | None = None,
                    field_specs: list | None = None, registry: dict | None = None,
                    output_dir: str | None = None,
                    page_hint: dict | None = None) -> dict | None:
    """Dispatch by archetype. Returns a Page schema, or None for non-routine pages.
    `entities` (the registry's entity map) lets FK Selects resolve a real label field
    from the target entity; it is optional and degrades gracefully when absent.
    `field_specs` (the plan page's `fields`) is the planner's per-field form spec, merged
    over the registry-derived defaults by build_form_page (form/edit archetypes only).
    `registry`/`output_dir` feed the FK-role authority (fk_semantics) so a domain FK is
    kept as an editable Select while actor/tenancy FKs are hidden (server-filled).
    `page_hint` is the planner's full per-page dict (description, actions, features, …)
    — threaded to Kanban/List so the polish helpers in `services.page_polish` can
    surface prose-mentioned columns, row actions, and feature composers."""
    columns = _as_field_dict(columns)  # tolerate dict OR list-of-fields shapes
    a = (archetype or "").strip().lower()
    # The plan's authoritative form→workflow decision (`page.submit.target`) —
    # thread it into build_form_page so its Slice A T5 override kicks in and
    # the domain workflow wins over the CRUD-derived default. Domain-agnostic:
    # the string is whatever the planner authored, verbatim.
    # Only kind='workflow' targets are workflow names; kind='data_api' targets
    # are entity names and must NOT be used as Form.props.workflow.
    _submit = (page_hint or {}).get("submit") if isinstance(page_hint, dict) else None
    submit_target = (
        _submit.get("target")
        if isinstance(_submit, dict) and _submit.get("kind") == "workflow"
        else None
    )
    if a == "list":
        return build_list_page(entity, columns, route, design_spec, page_hint=page_hint)
    if a in ("form", "create"):
        return build_form_page(entity, columns, route, design_spec, op="create",
                               entities=entities, field_specs=field_specs,
                               registry=registry, output_dir=output_dir,
                               submit_target=submit_target)
    if a == "edit":
        return build_form_page(entity, columns, route, design_spec, op="edit",
                               entities=entities, field_specs=field_specs,
                               registry=registry, output_dir=output_dir,
                               submit_target=submit_target)
    if a == "detail":
        return build_detail_page(entity, columns, route, design_spec,
                                 page_hint=page_hint)
    if a == "kanban":
        return build_kanban_page(entity, columns, route, design_spec, entities=entities,
                                 registry=registry, output_dir=output_dir,
                                 page_hint=page_hint)
    if a == "calendar":
        return build_calendar_page(entity, columns, route, design_spec, entities=entities,
                                   registry=registry, output_dir=output_dir)
    return None
