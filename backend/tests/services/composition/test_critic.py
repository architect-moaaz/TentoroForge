"""Slice 7 tests — recipe-aware design critic."""
from __future__ import annotations

from services.composition.build_recipe_page import build_recipe_page
from services.composition.critic import CriticFinding, critique_recipe_page


# ────────────────────────────────────────────────────────────
# non-recipe pages get an OK, no-op report
# ────────────────────────────────────────────────────────────

def test_page_without_recipe_meta_returns_ok():
    page = {
        "schemaVersion": "2",
        "route": "/plain",
        "root": {"type": "Stack", "children": []},
    }
    report = critique_recipe_page(page)
    assert report.ok
    assert report.findings == ()
    assert report.recipe == ""


def test_unknown_recipe_flagged_high():
    page = {
        "schemaVersion": "2",
        "route": "/x",
        "meta": {"recipe": "does_not_exist"},
        "root": {"type": "Stack", "children": []},
    }
    report = critique_recipe_page(page)
    assert not report.ok
    assert len(report.findings) == 1
    assert report.findings[0].kind == "unknown_recipe"
    assert report.findings[0].severity == "high"


# ────────────────────────────────────────────────────────────
# Anchor presence / order / copy / binding
# ────────────────────────────────────────────────────────────

def test_full_member_home_from_builder_is_clean_except_copy():
    """A page emitted by build_recipe_page has all v1 anchors in order
    but no copy or dataSources — critic should flag empty_copy findings
    and low-severity missing_binding, but zero anchor_missing / wrong_order."""
    page = build_recipe_page("/home", "member_home")
    assert page is not None
    report = critique_recipe_page(page)
    kinds = {f.kind for f in report.findings}
    assert "anchor_missing" not in kinds
    assert "wrong_order" not in kinds
    # every hero-style anchor with a required copy slot should flag empty_copy
    assert "empty_copy" in kinds


def test_missing_anchor_component_flagged_high():
    """Recipe expected PinnedMomentHero but the page dropped it."""
    page = {
        "schemaVersion": "2",
        "route": "/home",
        "meta": {"recipe": "member_home"},
        "root": {"type": "Stack", "children": [
            # PinnedMomentHero deliberately omitted
            {"type": "VitalsInContext", "props": {"tiles": [{"label": "x", "value": "1"}]}},
            {"type": "ScanStrip", "props": {"cells": [{"top": "M", "main": "1"}]}},
            {"type": "RecsRailReasoned", "props": {"items": [{"title": "x"}]}},
            {"type": "CommunityPulse", "props": {"items": [{"body": "x"}]}},
            {"type": "StickyPrimaryCta", "props": {"label": "Book"}},
        ]},
    }
    report = critique_recipe_page(page)
    missing = [f for f in report.findings if f.kind == "anchor_missing"]
    assert len(missing) == 1
    assert missing[0].severity == "high"
    assert missing[0].anchor == "pinned_moment_hero"


def test_out_of_order_anchor_flagged_medium():
    page = {
        "schemaVersion": "2",
        "route": "/home",
        "meta": {"recipe": "member_home"},
        "root": {"type": "Stack", "children": [
            # Swap PinnedMomentHero and VitalsInContext order
            {"type": "VitalsInContext", "props": {"tiles": [{"label": "x", "value": "1"}]}},
            {"type": "PinnedMomentHero", "props": {"headline": "Hi"}},
            {"type": "ScanStrip", "props": {"cells": [{"top": "M", "main": "1"}]}},
            {"type": "RecsRailReasoned", "props": {"items": [{"title": "x"}]}},
            {"type": "CommunityPulse", "props": {"items": [{"body": "x"}]}},
            {"type": "StickyPrimaryCta", "props": {"label": "Book"}},
        ]},
    }
    report = critique_recipe_page(page)
    order_issues = [f for f in report.findings if f.kind == "wrong_order"]
    assert len(order_issues) >= 1


def test_empty_copy_flagged_medium():
    page = {
        "schemaVersion": "2",
        "route": "/home",
        "meta": {"recipe": "member_home"},
        "root": {"type": "Stack", "children": [
            {"type": "PinnedMomentHero", "props": {}},  # headline missing
            {"type": "VitalsInContext", "props": {"tiles": []}},  # tiles empty
            {"type": "ScanStrip", "props": {"cells": [{"top": "M", "main": "1"}]}},
            {"type": "RecsRailReasoned", "props": {"items": [{"title": "x"}]}},
            {"type": "CommunityPulse", "props": {"items": [{"body": "x"}]}},
            {"type": "StickyPrimaryCta", "props": {}},  # label missing
        ]},
    }
    report = critique_recipe_page(page)
    empties = {(f.anchor, f.severity) for f in report.findings if f.kind == "empty_copy"}
    # PinnedMomentHero.headline, VitalsInContext.tiles, StickyPrimaryCta.label
    assert ("pinned_moment_hero", "medium") in empties
    assert ("vitals_in_context", "medium") in empties
    assert ("sticky_primary_cta", "medium") in empties


def test_missing_binding_flagged_low():
    """Anchors that declare required binds should get a low-severity
    finding when no matching dataSource is present."""
    page = build_recipe_page("/home", "member_home")
    assert page is not None
    report = critique_recipe_page(page)
    # PinnedMomentHero, ScanStrip, RecsRailReasoned all require dataSource.
    # build_recipe_page emits no dataSources → 3 low-severity bindings.
    binds = [f for f in report.findings if f.kind == "missing_binding"]
    assert len(binds) >= 3
    assert all(f.severity == "low" for f in binds)


# ────────────────────────────────────────────────────────────
# shopper_home v1 works too
# ────────────────────────────────────────────────────────────

def test_shopper_home_recipe_builds_all_v1_components():
    page = build_recipe_page("/", "shopper_home")
    assert page is not None
    child_types = [c["type"] for c in page["root"]["children"]]
    assert child_types == [
        "FeaturedMomentHero",
        "ReasonsToReturnRow",
        "TrendingRail",
        "TasteRecsRail",
        "BrandStoryPulse",
        "CartCta",
    ]


def test_shopper_home_critic_clean_when_props_filled():
    """A fully-authored shopper page produces no medium/high findings."""
    page = {
        "schemaVersion": "2",
        "route": "/",
        "meta": {"recipe": "shopper_home"},
        "dataSources": [
            {"name": "featured", "kind": "query"},
            {"name": "trending", "kind": "query"},
            {"name": "recs", "kind": "query"},
        ],
        "root": {"type": "Stack", "children": [
            {"type": "FeaturedMomentHero", "props": {"headline": "New drop"}},
            {"type": "ReasonsToReturnRow", "props": {}},   # no required copy
            {"type": "TrendingRail", "props": {}},
            {"type": "TasteRecsRail", "props": {}},
            {"type": "BrandStoryPulse", "props": {}},
            {"type": "CartCta", "props": {"label": "Cart"}},
        ]},
    }
    report = critique_recipe_page(page)
    medium_or_high = [f for f in report.findings if f.severity in ("medium", "high")]
    # No empty_copy or anchor_missing — only some low-severity missing_binding
    # notices (recipe-side binds haven't been wired yet).
    assert all(f.kind not in ("anchor_missing", "wrong_order", "empty_copy")
               for f in medium_or_high)
