"""Tests for the ProgressTracker — authoritative per-phase progress emission.

Failure modes we're closing:
  - ETA fluctuates 7 → 13 → 15 min (frontend guesses from status text)
  - Planning stuck at 13% for 19+ min (no sub-events during long phases)
  - Backend never emits real eta_seconds; frontend interpolates blindly

Contract:
  * `phase_start(key)` → emits `progress` event with phase_index/percent/eta
  * `phase_progress(percent)` → updates within-phase percent, re-emits
  * `phase_complete()` → snaps phase_percent to 100, moves index forward
  * `finalize()` → emits overall_percent=100, eta_seconds=0

`overall_percent` = weighted sum by phase baseline duration.
`eta_seconds` = remaining_baseline * elapsed-vs-baseline scale (bounded).
"""

from __future__ import annotations

from typing import Any

import pytest

from services.progress import PHASE_BASELINES, ProgressTracker


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def _tracker(events: list[tuple[str, dict]] | None = None) -> tuple[
    ProgressTracker, _Clock, list[tuple[str, dict]]
]:
    ev = events if events is not None else []
    clock = _Clock()
    tr = ProgressTracker(
        emit_fn=lambda kind, data: ev.append((kind, data)),
        now_fn=clock.now,
    )
    return tr, clock, ev


class TestPhaseCatalog:
    def test_baselines_are_positive_and_ordered(self):
        assert len(PHASE_BASELINES) >= 6, "expect at least the coarse phases"
        for key, secs in PHASE_BASELINES:
            assert isinstance(key, str) and key
            assert secs > 0

    def test_first_phase_is_discovery(self):
        assert PHASE_BASELINES[0][0] == "discovery"

    def test_baseline_total_matches_expected_range(self):
        # Complete profile baseline: 8–20 minutes today.
        total = sum(s for _, s in PHASE_BASELINES)
        assert 300 <= total <= 1500


