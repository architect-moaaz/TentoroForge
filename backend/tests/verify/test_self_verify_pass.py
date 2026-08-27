"""Unit tests for services.self_verify_pass — SV-5 skeleton."""
from __future__ import annotations

import os
from unittest.mock import patch

from services.self_verify_pass import is_enabled, is_smith_fix_enabled


def test_is_enabled_defaults_off() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert is_enabled() is False


def test_is_enabled_true_with_env() -> None:
    with patch.dict(os.environ, {"FORGE_SELF_VERIFY": "1"}):
        assert is_enabled() is True


def test_is_smith_fix_defaults_off() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert is_smith_fix_enabled() is False


def test_is_smith_fix_true_with_env() -> None:
    with patch.dict(os.environ, {"FORGE_VERIFY_SMITH_FIX": "1"}):
        assert is_smith_fix_enabled() is True


def test_standard_truthy_values_all_enable() -> None:
    """Slice 1 flag-profile migration: SELF_VERIFY now accepts the same
    truthy vocabulary as every other FORGE_* gate (1/true/yes/on). Previously
    it accepted only "1" which was inconsistent with the rest of the codebase.
    """
    for val in ("1", "true", "yes", "on"):
        with patch.dict(os.environ, {"FORGE_SELF_VERIFY": val}, clear=True):
            assert is_enabled() is True, f"expected {val!r} to enable"


def test_falsy_and_unset_do_not_enable() -> None:
    for val in ("0", "false", "no", "off"):
        with patch.dict(os.environ, {"FORGE_SELF_VERIFY": val}, clear=True):
            assert is_enabled() is False, f"expected {val!r} to leave it off"
    with patch.dict(os.environ, {}, clear=True):
        assert is_enabled() is False


def test_forge_quality_full_enables_without_per_flag_env() -> None:
    """One env var to rule them all — the whole point of Slice 1."""
    with patch.dict(os.environ, {"FORGE_QUALITY": "full"}, clear=True):
        assert is_enabled() is True
        assert is_smith_fix_enabled() is True
