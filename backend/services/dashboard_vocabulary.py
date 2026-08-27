"""Dashboard vocabulary resolver — the domain decides the landing page.

Every archetype vocabulary describes how its industry works: which shape
suits each entity, how a list splits into sections, what the empty states
should say. All of it landed on interior list screens. The dashboard —
the landing page, the first thing anyone sees — had no vocabulary
consumer at all, so an inventory app, a clinic and a bank all opened on
the same generic KPI-and-chart skeleton. That is the whole of "dashboards
are lame": not a rendering problem, a missing input.

This module is the bridge. A vocabulary declares a ``dashboard_recipe``
("for THIS business, these are the numbers that matter and these are the
lists you work from"); this resolves it against the entities the app
actually has and returns specs the dashboard authority can compose.

Deliberately conservative: an entity the app doesn't have is dropped
rather than invented, and a vocabulary with no recipe returns nothing so
the existing generic composer still runs. Domain input is an upgrade
path, never a new way to fail.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from services.archetype_vocabulary import match_entity_name
from services.page_vocabulary import _column_names, _keep_existing
from services.section_split import resolve_filter_values

logger = logging.getLogger(__name__)

DEFAULT_MAX_KPIS = 6
DEFAULT_MAX_SECTIONS = 3


def _enum_values(entity_meta: Any) -> dict[str, list[str]]:
    """Declared enum values per column — both registry shapes."""
    out: dict[str, list[str]] = {}
    if not isinstance(entity_meta, dict):
        return out
    fields = entity_meta.get("fields") or entity_meta.get("columns") or []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                name = f.get("name") or f.get("column")
                vals = f.get("enum_values") or f.get("enumValues")
                if name and isinstance(vals, list) and vals:
                    out[str(name)] = [str(v) for v in vals]
    elif isinstance(fields, dict):
        for name, meta in fields.items():
            if isinstance(meta, dict):
                vals = meta.get("enum_values") or meta.get("enumValues")
                if isinstance(vals, list) and vals:
                    out[str(name)] = [str(v) for v in vals]
    return out


def _bind_filter(spec: dict, entity: str, entity_meta: Any) -> dict | None:
    """Resolve a spec's candidate filter against the entity's real enum.

    Vocabulary filters name candidate values ("low_stock", "lowstock",
    "reorder") because the industry's word and the app's word often
    differ; the entity's declared enum picks the one this app can
    actually hold. Returns None when none of them can — a KPI pinned to
    an impossible status always reads zero, which looks like a broken
    metric rather than an honest one.
    """
    raw = spec.get("filter")
    if not raw:
        return spec
    if entity_meta is None:
        # No column info to check against: trust the vocabulary and
        # collapse each candidate list to its preferred (first) value.
        return {**spec, "filter": {
            k: (v[0] if isinstance(v, (list, tuple)) and v else v)
            for k, v in raw.items()
        }}
    cols = {c: "" for c in _column_names(entity_meta)}
    bound = resolve_filter_values(raw, cols, _enum_values(entity_meta),
                                  _context=f"dashboard:{entity}")
    return {**spec, "filter": bound} if bound else None


def resolve_dashboard_recipe(
    vocabulary: Any,
    available: Iterable[str],
    *,
    entities: dict[str, Any] | None = None,
    max_kpis: int = DEFAULT_MAX_KPIS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
) -> dict[str, Any]:
    """Turn a vocabulary's dashboard recipe into entity-bound specs.

    ``available`` is the set of entity names the app really has (from the
    resource registry). Returns
    ``{kpis: [...], sections: [...], empty_copy: str, status_badges: {...}}``
    with every spec's ``entity`` rewritten to the app's own spelling.
    Unresolvable entries are dropped, so a partial vocabulary match still
    yields a domain-shaped page rather than nothing.
    """
    recipe = getattr(vocabulary, "dashboard_recipe", None) or {}
    names = list(available or [])

    meta_of = entities if isinstance(entities, dict) else {}

    kpis: list[dict] = []
    for spec in (recipe.get("kpis") or []):
        if not isinstance(spec, dict):
            continue
        entity = match_entity_name(spec.get("entity", ""), names)
        if not entity:
            continue
        meta = meta_of.get(entity)
        bound = _bind_filter({**spec, "entity": entity}, entity, meta)
        if bound is None:
            continue
        # A sum/avg over a column the app never built renders a blank
        # tile; degrade to a plain count of the same entity instead.
        wanted_field = bound.get("field")
        if wanted_field and meta is not None:
            real = _keep_existing([wanted_field], _column_names(meta))
            if real:
                bound["field"] = real[0]
            else:
                logger.debug("[dashboard-vocab] %s.%s absent — %r degrades "
                             "to count", entity, wanted_field, bound.get("label"))
                bound = {k: v for k, v in bound.items() if k != "field"}
                bound["op"] = "count"
        kpis.append(bound)
        if len(kpis) >= max_kpis:
            break

    sections: list[dict] = []
    for spec in (recipe.get("sections") or []):
        if not isinstance(spec, dict):
            continue
        entity = match_entity_name(spec.get("entity", ""), names)
        if not entity:
            continue
        bound = _bind_filter({**spec, "entity": entity}, entity,
                             meta_of.get(entity))
        if bound is None:
            # An unfiltered working list is still useful; losing the
            # filter shouldn't cost the whole section.
            bound = {k: v for k, v in spec.items() if k != "filter"}
            bound["entity"] = entity
        sections.append(bound)
        if len(sections) >= max_sections:
            break

    states = getattr(vocabulary, "signature_states", None) or {}
    out = {
        "kpis": kpis,
        "sections": sections,
        "empty_copy": states.get("empty_dashboard", ""),
        "status_badges": dict(getattr(vocabulary, "status_badges", None) or {}),
    }
    # Nothing resolved → return the bare shape so callers can test one key
    # and fall through to the generic composer.
    if not kpis and not sections:
        return {"kpis": [], "sections": []}
    if kpis or sections:
        logger.info("[dashboard-vocab] %s → %d kpi(s), %d section(s)",
                    getattr(vocabulary, "id", "?"), len(kpis), len(sections))
    return out


__all__ = ["resolve_dashboard_recipe"]
