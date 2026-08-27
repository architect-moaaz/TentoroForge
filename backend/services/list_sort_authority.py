"""Sort order has an owner — the domain, not whoever composed the page.

Which row a list puts on top is a domain decision of the same kind as
which columns it shows, and it was free in the same way. Measured on the
inventory app: with reference screens attached the composer sorted stock
by ``updatedAt desc`` in every run and by ``qtyAvailable asc`` in none —
it had absorbed the recency ordering a reference screenshot happened to
show. A stock screen sorted by "recently touched" is a changelog; the
picker wanted whatever is running out.

The obvious repair — telling the composer so in its prompt — was tried
five ways and abandoned. That prompt turns out to be knife-edge: every
wording that produced a correct ``orderBy`` also cost the dashboard its
section structure (3 labelled sections → 0, reproducibly), and the one
wording that kept the sections did so by making the model omit
``orderBy`` altogether. Attending to ordering and composing layout
compete inside the single call, so the fix belongs outside it.

So this runs after composition and overwrites what the composer chose,
but only where the vocabulary actually states a preference. Silence is
the common case and means "the composer's choice stands" — this is an
owner for the decisions a domain has an opinion about, not a blanket
override.

Conservative in the same ways as the rest of the vocabulary layer: a
column the app never built is dropped rather than emitted (a dataSource
ordering by a missing column is a runtime error, not a cosmetic miss),
and an unknown archetype or absent recipe leaves every page untouched.
"""
from __future__ import annotations

import logging
from typing import Any

from services.page_vocabulary import resolve_page_recipe

logger = logging.getLogger(__name__)

# Only row-returning reads have a row order. ``get`` is a single record
# and ``aggregate``/``series`` carry their own grouping.
_ORDERABLE_OPS = ("list",)


def _entity_meta(plan: Any, entity: str) -> Any:
    """Find one entity's column record in either shape the plan uses."""
    if not isinstance(plan, dict) or not entity:
        return None
    entities = plan.get("entities")
    if isinstance(entities, dict):
        hit = entities.get(entity)
        if hit is not None:
            return hit
    for model in (plan.get("data_models") or []):
        if isinstance(model, dict) and str(model.get("name") or "") == entity:
            return model
    return None


def apply_list_sort(schema: Any, plan: Any, vocabulary: Any) -> list[dict]:
    """Set ``orderBy`` on every list dataSource the domain has a view on.

    Mutates ``schema`` in place. Returns one record per change, so the
    caller can log or report what the domain overrode — a silent
    rewrite of someone else's decision is how these layers become
    impossible to debug.
    """
    if not isinstance(schema, dict) or vocabulary is None:
        return []
    sources = schema.get("dataSources")
    if not isinstance(sources, list):
        return []

    changes: list[dict] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        if str(src.get("op") or "list").lower() not in _ORDERABLE_OPS:
            continue
        entity = str(src.get("entity") or "")
        if not entity:
            continue
        meta = _entity_meta(plan, entity)
        if meta is None:
            continue
        try:
            recipe = resolve_page_recipe(vocabulary, entity, meta)
        except Exception as exc:  # noqa: BLE001 — never fail a build over sort order
            logger.debug("[list-sort] %s: recipe lookup failed: %s", entity, exc)
            continue
        order = (recipe or {}).get("list_order") or {}
        if not order:
            continue

        wanted = [{"field": order["field"], "dir": order["dir"]}]
        if src.get("orderBy") == wanted:
            continue  # already right — keep the pass idempotent
        changes.append({
            "dataSource": src.get("name") or entity,
            "entity": entity,
            "was": src.get("orderBy"),
            "now": wanted,
        })
        src["orderBy"] = wanted

    if changes:
        logger.info("[list-sort] %s: set order on %d dataSource(s): %s",
                    getattr(vocabulary, "id", "?"), len(changes),
                    ", ".join(f"{c['dataSource']}→{c['now'][0]['field']} "
                              f"{c['now'][0]['dir']}" for c in changes))
    return changes


__all__ = ["apply_list_sort"]
