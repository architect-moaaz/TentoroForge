"""Ensure create/edit forms have an input for EVERY editable column.

`form_field_align` only adds inputs for *required* columns, so every optional
column the LLM omitted — notes, category, and crucially FK dropdowns
(customer/equipment) — silently disappears, leaving half-empty forms. This pass
scaffolds the full field set from the entity's real columns:

  - relational FK columns (customerId → Customer) → `Select` with `optionsFrom`
    pointing at a list dataSource it also adds to the page.
  - enum/numeric/date/bool/text columns → the right control (via semantic_field_types).
  - plain columns → `Input`.

Additive + idempotent: columns the form already covers are left as-is; only
create/edit forms (by filename or a Create/Update workflow) are touched.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any

from services.fk_semantics import default_hidden_fk_norms, hidden_fk_columns
from services.semantic_field_types import (
    _decide, _ent_key, _entity_from_form_workflow, _entity_key_for_file,
    _iter_nodes, _label, _norm, curated_enum_options, harvest_seed_options,
    harvest_workflow_statuses, _registry_enum_values, _registry_types,
    index_status_workflows,
)

_SYSTEM = {"id", "createdat", "updatedat", "deletedat", "createdby", "updatedby"}
# Conservative name-based hidden-FK default (actor/tenancy) — used only where no entity /
# registry is in scope to classify roles. The role-based set (fk_semantics.hidden_fk_columns)
# is the primary path so a DOMAIN FK is never hidden (it becomes an editable Select).
_DEFAULT_HIDDEN = default_hidden_fk_norms()
_LABEL_FIELDS = ("fullname", "name", "title", "label", "displayname", "email",
                 "code", "number", "sku", "reference")
_FIELD_TYPES = {"Input", "Textarea", "Select", "NumberInput", "DatePicker",
                "Switch", "Combobox", "MultiSelect", "RadioGroup", "MaskedInput",
                "KeyValueInput", "FileUpload", "TimePicker", "ColorPicker",
                "Slider", "Rating", "InputOTP"}

# Person-role FK columns denote *a user in a role* (a ticket's requester, a task's
# assignee) — they point at the app's User/person entity even though the role word
# ("requester") shares no letters with "User" and the registry relation records no
# `foreignKey` column to disambiguate which of several User relations it is. Without
# this, `requesterId` derives a phantom `requesters` source → GET /api/data/requesters
# 404s (there is no Requester table). Normalized (lowercase, alphanumerics only).
_PERSON_ROLE_FKS = {
    "requester", "requestor", "requestedby", "assignee", "assignedto", "assigned",
    "reporter", "reportedby", "submitter", "submittedby", "approver", "approvedby",
    "reviewer", "reviewedby", "author", "authoredby", "creator", "createdby",
    "updatedby", "modifiedby", "editor", "manager", "supervisor", "lead",
    "agent", "operator", "technician", "engineer", "handler", "responder",
    "recipient", "sender", "contact", "assignor", "requestedfor",
    "shortlistedby", "interviewedby", "hiredby", "rejectedby", "screenedby",
}
# Non-relational field types the LLM sometimes emits over a FK/uuid column (a plain
# text box instead of a dropdown). repair_fk_dropdowns upgrades these to a Select so
# a real row id is submitted — free text into a uuid column crashes the insert
# ("invalid input syntax for type uuid: \"M\"").
_FK_INPUT_TYPES = {"Input", "NumberInput", "Textarea", "MaskedInput"}
# Entity keys (singular, via _ent_key) that represent a person/account.
_USER_ENTITY_KEYS = ("user", "person", "member", "account", "employee", "staff",
                     "teammember", "profile", "people", "contact")


def _user_like_entity(entities: dict) -> str | None:
    """The entity that represents a person/account (User/Member/Employee/…), used to
    resolve person-role FKs that have no lexical match to it. Returns the real entity
    name so the caller can derive its `/api/data/<slug>`."""
    keys = {_ent_key(n): n for n in (entities or {})}
    for want in _USER_ENTITY_KEYS:
        wk = _ent_key(want)
        if wk in keys:
            return keys[wk]
    for k, n in keys.items():
        if any(w in k for w in ("user", "person", "member", "employee", "account")):
            return n
    return None


def _role_fk_target(stem_norm: str, entities: dict) -> str | None:
    """A person-role FK stem (requester/assignee/reviewer/…) that matches no entity
    by name resolves to the app's user/person entity when one exists. None otherwise
    (no role, or no user-like entity) — the caller then flags/prunes it."""
    if _norm(stem_norm) in _PERSON_ROLE_FKS:
        return _user_like_entity(entities)
    return None


# HAR-1: patterns that mark a "status value" as garbage — a label the
# LLM wrote into a workflow's ``values.status`` or a node title that the
# harvester picked up, but that no user should ever see in a Status
# dropdown. Rejected: any leading/embedded "Status" section header
# (``"Status"``, ``"Status X"``, ``"X Status"``), and the multi-word
# action-verb node labels ("Insert Profile", "Create Assignment").
_STATUS_HEADER_RE = __import__("re").compile(
    r"^(?:status(?:\s+\S.*)?|\S.*\s+status)$", __import__("re").IGNORECASE,
)
_ACTION_VERB_LABEL_RE = __import__("re").compile(
    r"^\s*(?:insert|create|add|remove|delete|update|edit|new)\s+\S.+$",
    __import__("re").IGNORECASE,
)


def _is_status_value_garbage(
    value: str,
    entity_names: set[str],
    workflow_names: set[str],
) -> bool:
    """Return True if ``value`` looks like harvester noise rather than a
    real status literal. Applied to any value pulled from the global
    workflow-harvested fallback (or a status-workflow list) so a poorly
    authored workflow can't leak entity/workflow names, section headers,
    or action-verb labels into unrelated Status dropdowns.

    Rejects:
      * Entity names (``"CandidateProfile"``, ``"candidateprofile"``)
      * Workflow names (``"CreateAssignment"``, ``"Create Assignment"``)
      * ``"Status"`` header patterns (``"Status"``, ``"Status Screened"``,
        ``"Candidate Status"``)
      * Multi-word action-verb labels (``"Insert Profile"``, ``"Update Foo"``)

    Accepts everything else — including snake_case literals like
    ``"cv_screened"`` and short PascalCase words like ``"Hired"``.
    """
    if not isinstance(value, str):
        return True
    v = value.strip()
    if not v:
        return True
    v_lower = v.lower()
    v_alnum = "".join(c for c in v_lower if c.isalnum())
    # (a) entity names — case-insensitive, spaces/underscores stripped
    for name in entity_names:
        n = "".join(c for c in str(name).lower() if c.isalnum())
        if n and n == v_alnum:
            return True
    # (b) workflow names — same normalization
    for name in workflow_names:
        n = "".join(c for c in str(name).lower() if c.isalnum())
        if n and n == v_alnum:
            return True
    # (c) "Status" header patterns
    if _STATUS_HEADER_RE.match(v):
        return True
    # (d) action-verb labels
    if _ACTION_VERB_LABEL_RE.match(v):
        return True
    return False


def _known_workflow_names(output_dir: str) -> set[str]:
    """Set of workflow ``name`` fields (fallback: filename stem) for
    every ``workflows/*.json``. Used by :func:`_is_status_value_garbage`
    to reject harvester values that are actually workflow labels."""
    out: set[str] = set()
    wf_dir = os.path.join(output_dir, "workflows")
    if not os.path.isdir(wf_dir):
        return out
    for fp in glob.glob(os.path.join(wf_dir, "*.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        n = d.get("name") if isinstance(d, dict) else None
        if isinstance(n, str) and n.strip():
            out.add(n.strip())
        # also add the filename stem (some workflows lack a `name` field)
        stem = os.path.splitext(os.path.basename(fp))[0]
        if stem:
            out.add(stem)
    return out


def _load_registry(output_dir: str) -> dict:
    try:
        with open(os.path.join(output_dir, "registry.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _fk_target(entity_key: str, field_norm: str, relations: list, entities: dict) -> str | None:
    """Resolve which entity a FK column points at, e.g. (appointment, patientid)→Patient
    or (member, planid)→MembershipPlan (the stem `plan` is a substring of the target)."""
    stem = re.sub(r"id$", "", _norm(field_norm))          # planid → plan
    rels_here = [r for r in (relations or [])
                 if isinstance(r, dict) and _ent_key(r.get("from_entity")) == entity_key]

    # 1) A relation whose target's name relates to the FK stem (exact, prefix, or
    #    substring either way — so `plan` matches `MembershipPlan`).
    for rel in rels_here:
        to = rel.get("to_entity")
        ton = _norm(to)
        if to and stem and (stem == ton or stem in ton or ton in stem):
            return to
    # 1b) A person-role FK (requesterId, assigneeId) → the user/person entity. Placed
    #     before the weak single-relation guess so a role never mis-binds to an
    #     unrelated lone relation, and prefer a role-matching relation target if one
    #     is itself user-like.
    rt = _role_fk_target(stem, entities)
    if rt:
        for rel in rels_here:
            if _ent_key(rel.get("to_entity")) == _ent_key(rt):
                return rel["to_entity"]
        return rt
    # 2) If this entity has exactly ONE relation, the FK almost certainly targets it.
    if len(rels_here) == 1 and rels_here[0].get("to_entity"):
        return rels_here[0]["to_entity"]
    # 3) Fallback: match the stem against any entity name (exact or substring).
    for name in entities:
        nk = _ent_key(name)
        if stem and (stem == nk or stem in nk or nk in stem):
            return name
    return None


def _label_field(entity_name: str, entities: dict) -> str:
    cols = ((entities.get(entity_name) or {}).get("fields") or {})
    norm_cols = {_norm(c): c for c in cols}
    for cand in _LABEL_FIELDS:
        if cand in norm_cols:
            return norm_cols[cand]
    return "id"


def _plural(entity_name: str) -> str:
    """Canonical list-source / binding name for an entity. Delegates to
    :func:`services.entity_names.derive_names` — the SINGLE naming
    authority — so every builder that names dataSources agrees on
    `AssessmentDay → assessmentDays` (not `assessmentDaies`), and
    kebab / camel / snake variants stay in lock-step across the whole
    pipeline. Kept as a thin wrapper for backwards-compat with existing
    call-sites; new code should read from the registry's `names` block."""
    from services.entity_names import derive_names
    return derive_names(entity_name).sourceName


def _is_create_edit_form(schema: dict, path: str) -> bool:
    base = os.path.basename(path)[:-5].lower()
    if re.search(r"(new|edit|create|update|add|form)", base):
        return True
    for n in _iter_nodes(schema):
        if n.get("type") == "Form":
            wf = (n.get("props") or {}).get("workflow")
            if isinstance(wf, str) and re.match(r"^(Create|Update)[A-Z]", wf):
                return True
    return False


def _find_form_container(schema: dict) -> list | None:
    form = next((n for n in _iter_nodes(schema) if n.get("type") == "Form"), None)
    if not isinstance(form, dict):
        return None
    children = form.get("children")
    if not isinstance(children, list):
        form["children"] = children = []
    for c in children:
        if isinstance(c, dict) and c.get("type") in ("Stack", "Grid") and isinstance(c.get("children"), list):
            return c["children"]
    return children


def _target_from_plan(plan, ent_name, col_name, ent_keys):
    """Return the FK target's display name from the plan, or None.

    Priority-0 for FK resolution: when the plan declares
    ``fields[].fk: {table, column}``, that target is authoritative. The
    convention-based ``_fk_target`` (name+relation inference) is only
    consulted when the plan is silent. Matches the plan's ``table`` value
    (case-insensitive, tolerant of camel/snake variants) against the known
    registry entities so we return the same display name the rest of the
    pipeline uses.
    """
    if plan is None or not ent_name:
        return None
    from services.plan_field_lookup import get_fk
    fk = get_fk(plan, ent_name, col_name)
    if not fk:
        return None
    target_table = fk.get("table")
    if not isinstance(target_table, str):
        return None
    target_key = _ent_key(target_table)
    return ent_keys.get(target_key)


def repair_fk_dropdowns(output_dir: str) -> dict:
    """Fix FK dropdowns whose dataSource points at a non-existent entity.

    The page agent guesses a short entity name from the FK column (planId →
    "Plan") but the real entity is "MembershipPlan", so `/api/data/plans` resolves
    to nothing and the dropdown is empty. For every Select/Combobox/MultiSelect
    with optionsFrom, re-resolve the referenced entity from the FK column +
    registry relations and canonicalize the dataSource (name + entity) and
    optionsFrom (source + label). Idempotent — correct dropdowns are unchanged.

    Resolution order:
      0. Plan-declared ``fields[].fk`` — authoritative when present.
      1. Registry ``relations`` + ``_fk_target`` convention inference — fallback
         for plans that don't carry ``fk`` (legacy) or FK columns the plan didn't
         declare explicitly.
    """
    from services.plan_field_lookup import load_plan
    plan = load_plan(output_dir)
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"repaired": 0, "files": 0}
    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    relations = reg.get("relations") or []
    if not entities:
        return {"repaired": 0, "files": 0}
    ent_keys = {_ent_key(n): n for n in entities}

    repaired = 0
    touched = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json"):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        page_ent = _entity_key_for_file(fp, set(ent_keys))
        # Actor/tenancy FKs (server-filled) to skip when upgrading text Inputs → Selects;
        # a domain FK is NOT hidden and IS upgraded. Role-based via fk_semantics.
        hidden = hidden_fk_columns(ent_keys.get(page_ent, page_ent or ""), reg, output_dir)
        ds_list = schema.get("dataSources") if isinstance(schema.get("dataSources"), list) else []
        ds_by_name = {d.get("name"): d for d in ds_list if isinstance(d, dict)}
        changed = False
        # Only upgrade plain Inputs → Selects inside actual create/edit forms; a
        # list/filter page may legitimately carry a text field whose name ends in "id".
        is_form = _is_create_edit_form(schema, fp)

        for node in _iter_nodes(schema):
            ntype = node.get("type")
            p = node.get("props")
            if not isinstance(p, dict) or not p.get("name"):
                continue
            nk = _norm(p["name"])

            # (A) Canonicalize an EXISTING FK dropdown's source/entity/label.
            if ntype in ("Select", "Combobox", "MultiSelect"):
                of = p.get("optionsFrom")
                if not isinstance(of, dict):
                    continue
                if not (nk.endswith("id") and nk != "id"):
                    continue
                # Plan-declared fk beats convention inference.
                ent_display = ent_keys.get(page_ent) if page_ent else None
                target = _target_from_plan(plan, ent_display, p["name"], ent_keys) \
                    or _fk_target(page_ent or "", nk, relations, entities)
                if not target:
                    continue
                new_name = _plural(target)
                new_label = _label_field(target, entities)
                ds = ds_by_name.get(of.get("source"))
                # Only rewrite when the current wiring is actually wrong (unknown entity
                # or mismatched source), so correct dropdowns stay untouched.
                cur_entity_ok = ds and _ent_key(ds.get("entity")) in ent_keys and _ent_key(ds.get("entity")) == _ent_key(target)
                if cur_entity_ok and of.get("source") == ds.get("name"):
                    continue
                if ds is not None:
                    ds["entity"] = target
                    ds["name"] = new_name
                    ds["op"] = ds.get("op") or "list"
                else:
                    ds_list.append({"name": new_name, "entity": target, "op": "list"})
                    schema["dataSources"] = ds_list
                of["source"] = new_name
                of["value"] = of.get("value") or "id"
                of["label"] = new_label
                ds_by_name = {d.get("name"): d for d in ds_list if isinstance(d, dict)}
                repaired += 1
                changed = True
                continue

            # (B) Upgrade a FK column the LLM rendered as a plain text Input into a
            #     Select. A uuid FK (candidateId, shortlistedById) as a free-text box
            #     lets a user submit "M" → PostgresError invalid uuid. Skip preset
            #     hidden fields (they carry a bound id via defaultValue) and owner/
            #     system FKs. Only when the FK resolves to a real target entity.
            if is_form and ntype in _FK_INPUT_TYPES:
                if not (nk.endswith("id") and nk != "id") or nk in _SYSTEM or nk in hidden:
                    continue
                if p.get("type") == "hidden":
                    continue
                ent_display = ent_keys.get(page_ent) if page_ent else None
                target = _target_from_plan(plan, ent_display, p["name"], ent_keys) \
                    or _fk_target(page_ent or "", nk, relations, entities)
                if not target:
                    continue
                new_name = _plural(target)
                new_label = _label_field(target, entities)
                if new_name not in ds_by_name:
                    ds_list.append({"name": new_name, "entity": target, "op": "list"})
                    schema["dataSources"] = ds_list
                    ds_by_name = {d.get("name"): d for d in ds_list if isinstance(d, dict)}
                # Convert the node in place: drop input-only props, wire the dropdown.
                for k in ("type", "rows", "placeholder", "inputMode"):
                    p.pop(k, None)
                node["type"] = "Select"
                p["options"] = [{"value": "__none", "label": f"Select {target}…"}]
                p["optionsFrom"] = {"source": new_name, "value": "id", "label": new_label}
                repaired += 1
                changed = True

        if changed:
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return {"repaired": repaired, "files": touched}


_LIFECYCLE_AT = re.compile(r"(?:^|_)[a-z0-9]+_?at$", re.I)


def _is_required_col(name: str, meta: dict) -> bool:
    """A column must be filled on a create form when it's NOT NULL, has no DB default,
    isn't the PK, and isn't a lifecycle *At timestamp. Mirrors
    deterministic_pages._is_required so LLM forms get the same `*` the built forms do."""
    if not isinstance(meta, dict) or meta.get("primaryKey"):
        return False
    not_null = meta.get("nullable") is False or meta.get("notNull") is True
    if not not_null or meta.get("hasDefault"):
        return False
    typ = str(meta.get("type", "")).lower()
    low = name.lower()
    if typ.startswith(("timestamp", "date", "time")) and _LIFECYCLE_AT.search(name) \
            and low != "date":
        return False
    return True


# Free-text columns whose *name* signals an optional field — never force-required
# by the structural fallback even when the registry is silent about nullability.
_OPTIONAL_NAME_HINTS = (
    "notes", "note", "description", "comment", "remarks", "remark", "memo",
    "message", "reason", "details", "detail", "bio", "summary", "instructions",
    "instruction", "additional", "optional",
)
# Column-name signals of a *core* (structurally mandatory) field: identity, status,
# and scheduling columns a record almost always needs. A plain text/varchar column
# matching NONE of these is treated as optional free text and left unmarked.
_CORE_NAME_HINTS = (
    "name", "title", "label", "status", "state", "stage", "phase", "priority",
    "severity", "category", "type", "kind", "code", "number", "reference", "sku",
    "email", "date", "amount", "price", "total", "quantity",
)


def _infer_required(name: str, meta: dict, hidden: set[str] | None = None) -> bool:
    """Deterministic structural fallback for when the registry leaves a column
    `nullable` because the planner marked nothing required (the all-nullable 98tuyun7
    case). A create/edit field is *probably* mandatory when it's a foreign key (a
    record needs its parent) or a core non-optional column (status/date/name/…). It
    is left alone when it's a lifecycle *At timestamp, a boolean flag, a DB-defaulted
    column, the PK, or an obviously-optional free-text field (notes/description/…).
    Never consults notNull — that is ensure_required_markers' other, authoritative
    path; this only *adds* to what that path marks.

    Conservative by design: a plain free-text column whose name matches no core hint
    is treated as optional and stays unmarked, so we over-mark FK/date/status/name
    fields (safe — they usually ARE required) without blocking genuinely-optional
    text. Idempotent / read-only: never touches the DB schema."""
    if not isinstance(meta, dict) or meta.get("primaryKey") or meta.get("hasDefault"):
        return False
    nk = _norm(name)
    hid = hidden if hidden is not None else _DEFAULT_HIDDEN
    if nk == "id" or nk in _SYSTEM or nk in hid:
        return False
    typ = str(meta.get("type", "")).lower()
    low = name.lower()
    # Boolean flag: an unchecked box (false) is a valid value — never force-required.
    if typ.startswith("bool"):
        return False
    # Foreign key (customerId, projectId) → the record needs its parent. Mark it.
    if nk.endswith("id") and nk != "id":
        return True
    # Lifecycle timestamp (createdAt/updatedAt/*At) → auto-set, not user-required.
    if typ.startswith(("timestamp", "date", "time")) and _LIFECYCLE_AT.search(name) \
            and low != "date":
        return False
    # Obviously-optional free text by name → leave unmarked.
    if any(h in nk for h in _OPTIONAL_NAME_HINTS):
        return False
    # A real date/time column (startDate, dueDate) → core scheduling field. Mark it.
    if typ.startswith(("timestamp", "date", "time")):
        return True
    # Remaining text/varchar/char columns are marked ONLY when the name looks core
    # (status/name/code/…); other free text is treated as optional (conservative).
    is_texty = typ.startswith(("varchar", "text", "char", "string", "citext")) or typ == ""
    if is_texty:
        return any(h in nk for h in _CORE_NAME_HINTS)
    # Non-text scalars (integer/numeric/enum/uuid/json) with no default → core. Mark.
    return True


def ensure_required_markers(output_dir: str) -> dict:
    """Stamp `validators.required` on create/edit form fields that are structurally
    mandatory but shipped without the marker — so an LLM-authored form gets the same
    `*` (and browser-side empty-submit guard) the deterministic builder emits. A
    field is marked when EITHER its backing column is NOT NULL per the registry
    (`_is_required_col`) OR the deterministic structural heuristic (`_infer_required`:
    FK columns + core status/date/name fields) says it's mandatory — the latter is
    the fallback for apps where the planner marked nothing required so every column
    is `nullable:true`. Additive + idempotent; skips PK/system/owner and hidden preset
    fields; never touches the DB schema. Returns {marked, files}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"marked": 0, "files": 0}
    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    if not entities:
        return {"marked": 0, "files": 0}
    known = {_ent_key(n) for n in entities}

    marked = 0
    touched = 0
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json") or base.startswith(("login", "signup", "register")):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        if not _is_create_edit_form(schema, fp):
            continue
        ent_key = _entity_from_form_workflow(schema, entities) or _entity_key_for_file(fp, known)
        if not ent_key:
            continue
        ent_name = next((n for n in entities if _ent_key(n) == ent_key), None)
        if not ent_name:
            continue
        cols = (entities.get(ent_name) or {}).get("fields") or {}
        if not isinstance(cols, dict) or not cols:
            continue
        col_by_norm = {_norm(c): (c, m) for c, m in cols.items()}
        # Actor/tenancy FKs (server-filled) never get a required marker; a domain FK is
        # NOT hidden and may be marked required like any editable column.
        hidden = hidden_fk_columns(ent_name, reg, output_dir)

        changed = False
        for node in _iter_nodes(schema):
            if node.get("type") not in _FIELD_TYPES:
                continue
            p = node.get("props")
            if not isinstance(p, dict) or not p.get("name"):
                continue
            nk = _norm(p["name"])
            if nk in _SYSTEM or nk in hidden:
                continue
            if p.get("type") == "hidden":
                continue
            entry = col_by_norm.get(nk)
            if not entry:
                continue
            col, meta = entry
            if not (_is_required_col(col, meta) or _infer_required(col, meta, hidden)):
                continue
            v = p.get("validators")
            if isinstance(v, dict) and "required" in v:
                continue  # author/prior pass already decided (True or False) — never override
            if not isinstance(v, dict):
                v = {}
            v["required"] = True
            p["validators"] = v
            marked += 1
            changed = True

        if changed:
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return {"marked": marked, "files": touched}


def ensure_enum_selects(output_dir: str) -> dict:
    """Upgrade a plain `Input` over an enum-ish column into a `Select` in create/edit
    forms, so an LLM-authored form that shipped `status`/`stage`/`priority` as free-text
    boxes gets a real dropdown. Value source, in priority order:

      0. **Plan-declared** ``entities[].fields[].enum_values`` — when the planner
         has explicitly declared the enum literals for a column, THAT list is used
         verbatim and no other source is consulted. This is the authoritative path
         (per the complete-plan-schema spec): the plan speaks, everyone else is
         silent. Prevents the pollution class where entity names + humanized
         aliases + workflow strings all merged into one Status dropdown.
      1. registry `enum_values` (schema-declared enum),
      2. workflow-harvested status/stage literals (+ the entity's status workflow),
      3. a conservative curated dictionary for well-known fields
         (`semantic_field_types.curated_enum_options`).

    Never invents values for open-ended fields (nationality, notes, title, …) — those
    aren't in any source and stay a plain Input. Additive + idempotent: skips existing
    Selects, hidden/system/owner fields, `*Id` FK columns (owned by repair_fk_dropdowns),
    and fields carrying `optionsFrom`. Returns {converted, files}."""
    from services.plan_field_lookup import (
        get_enum_options,
        get_enum_values,
        load_plan,
        title_case_key,
    )
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"converted": 0, "files": 0}
    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    if not entities:
        return {"converted": 0, "files": 0}
    known = {_ent_key(n) for n in entities}
    reg_enums = _registry_enum_values(output_dir)           # {ent_key -> {norm_col -> vals}}
    # Workflow-harvested literals — a global {norm_col -> [values]} map.
    wf_statuses = {_norm(c): v for c, v in harvest_workflow_statuses(output_dir).items()}
    status_idx = index_status_workflows(output_dir)
    # Plan is the authority. When it declares enum_values for a column, we
    # SKIP every other source and use those literals verbatim. Loaded once,
    # `plan_field_lookup` caches internally.
    plan = load_plan(output_dir)

    # HAR-1: sets used to filter garbage out of the global workflow-harvested
    # fallback. Entity + workflow names are never legitimate status values,
    # yet the LLM sometimes writes them into workflow `values.status` and the
    # global harvester dutifully surfaces them into every unrelated form.
    _entity_name_set = {str(n) for n in entities}
    _workflow_name_set = _known_workflow_names(output_dir)

    def _options_for(
        ent_key: str | None, name: str, nk: str, ent_name: str | None,
    ) -> list[dict[str, str]] | None:
        """Return `[{value, label}]` for the dropdown, or None if no source.

        Spec B1: plan-authored `label` on enum_values wins verbatim so users see
        `ACH Transfer` not `ach`. Any non-plan source (registry/workflow/curated)
        Title-Cases the raw value as a fallback labeler.
        """
        # Priority 0 — plan declaration. When present, this is the ONLY source.
        # No merging, no fallback, no humanized aliasing. That's the entire point:
        # the plan says these are the values, so these are the values.
        if plan is not None and ent_name:
            plan_opts = get_enum_options(plan, ent_name, name)
            if plan_opts:
                return plan_opts
        # Priority 1 — registry enum_values (schema-declared).
        if ent_key:
            ev = reg_enums.get(ent_key, {}).get(nk)
            if ev:
                return _titleize_keys(ev)
        # Priority 2 (HAR-1: moved before global wf_statuses for status cols) —
        # per-entity status workflow. When a status workflow targets THIS
        # entity, use ITS statuses, not the app-wide union that leaks values
        # across entities (candidate's Hired appearing on a drive's Status).
        if ent_key and (nk == "status" or nk.endswith("status")):
            st = status_idx.get(ent_key)
            if st and st.get("statuses"):
                clean = [
                    v for v in st["statuses"]
                    if not _is_status_value_garbage(
                        v, _entity_name_set, _workflow_name_set,
                    )
                ]
                if clean:
                    return _titleize_keys(clean)
        # Priority 3 — global wf_statuses fallback. Filtered against garbage
        # (entity names, workflow names, section headers) so a poorly authored
        # workflow can't pollute unrelated dropdowns app-wide.
        wv = wf_statuses.get(nk)
        if wv:
            clean = [
                v for v in wv
                if not _is_status_value_garbage(
                    v, _entity_name_set, _workflow_name_set,
                )
            ]
            if clean:
                return _titleize_keys(clean)
        curated = curated_enum_options(name)
        return _titleize_keys(curated) if curated else None

    def _titleize_keys(vals) -> list[dict[str, str]]:
        return [{"value": str(v), "label": title_case_key(str(v))} for v in vals]

    converted = 0
    touched = 0
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json") or base.startswith(("login", "signup", "register")):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        if not _is_create_edit_form(schema, fp):
            continue
        ent_key = _entity_from_form_workflow(schema, entities) or _entity_key_for_file(fp, known)
        ent_name = next((n for n in entities if _ent_key(n) == ent_key), None)
        # This pass only ever converts NON-FK enum-ish text Inputs (FK columns are skipped
        # below via the `*id` guard), so the hidden set only needs to exclude system/actor/
        # tenancy names; role-based when the entity resolves, name-based default otherwise.
        hidden = hidden_fk_columns(ent_name, reg, output_dir) if ent_name else _DEFAULT_HIDDEN

        changed = False
        for node in _iter_nodes(schema):
            if node.get("type") != "Input":  # only convert plain text inputs; leave typed controls
                continue
            p = node.get("props")
            if not isinstance(p, dict) or not p.get("name"):
                continue
            if p.get("optionsFrom") or p.get("type") == "hidden":
                continue
            nk = _norm(p["name"])
            if nk in _SYSTEM or nk in hidden:
                continue
            if nk.endswith("id") and nk != "id":
                continue  # FK column — owned by repair_fk_dropdowns
            opts = _options_for(ent_key, p["name"], nk, ent_name)
            if not opts:
                continue
            # Convert in place: drop input-only props, keep name/label/validators/className.
            for k in ("type", "rows", "placeholder", "inputMode"):
                p.pop(k, None)
            node["type"] = "Select"
            p["options"] = opts
            converted += 1
            changed = True

        if changed:
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return {"converted": converted, "files": touched}


def scaffold_forms(output_dir: str) -> dict:
    """Add missing editable-column inputs to create/edit forms. Returns {added, files}."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"added": 0, "files": 0}

    # Slice-3 ledger contract: don't scaffold EDIT forms for append-only
    # entities. Create forms are still legitimate (the ledger accepts new
    # rows), so this filter only fires on `edit.json` / `/edit` routes.
    from services.ensure_edit_routes import _append_only_names
    _append_only = _append_only_names(output_dir)

    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    relations = reg.get("relations") or []
    reg_types = _registry_types(output_dir)
    seed_opts = harvest_seed_options(output_dir)
    status_idx = index_status_workflows(output_dir)
    known = set(reg_types) | set(seed_opts) | {_ent_key(k) for k in status_idx}

    # Spec D W2 — load the plan once so the per-field loop can check
    # ``plan_column_semantics.get_semantic`` / ``get_enum_values`` BEFORE
    # falling back to the name+type ``_decide`` classifier. When the plan
    # is silent (or missing), behaviour is unchanged.
    from services.plan_column_semantics import (
        get_enum_values as _plan_get_enum_values,
        get_semantic as _plan_get_semantic,
    )
    from services.plan_field_lookup import load_plan as _load_plan
    plan = _load_plan(output_dir)

    added = 0
    touched = 0
    # Recursive: create/edit forms live at NESTED paths (foo/new.json,
    # foo/[id]/edit.json), not just top-level — a top-level-only scan skips them.
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json") or base.startswith(("login", "signup", "register")):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        if not _is_create_edit_form(schema, fp):
            continue
        # Prefer the Form's Create/Update<Entity> workflow (unambiguous) to resolve
        # the entity; fall back to the file/dir name.
        ent_key = _entity_from_form_workflow(schema, entities) or _entity_key_for_file(fp, known)
        if not ent_key:
            continue
        # Real entity name (registry key) for this entity_key.
        ent_name = next((n for n in entities if _ent_key(n) == ent_key), None)
        if not ent_name:
            continue
        # Slice-3: skip edit forms for append-only entities. `/new` (create)
        # is still fine — a ledger accepts new rows, just not updates. We
        # detect edit forms by the filename convention (`edit.json`) or the
        # `/edit` suffix on the route.
        if _append_only and (ent_name in _append_only or ent_name.lower() in _append_only):
            _route = str(schema.get("route") or "")
            if base == "edit.json" or _route.endswith("/edit"):
                continue
        cols = (entities.get(ent_name) or {}).get("fields") or {}
        if not isinstance(cols, dict) or not cols:
            continue

        container = _find_form_container(schema)
        if container is None:
            continue

        covered = {
            _norm((n.get("props") or {}).get("name"))
            for n in _iter_nodes(schema)
            if n.get("type") in _FIELD_TYPES and (n.get("props") or {}).get("name")
        }
        col_types = reg_types.get(ent_key, {})
        opts = dict(seed_opts.get(ent_key, {}))
        st = status_idx.get(ent_key)
        if st and st.get("statuses"):
            opts.setdefault("status", list(st["statuses"]))

        existing_ds = {d.get("name") for d in (schema.get("dataSources") or []) if isinstance(d, dict)}
        # Actor/tenancy FKs (server-filled) are never scaffolded; a domain FK is NOT hidden
        # and IS scaffolded as a relational Select. Role-based via fk_semantics.
        hidden = hidden_fk_columns(ent_name, reg, output_dir)
        new_nodes: list[dict] = []
        for col, meta in cols.items():
            nk = _norm(col)
            if nk in _SYSTEM or nk in hidden or nk in covered:
                continue
            if isinstance(meta, dict) and meta.get("primaryKey"):
                continue

            # Relational FK → Select with optionsFrom (+ ensure the list dataSource).
            if nk.endswith("id") and nk != "id":
                target = _fk_target(ent_key, nk, relations, entities)
                if target:
                    ds_name = _plural(target)
                    if ds_name not in existing_ds:
                        schema.setdefault("dataSources", []).append(
                            {"name": ds_name, "entity": target, "op": "list"})
                        existing_ds.add(ds_name)
                    new_nodes.append({"type": "Select", "props": {
                        "name": col, "label": _label(re.sub(r"[iI]d$", "", col)) or target,
                        # Static fallback (schema requires >=1 option with a non-empty
                        # value); optionsFrom replaces it with real rows at render time.
                        "options": [{"value": "__none", "label": f"Select {target}…"}],
                        "optionsFrom": {"source": ds_name, "value": "id",
                                        "label": _label_field(target, entities)},
                    }})
                    continue
                # Unresolvable FK → skip (don't emit a broken dropdown).
                continue

            # Spec D W2 — plan-first: if the planner authored a semantic
            # blob for this column, its `control` (when it names one of
            # the valid _FIELD_TYPES) wins verbatim over the name-regex
            # classifier. Plan-authored enum_values union into the option
            # list too so a plan-declared Select gets its vocabulary.
            plan_ctrl = _plan_get_semantic(plan, ent_name, col)
            plan_enum = _plan_get_enum_values(plan, ent_name, col)
            merged_opts = opts.get(nk)
            if plan_enum:
                merged_opts = list(merged_opts or [])
                for v in plan_enum:
                    if v and v not in merged_opts:
                        merged_opts.append(v)
            if plan_ctrl and plan_ctrl in _FIELD_TYPES:
                target_type = plan_ctrl
                extra: dict[str, Any] = {}
                if target_type in ("Select", "Combobox") and merged_opts:
                    extra["options"] = [{"value": v, "label": v} for v in merged_opts]
            else:
                target_type, extra = _decide(col, col_types.get(nk, ""), merged_opts)
                target_type = target_type or "Input"
            props = {"name": col, "label": _label(col)}
            props.update(extra or {})
            new_nodes.append({"type": target_type, "props": props})

        if new_nodes:
            container.extend(new_nodes)
            added += len(new_nodes)
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)

    return {"added": added, "files": touched}


# --------------------------------------------------------------------------- #
# Slice A T4 — SUBMIT-AUTHORITY form scaffolder
# --------------------------------------------------------------------------- #

def scaffold_forms_from_workflow_inputs(output_dir: str) -> dict:
    """For every form page whose plan.submit.kind=workflow, add any
    workflow input with source.kind=form_field that the form doesn't
    already have. Runs alongside :func:`scaffold_forms` (entity-driven)
    — the two are complementary: entity-driven for data_api forms,
    workflow-driven for workflow forms.

    Reads plan.json to find the workflow declaration. When plan.json
    is missing or malformed, returns {added:0, files:0} — the existing
    entity-driven pass handles those cases.
    """
    import json as _json
    plan_path = os.path.join(output_dir, "src", "contracts", "plan.json")
    if not os.path.isfile(plan_path):
        return {"added": 0, "files": 0}
    try:
        plan = _json.loads(open(plan_path, encoding="utf-8").read())
    except Exception:
        return {"added": 0, "files": 0}

    from services.submit_authority import derive_form_fields_from_workflow

    added = 0
    renamed_total = 0
    files_touched = 0
    schemas_dir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(schemas_dir):
        return {"added": 0, "files": 0, "renamed": 0}

    for page in plan.get("pages") or []:
        if not isinstance(page, dict):
            continue
        submit = page.get("submit")
        if not isinstance(submit, dict) or submit.get("kind") != "workflow":
            continue
        target_wf = submit.get("target")
        if not target_wf:
            continue

        # Fields the workflow's form_field inputs declare.
        expected_fields = derive_form_fields_from_workflow(plan, target_wf)
        if not expected_fields:
            continue

        # Locate the page schema file by route.
        route = page.get("route") or ""
        schema_file = _find_schema_for_route(schemas_dir, route)
        if schema_file is None:
            continue

        try:
            with open(schema_file, encoding="utf-8") as fh:
                schema = _json.load(fh)
        except Exception:
            continue

        # Existing form field names.
        covered = {
            (n.get("props") or {}).get("name")
            for n in _iter_nodes(schema)
            if n.get("type") in _FIELD_TYPES and (n.get("props") or {}).get("name")
        }

        # Modern page schemas use `component` (not `type`) on nodes,
        # so re-collect fields + locate the Form container using
        # component-aware walkers before adding anything.
        covered = _sa_collect_field_names(schema)
        container = _sa_find_form_children(schema)
        if container is None:
            continue

        # RENAME step (structural name-alignment). For every form field
        # whose CANONICAL name matches a workflow input's canonical name
        # but the raw names differ, rewrite the form field's `props.name`
        # to the workflow input's name. This makes the downstream wiring
        # a trivial identity map — no field_map needed anywhere. Fuzzy
        # matching in orphan_wiring_pass becomes belt-and-braces.
        #
        # Skip a rename when the target name is ALREADY present on the
        # form (a rename would collide with an existing field). Skip
        # when the source canonical is used by multiple workflow inputs
        # (ambiguous — first canonical wins, deterministic).
        expected_by_canon: dict[str, str] = {}
        for f in expected_fields:
            fname = f.get("name")
            c = _sa_canonicalize_field_name(fname)
            if not c or c in expected_by_canon:
                continue
            expected_by_canon[c] = str(fname)
        rename_map: dict[str, str] = {}
        for existing in covered:
            c = _sa_canonicalize_field_name(existing)
            if not c:
                continue
            target = expected_by_canon.get(c)
            if not target or target == existing:
                continue
            if target in covered:
                continue  # collision — leave both fields as-is
            rename_map[existing] = target
        renamed_here = _sa_rename_field_names(schema, rename_map)
        if renamed_here:
            # Update covered so the ADD loop below doesn't re-emit the
            # newly-renamed field name.
            covered = _sa_collect_field_names(schema)

        added_here = 0
        for f in expected_fields:
            fname = f.get("name")
            if not fname or fname in covered:
                continue
            container.append({
                "component": _control_for_workflow_type(f.get("type") or "text"),
                "props": {
                    "name": fname,
                    "label": _label(fname),
                },
            })
            added_here += 1

        if added_here or renamed_here:
            with open(schema_file, "w", encoding="utf-8") as fh:
                _json.dump(schema, fh, indent=2)
            added += added_here
            renamed_total += renamed_here
            files_touched += 1

    return {"added": added, "files": files_touched, "renamed": renamed_total}


def _find_schema_for_route(schemas_dir: str, route: str) -> str | None:
    """Map ``/feedback/new`` → ``<dir>/feedback/new.json`` (or flat
    ``feedback__new.json`` in tests). Tolerates both layouts."""
    if not route or route == "/":
        return None
    parts = [p for p in route.strip("/").split("/") if p and not p.startswith("[")]
    if not parts:
        return None
    # Nested layout — feedback/new.json
    nested = os.path.join(schemas_dir, *parts) + ".json"
    if os.path.isfile(nested):
        return nested
    # Flat layout — feedback__new.json
    flat = os.path.join(schemas_dir, "__".join(parts) + ".json")
    if os.path.isfile(flat):
        return flat
    # Fallback — any file whose top segment matches
    for candidate in glob.glob(os.path.join(schemas_dir, "**", "*.json"), recursive=True):
        rel = os.path.relpath(candidate, schemas_dir).replace(os.sep, "__")
        if rel == "__".join(parts) + ".json":
            return candidate
    return None


def _control_for_workflow_type(t: str) -> str:
    """Cheap type→control mapping for workflow-input-driven fields.
    Downstream ``semantic_field_types`` will refine later. Only picks
    the safe defaults; anything unknown → Input."""
    t = (t or "").lower()
    if t in ("integer", "int", "number"):
        return "NumberInput"
    if t in ("text", "textarea"):
        return "Textarea"
    if t in ("date", "timestamp", "datetime"):
        return "DatePicker"
    if t in ("boolean", "bool"):
        return "Switch"
    return "Input"


_SA_FIELD_COMPONENTS = frozenset({
    "Input", "Textarea", "Select", "Checkbox", "Switch", "RadioGroup",
    "DatePicker", "TimePicker", "FileUpload", "NumberInput", "Slider",
    "Combobox", "MaskedInput", "Rating", "InputOTP", "ColorPicker",
    "RichTextEditor", "KeyValueInput", "Cascader", "Transfer", "Tree",
})


def _sa_canonicalize_field_name(name: object) -> str:
    """Fold ``firstName`` / ``first_name`` / ``first-name`` / ``FIRST_NAME``
    to the same key. Non-string / empty returns ``""``. Duplicated from
    orphan_wiring_pass._canonicalize_field_name so this module stays
    loose-coupled — same algorithm, single-line change if it ever needs
    to evolve."""
    if not isinstance(name, str) or not name:
        return ""
    return "".join(c.lower() for c in name if c.isalnum())


def _sa_rename_field_names(schema: dict, rename_map: dict[str, str]) -> int:
    """Rename every field component's ``props.name`` per ``rename_map``.
    Only touches ``props.name`` — label, required, default, and every
    other prop key is preserved. Returns the count of nodes renamed."""
    if not rename_map:
        return 0
    count = 0

    def walk(n):
        nonlocal count
        if isinstance(n, dict):
            c = n.get("component") or n.get("type") or ""
            if c in _SA_FIELD_COMPONENTS:
                props = n.get("props")
                if isinstance(props, dict):
                    cur = props.get("name")
                    if isinstance(cur, str) and cur in rename_map:
                        props["name"] = rename_map[cur]
                        count += 1
            for v in n.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(n, list):
            for i in n:
                walk(i)

    walk(schema)
    return count


def _sa_find_form_children(schema: dict):
    """Find the first Form component's `children` list (mutable).
    Modern page schemas key on ``component`` (not ``type``)."""
    def walk(n):
        if isinstance(n, dict):
            c = n.get("component") or n.get("type") or ""
            if c == "Form":
                ch = n.get("children")
                if isinstance(ch, list):
                    return ch
            for v in n.values():
                if isinstance(v, (dict, list)):
                    r = walk(v)
                    if r is not None:
                        return r
        elif isinstance(n, list):
            for i in n:
                r = walk(i)
                if r is not None:
                    return r
        return None
    return walk(schema)


def _sa_collect_field_names(schema: dict) -> set[str]:
    """Every named field-component under the schema, component-aware."""
    out: set[str] = set()

    def walk(n):
        if isinstance(n, dict):
            c = n.get("component") or n.get("type") or ""
            if c in _SA_FIELD_COMPONENTS:
                name = (n.get("props") or {}).get("name")
                if isinstance(name, str) and name:
                    out.add(name)
            for v in n.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(n, list):
            for i in n:
                walk(i)
    walk(schema)
    return out
