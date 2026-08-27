"""O3 — uniform validate→repair→retry gates (services.phase_checks)."""
from __future__ import annotations

import json

import pytest

from services import phase_checks as pc


def _check(validate, repair=None, max_attempts=2, strict=False):
    return pc.PhaseCheck("t", validate, repair, max_attempts, strict)


def test_pass_first_try_no_repair_called():
    called = {"repair": 0}
    r = pc.run_check(_check(lambda o, p: (True, []),
                            lambda o, p: called.__setitem__("repair", 1)),
                     "/tmp/x", {})
    assert r["passed"] and r["attempts"] == 0 and called["repair"] == 0


def test_fail_then_repair_then_pass():
    state = {"fixed": False}

    def validate(o, p):
        return (state["fixed"], [] if state["fixed"] else [{"kind": "k", "detail": "d"}])

    def repair(o, p):
        state["fixed"] = True

    r = pc.run_check(_check(validate, repair), "/tmp/x", {})
    assert r["passed"] and r["attempts"] == 1 and r["unresolved"] == []


def test_exhausted_attempts_quarantines():
    calls = {"n": 0}

    def repair(o, p):
        calls["n"] += 1

    r = pc.run_check(_check(lambda o, p: (False, [{"kind": "still", "detail": "broken"}]),
                            repair, max_attempts=2), "/tmp/x", {})
    assert not r["passed"] and r["attempts"] == 2 and calls["n"] == 2
    assert r["unresolved"] == [{"kind": "still", "detail": "broken"}]


def test_validator_only_check_no_retry_loop():
    r = pc.run_check(_check(lambda o, p: (False, [{"kind": "x", "detail": "y"}])),
                     "/tmp/x", {})
    assert not r["passed"] and r["attempts"] == 0


def test_strict_check_raises_when_unresolved():
    with pytest.raises(RuntimeError, match="strict check"):
        pc.run_check(_check(lambda o, p: (False, [{"kind": "x", "detail": "y"}]),
                            strict=True), "/tmp/x", {})


def test_validator_crash_quarantines_not_raises():
    def boom(o, p):
        raise ValueError("kaput")

    r = pc.run_check(_check(boom), "/tmp/x", {})
    assert not r["passed"]
    assert r["unresolved"][0]["kind"] == "validator_crash"


def test_write_quarantine_persists(tmp_path):
    pc.write_quarantine(str(tmp_path), [{"check": "c", "passed": False}])
    data = json.loads((tmp_path / "src" / "contracts" / "quarantine.json").read_text())
    assert data["quarantine"][0]["check"] == "c"


def test_registry_covers_expected_phases():
    assert {c.name for c in pc.checks_for("contracts")} == {"contract_completeness"}
    assert {c.name for c in pc.checks_for("schema")} == {"schema_files_complete"}
    assert {c.name for c in pc.checks_for("pages")} == {"pages_coverage"}
    assert {c.name for c in pc.checks_for("finish")} == {"binding_contract"}
    assert pc.checks_for("design") == []


def test_binding_check_strict_follows_env(monkeypatch):
    monkeypatch.setenv("FORGE_BINDING_GATE", "strict")
    assert pc.checks_for("finish")[0].strict is True
    monkeypatch.setenv("FORGE_BINDING_GATE", "warn")
    assert pc.checks_for("finish")[0].strict is False
