"""Closed resource-set prompt block (Slice 2 of the resource-binding contract).

The page/schema agent authors UI wiring — a Form dispatches a workflow, a Table
binds its rows to an entity, a Select loads options from an entity slug. When it
does that from inference it can name a resource the backend doesn't have (a
mis-cased slug, a phantom workflow, a free-text Input feeding a uuid FK column).
Slice 1 added the hard *validation* gate that catches those after the fact; this
Slice hands the model the CLOSED set of REAL resources up front so it binds only
to them and the mismatch RATE the gate has to catch drops.

`build_resource_context(output_dir) -> str` returns a compact, token-efficient
prompt block listing:
  * Entities you may bind to — the exact registered slugs (the `pgTable`
    const names the data engine serves at `/api/data/<slug>`), each with its
    columns + drizzle types and which columns are FKs (→ which entity).
  * Workflows you may dispatch — the exact ids, each with its INPUT columns
    (the columns its db_insert/db_update writes) + trigger type.
Followed by a short, imperative bind-only instruction.

Reuses the registry readers from `binding_validator` (the SAME source of truth
the gate reads) so authoring and validation can never diverge. Best-effort —
never raises; on any internal error it returns "" so the prompt is unaffected.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re

from services.binding_validator import (
    _EXPORT_TABLE_RE,
    _canon,
    _pgtable_body,
    _read_workflows,
)

logger = logging.getLogger(__name__)

# A top-level column declaration inside a pgTable body: `driveId: uuid(`.
_COLUMN_DECL_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*)\s*\(")
# `.references(() => recruitmentDrives.id)` — capture the target const name.
_REFERENCES_RE = re.compile(r"references\(\s*\(\)\s*=>\s*([A-Za-z_$][\w$]*)")
# Drizzle helpers that appear in the `name: helper(` shape but aren't columns.
_NOT_A_COLUMN_TYPE = {"references", "default", "notnull", "primarykey"}


def _read_entities(output_dir: str) -> list[dict]:
    """Every registered entity: {slug, columns:[{name, type, notNull, fk}]}.

    `slug` is the pgTable const name (the data-engine registration slug). Each
    column carries its drizzle type, a notNull flag, and `fk` = the target
    entity const when the column is a `.references(() => <entity>.id)` FK.
    """
    sdir = os.path.join(output_dir, "src", "db", "schema")
    entities: list[dict] = []
    if not os.path.isdir(sdir):
        return entities
    for fp in sorted(glob.glob(os.path.join(sdir, "*.ts"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _EXPORT_TABLE_RE.finditer(text):
            const_name = m.group(1)
            body = _pgtable_body(text, m.end())
            columns = _parse_columns(body)
            entities.append({"slug": const_name, "columns": columns})
    return entities


def _parse_columns(body: str) -> list[dict]:
    """Parse a pgTable `{ ... }` body into ordered column descriptors."""
    matches = list(_COLUMN_DECL_RE.finditer(body))
    columns: list[dict] = []
    seen: set[str] = set()
    for i, cm in enumerate(matches):
        field, dtype = cm.group(1), cm.group(2).lower()
        if dtype in _NOT_A_COLUMN_TYPE or field in seen:
            continue
        seen.add(field)
        # The segment of this column's declaration runs until the next column.
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        segment = body[cm.start():seg_end]
        fk_match = _REFERENCES_RE.search(segment)
        columns.append({
            "name": field,
            "type": dtype,
            "notNull": ".notNull()" in segment,
            "fk": fk_match.group(1) if fk_match else None,
        })
    return columns


def _read_canonical_registry(output_dir: str) -> dict:
    """Load ``<output_dir>/contracts/resource-registry.json`` (the canonical
    registry) if present and parseable, else return {}.

    Additive/back-compat: older runs have no registry file, so a missing or
    unparseable file yields {} and the caller simply omits the extra sections.
    Never raises.
    """
    path = os.path.join(output_dir, "contracts", "resource-registry.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entity_id_to_name(registry: dict) -> dict[str, str]:
    """Map each entity's stable id (kebab-singular) → its display name.

    ``registry["entities"]`` is keyed by display name; each value carries an
    ``id``. This inverts to resolve interaction targetEntityId / relationship
    from/to ids back to human names.
    """
    out: dict[str, str] = {}
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return out
    for name, ent in entities.items():
        if not isinstance(ent, dict):
            continue
        eid = ent.get("id")
        if eid:
            out[str(eid)] = str(ent.get("name") or name)
    return out


def _interaction_line(it: dict, name_fn) -> str | None:
    """One '- "label" on page ...: dispatches workflow ...' line, or None."""
    if not isinstance(it, dict):
        return None
    label = it.get("label")
    workflow = it.get("workflowId")
    if not label or not workflow:
        return None
    source = it.get("sourcePage") or "(unknown)"
    target = name_fn(it.get("targetEntityId"))
    trig = it.get("trigger") or "manual"
    return (
        f'- "{label}" on page {source}: dispatches workflow {workflow} '
        f"targeting {target} (trigger: {trig})"
    )


def _relationship_line(rel: dict, name_fn) -> str | None:
    """One '- From type To (fk: col)' relationship line, or None."""
    if not isinstance(rel, dict):
        return None
    frm = rel.get("from")
    to = rel.get("to")
    if not frm or not to:
        return None
    rtype = rel.get("type") or "related-to"
    fk = rel.get("fkColumn") or "?"
    return f"- {name_fn(frm)} {rtype} {name_fn(to)} (fk: {fk})"


def _interaction_section_lines(inter_lines: list[str]) -> list[str]:
    if not inter_lines:
        return []
    return [
        "",
        "### Interactions — author button→workflow→entity wiring against these EXACT ids",
        *inter_lines,
    ]


def _relationship_section_lines(rel_lines: list[str]) -> list[str]:
    if not rel_lines:
        return []
    return [
        "",
        "### Relationships — the entity graph (use these FK columns for FK fields)",
        *rel_lines,
    ]


def _registry_section_lines(output_dir: str) -> list[str]:
    """Interaction-map + relationship-graph lines from the canonical registry.

    Returns [] when the registry file is absent/empty (back-compat) or has no
    interactions/relationships (so no empty headers are emitted). Never raises.
    """
    registry = _read_canonical_registry(output_dir)
    if not registry:
        return []

    id_to_name = _entity_id_to_name(registry)

    def _name(eid: object) -> str:
        return id_to_name.get(str(eid), str(eid)) if eid else "(unknown)"

    lines: list[str] = []

    interactions = registry.get("interactions")
    inter_lines: list[str] = []
    if isinstance(interactions, list):
        for it in interactions:
            line = _interaction_line(it, _name)
            if line:
                inter_lines.append(line)
    lines.extend(_interaction_section_lines(inter_lines))

    relationships = registry.get("relationships")
    rel_lines: list[str] = []
    if isinstance(relationships, list):
        for rel in relationships:
            line = _relationship_line(rel, _name)
            if line:
                rel_lines.append(line)
    lines.extend(_relationship_section_lines(rel_lines))

    return lines


_HEADER_LINES = [
    "## Closed resource set — bind ONLY to what exists here",
    "These are the REAL backend resources this app registers. Every "
    "dataSource / optionsFrom / Table-rows / workflow reference you emit "
    "MUST name one of these EXACT identifiers — never invent a resource "
    "name, a column, or a workflow id.",
]


def _entity_line(slug: str, columns: list[dict]) -> str:
    """One '- `slug` — col:type→FK*, ...' entity line (shared by full + slice)."""
    col_parts: list[str] = []
    for c in columns or []:
        seg = f"{c['name']}:{c['type']}"
        if c.get("fk"):
            seg += f"→{c['fk']}"
        if c.get("notNull"):
            seg += "*"
        col_parts.append(seg)
    cols_s = ", ".join(col_parts) if col_parts else "(no columns)"
    return f"- `{slug}` — {cols_s}"


def _entity_section_lines(entities: list[dict]) -> list[str]:
    """The '### Entities you may bind to' block for a list of {slug, columns}."""
    if not entities:
        return []
    lines = [
        "",
        "### Entities you may bind to (exact slug — its columns: type[, →FK entity])",
    ]
    for ent in entities:
        lines.append(_entity_line(ent["slug"], ent.get("columns") or []))
    lines.append("(`*` = NOT NULL / required. `→X` = FK referencing entity X.)")
    return lines


def _workflow_section_lines(records) -> list[str]:
    """The '### Workflows you may dispatch' block from _read_workflows records.

    `records` is any iterable of {id, trigger, input_columns} dicts; aliased
    records are deduped by id (a workflow appears under several keys)."""
    seen_ids: set[str] = set()
    wf_lines: list[str] = []
    for rec in records:
        wid = rec.get("id")
        if not wid or wid in seen_ids:
            continue
        seen_ids.add(wid)
        inputs = sorted(rec.get("input_columns") or [])
        inputs_s = ", ".join(inputs) if inputs else "(none)"
        trig = rec.get("trigger") or "manual"
        wf_lines.append(f"- `{wid}` — trigger: {trig}; input columns: {inputs_s}")
    if not wf_lines:
        return []
    return [
        "",
        "### Workflows you may dispatch (exact id — trigger; input columns)",
        *wf_lines,
    ]


_BINDING_RULES_LINES = [
    "",
    "### Binding rules (MANDATORY)",
    "- Bind every dataSource / optionsFrom / Table-rows ONLY to an entity "
    "slug from the list above — never invent a name.",
    "- Every Table, List, Chart, Calendar/Timeline/ResourceTimeline, and Stat "
    "MUST bind its data prop (rows / items / data / events / entries / "
    "resources / value) to a page dataSource DECLARED over one of the entities "
    "listed above. For a filtered or derived view "
    "(active / recent / upcoming / pending / …) DECLARE the dataSource WITH the "
    "filter / sort / limit — never invent a bare binding name that has no "
    "matching declared dataSource.",
    "- A form that dispatches a workflow: map each field's `name` to one of "
    "that workflow's INPUT columns; render an FK/uuid column as a Select with "
    "`optionsFrom` pointing at the referenced entity slug (never a free-text "
    "Input) — a uuid column fed a plain string crashes at runtime.",
    "- Put a workflow button only where the record context it needs exists.",
]


def build_resource_context(output_dir: str) -> str:
    """Build the closed resource-set + bind-only instruction prompt block.

    Returns "" when there are no registered entities/workflows (nothing to
    constrain) or on any read error — the caller appends it additively, so an
    empty string simply leaves the prompt unchanged.
    """
    try:
        entities = _read_entities(output_dir)
        workflows = _read_workflows(output_dir)
    except Exception:  # noqa: BLE001 — never break the prompt on a reader bug
        logger.exception("resource_registry_context: reader error (skipping block)")
        return ""

    if not entities and not workflows:
        return ""

    lines: list[str] = list(_HEADER_LINES)
    lines.extend(_entity_section_lines(entities))
    lines.extend(_workflow_section_lines(workflows.values()))
    # Canonical registry interaction-map + relationship-graph (additive; empty
    # for older runs with no contracts/resource-registry.json).
    lines.extend(_registry_section_lines(output_dir))
    lines.extend(_BINDING_RULES_LINES)
    return "\n".join(lines)


# ── registry-slice per-page context (enterprise scale, B1) ───────────────────
# Injecting the whole app into every per-page prompt is O(pages × app-size) —
# the primary enterprise-scale bottleneck. `build_resource_context_slice` bounds
# the block to the page's FOCAL entity: its full columns, its FK-NEIGHBORS (name
# + key/label columns only), the workflows that TARGET it, and the relationships
# incident to it — sourced from the cheaply-sliceable canonical registry. Same
# textual shape as the whole-app block, just smaller. Falls back to the whole-app
# block on a missing registry / unknown entity / any error (never raises).

# Column names that make a good human-readable display/label for an FK neighbor.
_DISPLAY_COLUMN_NAMES = {
    "name", "title", "label", "displayname", "fullname", "full_name",
    "email", "code", "sku", "reference", "number",
}
# Drizzle/SQL types that can serve as a fallback display column.
_STRINGY_TYPES = {"varchar", "text", "citext", "char", "character"}


def _registry_entities(registry: dict) -> dict[str, dict]:
    ents = registry.get("entities")
    return ents if isinstance(ents, dict) else {}


def _resolve_focal(entities: dict[str, dict], entity_name: str) -> tuple[str, dict] | None:
    """Find the registry entry for ``entity_name`` (by key, name, or id)."""
    if entity_name in entities and isinstance(entities[entity_name], dict):
        return entity_name, entities[entity_name]
    target = _canon(entity_name)
    for key, ent in entities.items():
        if not isinstance(ent, dict):
            continue
        for cand in (key, ent.get("name"), ent.get("id"), ent.get("slug")):
            if cand and _canon(str(cand)) == target:
                return key, ent
    return None


def _id_to_slug(entities: dict[str, dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ent in entities.values():
        if isinstance(ent, dict) and ent.get("id"):
            out[str(ent["id"])] = str(ent.get("slug") or ent["id"])
    return out


def _resolved_columns(columns, id_to_slug: dict[str, str]) -> list[dict]:
    """Copy ``columns`` rewriting each fk (a target entity id) to its slug so the
    `→X` annotation names the slug the LLM binds `optionsFrom` to."""
    out: list[dict] = []
    for c in columns or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        fk = c.get("fk")
        out.append({
            "name": c["name"],
            "type": c.get("type", "varchar"),
            "notNull": bool(c.get("notNull")),
            "fk": id_to_slug.get(str(fk), fk) if fk else None,
        })
    return out


def _key_label_columns(columns) -> list[dict]:
    """Reduce a neighbor's columns to id + one display column (enough to bind an
    FK Select, not the whole schema)."""
    cols = [c for c in (columns or []) if isinstance(c, dict) and c.get("name")]
    picked: list[dict] = []
    # id column(s)
    for c in cols:
        if _canon(str(c["name"])) in {"id", "uuid"} or c.get("name") == "id":
            picked.append(c)
    # a display/label column
    display = next(
        (c for c in cols if _canon(str(c["name"])) in _DISPLAY_COLUMN_NAMES), None
    )
    if display is None:
        display = next(
            (c for c in cols
             if c["name"] != "id"
             and str(c.get("type", "")).lower() in _STRINGY_TYPES), None
        )
    if display is not None and display not in picked:
        picked.append(display)
    return picked


def build_resource_context_slice(output_dir: str, entity_name: str) -> str:
    """Bounded per-page resource block for a page whose focal entity is
    ``entity_name`` — focal entity (full columns) + FK-neighbors (key/label
    columns only) + workflows targeting it + incident relationships.

    Sourced from ``contracts/resource-registry.json``. Falls back to the
    whole-app :func:`build_resource_context` when the registry is missing, the
    entity is unknown, or anything goes wrong. Never raises.
    """
    try:
        if not entity_name:
            return build_resource_context(output_dir)
        registry = _read_canonical_registry(output_dir)
        entities = _registry_entities(registry)
        if not entities:
            return build_resource_context(output_dir)
        resolved = _resolve_focal(entities, str(entity_name))
        if resolved is None:
            return build_resource_context(output_dir)
        focal_key, focal = resolved
        focal_id = str(focal.get("id") or focal_key)

        id_to_slug = _id_to_slug(entities)
        id_to_name = _entity_id_to_name(registry)

        # FK-neighbor entity ids: entities the focal FKs to, plus entities that
        # FK to the focal.
        neighbor_ids: set[str] = set()
        for fk in (focal.get("fks") or []):
            if isinstance(fk, dict) and fk.get("targetEntityId"):
                neighbor_ids.add(str(fk["targetEntityId"]))
        for c in (focal.get("columns") or []):
            if isinstance(c, dict) and c.get("fk"):
                neighbor_ids.add(str(c["fk"]))
        for ent in entities.values():
            if not isinstance(ent, dict):
                continue
            for fk in (ent.get("fks") or []):
                if isinstance(fk, dict) and str(fk.get("targetEntityId")) == focal_id:
                    neighbor_ids.add(str(ent.get("id") or ""))
        neighbor_ids.discard(focal_id)
        neighbor_ids.discard("")

        # Entity section: focal (full columns) then neighbors (key/label only).
        entity_dicts: list[dict] = [{
            "slug": str(focal.get("slug") or focal_id),
            "columns": _resolved_columns(focal.get("columns"), id_to_slug),
        }]
        by_id = {
            str(ent["id"]): ent
            for ent in entities.values()
            if isinstance(ent, dict) and ent.get("id")
        }
        for nid in sorted(neighbor_ids):
            ent = by_id.get(nid)
            if not ent:
                continue
            entity_dicts.append({
                "slug": str(ent.get("slug") or nid),
                "columns": _resolved_columns(_key_label_columns(ent.get("columns")), id_to_slug),
            })

        def _name(eid: object) -> str:
            return id_to_name.get(str(eid), str(eid)) if eid else "(unknown)"

        # Workflows that TARGET this entity → resolve to their real records.
        interactions = registry.get("interactions")
        target_wf_ids: list[str] = []
        inter_lines: list[str] = []
        if isinstance(interactions, list):
            for it in interactions:
                if not isinstance(it, dict):
                    continue
                if str(it.get("targetEntityId")) != focal_id:
                    continue
                if it.get("workflowId"):
                    target_wf_ids.append(str(it["workflowId"]))
                line = _interaction_line(it, _name)
                if line:
                    inter_lines.append(line)

        wf_records: list[dict] = []
        seen_wf: set[str] = set()
        try:
            wf_index = _read_workflows(output_dir)
        except Exception:  # noqa: BLE001
            wf_index = {}
        for wid in target_wf_ids:
            rec = wf_index.get(_canon(wid))
            rid = rec.get("id") if rec else None
            if rec and rid and rid not in seen_wf:
                seen_wf.add(rid)
                wf_records.append(rec)

        # Relationships incident to the focal entity only.
        relationships = registry.get("relationships")
        rel_lines: list[str] = []
        if isinstance(relationships, list):
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                if str(rel.get("from")) != focal_id and str(rel.get("to")) != focal_id:
                    continue
                line = _relationship_line(rel, _name)
                if line:
                    rel_lines.append(line)

        lines: list[str] = list(_HEADER_LINES)
        lines.extend(_entity_section_lines(entity_dicts))
        lines.extend(_workflow_section_lines(wf_records))
        lines.extend(_interaction_section_lines(inter_lines))
        lines.extend(_relationship_section_lines(rel_lines))
        lines.extend(_BINDING_RULES_LINES)
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 — never break the prompt; fall back whole-app
        logger.exception("resource_registry_context: slice error (falling back)")
        try:
            return build_resource_context(output_dir)
        except Exception:  # noqa: BLE001
            return ""
