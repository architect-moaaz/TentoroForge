"""Tests for services.artifact_authority — Phase 6 generic authority."""
from __future__ import annotations

import pytest

from services.artifact_authority import (
    is_authority_enabled,
    is_composer_authored,
    is_composer_authored_any,
    is_page_of_kind,
    should_assert_only,
    should_assert_only_any,
)


# ─────────────────────────── flag gate ─────────────────────────────────


class TestIsAuthorityEnabled:
    def test_all_artifacts_on_by_default(self, monkeypatch: pytest.MonkeyPatch):
        """Every composer is sole writer by default.

        These flags each defaulted OFF while their composer was unproven.
        A feature gate that is never switched on doesn't de-risk the
        feature — it deletes it while leaving the code in the tree.
        """
        for env in ("FORGE_DASHBOARD_AUTHORITY", "FORGE_COLLECTION_AUTHORITY",
                    "FORGE_RECORD_AUTHORITY", "FORGE_SHELL_AUTHORITY"):
            monkeypatch.delenv(env, raising=False)
        for k in ("dashboard", "collection", "record", "shell"):
            assert is_authority_enabled(k) is True

    def test_each_artifact_can_be_opted_out_independently(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")
        for env in ("FORGE_DASHBOARD_AUTHORITY", "FORGE_COLLECTION_AUTHORITY",
                    "FORGE_SHELL_AUTHORITY"):
            monkeypatch.delenv(env, raising=False)
        assert is_authority_enabled("record") is False
        for k in ("dashboard", "collection", "shell"):
            assert is_authority_enabled(k) is True

    def test_flags_are_independent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        # Explicit opt-out — a bare delenv would now read as ON.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        assert is_authority_enabled("collection") is True
        assert is_authority_enabled("dashboard") is False
        assert is_authority_enabled("record") is False

    def test_unknown_artifact_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        # Guard against a typo silently enabling the wrong artifact. This
        # matters more now that known artifacts default ON: an unrecognised
        # key must stay False rather than inherit the permissive default.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        assert is_authority_enabled("dashbord") is False
        assert is_authority_enabled("") is False
        assert is_authority_enabled("Dashboard") is False  # case-sensitive


# ─────────────────────────── page-type test ────────────────────────────


class TestIsPageOfKind:
    def test_collection_types(self):
        for t in ("list", "kanban", "calendar", "cards", "timeline", "board", "grid"):
            assert is_page_of_kind({"type": t}, "collection") is True, t
        assert is_page_of_kind({"type": "dashboard"}, "collection") is False
        assert is_page_of_kind({"type": "form"}, "collection") is False

    def test_record_types(self):
        for t in ("form", "detail", "create", "edit", "record", "new"):
            assert is_page_of_kind({"type": t}, "record") is True, t
        assert is_page_of_kind({"type": "list"}, "record") is False

    def test_dashboard_types(self):
        for t in ("dashboard", "overview", "home"):
            assert is_page_of_kind({"type": t}, "dashboard") is True

    def test_archetype_fallback(self):
        # Some planners write archetype instead of type.
        assert is_page_of_kind({"archetype": "kanban"}, "collection") is True

    def test_case_insensitive(self):
        assert is_page_of_kind({"type": "  KANBAN  "}, "collection") is True

    def test_non_dict_and_missing_type(self):
        assert is_page_of_kind(None, "collection") is False  # type: ignore
        assert is_page_of_kind({}, "collection") is False
        assert is_page_of_kind("kanban", "collection") is False  # type: ignore

    def test_unknown_artifact_returns_false(self):
        assert is_page_of_kind({"type": "kanban"}, "unknown") is False


# ─────────────────────────── composer marker ──────────────────────────


class TestIsComposerAuthored:
    def test_collection_marker(self):
        schema = {"meta": {"collection_maquette_composed": True}}
        assert is_composer_authored(schema, "collection") is True
        # Same schema is NOT dashboard-composer-authored.
        assert is_composer_authored(schema, "dashboard") is False

    def test_record_marker(self):
        schema = {"meta": {"record_maquette_composed": True}}
        assert is_composer_authored(schema, "record") is True

    def test_dashboard_marker(self):
        schema = {"meta": {"maquette_composed": True}}
        assert is_composer_authored(schema, "dashboard") is True

    def test_missing_meta_returns_false(self):
        assert is_composer_authored({}, "collection") is False

    def test_marker_false_returns_false(self):
        # Explicit False → treat as absent (defensive).
        schema = {"meta": {"collection_maquette_composed": False}}
        assert is_composer_authored(schema, "collection") is False

    def test_non_dict_returns_false(self):
        assert is_composer_authored(None, "collection") is False  # type: ignore
        assert is_composer_authored("nope", "collection") is False  # type: ignore

    def test_unknown_artifact_returns_false(self):
        schema = {"meta": {"maquette_composed": True}}
        assert is_composer_authored(schema, "unknown-kind") is False


# ─────────────────────────── combined helper ──────────────────────────


class TestShouldAssertOnly:
    def test_true_when_flag_on_and_marker_present(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        schema = {"meta": {"collection_maquette_composed": True}}
        assert should_assert_only(schema, "collection") is True

    def test_false_when_flag_off(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        schema = {"meta": {"collection_maquette_composed": True}}
        assert should_assert_only(schema, "collection") is False

    def test_false_when_marker_absent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        assert should_assert_only({}, "collection") is False

    def test_wrong_artifact_flag_doesnt_trigger(self, monkeypatch: pytest.MonkeyPatch):
        # Turning on the dashboard flag must not silently activate
        # assert-mode on a collection-composed schema.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        schema = {"meta": {"collection_maquette_composed": True}}
        assert should_assert_only(schema, "collection") is False


# ─────────────────────────── cross-artifact helpers ───────────────────


class TestCrossArtifactHelpers:
    def test_composer_authored_any_returns_artifact(self):
        assert is_composer_authored_any({"meta": {"collection_maquette_composed": True}}) == (True, "collection")
        assert is_composer_authored_any({"meta": {"maquette_composed": True}}) == (True, "dashboard")
        assert is_composer_authored_any({"meta": {"record_maquette_composed": True}}) == (True, "record")

    def test_composer_authored_any_none(self):
        assert is_composer_authored_any({}) == (False, None)
        assert is_composer_authored_any({"meta": {"other": True}}) == (False, None)
        assert is_composer_authored_any(None) == (False, None)  # type: ignore

    def test_should_assert_only_any_uses_matching_flag(self, monkeypatch: pytest.MonkeyPatch):
        # Collection marker + collection flag → True.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        monkeypatch.delenv("FORGE_DASHBOARD_AUTHORITY", raising=False)
        schema = {"meta": {"collection_maquette_composed": True}}
        assert should_assert_only_any(schema) is True

    def test_should_assert_only_any_wrong_flag_off(self, monkeypatch: pytest.MonkeyPatch):
        # Dashboard flag on doesn't rescue a collection-marked schema
        # from getting rewritten by cross-artifact guards.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        schema = {"meta": {"collection_maquette_composed": True}}
        assert should_assert_only_any(schema) is False

    def test_should_assert_only_any_no_marker(self):
        assert should_assert_only_any({}) is False


class TestFlagReadersAgree:
    """The two authority modules must never disagree about ``dashboard``.

    Regression: ``artifact_authority`` duplicated the env read instead of
    delegating, so when ``dashboard_authority``'s default flipped ON the
    guards keyed off ``artifact_authority`` stayed in rewrite mode and
    kept editing composer-authored dashboards.
    """

    def test_dashboard_delegates_to_its_owning_module(self, monkeypatch):
        from services import artifact_authority as aa
        from services import dashboard_authority as da

        monkeypatch.delenv("FORGE_DASHBOARD_AUTHORITY", raising=False)
        assert aa.is_authority_enabled("dashboard") is da.is_dashboard_authority_enabled()

    def test_agree_when_explicitly_off(self, monkeypatch):
        from services import artifact_authority as aa
        from services import dashboard_authority as da

        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
        assert aa.is_authority_enabled("dashboard") is False
        assert aa.is_authority_enabled("dashboard") is da.is_dashboard_authority_enabled()

    def test_agree_when_explicitly_on(self, monkeypatch):
        from services import artifact_authority as aa
        from services import dashboard_authority as da

        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        assert aa.is_authority_enabled("dashboard") is True
        assert aa.is_authority_enabled("dashboard") is da.is_dashboard_authority_enabled()

    def test_unknown_artifact_is_false(self):
        from services import artifact_authority as aa

        assert aa.is_authority_enabled("not-an-artifact") is False
