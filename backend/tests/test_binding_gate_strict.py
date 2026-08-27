"""Tests for the binding+registry gate strict-by-default decision.

Only the pure mode-decision helper `_binding_gate_is_strict` is exercised here;
the SSE streaming in `_stream_binding_gate` is not driven (it needs a rendered
scaffold). The helper is the single source of truth both call sites ride.
"""
from routers.generate import _binding_gate_is_strict


def test_unset_defaults_to_strict():
    # No env / empty → STRICT (fail-safe): defects don't ship silently.
    assert _binding_gate_is_strict(None) is True
    assert _binding_gate_is_strict("") is True
    assert _binding_gate_is_strict("   ") is True


def test_explicit_strict_aliases_are_strict():
    for v in ("strict", "on", "1", "hard", "STRICT", " On "):
        assert _binding_gate_is_strict(v) is True, v


def test_warn_escape_hatch_is_not_strict():
    for v in ("warn", "off", "0", "false", "advisory", "WARN", " off "):
        assert _binding_gate_is_strict(v) is False, v


def test_unrecognized_defaults_to_strict():
    # Fail-safe: anything we don't recognize still fails the build.
    assert _binding_gate_is_strict("banana") is True
