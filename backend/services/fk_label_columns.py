"""Show FK columns as the referenced record's label, not a raw UUID.

A table column bound to an FK id (`memberId`) renders the UUID, because the list
row only carries the id. This pass has two coordinated halves:

  1. Emit `src/lib/fk-labels.json` — for every entity, which FK columns point at
     which target entity + label field. The data-engine reads it and attaches a
     companion `<fkProp>Label` ("Alice Johnson") to each list row.
  2. Rewrite Table / DataGrid columns whose key is an FK column → `<fkProp>Label`,
     so the column DISPLAYS the name while the real id stays in the row for actions.

Deterministic + idempotent: derived entirely from `registry.json` (relations +
label fields); a column already pointing at `…Label` is left alone.
"""
from __future__ import annotations

import glob
import json
import os
import re

from services.form_scaffold import (
    _ent_key, _fk_target, _iter_nodes, _label_field, _load_registry, _plural,
)
from services.semantic_field_types import _norm

_TABLE_TYPES = {"Table", "DataGrid", "DataTable"}
_COL_KEYS = ("key", "field", "dataKey", "accessor")


def _fk_map(entities: dict, relations: list) -> dict[str, dict[str, dict]]:
    """{entity_key -> {fkProp -> {targetEntity, labelField}}} for every FK column."""
    out: dict[str, dict[str, dict]] = {}
    for name, ent in entities.items():
        fields = (ent or {}).get("fields") or {}
        if not isinstance(fields, dict):
            continue
        ekey = _ent_key(name)
        cols: dict[str, dict] = {}
        for col in fields:
            nk = _norm(col)
            if not (nk.endswith("id") and nk != "id"):
                continue
            target = _fk_target(ekey, nk, relations, entities)
            if not target:
                continue
            cols[col] = {"targetEntity": target, "labelField": _label_field(target, entities)}
        if cols:
            out[ekey] = cols
    return out


def _aliases(entity_name: str) -> list[str]:
    """Every identifier the /api/data route might pass for this entity, lowercased."""
    low = entity_name.lower()
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", entity_name).lower()
    plural = _plural(entity_name).lower()
    return list(dict.fromkeys([low, plural, kebab, kebab + "s"]))


def emit_fk_labels_json(output_dir: str, entities: dict, relations: list) -> int:
    """Write src/lib/fk-labels.json keyed by every route alias. Returns #entities."""
    fk_by_key = _fk_map(entities, relations)
    doc: dict[str, dict] = {}
    for name in entities:
        cols = fk_by_key.get(_ent_key(name))
        if not cols:
            continue
        for alias in _aliases(name):
            doc[alias] = cols
    libdir = os.path.join(output_dir, "src", "lib")
    os.makedirs(libdir, exist_ok=True)
    with open(os.path.join(libdir, "fk-labels.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return len(fk_by_key)


def _list_entity_key(schema: dict, known: set[str]) -> str | None:
    for d in (schema.get("dataSources") or []):
        if isinstance(d, dict) and d.get("op") in ("list", None) and d.get("entity"):
            k = _ent_key(d["entity"])
            if k in known:
                return k
    return None


def relabel_fk_columns(output_dir: str) -> dict:
    """Emit fk-labels.json + point FK table columns at their `<fkProp>Label`.
    Returns {relabeled, entities, files}."""
    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    relations = reg.get("relations") or []
    if not entities:
        return {"relabeled": 0, "entities": 0, "files": 0}

    n_ent = emit_fk_labels_json(output_dir, entities, relations)
    fk_by_key = _fk_map(entities, relations)
    known = set(fk_by_key)

    sdir = os.path.join(output_dir, "src", "schemas")
    relabeled = touched = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
        if os.path.basename(fp) in ("shell.json", "nav-flow.json"):
            continue
        try:
            schema = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        ekey = _list_entity_key(schema, known)
        cols_map = fk_by_key.get(ekey or "", {})
        if not cols_map:
            continue
        fk_props = {_norm(c) for c in cols_map}
        changed = False
        for node in _iter_nodes(schema):
            if node.get("type") not in _TABLE_TYPES:
                continue
            for col in ((node.get("props") or {}).get("columns") or []):
                if not isinstance(col, dict):
                    continue
                for ck in _COL_KEYS:
                    v = col.get(ck)
                    if isinstance(v, str) and _norm(v) in fk_props and not v.endswith("Label"):
                        col[ck] = f"{v}Label"
                        relabeled += 1
                        changed = True
                        break
        if changed:
            touched += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)

    return {"relabeled": relabeled, "entities": n_ent, "files": touched}
