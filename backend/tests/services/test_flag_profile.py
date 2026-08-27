"""Tests for services.flag_profile — the FORGE_* meta-flag resolver.

Slice 1 of the flag-consolidation work. Rules the module enforces:

* ``FORGE_QUALITY=full``  → every gate returns True (regardless of per-flag env)
* ``FORGE_QUALITY=off``   → every gate returns False (regardless of per-flag env)
* ``FORGE_QUALITY`` unset → fall back to per-flag env with the caller's default
* Per-flag env is truthy on ``1 / true / yes / on`` (case-insensitive)
"""
from __future__ import annotations

import pytest

from services.flag_profile import is_on


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Every test starts with a clean slate.
    for k in ("FORGE_QUALITY", "FORGE_TEST_FLAG", "FORGE_TEST_DEFAULT_ON"):
        monkeypatch.delenv(k, raising=False)
    yield


class TestQualityFullOverride:
    def test_full_returns_true_when_per_flag_is_unset(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "full")
        assert is_on("FORGE_TEST_FLAG") is True

    def test_full_returns_true_when_per_flag_is_explicitly_off(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "full")
        monkeypatch.setenv("FORGE_TEST_FLAG", "0")
        assert is_on("FORGE_TEST_FLAG") is True

    def test_full_ignores_default_false(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "full")
        assert is_on("FORGE_TEST_FLAG", default=False) is True

    def test_full_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "FULL")
        assert is_on("FORGE_TEST_FLAG") is True


class TestQualityOffOverride:
    def test_off_returns_false_when_per_flag_is_unset(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "off")
        assert is_on("FORGE_TEST_FLAG") is False

    def test_off_returns_false_when_per_flag_is_explicitly_on(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "off")
        monkeypatch.setenv("FORGE_TEST_FLAG", "1")
        assert is_on("FORGE_TEST_FLAG") is False

    def test_off_ignores_default_true(self, monkeypatch):
        monkeypatch.setenv("FORGE_QUALITY", "off")
        assert is_on("FORGE_TEST_FLAG", default=True) is False


class TestPerFlagFallback:
    def test_returns_default_when_env_unset(self):
        assert is_on("FORGE_TEST_FLAG", default=False) is False
        assert is_on("FORGE_TEST_DEFAULT_ON", default=True) is True

    def test_env_1_is_truthy(self, monkeypatch):
        monkeypatch.setenv("FORGE_TEST_FLAG", "1")
        assert is_on("FORGE_TEST_FLAG") is True

    def test_env_true_yes_on_are_truthy(self, monkeypatch):
        for val in ("true", "TRUE", "yes", "YES", "on", "ON"):
            monkeypatch.setenv("FORGE_TEST_FLAG", val)
            assert is_on("FORGE_TEST_FLAG") is True, f"expected {val!r} to be truthy"

    def test_env_0_false_no_off_are_falsy(self, monkeypatch):
        # Explicit falsy strings override even default=True.
        for val in ("0", "false", "FALSE", "no", "NO", "off", "OFF"):
            monkeypatch.setenv("FORGE_TEST_FLAG", val)
            assert is_on("FORGE_TEST_FLAG", default=True) is False, (
                f"expected {val!r} to override default=True to False"
            )

    def test_empty_string_env_preserves_default(self, monkeypatch):
        # Empty-string env is functionally "unset" (a common shell pattern:
        # `export FORGE_X=`) → preserve the caller's default.
        monkeypatch.setenv("FORGE_TEST_FLAG", "")
        assert is_on("FORGE_TEST_FLAG", default=True) is True
        assert is_on("FORGE_TEST_FLAG", default=False) is False

    def test_default_true_survives_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("FORGE_TEST_DEFAULT_ON", raising=False)
        assert is_on("FORGE_TEST_DEFAULT_ON", default=True) is True


class TestQualityUnknownValue:
    def test_unknown_quality_value_falls_through_to_per_flag(self, monkeypatch):
        # e.g. FORGE_QUALITY=partial or a typo — don't silently ignore, but
        # don't break either. Fall through to per-flag semantics.
        monkeypatch.setenv("FORGE_QUALITY", "partial")
        monkeypatch.setenv("FORGE_TEST_FLAG", "1")
        assert is_on("FORGE_TEST_FLAG") is True
        monkeypatch.delenv("FORGE_TEST_FLAG")
        assert is_on("FORGE_TEST_FLAG", default=False) is False
