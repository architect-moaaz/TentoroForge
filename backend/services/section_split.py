"""Section split — render one collection screen as multiple filtered sections.

The Claude-Artifact yoga demo splits ``/my-bookings`` into two
visually distinct sections stacked on the same page: Upcoming above,
Past below. That two-section layout is a universal booking-app
convention (also true for salons, courts, appointments) — a single
flat "Bookings" list reads as an admin backend.

This module is pure. It takes a base collection node (whatever
`_build_collection_node` produced) plus the resolved archetype
vocabulary + route + column map, and returns either:

  - the same node unchanged (no split applies), OR
  - a Stack of Card-wrapped section blocks, each carrying its own
    heading + filter-scoped dataSource ref.

Design decisions worth naming:

  - **Split only when the vocabulary declares it.** Non-booking apps
    with a bookings-like route never split — the recipe lives in the
    archetype vocabulary, not in the route slug alone.

  - **Split only when the entity has the filter column.** A vocabulary
    could name a filter column ("status") that a given entity doesn't
    carry. In that case we fall back to the un-split node rather than
    emitting a broken filter reference.

  - **Empty filter dicts pass through.** Some sections (Today,
    This-Week, KPI-Strip) exist purely as visual sub-headers with no
    server-side filter — the composer still splits into Card sections
    but each Card's dataSource has no `filter` key. This is
    intentional and visually honest (headed groups vs one flat list),
    even when both sections show the same rows for now.

  - **Filter column MUST be an equality match.** Runtime data-engine
    supports only ``eq()`` on list filters today. Vocabularies choose
    single canonical values per section (e.g. upcoming = confirmed,
    past = attended). Multi-value / range filters land in a follow-on
    runtime slice.

  - **Section titles come from the section key.** ``upcoming`` →
    "Upcoming", ``my-bookings`` → "My Bookings", etc. Vocabulary
    entries can override via a follow-on ``section_labels`` map.

Task: #671 (SL2-4). Builds on SL2-2 (vocabulary shape override) and
SL2-3 (empty-state library) to complete the archetype-aware
collection composition trio.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Route → section-recipe resolution ────────────────────────────────


def _extract_route_slug(route: str | None) -> str:
    """Match empty_state_library._extract_route_slug — same rule so
    section-lookup and empty-state-lookup use identical keys."""
    if not isinstance(route, str) or not route.strip():
        return ""
    parts = [p for p in route.strip().strip("/").split("/") if p]
    return parts[0].strip().lower() if parts else ""


def resolve_sections(vocabulary: Any,
                     route: str | None) -> list[str]:
    """Return the ordered section list for this route.

    Returns an empty list when the vocabulary is missing, has no
    ``section_recipes``, or has no matching entry for this route.
    Callers branch on ``len(result) >= 2`` — a single-section recipe
    is not a "split" and the caller should keep its base collection.
    """
    if vocabulary is None:
        return []
    recipes = getattr(vocabulary, "section_recipes", None)
    if not isinstance(recipes, dict) or not recipes:
        return []
    slug = _extract_route_slug(route)
    if not slug:
        return []
    sections = recipes.get(slug)
    if not isinstance(sections, list):
        return []
    # Copy so callers can't mutate the vocabulary.
    return [s for s in sections if isinstance(s, str) and s.strip()]


# ── Section metadata ─────────────────────────────────────────────────


def resolve_section_filter(vocabulary: Any,
                           section_name: str,
                           entity_columns: dict[str, str],
                           entity_enum_values: dict[str, list[str]] | None = None,
                           ) -> dict[str, str]:
    """Return the filter dict to apply on this section's dataSource.

    Empty dict when:
      - vocabulary is None or has no ``section_filters``;
      - the section isn't declared;
      - the section's filter names a column the entity lacks (fall
        back to unfiltered rather than emit a broken reference);
      - the entity declares enum_values for the column and NONE of
        the vocab's candidate values appear in that enum (a filter
        set to a non-existent value would filter to zero rows —
        prefer no filter over a guaranteed-empty query).

    Column names match case-insensitively — vocab keys are lowercase
    (``status``) but entity registries may spell them differently.

    Values MAY be a plain string OR a list of alternates
    (e.g. ``{"status": ["confirmed", "booked", "reserved"]}``).
    A list resolves to the first candidate that appears in the entity's
    declared enum_values; when the entity has no declared enum_values,
    the first candidate is picked as best-effort.
    """
    if vocabulary is None:
        return {}
    filters = getattr(vocabulary, "section_filters", None)
    if not isinstance(filters, dict):
        return {}
    raw = filters.get(section_name)
    if not isinstance(raw, dict) or not raw:
        return {}
    return resolve_filter_values(raw, entity_columns, entity_enum_values,
                                 _context=section_name)


def resolve_filter_values(raw: dict,
                          entity_columns: dict[str, str],
                          entity_enum_values: dict[str, list[str]] | None = None,
                          *,
                          _context: str = "",
                          ) -> dict[str, str]:
    """Resolve one vocabulary filter dict against a real entity.

    The single place the whole system turns a domain's *candidate*
    values into a value this app actually stores. Vocabularies are
    written in the industry's words ("low_stock"); a given app may have
    landed on ``lowstock`` or ``reorder``, so every filter value may be
    a list of alternates and the real enum decides which one wins.

    Drops a column the entity lacks, and drops a filter whose candidates
    are all absent from a declared enum — a filter pinned to a value no
    row can hold is a guaranteed-empty query, which reads as "broken"
    rather than "no data".
    """
    if not isinstance(raw, dict) or not raw:
        return {}

    entity_col_names_lower = {c.lower() for c in entity_columns.keys()}
    enum_lookup: dict[str, list[str]] = {}
    if isinstance(entity_enum_values, dict):
        for k, v in entity_enum_values.items():
            if isinstance(k, str) and isinstance(v, list):
                enum_lookup[k.lower()] = [str(x).lower() for x in v if isinstance(x, str)]

    valid: dict[str, str] = {}
    for col, val in raw.items():
        if not isinstance(col, str):
            continue
        if col.lower() not in entity_col_names_lower:
            logger.debug(
                "[section-split] filter column %r not on entity — dropping "
                "for %r", col, _context,
            )
            continue

        candidates: list[str] = []
        if isinstance(val, str):
            candidates = [val]
        elif isinstance(val, (list, tuple)):
            candidates = [str(x) for x in val if isinstance(x, str)]
        else:
            continue

        # If the plan declared enum_values for this column, verify at
        # least one candidate is a real value. Otherwise ship the
        # first candidate as-is (seeders may still use it, and if
        # not the section renders empty — which is still honest).
        declared = enum_lookup.get(col.lower(), [])
        chosen: str | None = None
        if declared:
            for c in candidates:
                if c.lower() in declared:
                    chosen = c
                    break
            if chosen is None:
                logger.debug(
                    "[section-split] none of %r match declared enum %r "
                    "for %s.%s — dropping filter",
                    candidates, declared, _context, col,
                )
                continue
        else:
            chosen = candidates[0] if candidates else None

        if chosen is not None:
            valid[col] = chosen
    return valid


def humanize_section_label(section_name: str) -> str:
    """``upcoming`` → ``Upcoming``.  ``my-bookings`` → ``My Bookings``.

    Vocabularies can grow a ``section_labels`` dict later to override
    (e.g. ``kpi-strip`` → "At a glance") — this helper is the default
    when no override exists.
    """
    if not isinstance(section_name, str) or not section_name.strip():
        return ""
    parts = re.split(r"[-_\s]+", section_name.strip())
    return " ".join(p.capitalize() for p in parts if p)


# ── Split emission ───────────────────────────────────────────────────


def _clone_data_source(base_ds: dict, new_name: str,
                       extra_filter: dict[str, str]) -> dict:
    """Return a copy of ``base_ds`` renamed + with the extra filter merged."""
    out = copy.deepcopy(base_ds)
    out["name"] = new_name
    if extra_filter:
        existing = out.get("filter") if isinstance(out.get("filter"), dict) else {}
        merged = {**existing, **extra_filter}
        out["filter"] = merged
    return out


def _rebind_node(node: dict, old_name: str, new_name: str) -> None:
    """Rewrite ``{{old_name}}`` bindings to ``{{new_name}}`` in place.

    Walks the node tree touching every string prop. Only replaces
    exact ``{{name}}`` and ``{{name.…}}`` matches so a similarly-named
    dataSource elsewhere in the app isn't clobbered.
    """
    pattern = re.compile(r"\{\{" + re.escape(old_name) + r"(\.[a-zA-Z0-9_.\[\]]+)?\}\}")

    def _sub(m: re.Match) -> str:
        tail = m.group(1) or ""
        return "{{" + new_name + tail + "}}"

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str):
                    obj[k] = pattern.sub(_sub, v)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str):
                    obj[i] = pattern.sub(_sub, v)
                else:
                    _walk(v)

    _walk(node)


def split_collection_into_sections(*,
                                    base_node: dict,
                                    base_ds_name: str,
                                    base_data_sources: list[dict],
                                    sections: list[str],
                                    vocabulary: Any,
                                    entity_columns: dict[str, str],
                                    entity_enum_values: dict[str, list[str]] | None = None,
                                    ) -> tuple[dict, list[dict]]:
    """Return (root_stack, expanded_data_sources) split into N sections.

    Each section becomes a Card containing a Heading + a clone of the
    base collection node re-bound to that section's dedicated
    dataSource. The dataSource carries the section-filter dict (from
    the vocabulary) as its ``filter`` prop.

    Sections whose filter would reference a missing column render
    unfiltered — the visual heading still communicates the intended
    grouping, and a follow-on runtime slice can grow full support.

    The returned root Stack replaces the original ``collection_node``
    at the composer's assembly step. The returned data-source list
    replaces the original single-entry list (the base_ds is dropped
    entirely; every consumer now points at a per-section clone).
    """
    if not sections:
        # Defensive — caller should have guarded on len(sections)>=2,
        # but bail cleanly instead of returning a malformed Stack.
        return base_node, base_data_sources

    if len(base_data_sources) != 1 or base_data_sources[0].get("name") != base_ds_name:
        logger.debug(
            "[section-split] unexpected base dataSources shape; skipping split "
            "(expected exactly one entry named %r)", base_ds_name,
        )
        return base_node, base_data_sources

    section_cards: list[dict] = []
    new_data_sources: list[dict] = []

    for section in sections:
        section_slug = re.sub(r"[^a-z0-9]+", "_",
                              section.strip().lower()).strip("_") or "section"
        new_name = f"{base_ds_name}_{section_slug}"
        section_filter = resolve_section_filter(
            vocabulary, section, entity_columns,
            entity_enum_values=entity_enum_values,
        )
        ds = _clone_data_source(base_data_sources[0], new_name, section_filter)
        # Marker so a downstream runtime slice can discover the split
        # without pattern-matching on the name.
        ds["section"] = section
        new_data_sources.append(ds)

        # Clone the base collection and re-bind to the new dataSource.
        cloned = copy.deepcopy(base_node)
        _rebind_node(cloned, base_ds_name, new_name)

        heading_text = humanize_section_label(section)
        card = {
            "type": "Card",
            "props": {
                "data-section-key": section,
                # Padded surface — matches the wellness-app card feel
                # (rounded, tinted background from tokens). Skip
                # elevation to avoid stacking against the collection
                # inside which may already have its own card treatment.
                "className": "p-6",
            },
            "children": [
                {
                    "type": "Stack",
                    "props": {"gap": "tokens.spacing.4"},
                    "children": [
                        {"type": "Heading",
                         "props": {"content": heading_text, "level": 2}},
                        cloned,
                    ],
                },
            ],
        }
        section_cards.append(card)

    root_stack = {
        "type": "Stack",
        "props": {"gap": "tokens.spacing.6",
                  "data-signature-move": "section-split"},
        "children": section_cards,
    }
    return root_stack, new_data_sources


__all__ = [
    "humanize_section_label",
    "resolve_section_filter",
    "resolve_sections",
    "split_collection_into_sections",
]