class TestPhaseStart:
    def test_emits_progress_event_with_phase_index(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        assert ev, "expected a progress event"
        kind, data = ev[0]
        assert kind == "progress"
        assert data["phase"] == "discovery"
        assert data["phase_index"] == 0
        assert data["phase_total"] == len(PHASE_BASELINES)
        assert data["phase_percent"] == 0

    def test_emits_eta_seconds_close_to_total_baseline_at_start(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        _, data = ev[0]
        total = sum(s for _, s in PHASE_BASELINES)
        assert 0.7 * total <= data["eta_seconds"] <= 1.5 * total

    def test_overall_percent_starts_at_zero(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        _, data = ev[0]
        assert data["overall_percent"] == 0

    def test_unknown_phase_is_ignored(self):
        tr, _, ev = _tracker()
        tr.phase_start("not_a_phase")
        assert ev == []


class TestPhaseProgress:
    def test_updates_within_phase_percent(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        ev.clear()
        tr.phase_progress(50)
        assert len(ev) == 1
        _, data = ev[0]
        assert data["phase"] == "discovery"
        assert data["phase_percent"] == 50

    def test_updates_overall_percent(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        disc_baseline = PHASE_BASELINES[0][1]
        total = sum(s for _, s in PHASE_BASELINES)
        ev.clear()
        tr.phase_progress(50)
        _, data = ev[0]
        expected_overall = round((disc_baseline * 0.5) / total * 100)
        assert abs(data["overall_percent"] - expected_overall) <= 1

    def test_clamps_percent_to_0_100(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        ev.clear()
        tr.phase_progress(150)
        _, data = ev[-1]
        assert data["phase_percent"] == 100
        tr.phase_progress(-10)
        _, data = ev[-1]
        assert data["phase_percent"] == 0

    def test_ignored_when_no_active_phase(self):
        tr, _, ev = _tracker()
        tr.phase_progress(50)  # phase_start never called
        assert ev == []


class TestPhaseComplete:
    def test_snaps_percent_to_100(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        ev.clear()
        tr.phase_complete()
        _, data = ev[-1]
        assert data["phase_percent"] == 100

    def test_advances_to_next_phase_on_next_start(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        tr.phase_complete()
        ev.clear()
        tr.phase_start("design")
        _, data = ev[0]
        assert data["phase"] == "design"
        assert data["phase_index"] == 1

    def test_completing_all_phases_yields_100_overall(self):
        tr, _, ev = _tracker()
        for key, _ in PHASE_BASELINES:
            tr.phase_start(key)
            tr.phase_complete()
        _, data = ev[-1]
        assert data["overall_percent"] == 100


class TestEtaAdaptsToRealElapsed:
    def test_scales_up_when_running_slower_than_baseline(self):
        tr, clock, ev = _tracker()
        tr.phase_start("discovery")
        disc_baseline = PHASE_BASELINES[0][1]
        # Advance to 2x the discovery baseline while still at 0%.
        clock.advance(disc_baseline * 2)
        ev.clear()
        tr.phase_progress(50)
        _, data = ev[0]
        # A big scale factor should push eta well above nominal remaining.
        total = sum(s for _, s in PHASE_BASELINES)
        virtual_done = disc_baseline * 0.5
        nominal_remaining = total - virtual_done
        assert data["eta_seconds"] > nominal_remaining

    def test_eta_never_negative(self):
        tr, clock, ev = _tracker()
        for key, secs in PHASE_BASELINES:
            tr.phase_start(key)
            clock.advance(secs)
            tr.phase_complete()
        for _, data in ev:
            assert data["eta_seconds"] >= 0


class TestFinalize:
    def test_emits_100_and_zero_eta(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        ev.clear()
        tr.finalize()
        _, data = ev[-1]
        assert data["overall_percent"] == 100
        assert data["eta_seconds"] == 0


class TestSubLabel:
    def test_carries_sub_label_when_provided(self):
        tr, _, ev = _tracker()
        tr.phase_start("frontend_schema")
        ev.clear()
        tr.phase_progress(30, sub_label="page 3 of 10")
        _, data = ev[0]
        assert data.get("sub_label") == "page 3 of 10"

    def test_absent_when_none(self):
        tr, _, ev = _tracker()
        tr.phase_start("discovery")
        ev.clear()
        tr.phase_progress(10)
        _, data = ev[0]
        assert "sub_label" not in data or data["sub_label"] in (None, "")


class TestRecalibrate:
    """Recalibration scales baselines with real plan counts.

    Before: `frontend_schema` always 120s → a 30-page app sat at 51%
    for ~15 min waiting for wall clock to catch reality, and the ETA
    ceiling drifted up cosmetically. After: baselines match the real
    per-page × parallelism envelope, so the % and ETA line up.
    """

    def test_frontend_schema_scales_with_pages(self):
        tr, _, ev = _tracker()
        tr.recalibrate(pages=30, entities=8, workflows=6, parallelism=5)
        # frontend_schema now reflects 30 pages / 5 parallel × 45s per page = 270s
        assert tr._phase_baselines[
            tr._index_by_key["frontend_schema"]
        ][1] >= 250

    def test_recalibrate_below_default_keeps_default(self):
        """Small apps should not shrink the baseline below defaults —
        the default is the floor to keep tiny apps from over-shooting."""
        tr, _, ev = _tracker()
        default_fs = dict(PHASE_BASELINES)["frontend_schema"]
        tr.recalibrate(pages=3, entities=2, workflows=1, parallelism=5)
        assert tr._phase_baselines[
            tr._index_by_key["frontend_schema"]
        ][1] == default_fs

    def test_recalibrate_emits_when_in_active_phase(self):
        tr, clk, ev = _tracker()
        tr.phase_start("frontend_schema")
        ev.clear()
        tr.recalibrate(pages=30, entities=8, workflows=6, parallelism=5)
        # A `progress` event fires so the frontend picks up the new ETA
        # immediately rather than waiting for the next phase_start.
        assert any(k == "progress" for k, _ in ev)

    def test_no_op_when_all_zero(self):
        tr, _, ev = _tracker()
        before = list(tr._phase_baselines)
        tr.recalibrate(pages=0, entities=0, workflows=0)
        assert tr._phase_baselines == before

    def test_percent_stays_honest_after_recalibrate(self):
        """The user-visible bug: at 51% with 18m ETA, the ring rode a
        cosmetic ceiling. After recalibrate() the % should reflect the
        NEW total (bigger denominator → smaller %), and ETA should be
        proportional to remaining_baseline. This is the anchor test —
        if it drifts, the bug is coming back."""
        tr, clk, ev = _tracker()
        tr.phase_start("frontend_schema")
        tr.phase_progress(50)  # halfway through the FAT phase
        pct_before = ev[-1][1]["overall_percent"]
        eta_before = ev[-1][1]["eta_seconds"]
        # 30-page app arrives late — recalibrate mid-phase.
        tr.recalibrate(pages=30, entities=8, workflows=6, parallelism=5)
        pct_after = ev[-1][1]["overall_percent"]
        eta_after = ev[-1][1]["eta_seconds"]
        # More remaining work → % lower or equal AND ETA higher.
        assert pct_after <= pct_before
        assert eta_after > eta_before
