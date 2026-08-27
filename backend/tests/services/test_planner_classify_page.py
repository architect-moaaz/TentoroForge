"""Tests for the inlined ``_classify_page_from_route`` helper in
``agents.planner`` — the deterministic six-type page taxonomy that runs
whenever the LLM did not author a ``page.type`` on the plan.

These tests replace ``test_page_type_classifier[_planner].py``: the
standalone module was deleted as part of Spec D W2 and the helper now
lives with its sole caller.
"""
from __future__ import annotations

import pytest

from agents.planner import _classify_page_from_route as classify


# ── error ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", ["/error", "/not-found", "/404", "/500"])
def test_error_routes(route):
    assert classify(route) == "error"


def test_error_takes_precedence_over_form_hint():
    # description says "form" but route is /error → error wins
    assert classify("/error", description="user creation form",
                    entity="User") == "error"


# ── auth ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", [
    "/login", "/signup", "/sign-in", "/sign-up",
    "/forgot-password", "/reset-password", "/register",
])
def test_auth_routes(route):
    assert classify(route) == "auth"


def test_auth_precedes_form_description():
    # /login + "login form" description → still auth
    assert classify("/login", description="login form") == "auth"


# ── form ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", ["/users/new", "/users/create", "/users/edit"])
def test_form_suffix(route):
    assert classify(route) == "form"


def test_form_description_keyword():
    assert classify("/contact", name="Contact",
                    description="Contact form for inquiries") == "form"


def test_form_suffix_beats_dynamic():
    # /requests/new has both a suffix and a dynamic-looking tail; suffix wins
    assert classify("/requests/new", entity="LeaveRequest") == "form"


# ── detail ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("route", ["/users/[id]", "/users/:id",
                                    "/orders/[orderId]"])
def test_detail_dynamic_segment(route):
    assert classify(route, entity="User") == "detail"


def test_detail_ignores_list_description():
    # dynamic segment wins over a description that says "list"
    assert classify("/users/[id]", description="List of items",
                    entity="User") == "detail"


# ── dashboard ────────────────────────────────────────────────────────

def test_dashboard_root():
    assert classify("/") == "dashboard"


def test_dashboard_slash_dashboard():
    assert classify("/dashboard") == "dashboard"


def test_dashboard_by_description():
    assert classify("/analytics",
                    description="Overview of usage metrics") == "dashboard"


def test_dashboard_when_empty_route():
    assert classify("") == "dashboard"


def test_dashboard_after_whitespace_strip():
    assert classify("  /  ") == "dashboard"


# ── list ─────────────────────────────────────────────────────────────

def test_list_plural_route_with_entity():
    assert classify("/users", entity="User") == "list"


def test_list_by_description():
    assert classify("/directory",
                    description="Browse the staff directory") == "list"


def test_list_fallback():
    # nothing matches — falls through to list
    assert classify("/settings") == "list"
