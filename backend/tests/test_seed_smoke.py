"""Tests for services.seed_smoke — no Docker is booted here.

We only exercise the guard rails (flag off, start.sh missing) and the pure
output-parsing classifier. The actual `start.sh --seed-only` run needs Docker
and is intentionally NOT invoked.
"""
import os

import pytest

from services import seed_smoke


@pytest.fixture(autouse=True)
def _clear_flag(monkeypatch):
    monkeypatch.delenv(seed_smoke.FLAG_ENV, raising=False)


def test_skipped_when_flag_off(tmp_path):
    # Even with a real start.sh present, no flag → skip (no Docker).
    (tmp_path / "start.sh").write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    res = seed_smoke.run_seed_smoke(str(tmp_path))
    assert res["skipped"] is True
    assert res["ok"] is None
    assert seed_smoke.FLAG_ENV in res["reason"]


def test_skipped_when_start_sh_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(seed_smoke.FLAG_ENV, "1")
    res = seed_smoke.run_seed_smoke(str(tmp_path))
    assert res["skipped"] is True
    assert "start.sh" in res["reason"]


def test_is_enabled(monkeypatch):
    assert seed_smoke.is_enabled() is False
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv(seed_smoke.FLAG_ENV, truthy)
        assert seed_smoke.is_enabled() is True
    monkeypatch.setenv(seed_smoke.FLAG_ENV, "0")
    assert seed_smoke.is_enabled() is False


def test_parse_success():
    out = "🌱 Seeding database...\n✅ Database seeded\nSEEDED_OK\n"
    res = seed_smoke.parse_seed_output(0, out)
    assert res["ok"] is True
    assert res["seeded"] is True
    assert res["errors"] == []


def test_parse_seed_error_detected():
    out = (
        "Running migrations...\n"
        'PostgresError: column "password" of relation "users" does not exist\n'
        "⚠️  Seeding failed (continuing) — login/seed data may be missing.\n"
        "SEEDED_OK\n"  # sentinel present but errors override → still a FAIL
    )
    res = seed_smoke.parse_seed_output(0, out)
    assert res["ok"] is False
    assert any("password" in e for e in res["errors"])
    assert "seed-smoke FAIL" in seed_smoke.summarize(res)


def test_parse_missing_sentinel_is_fail():
    res = seed_smoke.parse_seed_output(0, "did some stuff, no sentinel\n")
    assert res["ok"] is False
    assert res["seeded"] is False


def test_parse_nonzero_exit_is_fail():
    res = seed_smoke.parse_seed_output(1, "migrate step\nSEEDED_OK\n")
    assert res["ok"] is False


def test_parse_timeout_is_fail():
    res = seed_smoke.parse_seed_output(-1, "SEEDED_OK\n", timed_out=True)
    assert res["ok"] is False
    assert res["timed_out"] is True
    assert "TIMEOUT" in seed_smoke.summarize(res)


def test_summarize_skipped():
    assert "SKIP" in seed_smoke.summarize({"skipped": True, "reason": "flag off"})
