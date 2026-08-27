"""Align an LLM-generated create/edit form's field names to the entity's REAL columns
(from the registry), so submitted data maps to the database — and ensure every required
column actually has an input.

The page agent and the schema agent often disagree on field vocabulary: the form emits
`propertyName`/`streetAddress`/`postalCode`/`propertyType` while the table columns are
`name`/`address`/`zipCode`/`type`; or the form simply omits a required column (`units`).
Either way the workflow's db_insert reads `input.<column>`, gets undefined, and the insert
fails the NOT NULL constraint. This pass:
  1. renames form fields to real columns via exact, entity-prefix-stripped, and synonym
     matching;
  2. appends a basic input for any required (NOT NULL) column still missing, so the form
     can satisfy the insert.
"""
from __future__ import annotations

import re

from services.fk_semantics import hidden_fk_columns

_SYSTEM = {"id", "createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"}
# System timestamp columns that must never surface as an editable form field. The FK part
# of "hidden in forms" is now role-driven (actor/tenancy FKs, via fk_semantics) — a domain
# FK is NOT hidden. id is left out — an edit form may legitimately carry a hidden id.
_SYSTEM_TS = {"createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"}
_INPUT_TYPES = {
    "Input", "Select", "Textarea", "DatePicker", "Checkbox",
    "NumberInput", "Combobox", "RadioGroup", "Switch", "MaskedInput",
    "KeyValueInput", "FileUpload",
}

# normalized form-term -> normalized column concept
_SYN = {
    "streetaddress": "address", "addressline1": "address", "street": "address",
    "postalcode": "zipcode", "zip": "zipcode", "pincode": "zipcode",
    "fullname": "name", "title": "name", "label": "name",
    "phonenumber": "phone", "mobile": "phone", "contactnumber": "phone",
    "emailaddress": "email",
}


def _norm(s) -> str:
    return re.sub(r"[_\s-]", "", str(s or "").lower())


def _entity_columns(registry: dict, entity: str) -> dict:
    ents = registry.get("entities") or {}
    e = ents.get(entity) or ents.get((entity or "").lower()) or {}
    fields = e.get("fields") if isinstance(e, dict) else None
    cols: dict = {}
    if isinstance(fields, dict):
        cols = {k: (v if isinstance(v, dict) else {}) for k, v in fields.items()}
    elif isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict) and f.get("name"):
                cols[f["name"]] = f
    return cols


def _candidates(field_name: str, entity_norm: str):
    """Normalized names a form field might map to: itself, prefix-stripped, synonym."""
    n = _norm(field_name)
    yield n
    if entity_norm and n.startswith(entity_norm) and len(n) > len(entity_norm):
        yield n[len(entity_norm):]          # propertyName -> name, propertyType -> type
    if n in _SYN:
        yield _SYN[n]


