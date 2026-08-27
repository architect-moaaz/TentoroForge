"""Tests for fidelity_runner — covers the mapping + skip paths.

We don't exercise real Playwright here (slow + flaky in CI); the runner
delegates to playwright internally and we test that the mapping and
result-shape logic is correct."""
from __future__ import annotations
import pytest
from services.fidelity_mapper import fidelity_page_type_for


def test_fidelity_page_type_for_login_route():
    assert fidelity_page_type_for("/login") == "login"
    assert fidelity_page_type_for("/signin") == "login"
    assert fidelity_page_type_for("/sign-in") == "login"
    assert fidelity_page_type_for("/auth/callback") == "login"


def test_fidelity_page_type_for_login_by_role():
    assert fidelity_page_type_for("/some-route", "Sign in page") == "login"


def test_fidelity_page_type_for_dashboard():
    assert fidelity_page_type_for("/dashboard") == "dashboard"
    assert fidelity_page_type_for("/home") == "dashboard"


def test_fidelity_page_type_for_list():
    assert fidelity_page_type_for("/users") in (None, "list")
    assert fidelity_page_type_for("/users/list") == "list"


def test_fidelity_page_type_for_form():
    assert fidelity_page_type_for("/users/new") == "form"
    assert fidelity_page_type_for("/users/[id]/edit") == "form"


def test_fidelity_page_type_for_detail():
    assert fidelity_page_type_for("/users/[id]") == "detail"


def test_fidelity_page_type_for_calendar():
    assert fidelity_page_type_for("/calendar") == "calendar"
    assert fidelity_page_type_for("/schedule") == "calendar"


def test_fidelity_page_type_for_unsupported_returns_none():
    # report, console, wizard etc. don't have references — must be None
    assert fidelity_page_type_for("/reports") is None
    assert fidelity_page_type_for("/console") is None
    assert fidelity_page_type_for("/wizard") is None


@pytest.mark.asyncio
async def test_runner_yields_skip_when_no_pages():
    from services.fidelity_runner import run_fidelity_scoring
    events = []
    async for evt in run_fidelity_scoring(
        output_dir="/tmp/x", project_id="x", plan={"domain": "saas", "pages": []}
    ):
        events.append(evt)
    assert len(events) == 1
    assert events[0]["type"] == "skip"
    assert events[0]["reason"] == "no_pages"
