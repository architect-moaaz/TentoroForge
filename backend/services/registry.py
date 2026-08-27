"""
Contract Registry — shared state that tracks what each agent in the
code-generation pipeline has produced.

Every agent reads the registry for validation / context and appends to it
after producing output.  The file is persisted as ``registry.json`` inside
the project output directory.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, TypedDict

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema (informational — the runtime representation is a plain dict)
# ---------------------------------------------------------------------------

class FieldInfo(TypedDict, total=False):
    type: str
    nullable: bool
    primaryKey: bool
    enum_values: list[str]


class EntityInfo(TypedDict):
    fields: dict[str, FieldInfo]
    indexes: list[str]


class Relation(TypedDict):
    from_entity: str
    to_entity: str
    type: str
    foreignKey: str


class RouteInfo(TypedDict):
    entity: str
    request_fields: list[str]
    response_entity: str


class ComponentInfo(TypedDict):
    file: str
    props: dict[str, str]
    api_calls: list[str]


class PageInfo(TypedDict):
    file: str
    components: list[str]
    api_calls: list[str]


class WorkflowBinding(TypedDict):
    page: str
    variables: dict[str, str]


class RuleInfo(TypedDict, total=False):
    entity: str
    field: str
    operator: str
    value: Any
    type_constraint: str


class ContractRegistry(TypedDict):
    entities: dict[str, EntityInfo]
    relations: list[Relation]
    api_routes: dict[str, RouteInfo]
    components: dict[str, ComponentInfo]
    pages: dict[str, PageInfo]
    workflow_bindings: dict[str, WorkflowBinding]
    rules: dict[str, RuleInfo]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_registry() -> dict:
    """Return a registry with every section initialised to its zero-value."""
    return {
        "entities": {},
        "relations": [],
        "api_routes": {},
        "components": {},
        "pages": {},
        "workflow_bindings": {},
        "rules": {},
    }


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into *base*, mutating *base* in place."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_registry(plan: dict) -> dict:
    """Initialise a new contract registry from a ``plan.json`` dict.

    Pre-populates *entities*, *relations*, *api_routes*, *components*,
    *pages*, and *workflow_bindings* from the corresponding plan sections.
    """
    reg = _empty_registry()

    # -- entities ----------------------------------------------------------
    for model in plan.get("data_models", []):
        name = model.get("name")
        if not name:
            continue
        fields: dict[str, FieldInfo] = {}
        for f in model.get("fields", []):
            fname = f.get("name")
            if not fname:
                continue
            info: FieldInfo = {"type": f.get("type", "unknown"), "nullable": f.get("nullable", False), "primaryKey": f.get("primaryKey", False)}
            if "enum_values" in f:
                info["enum_values"] = f["enum_values"]
            fields[fname] = info
        reg["entities"][name] = {
            "fields": fields,
            "indexes": list(model.get("indexes", [])),
        }
        # Attach the canonical name variants NOW so every downstream
        # builder reads from ONE source of truth (see services.entity_names
        # — the historical failure mode was 4 local pluralizers that
        # disagreed and produced `assessmentDaies` / `assessment-days` /
        # `assessmentDays` for the same entity).
        from services.entity_names import enrich_entity
        enrich_entity(reg["entities"][name], name)

    # -- relations ---------------------------------------------------------
    for rel in plan.get("relations", []):
        reg["relations"].append({
            "from_entity": rel.get("from", ""),
            "to_entity": rel.get("to", ""),
            "type": rel.get("type", ""),
            "foreignKey": rel.get("foreignKey", ""),
        })

    # -- api_routes --------------------------------------------------------
    for route in plan.get("api_routes", []):
        method = route.get("method", "GET").upper()
        path = route.get("path", "")
        key = f"{method} {path}"
        reg["api_routes"][key] = {
            "entity": route.get("entity", ""),
            "request_fields": list(route.get("request_fields", [])),
            "response_entity": route.get("response_entity", ""),
        }

    # -- components --------------------------------------------------------
    for comp in plan.get("components", []):
        name = comp.get("name")
        if not name:
            continue
        reg["components"][name] = {
            "file": comp.get("file", ""),
            "props": comp.get("props", {}) if isinstance(comp.get("props"), dict) else {p: {} for p in comp.get("props", []) if isinstance(p, str)},
            "api_calls": list(comp.get("api_calls", [])),
        }

    # -- pages -------------------------------------------------------------
    for page in plan.get("pages", []):
        route = page.get("route")
        if not route:
            continue
        reg["pages"][route] = {
            "file": page.get("file", ""),
            "components": list(page.get("components", [])),
            "api_calls": list(page.get("api_calls", [])),
        }

    # -- workflow_bindings (human-task steps) -------------------------------
    for wf in plan.get("workflows", []):
        for step in wf.get("steps", []):
            if isinstance(step, str):
                # Simple string step names (e.g. from design analyzer)
                reg["workflow_bindings"][step] = {"page": "", "variables": {}}
                continue
            step_name = step.get("name")
            if not step_name:
                continue
            reg["workflow_bindings"][step_name] = {
                "page": step.get("page", ""),
                "variables": step.get("variables", {}) if isinstance(step.get("variables"), dict) else {},
            }

    log.info(
        "Registry created: %d entities, %d relations, %d routes, %d components, %d pages, %d bindings",
        len(reg["entities"]),
        len(reg["relations"]),
        len(reg["api_routes"]),
        len(reg["components"]),
        len(reg["pages"]),
        len(reg["workflow_bindings"]),
    )
    return reg


def load_registry(output_dir: str) -> dict:
    """Load the registry from ``{output_dir}/registry.json``.

    Returns an empty registry when the file does not exist.
    """
    path = Path(output_dir) / "registry.json"
    if not path.exists():
        log.debug("Registry file not found at %s — returning empty registry", path)
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        log.info("Registry loaded from %s", path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read registry at %s: %s — returning empty registry", path, exc)
        return _empty_registry()


def save_registry(output_dir: str, registry: dict) -> None:
    """Atomically write the registry to ``{output_dir}/registry.json``.

    Writes to a temporary file first, then renames so that a crash never
    leaves a half-written file on disk.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "registry.json"

    fd, tmp_path = tempfile.mkstemp(dir=str(out), suffix=".tmp", prefix="registry_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(registry, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, str(target))
        log.info("Registry saved to %s", target)
    except BaseException:
        # Clean up the temp file on any failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def merge_section(registry: dict, section: str, entries: dict) -> dict:
    """Deep-merge *entries* into ``registry[section]`` and return the registry.

    For list-valued sections (e.g. ``relations``) the entries are appended.
    For dict-valued sections the merge is recursive so that nested keys are
    updated without discarding siblings.
    """
    registry = copy.deepcopy(registry)

    current = registry.get(section)
    if current is None:
        registry[section] = entries
    elif isinstance(current, list) and isinstance(entries, list):
        current.extend(entries)
    elif isinstance(current, dict) and isinstance(entries, dict):
        _deep_merge(current, entries)
    else:
        registry[section] = entries

    log.debug("Merged into '%s': %d top-level entries", section, len(entries) if isinstance(entries, (dict, list)) else 1)
    return registry


# Re-exported so the documented path `services.registry.enrich_entity_names`
# actually resolves (register EN-1). The implementation lives with the naming
# authority in services.entity_names; this is the name the rest of the codebase
# and entity_names' own docstring have always referred to.
from services.entity_names import enrich_entity_names  # noqa: E402,F401


def _norm_entity(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _entity_names_match(a: str, b: str) -> bool:
    """Singular/plural-insensitive entity-name match (Reservation ↔ Reservations).

    The canonical-key comparison below is the authoritative one; the
    hand-rolled suffix rules are kept underneath it because this matcher
    is deliberately tolerant and removing a rule could only ever lose a
    match. The local rules missed irregulars the authority handles
    (``Address`` ↔ ``addresses``, ``Status`` ↔ ``statuses``), which left
    the accurate schema-extracted entity unmerged and the deterministic
    builder reading the stale plan entity — every field ``nullable:
    false``, no ``hasDefault``."""
    na, nb = _norm_entity(a), _norm_entity(b)
    if na == nb:
        return True

    ka, kb = _safe_entity_key(a), _safe_entity_key(b)
    if ka is not None and ka == kb:
        return True

    for x, y in ((na, nb), (nb, na)):
        if x + "s" == y or x + "es" == y:
            return True
        if x.endswith("y") and x[:-1] + "ies" == y:
            return True
    return False


def _safe_entity_key(name: str) -> str | None:
    """:func:`services.entity_names.entity_key`, or None when unnameable."""
    from services.entity_names import EntityNameError, entity_key
    try:
        return entity_key(name)
    except EntityNameError:
        return None


def reconcile_entities(registry: dict, extracted: dict) -> dict:
    """Fold schema-extracted entities (accurate nullable/hasDefault/type, read from
    the real Drizzle files) onto the registry's existing plan entities.

    The plan keys entities by their singular model name (``Reservation``); the
    extractor keys them by the PascalCased table name (``Reservations``). A blind
    merge leaves BOTH — and the deterministic builder reads the stale singular one
    (every field ``nullable: false``, no ``hasDefault``). Here we MATCH an extracted
    entity to its plan entity (singular/plural-insensitive) and deep-merge the
    accurate fields ONTO the plan key — so the canonical name everything else
    references gains correct metadata. Unmatched extracted entities are added as-is.
    """
    registry = copy.deepcopy(registry)
    ents = registry.setdefault("entities", {})
    for ext_name, ext_info in (extracted or {}).items():
        match_key = next((k for k in ents if _entity_names_match(k, ext_name)), None)
        if match_key:
            target = ents[match_key].setdefault("fields", {})
            # The extractor is authoritative for nullable/hasDefault/type — it reads the
            # real Drizzle schema, whereas the plan seeds every field `nullable: False`
            # as a meaningless default. Let the extracted metadata WIN (deep-merge onto
            # the plan fields). See test_registry_accuracy.
            _deep_merge(target, ext_info.get("fields", {}))
            if ext_info.get("indexes"):
                ents[match_key]["indexes"] = ext_info["indexes"]
        else:
            ents[ext_name] = ext_info

    # Refresh the canonical name variants on every entity — new arrivals
    # get them, existing ones stay in sync if the entity name changed
    # (idempotent + safe on repeat reconciles).
    from services.entity_names import enrich_entity
    for k, v in ents.items():
        enrich_entity(v, k)

    return registry


def registry_summary_for_agent(registry: dict, sections: list[str]) -> str:
    """Format selected *sections* of the registry as a compact text block
    suitable for injection into an agent prompt.

    Sections that are empty or missing are silently skipped.
    """
    parts: list[str] = []

    for section in sections:
        data = registry.get(section)
        if not data:
            continue

        if section == "entities":
            lines = [f"## Entities"]
            for ename, info in data.items():
                field_strs = []
                for fname, finfo in info.get("fields", {}).items():
                    markers = []
                    if finfo.get("primaryKey"):
                        markers.append("PK")
                    if finfo.get("nullable"):
                        markers.append("null")
                    suffix = f" ({', '.join(markers)})" if markers else ""
                    field_strs.append(f"{fname}: {finfo.get('type', '?')}{suffix}")
                lines.append(f"- {ename} {{ {', '.join(field_strs)} }}")
                idxs = info.get("indexes")
                if idxs:
                    # An index entry may be a plain column name or a composite
                    # (nested list of columns) — coerce both so join never crashes.
                    idx_strs = [
                        "+".join(str(c) for c in i) if isinstance(i, (list, tuple)) else str(i)
                        for i in idxs
                    ]
                    lines.append(f"  indexes: {', '.join(idx_strs)}")
            parts.append("\n".join(lines))

        elif section == "relations":
            lines = [f"## Relations"]
            for rel in data:
                lines.append(f"- {rel.get('from_entity')} -> {rel.get('to_entity')} [{rel.get('type')}] FK={rel.get('foreignKey')}")
            parts.append("\n".join(lines))

        elif section == "api_routes":
            lines = ["## API Routes"]
            for key, info in data.items():
                lines.append(f"- {key} -> {info.get('response_entity', '?')}")
            parts.append("\n".join(lines))

        elif section == "components":
            lines = ["## Components"]
            for cname, info in data.items():
                props = ", ".join(f"{k}: {v}" for k, v in info.get("props", {}).items())
                calls = ", ".join(info.get("api_calls", []))
                detail = []
                if props:
                    detail.append(f"props={{ {props} }}")
                if calls:
                    detail.append(f"calls=[{calls}]")
                lines.append(f"- {cname} ({info.get('file', '?')}) {' '.join(detail)}".rstrip())
            parts.append("\n".join(lines))

        elif section == "pages":
            lines = ["## Pages"]
            for route, info in data.items():
                comps = ", ".join(info.get("components", []))
                lines.append(f"- {route} -> [{comps}]")
            parts.append("\n".join(lines))

        elif section == "workflow_bindings":
            lines = ["## Workflow Bindings"]
            for node, info in data.items():
                vs = ", ".join(f"{k}: {v}" for k, v in info.get("variables", {}).items())
                lines.append(f"- {node} page={info.get('page', '?')} vars={{ {vs} }}")
            parts.append("\n".join(lines))

        elif section == "rules":
            lines = ["## Rules"]
            for rname, info in data.items():
                lines.append(f"- {rname}: {info.get('entity')}.{info.get('field')} {info.get('operator')} {info.get('value', '')}")
            parts.append("\n".join(lines))

        else:
            # Generic fallback — dump as compact JSON.
            parts.append(f"## {section}\n{json.dumps(data, indent=1, ensure_ascii=False)}")

    return "\n\n".join(parts)
