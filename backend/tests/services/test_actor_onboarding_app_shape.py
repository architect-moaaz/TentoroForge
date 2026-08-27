"""Tests for M3-T3: _decide_auth_gating + _ensure_auth_pages read
plan.app_shape.auth.

The four-axis substrate's auth.surface primitive is authoritative
over the historic entity-presence heuristic. `none` = no auth,
`modal` = LoginModal (no route pages), `route`/`sso-only` = the
existing /login+/signup routes."""
from __future__ import annotations

import pytest

from agents.planner import _decide_auth_gating, _ensure_auth_pages


def _shape(surface: str, gating: str = "on-load") -> dict:
    return {
        "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
        "auth": {"surface": surface, "gating": gating},
        "nav": {"menu": "sidebar-links", "back": "crumb"},
        "workflows": {"executionMode": "await-with-progress"},
        "data": {"readShape": "list", "denormalization": "moderate"},
        "identity": {"usageMode": "multi-user-team"},
    }


# ══════════════════════════════════════════════════════════════════
# _decide_auth_gating — reads app_shape.auth.surface first
# ══════════════════════════════════════════════════════════════════


class TestDecideAuthGatingWithShape:
    def test_shape_none_forces_ungated(self):
        # Even with entities (heuristic would gate), shape=none wins.
        plan = {
            "app_shape": _shape("none"),
            "entities": [{"name": "User"}],
        }
        assert _decide_auth_gating(plan) is False

    def test_shape_modal_forces_gated(self):
        # No entities (heuristic would ungate), but shape=modal is gated.
        plan = {"app_shape": _shape("modal"), "entities": []}
        assert _decide_auth_gating(plan) is True

    def test_shape_route_forces_gated(self):
        plan = {"app_shape": _shape("route"), "entities": []}
        assert _decide_auth_gating(plan) is True

    def test_shape_sso_only_forces_gated(self):
        plan = {"app_shape": _shape("sso-only"), "entities": []}
        assert _decide_auth_gating(plan) is True

    def test_explicit_authgated_still_wins(self):
        # User-supplied plan.authGated override beats shape derivation
        # (manual preference > automatic).
        plan = {"app_shape": _shape("none"), "authGated": True}
        assert _decide_auth_gating(plan) is True

    def test_no_shape_falls_through_to_heuristic(self):
        # Plan without app_shape → existing entity-heuristic behavior.
        plan = {"entities": [{"name": "Order"}]}
        assert _decide_auth_gating(plan) is True

    def test_no_shape_no_entities_ungated(self):
        assert _decide_auth_gating({"entities": []}) is False


# ══════════════════════════════════════════════════════════════════
# _ensure_auth_pages — modal auth strips /login and /signup routes
# ══════════════════════════════════════════════════════════════════


class TestEnsureAuthPagesModal:
    def test_modal_shape_strips_login_and_signup(self):
        plan = {
            "app_shape": _shape("modal"),
            "pages": [
                {"route": "/login", "name": "Login", "type": "auth"},
                {"route": "/signup", "name": "Sign Up", "type": "auth"},
                {"route": "/dashboard", "name": "Dashboard", "type": "list"},
            ],
        }
        result = _ensure_auth_pages(plan, gated=True)
        routes = {p.get("route") for p in result["pages"]}
        assert "/login" not in routes
        assert "/signup" not in routes
        assert "/dashboard" in routes  # non-auth pages survive

    def test_modal_shape_does_not_add_pages_when_absent(self):
        plan = {"app_shape": _shape("modal"), "pages": [{"route": "/", "type": "list"}]}
        result = _ensure_auth_pages(plan, gated=True)
        routes = {p.get("route") for p in result["pages"]}
        assert "/login" not in routes
        assert "/signup" not in routes
        assert "/" in routes

    def test_route_shape_adds_login_when_missing(self):
        # shape=route → existing behavior: add /login when gated + missing
        plan = {
            "app_shape": _shape("route"),
            "pages": [{"route": "/dashboard", "type": "list"}],
            "actors": [],
        }
        result = _ensure_auth_pages(plan, gated=True)
        routes = {p.get("route") for p in result["pages"]}
        assert "/login" in routes

    def test_ungated_strips_login_regardless_of_shape(self):
        # gated=False path is unchanged
        plan = {
            "app_shape": _shape("modal"),
            "pages": [
                {"route": "/login", "type": "auth"},
                {"route": "/", "type": "list"},
            ],
        }
        result = _ensure_auth_pages(plan, gated=False)
        routes = {p.get("route") for p in result["pages"]}
        assert "/login" not in routes
        assert "/" in routes

    def test_no_shape_falls_through_to_legacy(self):
        # No app_shape → existing gated-adds-login behavior
        plan = {
            "pages": [{"route": "/dashboard", "type": "list"}],
            "actors": [],
        }
        result = _ensure_auth_pages(plan, gated=True)
        routes = {p.get("route") for p in result["pages"]}
        assert "/login" in routes


# ══════════════════════════════════════════════════════════════════
# End-to-end: shape=none produces an app with no login page
# ══════════════════════════════════════════════════════════════════


class TestSnap2AppFlow:
    def test_snap2app_shape_no_login_page(self):
        # Snap2App-shaped plan: modal auth + none menu + capture interaction
        snap2app = {
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient",
                           "primaryInteraction": "capture", "density": "spacious"},
                "auth": {"surface": "modal", "gating": "on-action"},
                "nav": {"menu": "none", "back": "history"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "list", "denormalization": "aggressive"},
                "identity": {"usageMode": "single-session"},
            },
            "entities": [{"name": "scan_session"}, {"name": "price_result"}],
            "pages": [
                {"route": "/", "type": "hero"},
                {"route": "/scan", "type": "detail"},
                {"route": "/history", "type": "list"},
            ],
        }
        # Gated=True because auth.surface=modal
        assert _decide_auth_gating(snap2app) is True
        result = _ensure_auth_pages(snap2app, gated=True)
        routes = {p.get("route") for p in result["pages"]}
        # No /login or /signup pages emitted
        assert "/login" not in routes
        assert "/signup" not in routes
        # But the real pages survive
        assert "/" in routes and "/scan" in routes and "/history" in routes

    def test_tip_calculator_ungated(self):
        # Tip calculator: no auth at all
        plan = {
            "app_shape": {
                "layout": {"shell": "none", "hero": "none",
                           "primaryInteraction": "form", "density": "spacious"},
                "auth": {"surface": "none", "gating": "none"},
                "nav": {"menu": "none", "back": "none"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "single-record", "denormalization": "none"},
                "identity": {"usageMode": "single-session"},
            },
            "entities": [{"name": "bill"}],
            "pages": [{"route": "/", "type": "hero"}],
        }
        assert _decide_auth_gating(plan) is False
