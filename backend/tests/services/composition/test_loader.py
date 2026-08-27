"""Loader + validator tests for the composition recipe library.

These tests do two jobs:

1. Guarantee the on-disk library is self-consistent — every recipe cites
   anchors that exist, every anchor is referenced by at least one recipe,
   bidirectional appears_in index agrees with recipe.anchors.

2. Exercise the validator on synthesised bad inputs so a future edit that
   breaks cross-references fails a test rather than silently degrading
   generation quality.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.composition import loader
from services.composition.loader import (
    Anchor,
    Category,
    CompositionLibraryError,
    Recipe,
    validate_library,
)


# ── on-disk library must be self-consistent ────────────────────
def test_ships_50_recipes_across_10_categories():
    """The library ships at v1 with 50 recipes / 10 categories."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    assert len(lib.recipes) == 50, f"expected 50 recipes, got {len(lib.recipes)}"
    assert len(lib.categories) == 10, (
        f"expected 10 categories, got {len(lib.categories)}"
    )


def test_declared_recipe_counts_match_actual():
    """Each category's declared recipe_count matches the actual count."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    for cat in lib.categories:
        actual = sum(1 for r in lib.recipes.values() if r.category == cat.id)
        assert actual == cat.recipe_count, (
            f"category {cat.id!r}: declared {cat.recipe_count} recipes, "
            f"actual {actual}"
        )


def test_every_recipe_anchor_exists():
    """Every anchor cited by every recipe resolves in anchors.json."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    for r_name, r in lib.recipes.items():
        for a_name in r.anchors:
            assert a_name in lib.anchors, (
                f"recipe {r_name!r} cites unknown anchor {a_name!r}"
            )


def test_no_orphan_anchors():
    """Every anchor is referenced by at least one recipe."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    all_referenced = {a for r in lib.recipes.values() for a in r.anchors}
    orphans = set(lib.anchors) - all_referenced
    assert not orphans, f"orphan anchors (declared, never used): {sorted(orphans)}"


def test_bidirectional_appears_in_agrees_with_recipe_anchors():
    """anchor.appears_in must match recipe.anchors in both directions."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    for a_name, a in lib.anchors.items():
        for r_name in a.appears_in:
            assert r_name in lib.recipes, (
                f"anchor {a_name!r}: appears_in cites unknown recipe {r_name!r}"
            )
            assert a_name in lib.recipes[r_name].anchors, (
                f"anchor {a_name!r}: claims to appear in {r_name!r} but that "
                f"recipe does not list it"
            )


def test_every_recipe_has_a_persona():
    """Every recipe declares at least one persona so discovery can match it."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    for r_name, r in lib.recipes.items():
        assert r.personas, f"recipe {r_name!r} has no personas"


def test_every_recipe_has_at_least_one_anchor():
    """A recipe with zero anchors is meaningless."""
    loader.load_library.cache_clear()
    lib = loader.load_library()
    for r_name, r in lib.recipes.items():
        assert r.anchors, f"recipe {r_name!r} has no anchors"


# ── validator catches synthetic breakage ───────────────────────
def _make_cat(id="home"):
    return Category(id=id, label="Home", recipe_count=1)


def _make_recipe(name="foo", category="home", anchors=("hero",)):
    return Recipe(
        name=name, category=category, label="Foo", purpose="p",
        personas=("member",), anchors=tuple(anchors),
    )


def _make_anchor(name="hero", appears_in=("foo",), categories=("home",)):
    return Anchor(
        name=name, categories=tuple(categories),
        appears_in=tuple(appears_in), binds_required=(), binds_optional=(),
        copy_slots=(), tokens=(), component="Hero",
    )


def test_validator_flags_missing_anchor_reference():
    """A recipe citing a non-existent anchor must fail validation."""
    cats = [_make_cat()]
    recipes = {"foo": _make_recipe(anchors=("missing_anchor",))}
    anchors = {"hero": _make_anchor()}
    with pytest.raises(CompositionLibraryError, match="missing_anchor"):
        validate_library(cats, recipes, anchors)


def test_validator_flags_orphan_anchor():
    """An anchor referenced by zero recipes must fail validation."""
    cats = [_make_cat()]
    recipes = {"foo": _make_recipe(anchors=("hero",))}
    anchors = {
        "hero": _make_anchor(),
        "orphan": _make_anchor(name="orphan", appears_in=()),
    }
    with pytest.raises(CompositionLibraryError, match="orphan"):
        validate_library(cats, recipes, anchors)


def test_validator_flags_unknown_category():
    """A recipe whose category is not in the declared list must fail."""
    cats = [_make_cat("home")]
    recipes = {"foo": _make_recipe(category="quantum", anchors=("hero",))}
    anchors = {"hero": _make_anchor()}
    with pytest.raises(CompositionLibraryError, match="quantum"):
        validate_library(cats, recipes, anchors)


def test_validator_flags_appears_in_pointing_at_unknown_recipe():
    """An anchor whose appears_in cites a non-existent recipe must fail."""
    cats = [_make_cat()]
    recipes = {"foo": _make_recipe(anchors=("hero",))}
    anchors = {"hero": _make_anchor(appears_in=("foo", "ghost"))}
    with pytest.raises(CompositionLibraryError, match="ghost"):
        validate_library(cats, recipes, anchors)


def test_validator_flags_asymmetric_appears_in():
    """appears_in must be a mirror of recipe.anchors."""
    cats = [_make_cat()]
    # Anchor claims to appear in `foo`, but `foo` does NOT list this anchor
    recipes = {"foo": _make_recipe(anchors=("hero",))}
    anchors = {
        "hero": _make_anchor(appears_in=("foo",)),
        "lonely": _make_anchor(name="lonely", appears_in=("foo",)),
    }
    with pytest.raises(CompositionLibraryError, match="lonely"):
        validate_library(cats, recipes, anchors)


# ── accessors ──────────────────────────────────────────────────
def test_list_categories_returns_all_ten():
    loader.load_library.cache_clear()
    cats = loader.list_categories()
    ids = {c.id for c in cats}
    assert ids == {
        "home", "list", "detail", "form", "flow",
        "system", "workflow", "location", "learning", "calendar",
    }


def test_list_recipes_filters_by_category():
    loader.load_library.cache_clear()
    home = loader.list_recipes("home")
    assert len(home) == 10
    assert all(r.category == "home" for r in home)


def test_get_recipe_returns_expected_shape():
    loader.load_library.cache_clear()
    r = loader.get_recipe("member_home")
    assert r.category == "home"
    assert "pinned_moment_hero" in r.anchors
    assert "member" in r.personas


def test_get_recipe_raises_on_unknown():
    loader.load_library.cache_clear()
    with pytest.raises(CompositionLibraryError, match="ghost"):
        loader.get_recipe("ghost")


def test_get_anchor_returns_expected_shape():
    loader.load_library.cache_clear()
    a = loader.get_anchor("pinned_moment_hero")
    assert "member_home" in a.appears_in
    assert a.component  # non-empty component name


def test_get_anchor_raises_on_unknown():
    loader.load_library.cache_clear()
    with pytest.raises(CompositionLibraryError, match="ghost"):
        loader.get_anchor("ghost")


# ── load caching ───────────────────────────────────────────────
def test_load_library_is_cached():
    """Second call to load_library returns the same object (LRU-cached)."""
    loader.load_library.cache_clear()
    a = loader.load_library()
    b = loader.load_library()
    assert a is b, "load_library must be cached"
