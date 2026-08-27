"""Slice 3 wiring tests — derive_page_recipes + apply_recipes_to_brief."""
from __future__ import annotations

import pytest

from schemas.design_brief import (
    DesignBrief, Identity, Layout, Palette, SignatureMove, Typography,
)
from services.composition.apply_recipes import (
    apply_recipes_to_brief,
    derive_page_recipes,
)


def _brief() -> DesignBrief:
    return DesignBrief(
        identity=Identity(domain="Test", register=["structured"], voice="warm_precise"),
        palette=Palette(
            brand="#2D5A8E", accent="#E8A020",
            neutrals_base="#F5F5F5", neutrals_tint="cool",
            surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
            foreground_primary="#111111", foreground_muted="#666666",
        ),
        typography=Typography(display_family="Serif", body_family="Sans"),
        layout=Layout(density="compact", radius="soft_8", grid="12col"),
        signature_moves=[SignatureMove(kind="warm_serif_h1", detail="x")],
    )


# ────────────────────────────────────────────────────────────
# derive_page_recipes
# ────────────────────────────────────────────────────────────

class TestDerivePageRecipes:
    def test_empty_plan_returns_empty(self):
        assert derive_page_recipes({}) == {}
        assert derive_page_recipes(None) == {}  # type: ignore[arg-type]

    def test_page_persona_takes_precedence_over_plan_actor(self):
        plan = {
            "actors": [{"role": "operator"}],
            "pages": [
                {"route": "/home", "persona": "member", "title": "home dashboard"},
            ],
        }
        got = derive_page_recipes(plan)
        # persona "member" + intent "home dashboard" → member_home
        assert got == {"/home": "member_home"}

    def test_plan_actor_fallback_when_page_lacks_persona(self):
        plan = {
            "actors": [{"role": "dispatcher"}],
            "pages": [
                {"route": "/console", "title": "operations console"},
            ],
        }
        got = derive_page_recipes(plan)
        assert got == {"/console": "operator_console"}

    def test_pages_without_recipe_match_are_omitted(self):
        plan = {
            "pages": [
                {"route": "/settings", "title": "settings"},  # no persona, unlikely recipe match
                {"route": "/home", "persona": "member", "title": "your day"},
            ],
        }
        got = derive_page_recipes(plan)
        # /home matches member_home; /settings falls through
        assert "/home" in got
        assert got["/home"] == "member_home"

    def test_multiple_pages_route_independently(self):
        # Task #596 — routes must be home-shaped for home-category recipes;
        # /route (a list-kind path) → the kind gate correctly rejects
        # field_worker_today's home category. Test the intent (per-page
        # persona routes independently) with two genuine home-shaped routes.
        plan = {
            "pages": [
                {"route": "/home",  "persona": "member", "title": "your day"},
                {"route": "/today", "persona": "driver", "title": "field worker today jobs"},
            ],
        }
        got = derive_page_recipes(plan)
        assert got.get("/home") == "member_home"
        assert got.get("/today") == "field_worker_today"

    def test_falls_back_to_slug_or_name_when_no_route(self):
        plan = {
            "pages": [
                {"slug": "member-home", "persona": "member", "title": "your day"},
            ],
        }
        got = derive_page_recipes(plan)
        assert "member-home" in got

    def test_nested_app_shape_pages(self):
        plan = {
            "app_shape": {
                "pages": [
                    {"route": "/home", "persona": "member", "title": "your day"},
                ],
            },
        }
        got = derive_page_recipes(plan)
        assert got == {"/home": "member_home"}


# ────────────────────────────────────────────────────────────
# apply_recipes_to_brief
# ────────────────────────────────────────────────────────────

class TestApplyRecipesToBrief:
    def test_empty_derivation_returns_brief_unchanged(self):
        brief = _brief()
        got = apply_recipes_to_brief(brief, {"pages": []})
        assert got.page_recipes == {}
        # Identity is by-value not by-reference; check they carry equal state.
        assert got.model_dump() == brief.model_dump()

    def test_stamps_derived_recipes(self):
        brief = _brief()
        plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
        got = apply_recipes_to_brief(brief, plan)
        assert got.page_recipes == {"/home": "member_home"}

    def test_existing_page_recipes_win_by_default(self):
        brief = _brief()
        brief = brief.model_copy(update={"page_recipes": {"/home": "creator_workspace"}})
        plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
        got = apply_recipes_to_brief(brief, plan)
        # Existing override kept — derived is a fallback, not authoritative.
        assert got.page_recipes["/home"] == "creator_workspace"

    def test_overwrite_flag_replaces_wholesale(self):
        brief = _brief()
        brief = brief.model_copy(update={"page_recipes": {"/home": "creator_workspace"}})
        plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
        got = apply_recipes_to_brief(brief, plan, overwrite=True)
        assert got.page_recipes == {"/home": "member_home"}

    def test_returns_new_brief_not_mutation(self):
        brief = _brief()
        plan = {"pages": [{"route": "/home", "persona": "member", "title": "your day"}]}
        got = apply_recipes_to_brief(brief, plan)
        # Original untouched.
        assert brief.page_recipes == {}
        assert got is not brief
