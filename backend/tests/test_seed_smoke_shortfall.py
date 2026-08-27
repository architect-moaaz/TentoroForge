"""Tests for seed-smoke row-shortfall detection (empty-table-where-planned).

Pure output parsing — no Docker, no DB. Covers `detect_seed_row_shortfall` and
its effect on `parse_seed_output`'s success verdict.
"""
from services import seed_smoke


def test_shortfall_from_mismatch_marker():
    out = "❌ SEED MISMATCH: customers planned 10 inserted 0\nSEEDED_OK\n"
    assert seed_smoke.detect_seed_row_shortfall(out) == ["customers"]


def test_shortfall_from_seeded_zero_line():
    out = "🌱 seeding...\nseeded 0/8 orders\nSEEDED_OK\n"
    assert seed_smoke.detect_seed_row_shortfall(out) == ["orders"]


def test_no_shortfall_when_all_seeded():
    out = "seeded 8/8 users\nseeded 3/3 orders\nseeded 5/5 customers\nSEEDED_OK\n"
    assert seed_smoke.detect_seed_row_shortfall(out) == []


def test_multiple_shortfalls_deduped_and_ordered():
    out = (
        "seeded 0/8 orders\n"
        "❌ SEED MISMATCH: customers planned 10 inserted 0\n"
        "seeded 0/8 orders\n"  # duplicate → collapsed
    )
    assert seed_smoke.detect_seed_row_shortfall(out) == ["orders", "customers"]


def test_planned_zero_is_not_a_shortfall():
    # A table that planned nothing and inserted nothing is fine, not a defect.
    out = "seeded 0/0 audit_log\nSEEDED_OK\n"
    assert seed_smoke.detect_seed_row_shortfall(out) == []


def test_parse_marks_fail_on_row_shortfall():
    # Clean exit + sentinel + no error markers, but a table landed zero rows.
    out = (
        "Running migrations...\n"
        "seeded 5/5 users\n"
        "❌ SEED MISMATCH: orders planned 8 inserted 0\n"
        "SEEDED_OK\n"
    )
    res = seed_smoke.parse_seed_output(0, out)
    assert res["ok"] is False
    assert res["seeded"] is True
    assert res["row_shortfall"] == ["orders"]
    assert "orders" in seed_smoke.summarize(res)


def test_parse_ok_when_no_shortfall():
    out = "seeded 8/8 users\nseeded 3/3 orders\nSEEDED_OK\n"
    res = seed_smoke.parse_seed_output(0, out)
    assert res["ok"] is True
    assert res["row_shortfall"] == []