def align_form_fields(schema: dict, entity: str | None, registry: dict) -> tuple[dict, dict]:
    """Rename form-field names to real columns + add inputs for missing required columns."""
    report = {"renamed": 0, "added": []}
    if not entity:
        return schema, report
    cols = _entity_columns(registry or {}, entity)
    if not cols:
        return schema, report

    # Role-based hidden FKs (actor/tenancy — server-filled); a domain FK is NOT hidden and
    # is treated like any other editable column. Falls back to the conservative name-based
    # default when the registry can't classify (fk_semantics.hidden_fk_columns).
    hidden = hidden_fk_columns(entity, registry or {})

    entity_norm = _norm(entity)
    norm_to_real: dict[str, str] = {}
    for name, meta in cols.items():
        nn = _norm(name)
        if nn in _SYSTEM:
            continue
        if isinstance(meta, dict) and meta.get("primaryKey"):
            continue
        norm_to_real[nn] = name

    covered: set[str] = set()           # real columns the form provides

    def walk(n, container=None):
        if isinstance(n, dict):
            if n.get("type") in _INPUT_TYPES:
                p = n.get("props")
                if isinstance(p, dict) and p.get("name"):
                    real = None
                    for cand in _candidates(p["name"], entity_norm):
                        if cand in norm_to_real:
                            real = norm_to_real[cand]
                            break
                    if real:
                        if real != p["name"]:
                            p["name"] = real
                            report["renamed"] += 1
                        covered.add(real)
            for v in n.values():
                walk(v, n)
        elif isinstance(n, list):
            for v in n:
                walk(v, n)

    root = schema.get("root") or schema
    walk(root)

    # Backfill: append an input for EVERY editable column the form still doesn't cover —
    # not just NOT-NULL ones. The planner routinely marks columns nullable, so a
    # required-only backfill left a partially-authored LLM form partial. Editable = all
    # columns minus PK / system timestamps / hidden actor-tenancy FKs (the SAME authority
    # the deterministic builder uses via `_editable_columns`); each missing control is
    # built through `deterministic_pages._input_for`, so FK→Select, jsonb→KeyValueInput,
    # file→FileUpload and the required-marker (only where notNull) all match the builder.
    # Idempotent — a column already present (post-rename) is in `covered` and skipped.
    from services.deterministic_pages import _editable_columns, _input_for as _det_input_for
    entities = (registry or {}).get("entities") or {}
    missing = [(name, meta) for name, meta in _editable_columns(cols, hidden)
               if name not in covered]
    if missing:
        form = _find_form_field_container(root)
        if form is not None:
            for col, meta in missing:
                form.append(_det_input_for(col, meta, entities, hidden))
                report["added"].append(col)

    # Strip server-managed columns (actor/tenancy FKs, timestamps) that the LLM
    # or a prior pass may have surfaced as editable fields — e.g. a "Workspace"
    # select with no options that makes the form unsubmittable. These are set
    # server-side, never by the user. A DOMAIN FK is not in `hidden`, so it stays.
    report["stripped"] = _strip_hidden_form_fields(root, hidden | _SYSTEM_TS)

    return schema, report


def _strip_hidden_form_fields(root, hidden_names: set[str]) -> int:
    """Remove hidden (actor/tenancy FK + system-timestamp) columns from every Form's
    declarative `fields` prop AND from bare input-node children, in place. `hidden_names`
    is the pre-normalized set. Returns the count removed."""
    removed = 0

    def hidden(name) -> bool:
        return _norm(name) in hidden_names

    def walk(node):
        nonlocal removed
        if isinstance(node, dict):
            if node.get("type") == "Form":
                p = node.get("props")
                if isinstance(p, dict) and isinstance(p.get("fields"), list):
                    kept = [f for f in p["fields"]
                            if not (isinstance(f, dict) and hidden(f.get("name", "")))]
                    removed += len(p["fields"]) - len(kept)
                    p["fields"] = kept
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            keep = []
            for item in node:
                if (isinstance(item, dict) and item.get("type") in _INPUT_TYPES
                        and hidden((item.get("props") or {}).get("name", ""))):
                    removed += 1
                    continue
                keep.append(item)
            node[:] = keep
            for item in node:
                walk(item)

    walk(root)
    return removed


def _find_form_field_container(node) -> list | None:
    """The children list of the deepest single Stack inside the first Form — where the
    declarative inputs live. Falls back to the Form's own children."""
    found = {"form": None}

    def find_form(n):
        if found["form"] is not None:
            return
        if isinstance(n, dict):
            if n.get("type") == "Form":
                found["form"] = n
                return
            for v in n.values():
                find_form(v)
        elif isinstance(n, list):
            for v in n:
                find_form(v)

    find_form(node)
    form = found["form"]
    if not isinstance(form, dict):
        return None
    children = form.get("children")
    if not isinstance(children, list):
        form["children"] = children = []
    # Prefer an inner Stack of inputs if present.
    for c in children:
        if isinstance(c, dict) and c.get("type") in ("Stack", "Grid") and isinstance(c.get("children"), list):
            return c["children"]
    return children
