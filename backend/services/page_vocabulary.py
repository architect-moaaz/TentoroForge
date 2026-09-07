"""Page vocabulary resolver — the domain decides what a page SHOWS.

``component_preferences`` told composers how an entity should be
*shaped* (dense table vs card grid). Nothing told them what it should
*show*, so the column set on every list and the field grouping on every
record page were free choices — which is how a warehouse app ends up
leading its item table with ``createdAt`` while the next one leads with
``id``. Neither is what a picker wants; both are what you get when
nobody in the loop knows the job.

This is the counterpart to :mod:`services.dashboard_vocabulary`: a
vocabulary declares, per entity, the columns its industry reads first
and the groups a record splits into; this binds those names to the
columns the app actually built.

Conservative in the same way: a column the app lacks is dropped rather
than invented, a section left with no surviving fields disappears, and
an entity with no recipe returns nothing so the existing LLM authoring
runs untouched. Domain input is an upgrade path, never a new way to fail.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from services.archetype_vocabulary import match_entity_name

logger = logging.getLogger(__name__)

MAX_LIST_COLUMNS = 7
MAX_DETAIL_SECTIONS = 5

# Below this many surviving columns the recipe has told us almost nothing
# about this app, and a two-column table of whatever happened to match is
# less useful than the generic fallback.
MIN_LIST_COLUMNS = 3

# Names an identifying column tends to have, best first. A list whose
# rows can't be told apart is not a list, so if the domain's identity
# column is absent from this app we look for the app's own before
# accepting a column set that leads with a number or a date.
_IDENTITY_HINTS = ("name", "title", "label", "subject", "sku", "code",
                   "reference", "number", "email", "slug")


def _column_names(entity_meta: Any) -> list[str]:
    """Pull the column names out of a registry/plan entity record.

    Tolerates both shapes the pipeline uses: a list of field dicts and a
    plain ``{name: meta}`` mapping.
    """
    if isinstance(entity_meta, dict):
        cols = entity_meta.get("fields") or entity_meta.get("columns") or []
    else:
        cols = entity_meta or []
    names: list[str] = []
    if isinstance(cols, dict):
        names = [str(k) for k in cols.keys()]
    elif isinstance(cols, list):
        for f in cols:
            if isinstance(f, dict):
                n = f.get("name") or f.get("column")
                if n:
                    names.append(str(n))
            elif isinstance(f, str):
                names.append(f)
    return names


def _keep_existing(wanted: Iterable[str], have: list[str]) -> list[str]:
    """Filter to columns the entity really has, preserving the domain's
    order and returning the APP's spelling (case/underscore drift is
    common between a vocabulary and a generated schema)."""
    by_norm = {str(c).replace("_", "").lower(): c for c in have}
    out: list[str] = []
    for w in wanted or []:
        hit = by_norm.get(str(w).replace("_", "").lower())
        if hit and hit not in out:
            out.append(hit)
    return out


def _has_identity(cols: Iterable[str]) -> bool:
    return any(any(h in str(c).replace("_", "").lower() for h in _IDENTITY_HINTS)
               for c in cols)


def _find_identity(have: list[str]) -> str | None:
    """The app's own identifying column, by the domain's usual names."""
    folded = {str(c).replace("_", "").lower(): c for c in have}
    for hint in _IDENTITY_HINTS:
        for norm, real in folded.items():
            if norm == hint:
                return real
    for hint in _IDENTITY_HINTS:
        for norm, real in folded.items():
            if hint in norm:
                return real
    return None


_SORT_DIRS = ("asc", "desc")


def _resolve_list_order(recipe: dict, have: Iterable[str]) -> dict:
    """Bind the domain's sort choice to a column the app really has.

    Same contract as the column set: name a column this app never built
    and the order is dropped rather than emitted, because a dataSource
    ordering by a missing column is a runtime error, not a cosmetic miss.
    """
    raw = recipe.get("list_order")
    if not isinstance(raw, dict):
        return {}
    # ``field`` may name several candidates, best first — the same shape
    # dashboard filters use. One domain concept gets spelled
    # ``quantityAvailable`` in one app and ``qtyAvailable`` in the next,
    # and normalising case and underscores does not bridge that.
    raw_field = raw.get("field")
    candidates = raw_field if isinstance(raw_field, (list, tuple)) else [raw_field]
    candidates = [str(c).strip() for c in candidates if str(c or "").strip()]
    if not candidates:
        return {}
    kept = _keep_existing(candidates, have)
    if not kept:
        return {}
    direction = str(raw.get("dir") or "asc").strip().lower()
    if direction not in _SORT_DIRS:
        direction = "asc"
    return {"field": kept[0], "dir": direction}


def resolve_page_recipe(vocabulary: Any,
                        entity_name: str,
                        entity_meta: Any,
                        *,
                        max_columns: int = MAX_LIST_COLUMNS,
                        max_sections: int = MAX_DETAIL_SECTIONS,
                        ) -> dict[str, Any]:
    """Bind one entity's page recipe to the columns the app really has.

    ``entity_name`` is the APP's name for the entity; the vocabulary is
    searched with the same fuzzy matching used for dashboards, so
    ``PurchaseOrder`` finds the ``purchase_orders`` recipe.

    Returns ``{list_columns, detail_sections, filter_chips, list_order}``
    with every
    name rewritten to the app's spelling, or ``{}`` when nothing
    survives — callers branch on emptiness and fall back to their
    existing behaviour.
    """
    recipes = getattr(vocabulary, "page_recipes", None)
    if not isinstance(recipes, dict) or not recipes:
        return {}
    key = match_entity_name(entity_name, list(recipes.keys()))
    recipe = recipes.get(key) if key else None
    if not isinstance(recipe, dict) or not recipe:
        return {}

    have = _column_names(entity_meta)
    if not have:
        return {}

    list_columns = _keep_existing(recipe.get("list_columns") or [], have)
    # Restore an identifying column BEFORE judging the match: a list whose
    # rows can't be told apart is not a list, and the app's own name for
    # that column counts toward how well the recipe fits.
    if list_columns and not _has_identity(list_columns):
        ident = _find_identity(have)
        if ident:
            logger.debug("[page-vocab] %s: recipe lost its identifying column; "
                         "leading with %r instead", entity_name, ident)
            list_columns = [ident] + [c for c in list_columns if c != ident]
    list_columns = list_columns[:max_columns]
    if list_columns and (len(list_columns) < MIN_LIST_COLUMNS
                         or not _has_identity(list_columns)):
        logger.debug("[page-vocab] %s: only %d usable column(s) — deferring to "
                     "the generic column set", entity_name, len(list_columns))
        list_columns = []

    detail_sections: list[dict] = []
    for sec in (recipe.get("detail_sections") or []):
        if not isinstance(sec, dict):
            continue
        fields = _keep_existing(sec.get("fields") or [], have)
        if not fields:
            # A heading with nothing under it is worse than no heading.
            continue
        detail_sections.append({"label": sec.get("label") or "", "fields": fields})
        if len(detail_sections) >= max_sections:
            break

    filter_chips = _keep_existing(recipe.get("filter_chips") or [], have)
    list_order = _resolve_list_order(recipe, have)

    # An order on its own is worth returning: the columns may all have
    # missed while the domain still knows which row belongs on top.
    if not list_columns and not detail_sections and not list_order:
        return {}

    out = {
        "list_columns": list_columns,
        "detail_sections": detail_sections,
        "filter_chips": filter_chips,
        "list_order": list_order,
    }
    logger.info("[page-vocab] %s/%s → %d column(s), %d section(s)",
                getattr(vocabulary, "id", "?"), entity_name,
                len(list_columns), len(detail_sections))
    return out


def _load_brief(root: Any) -> Any:
    """The app's persisted design brief, or None.

    The compose call sites passed ``brief=None``, which silently dropped
    the identity + locked-field signal the merge uses to pick a palette
    and voice — the composition was being made half-blind.
    """
    import json
    from pathlib import Path
    for rel in ("src/contracts/design-brief.json", "src/contracts/brief.json"):
        try:
            f = Path(root) / rel
            if f.is_file():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return None


def vocabulary_for_output_dir(root: Any) -> Any:
    """Load the archetype vocabulary that applies to a generated app.

    Reads the app's own plan for its archetype and runs it through the
    same compose/modify path the collection composer uses, so a
    per-app-composed vocabulary reaches every consumer rather than only
    the one that happened to load it. Returns None on any failure —
    every caller treats absence as "no domain input".
    """
    try:
        import json
        from pathlib import Path
        from services.vocab_composer_pipeline import (
            load_compose_and_modify_vocab_sync,
        )
        plan_path = Path(root) / "src" / "contracts" / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        vocab, _preset, _ = load_compose_and_modify_vocab_sync(
            plan=plan, brief=_load_brief(root), output_dir=root)
        return vocab
    except Exception as exc:  # noqa: BLE001
        logger.debug("[page-vocab] vocabulary load skipped for %s: %s", root, exc)
        return None


def vocabulary_for_plan(plan: Any) -> Any:
    """The vocabulary an app should be designed against.

    Prefers the COMPOSED vocabulary — the LLM merge of the candidate
    business vocabularies, scored against the app's requirement. Falls
    back to the plan's single base archetype only when there is no
    output dir to resolve a composition from (unit-test path).

    The distinction matters: for most of this system's life the merge
    reached only the page *rewriters*, while the maquette authors — the
    layer that actually decides what a screen is — read the single base
    archetype. The composition was computed and then not used where it
    was meant to be used.
    """
    if not isinstance(plan, dict):
        return None
    out = plan.get("_output_dir")
    if out:
        vocab = vocabulary_for_output_dir(out)
        if vocab is not None:
            return vocab
    try:
        from services.archetype_vocabulary import load_vocabulary
        return load_vocabulary(plan.get("archetype"))
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "resolve_page_recipe",
    "vocabulary_for_output_dir",
    "vocabulary_for_plan",
]
