"""Tests for scripts/fleet.py — the pure parts (no LLM, no generation)."""
from __future__ import annotations

import json

import pytest

from scripts.fleet import (
    load_baselines, load_fixture, render_table, select_fixtures,
)


def test_select_all_fixtures_sorted():
    names = select_fixtures(None)
    assert names == sorted(names)
    assert "doc-intel" in names and "leave-management" in names


def test_select_only_subset():
    assert select_fixtures("banking,doc-intel") == ["banking", "doc-intel"]


def test_select_unknown_fixture_exits():
    with pytest.raises(SystemExit):
        select_fixtures("nope-not-real")


def test_load_fixture_shapes():
    fx = load_fixture("doc-intel")
    assert fx["plan"] and fx["plan"].get("data_models")
    assert len(fx["description"]) > 40
    assert fx["meta"]["profile"] == "fast"
    # leave-management started plan-less; the Phase-0 fleet run seeded its
    # plan (by design — _replan writes plans back for plan-less fixtures),
    # so it now loads like the others. A missing plan.json → plan=None is
    # covered by load_fixture's read path either way.
    lm = load_fixture("leave-management")
    assert lm["plan"] and lm["plan"].get("data_models")


def test_render_table_with_baseline_delta():
    results = [
        {"fixture": "doc-intel", "status": "ok", "functional": 80.0,
         "design": 85.0, "composite": 80.0, "wall_s": 312.0},
        {"fixture": "banking", "status": "failed", "error": "boom"},
        {"fixture": "leave-management", "status": "skipped",
         "reason": "no plan.json — run with --replan to seed"},
    ]
    baselines = {"doc-intel": {"composite": 82.0}}
    table = render_table(results, baselines)
    assert "| doc-intel | ok | 80.0 | 85.0 | 80.0 | -2.0 |" in table
    assert "failed (boom)" in table
    assert "skipped" in table
    # no baseline → em dash
    assert table.count("—") >= 1


def test_render_table_no_baselines():
    results = [{"fixture": "doc-intel", "status": "ok", "functional": 80.0,
                "design": 85.0, "composite": 80.0, "wall_s": 10.0}]
    table = render_table(results, {})
    assert "| — |" in table


def test_load_baselines_missing_is_empty(tmp_path, monkeypatch):
    import scripts.fleet as fleet
    monkeypatch.setattr(fleet, "BASELINES_PATH", tmp_path / "none.json")
    assert fleet.load_baselines() == {}


def test_load_baselines_reads_file(tmp_path, monkeypatch):
    import scripts.fleet as fleet
    p = tmp_path / "baselines.json"
    p.write_text(json.dumps({"doc-intel": {"composite": 80.0}}), encoding="utf-8")
    monkeypatch.setattr(fleet, "BASELINES_PATH", p)
    assert fleet.load_baselines()["doc-intel"]["composite"] == 80.0


# ───────────────────────── S5: bless + compare ──────────────────────────

def _summary(**overrides):
    base = {
        "run_ts": "20260817T000000Z",
        "results": [
            {"fixture": "doc-intel", "status": "ok", "functional": 68.0,
             "design": 97.0, "composite": 68.0, "tier": "static",
             "wall_s": 367.0, "scorecard": "/nope/scorecard.json"},
            {"fixture": "leave-management", "status": "skipped",
             "reason": "no plan"},
        ],
    }
    base.update(overrides)
    return base


def test_build_baselines_only_ok_results():
    from scripts.fleet import build_baselines
    card = {"breakdown": {"proof": {"penalty": 18}, "delivery": {"penalty": 2}}}
    b = build_baselines(_summary(), card_reader=lambda r: card)
    assert set(b) == {"doc-intel"}          # skipped fixture not blessed
    entry = b["doc-intel"]
    assert entry["functional"] == 68.0
    assert entry["breakdown"] == {"proof": 18, "delivery": 2}
    assert entry["run_ts"] == "20260817T000000Z"


def test_compare_within_tolerance_ok():
    from scripts.fleet import compare_results
    baselines = {"doc-intel": {"functional": 68.0, "design": 97.0}}
    results = [{"fixture": "doc-intel", "status": "ok",
                "functional": 66.5, "design": 97.0}]
    assert compare_results(results, baselines, tolerance=2.0) == []


def test_compare_drop_beyond_tolerance_flagged():
    from scripts.fleet import compare_results
    baselines = {"doc-intel": {"functional": 68.0, "design": 97.0}}
    results = [{"fixture": "doc-intel", "status": "ok",
                "functional": 60.0, "design": 97.0}]
    regs = compare_results(results, baselines, tolerance=2.0)
    assert len(regs) == 1
    assert regs[0]["kind"] == "functional"
    assert regs[0]["drop"] == 8.0


def test_compare_failed_fixture_is_regression():
    from scripts.fleet import compare_results
    regs = compare_results(
        [{"fixture": "banking", "status": "failed", "error": "boom"}],
        {"banking": {"functional": 80.0, "design": 80.0}}, tolerance=2.0)
    assert regs == [{"fixture": "banking", "kind": "not_ok",
                     "detail": "boom"}]


def test_compare_new_fixture_without_baseline_ignored():
    from scripts.fleet import compare_results
    regs = compare_results(
        [{"fixture": "new-one", "status": "ok",
          "functional": 10.0, "design": 10.0}], {}, tolerance=2.0)
    assert regs == []


def test_compare_improvement_never_flags():
    from scripts.fleet import compare_results
    baselines = {"doc-intel": {"functional": 68.0, "design": 90.0}}
    results = [{"fixture": "doc-intel", "status": "ok",
                "functional": 95.0, "design": 99.0}]
    assert compare_results(results, baselines, tolerance=2.0) == []


def test_attribute_sources_names_worse_penalties():
    from scripts.fleet import attribute_sources
    card = {"breakdown": {"proof": {"penalty": 34},
                          "delivery": {"penalty": 2},
                          "binding_smoke": {"penalty": 6}}}
    base = {"breakdown": {"proof": 18, "delivery": 2}}
    srcs = attribute_sources(card, base)
    assert srcs == ["proof +16", "binding_smoke +6"]


def test_latest_run_dir_picks_newest(tmp_path, monkeypatch):
    import scripts.fleet as fleet
    monkeypatch.setattr(fleet, "RESULTS_DIR", tmp_path)
    for ts in ("20260101T000000Z", "20260817T120000Z"):
        d = tmp_path / ts
        d.mkdir()
        (d / "summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "20269999T000000Z").mkdir()   # no summary — ignored
    assert fleet.latest_run_dir().name == "20260817T120000Z"
