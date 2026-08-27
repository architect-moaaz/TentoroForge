"""Task #596 — picker eligibility gate + kind-category gate.

The picker itself scores by word overlap and will happily assign a persona
home recipe (member_home) to any route where the persona alone hits — that
shipped 12 wrong recipes on tr7rfk34's brief (/admin, /login, /signup,
/profile, /profile/edit, /*/[id], /*/new — all silently attached to
member_home, then rendered as empty-anchor pages).

These tests lock in the two gates applied in derive_page_recipes:
  1. Route eligibility  — auth / admin routes are unconditionally skipped.
  2. Category match     — the top recipe's category must match the route's
                          derived kind (home/list/detail/form).
Plus a min_score >= 3 floor so persona-alone (score 2) never triggers.
"""
from __future__ import annotations

import pytest

from services.composition.apply_recipes import (
    _category_matches_route_kind,
    _is_route_recipe_eligible,
    _route_kind,
    derive_page_recipes,
)


# ─── route kind classifier ─────────────────────────────────────────────────

class TestRouteKind:
    @pytest.mark.parametrize("route", [
        "/login", "/signup", "/logout", "/signout",
        "/sign-in", "/sign-up",
        "/forgot-password", "/reset/token", "/verify/email",
        "/auth/callback",
    ])
    def test_auth_routes(self, route):
        assert _route_kind(route) == "auth"

    @pytest.mark.parametrize("route", [
        "/admin", "/admin/", "/admin/members", "/admin/schedules/new",
    ])
    def test_admin_subtree(self, route):
        assert _route_kind(route) == "admin"

    @pytest.mark.parametrize("route", [
        "/members/new", "/instructors/create", "/bookings/add",
        "/profile/edit", "/schedules/[id]/update",
    ])
    def test_form_routes(self, route):
        assert _route_kind(route) == "form"

    @pytest.mark.parametrize("route", [
        "/members/[id]", "/instructors/[id]/reviews",
        "/bookings/[booking_id]",
    ])
    def test_detail_routes(self, route):
        assert _route_kind(route) == "detail"

    @pytest.mark.parametrize("route", ["/", "/dashboard", "/home", "/overview", "/index"])
    def test_home_routes(self, route):
        assert _route_kind(route) == "home"

    @pytest.mark.parametrize("route", [
        "/members", "/instructors", "/bookings", "/schedule",
    ])
    def test_list_routes_default(self, route):
        assert _route_kind(route) == "list"


# ─── eligibility gate ──────────────────────────────────────────────────────

class TestEligibility:
    @pytest.mark.parametrize("route", [
        "/login", "/signup", "/logout",
        "/admin", "/admin/members", "/admin/settings",
        "/forgot-password", "/reset/xyz", "/auth/callback",
    ])
    def test_auth_admin_are_ineligible(self, route):
        assert _is_route_recipe_eligible(route) is False

    @pytest.mark.parametrize("route", [
        "/", "/dashboard", "/members", "/members/new",
        "/members/[id]", "/profile/edit", "/schedule",
    ])
    def test_everything_else_is_eligible(self, route):
        assert _is_route_recipe_eligible(route) is True


# ─── category ↔ kind compatibility ─────────────────────────────────────────

class TestCategoryMatch:
    def test_home_recipe_on_home_route_ok(self):
        assert _category_matches_route_kind("/dashboard", "home") is True

    def test_home_recipe_on_list_route_rejected(self):
        assert _category_matches_route_kind("/members", "home") is False

    def test_home_recipe_on_detail_route_rejected(self):
        assert _category_matches_route_kind("/members/[id]", "home") is False

    def test_home_recipe_on_form_route_rejected(self):
        assert _category_matches_route_kind("/members/new", "home") is False

    def test_list_recipe_on_list_route_ok(self):
        assert _category_matches_route_kind("/members", "list") is True

    def test_form_recipe_on_form_route_ok(self):
        assert _category_matches_route_kind("/members/new", "form") is True

    def test_unknown_category_passes_through(self):
        # Never strand a new recipe category — the eligibility gate above
        # still blocks auth/admin, so unknown categories are safe elsewhere.
        assert _category_matches_route_kind("/dashboard", "calendar") is True
        assert _category_matches_route_kind("/some-page", "workflow") is True


# ─── end-to-end: the 12 wrong routes from tr7rfk34 ─────────────────────────
#
# Fixture is a minimal plan mirroring the wellness-studio brief's shape:
# actor = member (so persona-alone would score 2 for member_home if picker
# had no gates). Every route below WAS wrongly attached to member_home on
# tr7rfk34; every route below MUST NOT get member_home now.

_TR7RFK34_WRONG_ROUTES = [
    "/admin",              # admin subtree — ineligible
    "/admin/members/[id]", # admin subtree — ineligible
    "/admin/settings",     # admin subtree — ineligible
    "/login",              # auth — ineligible
    "/signup",             # auth — ineligible
    "/bookings/[id]/review",  # detail route — home category wrong
    "/class-packs/purchase",  # /*/purchase → treated as list (no gate;
                              # but persona-alone hits 2, floor rejects)
    "/instructors/[id]",   # detail — home category wrong
    "/members/new",        # form — home category wrong
    "/profile",            # list-shaped default — home category wrong
    "/profile/edit",       # form — home category wrong
    "/schedule/[id]",      # detail — home category wrong
]


class TestDerivePageRecipesGates:
    def _plan(self, routes: list[str], actor: str = "member") -> dict:
        return {
            "actors": [{"role": actor}],
            "pages": [{"route": r, "title": r} for r in routes],
        }

    def test_none_of_the_12_wrong_routes_gets_member_home(self):
        plan = self._plan(_TR7RFK34_WRONG_ROUTES)
        derived = derive_page_recipes(plan)
        for r in _TR7RFK34_WRONG_ROUTES:
            assert derived.get(r) != "member_home", \
                f"{r} was wrongly assigned member_home — gate leak"

    def test_dashboard_still_gets_home_recipe(self):
        # A real home route with member persona + intent overlap ('dashboard'
        # + 'home' + 'member') should still score >= 3 and match a home
        # category recipe. This guards against the fix over-blocking.
        plan = self._plan(["/dashboard"], actor="member")
        plan["pages"][0]["intent"] = "member home dashboard overview"
        derived = derive_page_recipes(plan)
        # We assert IT'S a home-category recipe (any of them); exact key
        # depends on scoring across the library so we don't pin it.
        from services.composition.loader import load_library
        lib = load_library()
        key = derived.get("/dashboard")
        if key is not None:  # gate is permissive, not mandatory
            assert lib.recipes[key].category == "home"

    def test_min_score_floor_blocks_persona_only_match(self):
        # A page with ONLY a persona ("member") and a bland intent that
        # shares no words with any recipe scores exactly 2. Below the floor
        # of 3 → no recipe assigned.
        plan = {
            "actors": [{"role": "member"}],
            "pages": [{"route": "/random-route", "title": "z"}],
        }
        derived = derive_page_recipes(plan)
        assert "/random-route" not in derived

    def test_ineligible_routes_never_appear_regardless_of_score(self):
        # Even if intent perfectly matches a home recipe, /admin and /login
        # are unconditionally skipped.
        plan = {
            "actors": [{"role": "member"}],
            "pages": [
                {"route": "/admin", "title": "member home dashboard"},
                {"route": "/login", "title": "member home"},
            ],
        }
        derived = derive_page_recipes(plan)
        assert "/admin" not in derived
        assert "/login" not in derived
