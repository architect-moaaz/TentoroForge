"""Reconcile the CANONICAL resource registry to the REAL emitted schema.

``contracts/resource-registry.json`` (the canonical registry the page-schema
agent binds against, via ``resource_registry_context``) is built from the RAW
plan *before* schema generation. Its per-column ``notNull`` comes from the
plan's ``nullable`` and its ``enum`` from the plan's ``enum_values`` — neither
reliably emitted by the planner, so both drift from the schema the app actually
ships. Meanwhile ``registry.json`` is corrected against the real Drizzle files
by ``registry.reconcile_entities``. The two diverge: the page agent sees wrong
required-flags + no enums while the form guards see the correct ones.

``reconcile_registry_to_schema(output_dir)`` closes that gap: it re-reads the
GROUND-TRUTH entities from the emitted schema (the same accurate reader
``reconcile_entities`` uses — ``extract_entities_from_schema``) and overwrites
each canonical column's ``type`` / ``notNull`` / ``enum`` / ``primaryKey`` from
it, adds schema-only columns, and preserves registry-owned naming metadata.
Runs after schema-gen, before the page/schema agents. Never raises; idempotent.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from services.registry import _entity_names_match
from services.registry_extractor import (
    _TABLE_START_RE,
    _extract_brace_block,
    _iter_columns,
    extract_entities_from_schema,
)

log = logging.getLogger(__name__)

_NOOP = {"entities_reconciled": 0, "columns_updated": 0}

# ---------------------------------------------------------------------------
# FK-target capture from the REAL schema `.references()` / `foreignKey()`
# ---------------------------------------------------------------------------

# Inline column FK:  .references(() => staff.id)  /  .references(() => staff.id, {…})
_REF_INLINE_RE = re.compile(r"\.references\(\s*\(\s*\)\s*=>\s*(\w+)\s*\.\s*\w+")

# Composite-form FK inside the `(table) => [ … ]` block:
#   foreignKey({ columns: [table.customerId], foreignColumns: [customers.id] })
_FK_BLOCK_RE = re.compile(
    r"foreignKey\(\s*\{"
    r"[^{}]*?columns:\s*\[\s*table\.(\w+)\s*\]"
    r"[^{}]*?foreignColumns:\s*\[\s*(\w+)\s*\.\s*\w+\s*\]"
    r"[^{}]*?\}",
    re.DOTALL,
)


def _norm_ident(s) -> str:
    """Lowercase, alphanumerics-only, trailing-plural-insensitive key for matching a
    pgTable const / table string / entity table+slug+id (staff/Staff/staffs → staff,
    recruitment_drives/recruitmentDrives → recruitmentdrive)."""
    base = re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    if base.endswith("ies") and len(base) > 3:
        return base[:-3] + "y"
    if base.endswith("es") and len(base) > 3:
        return base[:-2]
    if base.endswith("s") and len(base) > 1:
        return base[:-1]
    return base


def extract_fk_references(output_dir: str) -> dict:
    """Parse the REAL emitted Drizzle schema and return the ground-truth FK map.

    Reads ``<output_dir>/src/db/schema/*.ts`` and captures every FK column →
    target table, from BOTH forms the builders emit:

    * inline ``vetId: uuid("vet_id").references(() => staff.id)``
    * composite ``foreignKey({columns:[table.customerId],
      foreignColumns:[customers.id]})`` inside the ``(table) => [ … ]`` block.

    The reference target (``staff`` / ``customers``) is the referenced pgTable
    *const*; we resolve it to that table's declared name via the const→table map
    built across all files. Returns ``{owning_table: {fkColumnCamel: target_table}}``
    (both table strings as declared in ``pgTable("…")``). Never raises; ``{}`` when
    the schema dir is absent.
    """
    schema_dir = Path(output_dir) / "src" / "db" / "schema"
    if not schema_dir.is_dir():
        return {}

    files: list[tuple[str, str]] = []  # (filename, content)
    const_to_table: dict[str, str] = {}
    for ts_file in sorted(schema_dir.glob("*.ts")):
        try:
            content = ts_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append((ts_file.name, content))
        for m in _TABLE_START_RE.finditer(content):
            const_to_table[m.group(1)] = m.group(2)

    def _target(const: str) -> str:
        return const_to_table.get(const, const)

    fk_map: dict[str, dict[str, str]] = {}
    for _name, content in files:
        # Positions of each pgTable declaration so a foreignKey() block can be
        # attributed to the table whose `(table) => […]` it lives in.
        starts = [(m.start(), m.group(1), m.group(2), m.end()) for m in _TABLE_START_RE.finditer(content)]
        for idx, (start, _var, table_name, cols_open) in enumerate(starts):
            region_end = starts[idx + 1][0] if idx + 1 < len(starts) else len(content)
            region = content[start:region_end]
            cols = fk_map.setdefault(table_name, {})

            # inline `.references()` on each column
            block = _extract_brace_block(content, cols_open)
            for fname, _type_fn, chain in _iter_columns(block):
                rm = _REF_INLINE_RE.search(chain)
                if rm:
                    cols[fname] = _target(rm.group(1))

            # composite foreignKey() blocks belonging to THIS table's region
            for fm in _FK_BLOCK_RE.finditer(region):
                cols[fm.group(1)] = _target(fm.group(2))

    # Drop tables with no FKs so callers can treat presence as "has an FK".
    return {t: cols for t, cols in fk_map.items() if cols}


def pair_fk_columns_to_relationships(entity: dict, registry: dict) -> dict:
    """Pair an entity's FK-shaped columns to its registry relationships.

    A SECOND source of FK truth for when the emitted schema carries no
    ``.references()`` on the column (the planner named the relationship
    ``appointment → staff`` but never said which column is the FK, so
    ``schema_builder`` emitted ``vetId`` as a plain uuid). The canonical
    registry's ``relationships[]`` still carries the ``{from, to}`` pairing,
    and the entity has FK-shaped columns — this deterministically pairs them.

    Returns ``{fkColumn: target_entity_id}`` for the columns it can resolve.

    * Candidate FK columns = the entity's uuid columns whose name ends in
      ``Id`` (not bare ``id``) and that DON'T already have a resolved ``fk``.
    * Candidate targets = ``relationships[]`` with ``from == this entity id``
      (their ``to`` = target entity id), minus any target already claimed by a
      resolved column.
    * Pass 1 — strong name match: strip the trailing ``Id`` and compare
      singular/plural-insensitively to the target entity's id/name/slug/camel
      (``petId`` ↔ ``pet``, ``ownerId`` ↔ ``owner``).
    * Pass 2 — elimination: only when EXACTLY one FK column AND exactly one
      relationship target remain unmatched, pair them (``vetId`` ↔ ``staff``).
      2+ ambiguous leftovers are left unresolved — never a guess/mis-pair.

    Deterministic; never raises.
    """
    if not isinstance(entity, dict) or not isinstance(registry, dict):
        return {}
    entity_id = entity.get("id")
    if not entity_id:
        return {}

    entities = registry.get("entities")
    entities = entities if isinstance(entities, dict) else {}
    relationships = registry.get("relationships")
    relationships = relationships if isinstance(relationships, list) else []
    columns = entity.get("columns")
    columns = columns if isinstance(columns, list) else []

    id_to_ent: dict[str, dict] = {}
    for ent in entities.values():
        if isinstance(ent, dict) and ent.get("id"):
            id_to_ent.setdefault(ent["id"], ent)

    # Candidate FK columns: uuid, name ends in "Id" (not bare "id"), fk unresolved.
    fk_cols: list[str] = []
    resolved_targets: set = set()
    for col in columns:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if not isinstance(name, str) or not name:
            continue
        if col.get("fk"):
            resolved_targets.add(col.get("fk"))
            continue
        low = name.lower()
        if low == "id" or not low.endswith("id"):
            continue
        if str(col.get("type", "")).lower() != "uuid":
            continue
        fk_cols.append(name)

    # Candidate targets: relationships from this entity, minus already-claimed.
    targets: list[str] = []
    seen: set = set()
    for rel in relationships:
        if not isinstance(rel, dict) or rel.get("from") != entity_id:
            continue
        to = rel.get("to")
        if not to or to in resolved_targets or to in seen:
            continue
        seen.add(to)
        targets.append(to)

    result: dict[str, str] = {}
    claimed: set = set()

    # Pass 1 — strong name match (stem == target id/name/slug/camel).
    remaining_cols: list[str] = []
    for col in fk_cols:
        stem = _norm_ident(col[:-2])  # strip trailing "Id"
        matched = None
        for tgt in targets:
            if tgt in claimed:
                continue
            tent = id_to_ent.get(tgt) or {}
            keys = (tgt, tent.get("id"), tent.get("name"), tent.get("slug"),
                    tent.get("camel"), tent.get("table"))
            if any(k and _norm_ident(k) == stem for k in keys):
                matched = tgt
                break
        if matched:
            result[col] = matched
            claimed.add(matched)
        else:
            remaining_cols.append(col)

    # Pass 2 — elimination: exactly one unmatched column AND one unmatched target.
    unmatched_targets = [t for t in targets if t not in claimed]
    if len(remaining_cols) == 1 and len(unmatched_targets) == 1:
        result[remaining_cols[0]] = unmatched_targets[0]

    return result


def _apply_relationship_pairing(registry: dict) -> int:
    """Fold relationship-based FK pairings onto the canonical registry for the
    columns the schema `.references()` capture left unresolved. Same mutations as
    ``_apply_fk_targets`` (``column.fk`` / ``entity.fks`` / ``relationships.fkColumn``);
    returns the number of links applied. ``pair_fk_columns_to_relationships`` skips
    columns that already carry an ``fk``, so schema-derived targets always win."""
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return 0
    relationships = registry.get("relationships")
    relationships = relationships if isinstance(relationships, list) else []

    applied = 0
    for entity in entities.values():
        if not isinstance(entity, dict):
            continue
        paired = pair_fk_columns_to_relationships(entity, registry)
        if not paired:
            continue
        owner_id = entity.get("id")
        columns = entity.get("columns")
        columns = columns if isinstance(columns, list) else []
        by_name = {c.get("name"): c for c in columns if isinstance(c, dict)}
        fks = entity.get("fks")
        if not isinstance(fks, list):
            fks = []
            entity["fks"] = fks
        fk_by_col = {f.get("column"): f for f in fks if isinstance(f, dict)}

        for col_name, target_id in paired.items():
            col = by_name.get(col_name)
            if isinstance(col, dict) and not col.get("fk"):
                col["fk"] = target_id
                applied += 1
            if col_name not in fk_by_col:
                fks.append({"column": col_name, "targetEntityId": target_id})
                fk_by_col[col_name] = fks[-1]
            for rel in relationships:
                if (isinstance(rel, dict) and rel.get("from") == owner_id
                        and rel.get("to") == target_id and not rel.get("fkColumn")):
                    rel["fkColumn"] = col_name
                    break
    return applied


def _entity_index_by_ident(entities: dict) -> dict:
    """Map every normalized identifier (table/slug/id/camel/name) → entity id, so a
    schema table string resolves to the canonical registry entity id."""
    out: dict[str, str] = {}
    for entity in entities.values():
        if not isinstance(entity, dict):
            continue
        eid = entity.get("id")
        if not eid:
            continue
        for key in ("table", "slug", "id", "camel", "name"):
            v = entity.get(key)
            if v:
                out.setdefault(_norm_ident(v), eid)
    return out


def _apply_fk_targets(registry: dict, fk_refs: dict) -> int:
    """Fold the schema's FK ground truth onto the canonical registry:
    set each FK column's ``fk`` to the target entity id, populate the owning
    entity's ``fks`` list, and fill in matching ``relationships[].fkColumn``.
    Mutates ``registry`` in place; returns the number of FK links applied."""
    entities = registry.get("entities")
    if not isinstance(entities, dict) or not fk_refs:
        return 0
    ident_to_id = _entity_index_by_ident(entities)

    # owning table string → owning entity dict
    owner_by_ident: dict[str, dict] = {}
    for entity in entities.values():
        if not isinstance(entity, dict):
            continue
        for key in ("table", "slug", "id", "camel", "name"):
            v = entity.get(key)
            if v:
                owner_by_ident.setdefault(_norm_ident(v), entity)

    relationships = registry.get("relationships")
    relationships = relationships if isinstance(relationships, list) else []

    applied = 0
    for owning_table, cols in fk_refs.items():
        entity = owner_by_ident.get(_norm_ident(owning_table))
        if not entity:
            continue
        owner_id = entity.get("id")
        columns = entity.get("columns")
        columns = columns if isinstance(columns, list) else []
        by_name = {c.get("name"): c for c in columns if isinstance(c, dict)}
        fks = entity.get("fks")
        if not isinstance(fks, list):
            fks = []
            entity["fks"] = fks
        fk_by_col = {f.get("column"): f for f in fks if isinstance(f, dict)}

        for col_name, target_table in cols.items():
            target_id = ident_to_id.get(_norm_ident(target_table))
            if not target_id:
                continue
            col = by_name.get(col_name)
            if isinstance(col, dict) and col.get("fk") != target_id:
                col["fk"] = target_id
                applied += 1
            existing = fk_by_col.get(col_name)
            if existing is None:
                fks.append({"column": col_name, "targetEntityId": target_id})
                fk_by_col[col_name] = fks[-1]
            elif existing.get("targetEntityId") != target_id:
                existing["targetEntityId"] = target_id
            # fill the matching relationship's fkColumn (from owner → target)
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                if rel.get("from") == owner_id and rel.get("to") == target_id and not rel.get("fkColumn"):
                    rel["fkColumn"] = col_name
                    break
    return applied


def _registry_path(output_dir: str) -> str:
    return os.path.join(output_dir, "contracts", "resource-registry.json")


def _load_registry(output_dir: str) -> dict | None:
    """Load the canonical registry; return None if absent or unparseable."""
    path = _registry_path(output_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _extracted_column(field_name: str, extracted_field: dict) -> dict:
    """Translate an extractor field dict into the canonical column shape.

    Extractor shape (from ``extract_entities_from_schema``):
        {type, primaryKey, nullable, unique?, hasDefault?, enum_values?}
    Canonical column shape:
        {name, type, notNull, fk, enum, primaryKey?}

    The extractor reads the real schema, so it is authoritative for
    ``type`` / ``notNull`` (``nullable:false`` → ``notNull:true``) /
    ``primaryKey``. It carries enum values only when the schema declares them
    (a ``.$type<"a" | "b">()`` hint) — absence means "schema says nothing",
    not "no enum", so the caller preserves any existing canonical enum.
    """
    col: dict = {
        "name": field_name,
        "type": extracted_field.get("type", "varchar"),
        "notNull": not bool(extracted_field.get("nullable", True)),
    }
    ev = extracted_field.get("enum_values")
    if isinstance(ev, list) and ev:
        col["enum"] = list(ev)
    if extracted_field.get("primaryKey"):
        col["primaryKey"] = True
    return col


def _reconcile_entity(canonical: dict, extracted_fields: dict) -> int:
    """Overwrite/extend ``canonical`` entity columns from ``extracted_fields``.

    Returns the number of columns changed (updated or added). ``canonical`` is
    mutated in place. Registry-owned metadata (``id``/``name``/``table``/
    ``slug``/``camel``/``schemaFile``/``fks`` and each column's ``fk``, which
    the extractor does not know) is preserved.
    """
    columns = canonical.get("columns")
    if not isinstance(columns, list):
        columns = []
        canonical["columns"] = columns

    by_name = {c.get("name"): c for c in columns if isinstance(c, dict)}
    changed = 0

    for fname, finfo in extracted_fields.items():
        if not isinstance(finfo, dict):
            continue
        truth = _extracted_column(fname, finfo)
        existing = by_name.get(fname)
        if existing is None:
            # schema-only column → add it (fk unknown from schema).
            truth.setdefault("fk", None)
            truth.setdefault("enum", None)
            columns.append(truth)
            by_name[fname] = truth
            changed += 1
            continue

        col_changed = False
        # type / notNull / primaryKey: extractor (real schema) always wins.
        for key in ("type", "notNull"):
            if existing.get(key) != truth[key]:
                existing[key] = truth[key]
                col_changed = True
        if "primaryKey" in truth and existing.get("primaryKey") != truth["primaryKey"]:
            existing["primaryKey"] = truth["primaryKey"]
            col_changed = True
        # enum: overwrite ONLY when the schema actually declares values;
        # otherwise keep the canonical enum (schema is silent, not empty).
        if "enum" in truth and existing.get("enum") != truth["enum"]:
            existing["enum"] = truth["enum"]
            col_changed = True
        # ensure the canonical enum key exists (stable serialization).
        elif "enum" not in existing:
            existing["enum"] = None
            col_changed = True
        if col_changed:
            changed += 1

    return changed


def _match_extracted(entity_key: str, entity: dict, extracted: dict) -> dict | None:
    """Find the extracted entity for a canonical entity.

    Matches by (1) the registry entity key / ``name`` singular/plural-insensitively
    against extracted keys (extractor keys by PascalCased table name), then
    (2) falls back to the PascalCased ``table`` field.
    """
    name = entity.get("name") or entity_key
    for ext_key in extracted:
        if _entity_names_match(ext_key, name) or _entity_names_match(ext_key, entity_key):
            return extracted[ext_key]
    table = entity.get("table")
    if table:
        for ext_key in extracted:
            if _entity_names_match(ext_key, table):
                return extracted[ext_key]
    return None


def reconcile_registry_to_schema(output_dir: str) -> dict:
    """Correct the canonical registry's columns against the real emitted schema.

    Loads ``<output_dir>/contracts/resource-registry.json``, folds the accurate
    per-column metadata read from ``src/db/schema/*.ts`` onto each entity, and
    re-persists deterministically (``indent=2, sort_keys=True``). No-op (never
    raises) when the registry file is absent/unparseable. Idempotent.

    Returns ``{"entities_reconciled": int, "columns_updated": int}``.
    """
    registry = _load_registry(output_dir)
    if registry is None:
        return dict(_NOOP)

    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return dict(_NOOP)

    extracted = extract_entities_from_schema(output_dir) or {}
    if not extracted:
        return dict(_NOOP)

    entities_reconciled = 0
    columns_updated = 0
    for ekey, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        ext = _match_extracted(ekey, entity, extracted)
        if not ext:
            continue
        changed = _reconcile_entity(entity, ext.get("fields", {}))
        if changed:
            entities_reconciled += 1
            columns_updated += changed

    # Capture FK column → target-entity links from the schema `.references()` /
    # `foreignKey()` (the canonical registry ships them null because the plan's
    # relations rarely name the fk column). This is what lets FK dropdowns bind to
    # the REAL target (vetId → staff) instead of guessing from the column name.
    fk_applied = _apply_fk_targets(registry, extract_fk_references(output_dir))
    columns_updated += fk_applied

    # Second source of FK truth: pair FK-shaped columns to the entity's registry
    # relationships (name + elimination) for the columns the schema `.references()`
    # left unresolved — so the registry is complete even when schema_builder
    # emitted the FK column with no `.references()`.
    columns_updated += _apply_relationship_pairing(registry)

    with open(_registry_path(output_dir), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(registry, indent=2, sort_keys=True))

    return {
        "entities_reconciled": entities_reconciled,
        "columns_updated": columns_updated,
    }
