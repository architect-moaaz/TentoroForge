"""Tests for services.route_intent (B-022.6, .7, .9 root fix)."""

from __future__ import annotations

import pytest

from services.route_intent import classify_route, RouteIntent


# ---------- singleton — profile / settings / account ----------------------

class TestSingletonRoutes:
    @pytest.mark.parametrize("route", [
        "/profile", "/profile/", "/settings", "/account",
        "/my-profile", "/my-settings", "/preferences",
    ])
    def test_singleton_kind(self, route):
        r = classify_route(route, entities=["User"])
        assert r.kind == "singleton_current_user"
        assert r.filter == {"id": "{{currentUser.id}}"}

    def test_resolves_user_entity(self):
        r = classify_route("/profile", entities=["User", "Recipe"])
        assert r.entity == "User"


# ---------- my-X — current-user-scope list --------------------------------

class TestMyXRoutes:
    def test_my_recipes(self):
        r = classify_route("/my-recipes", entities=["Recipe", "User"])
        assert r.kind == "current_user_scope_list"
        assert r.entity == "Recipe"
        assert r.filter == {"ownerId": "{{currentUser.id}}"}

    def test_my_orders(self):
        r = classify_route("/my-orders", entities=["Order"])
        assert r.kind == "current_user_scope_list"
        assert r.entity == "Order"

    def test_my_prefix_matches_various_cases(self):
        for path in ("/my-plants", "/my_plants", "/myplants"):
            r = classify_route(path, entities=["Plant"])
            assert r.kind == "current_user_scope_list", path
            assert r.entity == "Plant", path


# ---------- role-scoped lists ---------------------------------------------

class TestRoleScopeList:
    def test_home_cooks_filters_role_cook(self):
        r = classify_route("/home-cooks", entities=["User"])
        assert r.kind == "role_scope_list"
        assert r.entity == "User"
        assert r.filter == {"role": "cook"}

    def test_reviewers(self):
        r = classify_route("/reviewers", entities=["User"])
        assert r.kind == "role_scope_list"
        assert r.filter == {"role": "reviewer"}

    def test_recruiters(self):
        r = classify_route("/recruiters", entities=["User"])
        assert r.filter == {"role": "recruiter"}


# ---------- default CRUD passes through -----------------------------------

class TestDefaultCrud:
    def test_generic_entity_list(self):
        r = classify_route("/orders", entities=["Order"])
        # /orders doesn't match a role pattern (no plural like "buyers") and
        # isn't singleton — falls through to CRUD.
        assert r.kind == "crud"
        assert r.filter is None

    def test_unknown_segment(self):
        r = classify_route("/completely-unknown", entities=["Recipe"])
        assert r.kind == "crud"

    def test_empty_route(self):
        r = classify_route("", entities=None)
        assert r.kind == "crud"


# ---------- entity resolution edge cases ----------------------------------

class TestEntityResolution:
    def test_case_insensitive(self):
        r = classify_route("/my-recipes", entities=["recipe"])
        assert r.entity == "recipe"

    def test_singular_declared_entity_matches_plural_route(self):
        r = classify_route("/my-plants", entities=["Plant"])
        assert r.entity == "Plant"

    def test_no_entities_leaves_entity_none(self):
        r = classify_route("/my-recipes", entities=None)
        assert r.kind == "current_user_scope_list"
        assert r.entity is None
        # Still returns filter — the caller can decide.
        assert r.filter == {"ownerId": "{{currentUser.id}}"}


# ---------- covers UAT specifics ------------------------------------------

class TestUatSpecifics:
    def test_b022_6_profile(self):
        """B-022.6: /profile should be singleton, not User CRUD."""
        r = classify_route("/profile", entities=["User"])
        assert r.kind == "singleton_current_user"

    def test_b022_7_home_cooks(self):
        """B-022.7: /home-cooks should filter Users by role=cook."""
        r = classify_route("/home-cooks", entities=["User"])
        assert r.kind == "role_scope_list"
        assert r.filter == {"role": "cook"}

    def test_b022_9_my_recipes(self):
        """B-022.9: /my-recipes should filter Recipes by owner."""
        r = classify_route("/my-recipes", entities=["Recipe"])
        assert r.kind == "current_user_scope_list"
        assert r.filter == {"ownerId": "{{currentUser.id}}"}
