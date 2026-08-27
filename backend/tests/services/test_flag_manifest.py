"""The manifest must stay the complete answer to "what is running?".

A declared list is only reassuring while it is exhaustive. The moment
someone adds `os.getenv("FORGE_NEW_THING")` in a service without listing
it, the file goes back to being a partial picture and the whole exercise
is undone. That is what the first test here prevents — it fails the build
rather than letting the list quietly fall behind.

The rest pin the semantics: the manifest supplies defaults, the
environment still overrides for debugging, and config values / modes stay
out (they have no shipped boolean).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from services.flag_manifest import SHIPPED, is_declared, shipped_default, summary
from services.flag_profile import is_on

BACKEND = Path(__file__).resolve().parents[2]
PAT = re.compile(r'FORGE_[A-Z0-9_]+')
PRUNE = {"node_modules", "__pycache__", ".git", "dist", ".next", "output", ".venv", "venv"}

# Excluded by design — see the manifest docstring. Config values carry a
# string/number, modes carry one of several words; neither is a shipped
# boolean and forcing them into one would lose their meaning.
CONFIG = re.compile(
    r'MODEL|URL|TIMEOUT|_DIR|PATH|KEY|SECRET|PORT|HOST|ROUNDS|LOOKBACK|'
    r'CONCURRENCY|LIMIT|_MAX|_MIN|SIZE|TTL|RETRIES|BASE|TOKEN|THRESHOLD|'
    r'BUDGET|GAP|TOLERANCE|RETENTION')
MODE = re.compile(r'GATE$|QUALITY$|PROFILE$|MODE$|LEVEL$')


def _production_gates() -> set[str]:
    """Every binary FORGE_* gate referenced by non-test backend code."""
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(BACKEND):
        dirnames[:] = [d for d in dirnames if d not in PRUNE]
        if f"{os.sep}tests" in dirpath:
            continue
        for name in filenames:
            if not name.endswith(".py"):
                continue
            try:
                text = Path(dirpath, name).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for flag in PAT.findall(text):
                if not CONFIG.search(flag) and not MODE.search(flag):
                    found.add(flag)
    return found


class TestManifestIsExhaustive:
    def test_every_production_gate_is_declared(self):
        """The one test that keeps this file honest.

        If this fails you added a gate without declaring it. Add it to
        SHIPPED with the state it ships in — that is the whole cost, and
        it buys everyone the ability to read one file instead of grepping
        the tree.
        """
        undeclared = sorted(_production_gates() - set(SHIPPED))
        assert not undeclared, (
            f"{len(undeclared)} binary gate(s) read in production but not "
            f"declared in services/flag_manifest.py: {undeclared}"
        )

    def test_no_stale_entries(self):
        """A gate nobody reads any more is noise in the other direction."""
        stale = sorted(set(SHIPPED) - _production_gates())
        assert not stale, (
            f"{len(stale)} declared gate(s) no longer read anywhere — delete "
            f"them from the manifest: {stale}"
        )

    def test_every_value_is_a_real_bool(self):
        bad = {k: v for k, v in SHIPPED.items() if not isinstance(v, bool)}
        assert not bad, f"non-boolean entries: {bad}"

    def test_config_and_modes_stay_out(self):
        intruders = [f for f in SHIPPED if CONFIG.search(f) or MODE.search(f)]
        assert not intruders, (
            f"config values / modes have no shipped boolean: {intruders}")


class TestManifestDoesNotChangeBehaviour:
    """The manifest documents; it does not decide.

    Making it authoritative over ``is_on``'s default was tried and
    reverted — an inferred default disagreed with what call sites pass, in
    both directions, and silently moved ~25 behaviours including Smith and
    self-verify. Reconciling a gate is a per-gate decision, not a
    derivation, so these tests pin that reading the manifest costs nothing.
    """

    def test_callers_default_is_untouched(self, monkeypatch):
        monkeypatch.delenv("FORGE_QUALITY", raising=False)
        monkeypatch.delenv("FORGE_AUTOFIX_V2", raising=False)
        assert is_on("FORGE_AUTOFIX_V2", default=True) is True
        assert is_on("FORGE_AUTOFIX_V2", default=False) is False

    def test_env_still_wins(self, monkeypatch):
        monkeypatch.delenv("FORGE_QUALITY", raising=False)
        monkeypatch.setenv("FORGE_AUTOFIX_V2", "1")
        assert is_on("FORGE_AUTOFIX_V2", default=False) is True

    def test_effective_reports_env_on_top_of_declared(self):
        from services.flag_manifest import effective
        eff = effective({"FORGE_AUTOFIX_V2": "1"})
        assert eff["FORGE_AUTOFIX_V2"] is True
        assert SHIPPED["FORGE_AUTOFIX_V2"] is False, "declared state unchanged"


class TestTheTransportGatesSurvived:
    """Deriving the manifest from .env alone would have recorded these as
    False — they are absent from .env and default ON in code. That would
    have switched off the pipeline transport in a change that looked like
    pure cleanup."""

    @pytest.mark.parametrize("flag", [
        "FORGE_LANGGRAPH", "FORGE_LANGGRAPH_PIPELINE",
        "FORGE_DETERMINISTIC_WORKFLOWS", "FORGE_DETERMINISTIC_CRUD",
    ])
    def test_code_default_on_gates_are_declared_on(self, flag):
        assert SHIPPED[flag] is True, f"{flag} ships ON; the manifest says otherwise"


class TestHelpers:
    def test_is_declared(self):
        assert is_declared("FORGE_LANGGRAPH")
        assert not is_declared("FORGE_MADE_UP")

    def test_shipped_default_fallback(self):
        assert shipped_default("FORGE_MADE_UP", True) is True

    def test_summary_reports_both_numbers(self):
        """Default-on and on-in-this-environment are different questions;
        the census must not blur them."""
        s = summary()
        assert str(len(SHIPPED)) in s
        assert "by default" in s and "in this environment" in s
