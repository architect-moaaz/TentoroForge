"""Point every FK dropdown at the entity the schema ACTUALLY references.

The page/form agents (and the earlier name-guessing FK guards) derive a FK
dropdown's source from the column NAME: ``vetId`` → ``vets``, ``administeredById``
→ ``administered-bys``. That is wrong whenever the FK column name differs from the
target entity name — ``vetId`` and ``administeredById`` both reference **Staff** in
the vet app, so the dropdowns pointed at non-existent ``vets``/``pets`` sources (or
were left as free-text Inputs that feed ``"M"`` into a uuid column → the insert
crash).

The GROUND TRUTH lives in the emitted Drizzle schema — ``.references(() =>
staff.id)`` on the column — so this guard reads it (via
``registry_schema_reconcile.extract_fk_references``, the same parser that fills the
registry's FK links) and, for every FK column on a page's entity:

* rewrites an existing ``Select``/``Combobox``/``MultiSelect`` ``optionsFrom.source``
  to the REAL target slug (preserving ``value``/``label``); and
* promotes a uuid FK column the LLM rendered as a plain ``Input`` into a ``Select``
  bound to that target (so a real row id is submitted, never free text).

It always upserts a matching ``dataSources`` entry so the source resolves (and so
the later ``schema_references`` pass sees a real entity and leaves it alone).
Additive + idempotent; never raises.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re

from services.registry_schema_reconcile import (
    _norm_ident,
    extract_fk_references,
    pair_fk_columns_to_relationships,
)
from services.semantic_field_types import (
    _entity_from_form_workflow,
    _entity_key_for_file,
    _iter_nodes,
)
from services.workflow_action_mapper import _ent_key

log = logging.getLogger(__name__)

_LABEL_FIELDS = ("fullname", "name", "title", "label", "displayname", "email",
                 "code", "number", "sku", "reference")
_FK_INPUT_TYPES = {"Input", "NumberInput", "Textarea", "MaskedInput"}
_SELECT_TYPES = {"Select", "Combobox", "MultiSelect"}
_SYSTEM = {"id", "createdat", "updatedat", "deletedat", "createdby", "updatedby"}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _load_registry(output_dir: str) -> dict:
    """The canonical resource registry (preferred, carries slug + FK links); fall
    back to the extracted registry.json. Returns {} when neither is present."""
    for rel in ("contracts/resource-registry.json", "registry.json"):
        path = os.path.join(output_dir, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("entities"), dict):
            return data
    return {}


def _entity_field_names(entity: dict) -> list[str]:
    """Column names for an entity in either registry shape (canonical ``columns``
    list of dicts, or extracted ``fields`` dict)."""
    cols = entity.get("columns")
    if isinstance(cols, list):
        return [c.get("name") for c in cols if isinstance(c, dict) and c.get("name")]
    fields = entity.get("fields")
    if isinstance(fields, dict):
        return list(fields.keys())
    return []


def _label_field(entity: dict) -> str:
    norm_cols = {_norm(n): n for n in _entity_field_names(entity)}
    for cand in _LABEL_FIELDS:
        if cand in norm_cols:
            return norm_cols[cand]
    return "id"


def _build_ground_truth(output_dir: str, registry: dict) -> tuple[dict, dict]:
    """From the schema `.references()` map build:

    * ``fk_by_ent``: ``{owner_ent_key: {norm_col: {col, source, label, entity}}}``
      — the real target slug/label/entity-name for each FK column of an entity.
    * ``ident_to_ent``: ``{_ent_key(anything): entity_dict}`` for page-entity lookup.
    """
    entities = registry.get("entities") or {}

    # every identifier (name/table/slug/id/camel) → entity dict + its slug
    ident_to_ent: dict[str, dict] = {}
    for name, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        for key in (name, entity.get("name"), entity.get("table"),
                    entity.get("slug"), entity.get("id"), entity.get("camel")):
            if key:
                ident_to_ent.setdefault(_ent_key(key), entity)
                ident_to_ent.setdefault(_norm_ident(key), entity)

    def _resolve(ident: str) -> dict | None:
        return ident_to_ent.get(_ent_key(ident)) or ident_to_ent.get(_norm_ident(ident))

    fk_by_ent: dict[str, dict] = {}
    for owning_table, cols in extract_fk_references(output_dir).items():
        owner = _resolve(owning_table)
        if not owner:
            continue
        owner_key = _ent_key(owner.get("id") or owner.get("name") or owning_table)
        bucket = fk_by_ent.setdefault(owner_key, {})
        for col_name, target_table in cols.items():
            target = _resolve(target_table)
            if not target:
                continue
            slug = target.get("slug") or target.get("id") or _norm(target_table)
            bucket[_norm(col_name)] = {
                "col": col_name,
                "source": slug,
                "label": _label_field(target),
                "entity": target.get("name") or target.get("id") or slug,
            }

    # FALLBACK — when the schema carried no `.references()` for an FK column,
    # the registry's ALREADY-RESOLVED FK links. `reconcile_registry_to_schema`
    # populates `entity.fks` / `column.fk` from BOTH schema `.references()` AND the
    # relationship pairing, and runs earlier in the pipeline — so by the time this
    # guard runs the link is usually already on the registry. Read it directly (the
    # fresh pairing below would SKIP an already-resolved column, missing it otherwise).
    for name, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        owner_key = _ent_key(entity.get("id") or entity.get("name") or name)
        bucket = fk_by_ent.setdefault(owner_key, {})
        resolved: list[tuple[str, str]] = []
        for fk in (entity.get("fks") or []):
            if isinstance(fk, dict) and fk.get("column") and fk.get("targetEntityId"):
                resolved.append((fk["column"], fk["targetEntityId"]))
        for c in (entity.get("columns") or []):
            if isinstance(c, dict) and c.get("name") and c.get("fk"):
                resolved.append((c["name"], c["fk"]))
        for col_name, target_id in resolved:
            nk = _norm(col_name)
            if nk in bucket:
                continue  # schema `.references()` (added above) is authoritative
            target = _resolve(target_id)
            if not target:
                continue
            slug = target.get("slug") or target.get("id") or _norm(target_id)
            bucket[nk] = {
                "col": col_name,
                "source": slug,
                "label": _label_field(target),
                "entity": target.get("name") or target.get("id") or slug,
            }

    # pair the entity's FK-shaped columns to its registry relationships (name +
    # elimination). Schema-derived targets above always win (we never overwrite
    # a norm_col already in the bucket).
    for name, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        paired = pair_fk_columns_to_relationships(entity, registry)
        if not paired:
            continue
        owner_key = _ent_key(entity.get("id") or entity.get("name") or name)
        bucket = fk_by_ent.setdefault(owner_key, {})
        for col_name, target_id in paired.items():
            nk = _norm(col_name)
            if nk in bucket:
                continue  # schema `.references()` is authoritative
            target = _resolve(target_id)
            if not target:
                continue
            slug = target.get("slug") or target.get("id") or _norm(target_id)
            bucket[nk] = {
                "col": col_name,
                "source": slug,
                "label": _label_field(target),
                "entity": target.get("name") or target.get("id") or slug,
            }
    return fk_by_ent, ident_to_ent


def _page_entity_key(schema: dict, path: str, known_keys: set[str]) -> str | None:
    """The entity a form/page is about — from its Create/Update<Entity> workflow
    (unambiguous) first, then its filename/parent dir."""
    return (_entity_from_form_workflow(schema, known_keys)
            or _entity_key_for_file(path, known_keys))


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


def _upsert_data_source(schema: dict, source: str, entity_name: str) -> None:
    """Ensure a `dataSources` entry named `source` for `entity_name` exists, so the
    dropdown's optionsFrom resolves (and schema_references keeps it)."""
    ds = schema.get("dataSources")
    if not isinstance(ds, list):
        ds = []
        schema["dataSources"] = ds
    for d in ds:
        if isinstance(d, dict) and d.get("name") == source:
            d.setdefault("entity", entity_name)
            d.setdefault("op", "list")
            return
    ds.append({"name": source, "entity": entity_name, "op": "list"})


