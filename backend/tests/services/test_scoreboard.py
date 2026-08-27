"""A scoreboard nobody can afford to run is a scoreboard you do not have.

The existing fleet harness (`scripts/fleet.py` + `services/scorecard.py`) is the
best instrument the old platform built, and it is unusable as a gate during a
substrate rebuild: every reading costs an LLM generation and a build. So changes
to the schema, the capabilities or the matrix ship unmeasured, which is exactly
when measurement matters most.

This tier scores the Blueprint instead — pure, deterministic, milliseconds. The
tests that matter are the ones proving it can actually fail: a harness that only
ever goes green is decoration.
"""
import json

import pytest

from services.blueprint.scoreboard import (
    METRIC_ORDER,
    BASELINE_PATH,
    Score,
    ScoreRegression,
    assert_no_regression,
    bless,
    compare,
    load_baseline,
    load_fleet,
    render_table,
    score,
    score_fleet,
    score_validated,
)
from services.blueprint.verification import EDGES


@pytest.fixture()
def fleet() -> dict[str, dict]:
    return load_fleet()


# --- the fixtures themselves ------------------------------------------------

def test_the_fleet_has_fixtures(fleet):
    assert set(fleet) >= {"recruitment", "degraded"}


def test_every_fixture_is_a_legal_blueprint(fleet):
    """A fixture that fails the contract would measure nothing."""
    for name, doc in fleet.items():
        s = score_validated(doc, app=name)
        assert s.valid, (name, s.errors[:3])


def test_the_coherent_fixture_scores_perfectly(fleet):
    s = score(fleet["recruitment"], app="recruitment")
    assert s.findings == 0
    assert s.composite == 1.0


def test_the_degraded_fixture_fails_on_every_axis_it_should(fleet):
    """One deliberate defect per metric — the classic bugs from the old chain."""
    s = score(fleet["degraded"], app="degraded")
    assert s.composite < 0.3
    assert s.metrics["guarded"] == 0.0     # unguarded POST
    assert s.metrics["reachable"] == 0.0   # list page not in nav
    assert s.metrics["wired"] == 0.0       # orphan manual workflow
    assert s.metrics["bound"] == 0.0       # count displayed as a percent
    assert s.metrics["tested"] == 0.0      # untested requirement
    assert s.metrics["implemented"] == 0.0 # built, but no codeMap
    assert s.metrics["grounded"] == 1.0, "entities are still sound; not a blanket zero"


# --- metric semantics -------------------------------------------------------

def test_metrics_derive_from_the_verification_matrix():
    """If the scoreboard invented its own idea of 'good' it could disagree with
    verification, and then neither number would mean anything."""
    s = score({"schemaVersion": "1", "version": 1,
               "application": {"id": "a", "name": "n", "domain": "d"}})
    assert set(s.by_edge) <= set(EDGES)


def test_inapplicable_metrics_report_none_not_zero():
    """An app with no widgets is not bad at widgets."""
    s = score({"schemaVersion": "1", "version": 1,
               "application": {"id": "a", "name": "n", "domain": "d"}})
    assert s.metrics["bound"] is None
    assert s.counts["bound"] == {"ok": 0, "total": 0}


def test_composite_ignores_undefined_metrics(fleet):
    s = score(fleet["recruitment"])
    defined = [v for v in s.metrics.values() if v is not None]
    assert s.composite == pytest.approx(sum(defined) / len(defined), abs=1e-4)


def test_an_invalid_blueprint_scores_zero_and_says_why():
    bad = {"schemaVersion": "1", "application": {"id": "a", "name": "n", "domain": "d"},
           "requirements": [{"id": "NOPE-1", "description": "x"}]}
    s = score_validated(bad, app="bad")
    assert not s.valid and s.composite == 0.0 and s.errors


def test_scoring_is_pure(fleet):
    doc = fleet["recruitment"]
    before = json.dumps(doc, sort_keys=True)
    score(doc)
    assert json.dumps(doc, sort_keys=True) == before


# --- the regression gate: the whole point -----------------------------------

def test_the_committed_baseline_still_holds():
    """The gate itself. If a substrate change makes a fixture worse, this fails."""
    assert_no_regression(load_baseline(), score_fleet())


def test_a_regression_is_actually_caught(fleet):
    """Prove the gate can fail — otherwise it is decoration."""
    baseline = {"recruitment": score(fleet["recruitment"], app="recruitment").to_dict()}
    broken = json.loads(json.dumps(fleet["recruitment"]))
    broken["apis"][1].pop("permission")  # regress one metric only

    losses = compare(baseline, {"recruitment": score(broken, app="recruitment")})
    assert losses, "a real regression went undetected"
    assert {r.metric for r in losses} == {"composite", "guarded"}
    assert all(r.delta < 0 for r in losses)

    with pytest.raises(ScoreRegression) as exc:
        assert_no_regression(baseline, {"recruitment": score(broken, app="recruitment")})
    assert "guarded" in str(exc.value)


def test_an_improvement_is_not_a_regression(fleet):
    baseline = {"degraded": score(fleet["degraded"], app="degraded").to_dict()}
    fixed = json.loads(json.dumps(fleet["degraded"]))
    fixed["apis"][1]["permission"] = "PERM-001"
    assert compare(baseline, {"degraded": score(fixed, app="degraded")}) == []


def test_deleting_a_fixture_counts_as_a_regression(fleet):
    """The easiest way to make a scoreboard go green is to stop measuring."""
    baseline = {"recruitment": score(fleet["recruitment"], app="recruitment").to_dict()}
    losses = compare(baseline, {})
    assert [r.metric for r in losses] == ["<missing>"]


def test_a_fixture_going_invalid_counts_as_a_regression(fleet):
    baseline = {"recruitment": score(fleet["recruitment"], app="recruitment").to_dict()}
    broken = Score(app="recruitment", valid=False, composite=0.0, errors=["boom"])
    losses = compare(baseline, {"recruitment": broken})
    assert [r.metric for r in losses] == ["<invalid>"]


def test_tolerance_permits_noise_but_not_a_real_drop(fleet):
    baseline = {"recruitment": score(fleet["recruitment"], app="recruitment").to_dict()}
    nudged = json.loads(json.dumps(fleet["recruitment"]))
    nudged["apis"][1].pop("permission")
    current = {"recruitment": score(nudged, app="recruitment")}
    assert compare(baseline, current, tolerance=1.0) == []
    assert compare(baseline, current, tolerance=0.01) != []


def test_blessing_is_explicit(tmp_path, fleet):
    """A harness that re-blesses on every run cannot detect anything."""
    path = tmp_path / "baseline.json"
    assert load_baseline(path) == {}
    scores = {"recruitment": score(fleet["recruitment"], app="recruitment")}
    bless(scores, path)
    assert load_baseline(path)["recruitment"]["composite"] == 1.0
    assert_no_regression(load_baseline(path), scores)


# --- reporting --------------------------------------------------------------

def test_table_renders_every_metric_and_a_delta(fleet):
    scores = score_fleet()
    table = render_table(scores, load_baseline())
    for metric in METRIC_ORDER:
        assert metric[:9] in table
    assert "composite" in table
    assert "degraded" in table and "recruitment" in table


def test_table_marks_invalid_fixtures_rather_than_scoring_them():
    table = render_table({"bad": Score(app="bad", valid=False, errors=["x"])})
    assert "INVALID" in table


def test_baseline_file_is_committed():
    assert BASELINE_PATH.exists(), (
        "bless the fleet: python -c 'from services.blueprint.scoreboard import "
        "score_fleet, bless; bless(score_fleet())'"
    )
