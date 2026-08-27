"""Every archetype vocabulary must carry a dashboard + page recipe, and
those recipes may only name things the vocabulary itself declares.

A recipe is hand-authored domain knowledge, which makes it exactly the
kind of artifact that rots quietly: an entity renamed in
``component_preferences`` but not in the recipe still *looks* fine, and
the only symptom is a dashboard tile that silently never renders. These
rules make that a test failure instead.

The self-consistency rule matters more than it looks. A filter value
that isn't in ``status_badges`` is a value the badge layer can't style,
so the section renders unstyled text where the domain promised a status
pill — and a value absent from the vocabulary is usually a value absent
from the app.
"""
from __future__ import annotations

import pytest

from services.archetype_vocabulary import _build_registry

_VALID_OPS = {"count", "sum", "avg"}
_REGISTRY = _build_registry()
_IDS = sorted(_REGISTRY)


def _declared_entities(vocab) -> set[str]:
    return {k.lower() for k in vocab.component_preferences}


def _filter_values(filt) -> list[tuple[str, str]]:
    """Flatten ``{"status": ["a", "b"]}`` → [("status","a"), ("status","b")]."""
    out: list[tuple[str, str]] = []
    for col, val in (filt or {}).items():
        vals = val if isinstance(val, (list, tuple)) else [val]
        out.extend((col, str(v)) for v in vals)
    return out


@pytest.mark.parametrize("vid", _IDS)
def test_every_vocabulary_has_a_dashboard_recipe(vid):
    """Coverage. A vocabulary without one leaves that industry's landing
    page generic — the whole defect this layer exists to fix."""
    recipe = _REGISTRY[vid].dashboard_recipe
    assert recipe.get("kpis"), f"{vid}: no dashboard KPIs"
    assert recipe.get("sections"), f"{vid}: no dashboard sections"


@pytest.mark.parametrize("vid", _IDS)
def test_every_vocabulary_has_page_recipes(vid):
    assert _REGISTRY[vid].page_recipes, f"{vid}: no page recipes"


@pytest.mark.parametrize("vid", _IDS)
def test_dashboard_recipe_is_structurally_sound(vid):
    for kpi in _REGISTRY[vid].dashboard_recipe.get("kpis", []):
        label = kpi.get("label")
        assert label, f"{vid}: KPI with no label"
        assert kpi.get("entity"), f"{vid}/{label}: KPI with no entity"
        op = kpi.get("op", "count")
        assert op in _VALID_OPS, f"{vid}/{label}: unknown op {op!r}"
        if op in ("sum", "avg"):
            assert kpi.get("field"), f"{vid}/{label}: {op} needs a field"
    for sec in _REGISTRY[vid].dashboard_recipe.get("sections", []):
        assert sec.get("title"), f"{vid}: section with no title"
        assert sec.get("entity"), f"{vid}/{sec.get('title')}: no entity"


@pytest.mark.parametrize("vid", _IDS)
def test_recipes_only_name_entities_the_vocabulary_declares(vid):
    """Recipes and component_preferences must agree, or the recipe binds
    to nothing and the page silently falls back to generic."""
    vocab = _REGISTRY[vid]
    declared = _declared_entities(vocab)
    used = {str(s.get("entity", "")).lower()
            for s in (vocab.dashboard_recipe.get("kpis", [])
                      + vocab.dashboard_recipe.get("sections", []))}
    used |= {k.lower() for k in vocab.page_recipes}
    unknown = sorted(used - declared)
    assert not unknown, (
        f"{vid}: recipe names entities absent from component_preferences: "
        f"{unknown}"
    )


@pytest.mark.parametrize("vid", _IDS)
def test_recipe_filter_values_are_declared_statuses(vid):
    """A filter value the vocabulary doesn't know is one the badge layer
    can't style and the app probably can't hold."""
    vocab = _REGISTRY[vid]
    badges = {k.lower() for k in vocab.status_badges}
    offenders: list[str] = []
    for spec in (vocab.dashboard_recipe.get("kpis", [])
                 + vocab.dashboard_recipe.get("sections", [])):
        for col, val in _filter_values(spec.get("filter")):
            # Only status-ish columns are badge-backed; a filter on
            # e.g. `active` boolean or a date column is its own thing.
            if "status" not in col.lower() and "state" not in col.lower():
                continue
            if val.lower() not in badges:
                offenders.append(
                    f"{spec.get('label') or spec.get('title')}: {col}={val}")
    assert not offenders, (
        f"{vid}: filter values missing from status_badges: {offenders}")


@pytest.mark.parametrize("vid", _IDS)
def test_page_recipes_are_structurally_sound(vid):
    for entity, r in _REGISTRY[vid].page_recipes.items():
        assert isinstance(r, dict), f"{vid}/{entity}: recipe is not a dict"
        cols = r.get("list_columns") or []
        assert cols, f"{vid}/{entity}: no list_columns"
        assert len(cols) <= 7, (
            f"{vid}/{entity}: {len(cols)} columns — a list that wide is a "
            f"spreadsheet, not a screen")
        assert len(cols) == len(set(cols)), f"{vid}/{entity}: duplicate columns"
        for sec in (r.get("detail_sections") or []):
            assert sec.get("label"), f"{vid}/{entity}: section with no label"
            assert sec.get("fields"), (
                f"{vid}/{entity}/{sec.get('label')}: section with no fields")


@pytest.mark.parametrize("vid", _IDS)
def test_dashboard_empty_copy_exists(vid):
    """Recipes resolve to nothing on a brand-new app; the empty state is
    what the first-ever visitor actually reads."""
    assert _REGISTRY[vid].signature_states.get("empty_dashboard"), (
        f"{vid}: no empty_dashboard copy")