def reconcile_fk_sources(output_dir: str) -> dict:
    """Point every FK dropdown at the schema's REAL referenced entity.

    Returns ``{"fixed": int, "promoted": int, "files": int}`` — sources rewritten,
    Inputs promoted to Selects, files touched. Never raises.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"fixed": 0, "promoted": 0, "files": 0}

    registry = _load_registry(output_dir)
    fk_by_ent, ident_to_ent = _build_ground_truth(output_dir, registry)
    if not fk_by_ent:
        return {"fixed": 0, "promoted": 0, "files": 0}
    known_keys = set(ident_to_ent)

    fixed = 0
    promoted = 0
    files = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json", "registry.json", "load.json"):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(schema, dict):
            continue

        page_key = _page_entity_key(schema, fp, known_keys)
        fk_cols = fk_by_ent.get(page_key or "")
        if not fk_cols:
            continue
        is_form = _is_create_edit_form(schema, fp)
        changed = False

        for node in _iter_nodes(schema):
            ntype = node.get("type")
            p = node.get("props")
            if not isinstance(p, dict) or not p.get("name"):
                continue
            nk = _norm(p["name"])
            if nk in _SYSTEM:
                continue
            gt = fk_cols.get(nk)
            if not gt:
                continue  # not an FK column of this entity — leave untouched

            # (A) existing FK dropdown → point source at the REAL target slug.
            if ntype in _SELECT_TYPES:
                of = p.get("optionsFrom")
                if not isinstance(of, dict):
                    of = {}
                if of.get("source") == gt["source"]:
                    continue  # already correct — idempotent
                of["source"] = gt["source"]
                of.setdefault("value", "id")
                of.setdefault("label", gt["label"])
                p["optionsFrom"] = of
                _upsert_data_source(schema, gt["source"], gt["entity"])
                fixed += 1
                changed = True
                continue

            # (B) uuid FK rendered as a plain Input → promote to a Select so a real
            #     row id is submitted (free text into a uuid column crashes insert).
            if is_form and ntype in _FK_INPUT_TYPES and p.get("type") != "hidden":
                for k in ("type", "rows", "placeholder", "inputMode"):
                    p.pop(k, None)
                node["type"] = "Select"
                p["options"] = [{"value": "__none", "label": f"Select {gt['entity']}…"}]
                p["optionsFrom"] = {"source": gt["source"], "value": "id", "label": gt["label"]}
                _upsert_data_source(schema, gt["source"], gt["entity"])
                promoted += 1
                changed = True

        if changed:
            files += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)

    return {"fixed": fixed, "promoted": promoted, "files": files}
