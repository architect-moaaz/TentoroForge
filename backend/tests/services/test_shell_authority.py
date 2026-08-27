"""Tests for Phase 6c — Shell Authority.

Under FORGE_SHELL_AUTHORITY the deterministic shell builder is the
sole writer. Verified:

- The env flag + marker plumb correctly through artifact_authority
- When the deterministic builder produces a renderable shell, the
  composer stamps the ``shell_deterministic_composed`` marker
- When the deterministic builder can't produce (returns None or
  unrenderable) AND the flag is on, ``generate_shell_to_file``
  refuses the LLM fallback and returns None
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services.artifact_authority import (
    is_authority_enabled,
    is_composer_authored,
    is_composer_authored_any,
    should_assert_only,
)


class TestShellAuthorityFlag:
    def test_on_by_default(self, monkeypatch: pytest.MonkeyPatch):
        """Shell authority ships ON. It defaulted off while the deterministic
        shell builder was unproven; leaving it off permanently would have made
        the composer sole-writer in code and never once on a real build."""
        monkeypatch.delenv("FORGE_SHELL_AUTHORITY", raising=False)
        assert is_authority_enabled("shell") is True

    def test_explicit_opt_out_still_works(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "0")
        assert is_authority_enabled("shell") is False

    def test_on_with_truthy(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "1")
        assert is_authority_enabled("shell") is True

    def test_flag_independent_from_page_flags(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        # Turning dashboard on must not activate shell.
        assert is_authority_enabled("shell") is False


class TestShellComposerMarker:
    def test_shell_marker_recognized(self):
        schema = {"meta": {"shell_deterministic_composed": True}}
        assert is_composer_authored(schema, "shell") is True

    def test_shell_marker_does_not_confuse_dashboard(self):
        schema = {"meta": {"shell_deterministic_composed": True}}
        assert is_composer_authored(schema, "dashboard") is False

    def test_composer_authored_any_returns_shell(self):
        schema = {"meta": {"shell_deterministic_composed": True}}
        assert is_composer_authored_any(schema) == (True, "shell")

    def test_should_assert_only_shell(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "1")
        schema = {"meta": {"shell_deterministic_composed": True}}
        assert should_assert_only(schema, "shell") is True

    def test_should_assert_only_shell_flag_off(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        schema = {"meta": {"shell_deterministic_composed": True}}
        assert should_assert_only(schema, "shell") is False


class TestGenerateShellToFileAuthority:
    """Verify the flag makes ``generate_shell_to_file`` refuse the LLM
    fallback when the deterministic builder can't produce a renderable
    shell. Uses an injected deterministic-builder failure to force the
    control path.
    """

    def _run(self, coro):
        return asyncio.run(coro)

    def test_flag_on_deterministic_none_refuses_llm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "1")
        # Force the deterministic path to yield an unrenderable shell.
        from services import shell_guardrail as _sg
        monkeypatch.setattr(_sg, "is_renderable_shell", lambda _s: False)

        # Sentinel — track whether the LLM path fires.
        llm_calls = {"n": 0}

        async def _boom_llm_agent(*args, **kwargs):  # noqa: ARG001
            llm_calls["n"] += 1
            if False:
                yield None  # never reached — but the fn must be an async gen
            return
        from agents import shell_layout_agent as _sla
        monkeypatch.setattr(_sla, "run_shell_layout_agent", _boom_llm_agent)

        result = self._run(_sla.generate_shell_to_file(
            str(tmp_path), plan={}, nav_flow={},
        ))
        # Refused to fall through to the LLM.
        assert result is None
        assert llm_calls["n"] == 0

    def test_flag_off_deterministic_none_falls_through_to_llm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Regression guard: with the flag off the historical fallback
        # behaviour is preserved — the LLM path IS invoked.
        monkeypatch.setenv("FORGE_SHELL_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        from services import shell_guardrail as _sg
        monkeypatch.setattr(_sg, "is_renderable_shell", lambda _s: False)

        llm_calls = {"n": 0}

        async def _stub_llm_agent(*args, **kwargs):  # noqa: ARG001
            llm_calls["n"] += 1
            # Return empty — the outer code will treat this as "no schema"
            # and return None, but the KEY assertion is that we DID reach
            # this fn (contrast with the flag-on case above).
            if False:
                yield None
            return
        from agents import shell_layout_agent as _sla
        monkeypatch.setattr(_sla, "run_shell_layout_agent", _stub_llm_agent)

        self._run(_sla.generate_shell_to_file(
            str(tmp_path), plan={}, nav_flow={},
        ))
        # LLM path was reached (fallback).
        assert llm_calls["n"] == 1
