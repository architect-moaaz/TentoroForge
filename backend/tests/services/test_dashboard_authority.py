"""Tests for services.dashboard_authority — Phase 3 gate + helpers."""
from __future__ import annotations

import pytest

from services.dashboard_authority import (
    is_composer_authored,
    is_dashboard_authority_enabled,
    is_dashboard_page,
)


class TestIsDashboardAuthorityEnabled:
    def test_on_by_default(self, monkeypatch: pytest.MonkeyPatch):
        """Default flipped to ON.

        While it defaulted off, the dashboard maquette was authored on every
        build and then discarded: with the authority off the LLM writes the
        dashboard page first and the composer refuses to overwrite an
        already-authored page, so the montage's KPI/chart/activity decisions
        never reached a screen.
        """
        monkeypatch.delenv("FORGE_DASHBOARD_AUTHORITY", raising=False)
        assert is_dashboard_authority_enabled() is True

    def test_on_with_truthy_values(self, monkeypatch: pytest.MonkeyPatch):
        for val in ("1", "true", "yes", "on", "TRUE", "On"):
            monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", val)
            assert is_dashboard_authority_enabled() is True, f"failed for {val!r}"

    def test_blank_is_not_an_opt_out(self, monkeypatch: pytest.MonkeyPatch):
        """An empty value is an unset value — it must not disable the default."""
        for val in ("", "  "):
            monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", val)
            assert is_dashboard_authority_enabled() is True, f"failed for {val!r}"

    def test_off_with_falsy_values(self, monkeypatch: pytest.MonkeyPatch):
        for val in ("0", "false", "no", "off", "OFF", "False"):
            monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", val)
            assert is_dashboard_authority_enabled() is False, f"failed for {val!r}"

    def test_reads_env_per_call(self, monkeypatch: pytest.MonkeyPatch):
        # Runtime toggle without process restart is required so tests
        # (and future runtime feature-flag systems) can flip mid-flight.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        assert is_dashboard_authority_enabled() is True
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
        assert is_dashboard_authority_enabled() is False


class TestIsDashboardPage:
    def test_type_dashboard(self):
        assert is_dashboard_page({"type": "dashboard"}) is True

    def test_type_overview_and_home_also_count(self):
        # Some planners emit synonyms — kept in one place so a new
        # synonym only needs to be added to _DASHBOARD_PAGE_TYPES.
        assert is_dashboard_page({"type": "overview"}) is True
        assert is_dashboard_page({"type": "home"}) is True

    def test_archetype_fallback(self):
        # Planner may write ``archetype`` instead of ``type``.
        assert is_dashboard_page({"archetype": "dashboard"}) is True

    def test_case_insensitive_and_trimmed(self):
        assert is_dashboard_page({"type": "  Dashboard  "}) is True
        assert is_dashboard_page({"type": "DASHBOARD"}) is True

    def test_list_form_detail_return_false(self):
        for kind in ("list", "form", "detail", "settings", "auth", "custom", ""):
            assert is_dashboard_page({"type": kind}) is False, kind

    def test_non_dict_inputs_return_false(self):
        assert is_dashboard_page(None) is False  # type: ignore
        assert is_dashboard_page("dashboard") is False  # type: ignore
        assert is_dashboard_page(["dashboard"]) is False  # type: ignore

    def test_missing_type_and_archetype_returns_false(self):
        # /foo is neither a landing route nor a dashboard-suffix route.
        assert is_dashboard_page({"route": "/foo"}) is False

    def test_admin_type_is_dashboard(self):
        # Ops apps routinely type the admin landing surface as "admin"
        # (not "dashboard") — treated as dashboard-shaped now.
        for t in ("admin", "admin-dashboard", "AdminHome"):
            assert is_dashboard_page({"type": t}) is True, t

    def test_analytics_reports_insights_types(self):
        # Reports/insights/analytics landings share the KPI+chart+list
        # shape — composer authority applies.
        for t in ("analytics", "reports", "insights", "landing"):
            assert is_dashboard_page({"type": t}) is True, t

    def test_route_based_fallback_landing(self):
        # Route wins even when type is a generic "page" — apps whose
        # planner forgot to type the landing correctly still get
        # composer authority.
        for r in ("/", "/home", "/dashboard", "/overview", "/admin"):
            assert is_dashboard_page({"type": "page", "route": r}) is True, r

    def test_route_based_fallback_suffix(self):
        # Nested dashboards: /admin/dashboard, /reports/overview
        assert is_dashboard_page({"type": "page", "route": "/admin/dashboard"}) is True
        assert is_dashboard_page({"type": "page", "route": "/reports/overview"}) is True
        assert is_dashboard_page({"type": "page", "route": "/team/home"}) is True
        assert is_dashboard_page({"type": "page", "route": "/org/admin"}) is True

    def test_route_trailing_slash_normalized(self):
        assert is_dashboard_page({"route": "/admin/"}) is True
        assert is_dashboard_page({"route": "/"}) is True

    def test_route_not_dashboard_shape(self):
        # Content routes that shouldn't trigger authority.
        for r in ("/settings", "/users", "/bookings", "/foo/bar"):
            assert is_dashboard_page({"type": "list", "route": r}) is False, r


class TestIsComposerAuthored:
    def test_missing_meta_returns_false(self):
        assert is_composer_authored({"id": "x"}) is False

    def test_meta_without_marker_returns_false(self):
        assert is_composer_authored({"meta": {"other": True}}) is False

    def test_marker_true_returns_true(self):
        assert is_composer_authored({"meta": {"maquette_composed": True}}) is True

    def test_marker_false_returns_false(self):
        # An explicit False should also read as "not composer-authored" —
        # nothing meaningful sets it to False today, but guards should
        # treat it the same as absent to avoid subtle bypasses.
        assert is_composer_authored({"meta": {"maquette_composed": False}}) is False

    def test_non_dict_returns_false(self):
        assert is_composer_authored(None) is False  # type: ignore
        assert is_composer_authored("not-a-dict") is False  # type: ignore
