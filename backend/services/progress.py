"""Authoritative per-phase generation progress.

Fixes the "planning stuck at 13% for 19 min" + "ETA fluctuates wildly"
class. The frontend currently guesses phase from status-message text and
invents percent/ETA from hardcoded baselines — this module makes the
backend emit the real thing, with sub-events during long phases.

Contract emitted:

    sse_event("progress", {
        "phase":           "frontend_schema",
        "phase_index":     5,
        "phase_total":     11,
        "phase_percent":   40,       # 0..100 within the current phase
        "overall_percent": 47,       # 0..100 weighted by baselines
        "eta_seconds":     180,      # remaining, adjusted by real elapsed
        "sub_label":       "page 3 of 10",   # optional
    })

Wiring:

    tracker = ProgressTracker(emit_fn=lambda k, d: queue.put(sse_event(k, d)))

    tracker.phase_start("discovery")
    ...
    tracker.phase_start("design"); tracker.phase_complete()  # transitions

    # inside per-unit loops:
    tracker.phase_progress(percent, sub_label=f"page {i+1} of {n}")

    tracker.finalize()

Recalibration:

    tracker.recalibrate(pages=30, entities=8, workflows=6, parallelism=5)

    Once the plan is produced, callers pass the real counts so
    ``frontend_schema`` (the fat phase) no longer estimates 120s for a
    30-page app — the honest baseline is ``pages * per_page / parallelism``.
    This is what makes the % + ETA truthful on enterprise-scale apps.

Phase baselines are best-known-so-far; they only affect the initial ETA.
The scale factor (real elapsed / expected elapsed) adapts the estimate
as the run progresses — a slow discovery pushes the whole ETA up.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

# Ordered baseline table: (phase_key, expected_seconds). These are the
# defaults for a small (~5 page, 3 entity) app — recalibrate() rewrites
# the entries whose runtime scales with plan size.
DEFAULT_PHASE_BASELINES: list[tuple[str, int]] = [
    ("discovery",        60),
    ("design",           45),
    ("contract",         30),
    ("schema",           45),
    ("bizlogic_api",     40),
    ("auth",             15),
    ("frontend_schema", 120),   # includes _author_units — the fat one
    ("components",       25),
    ("pages",            25),
    ("workflows",        20),
    ("seed",             15),
    ("qa",               25),
]

# Per-unit LLM cost baselines used by recalibrate(). Tuned to real
# observations — a schema-page authoring call runs ~35-55s on the current
# planner model. Kept generous so a normal-sized app doesn't tick up
# under-estimated and then drift.
_SECS_PER_PAGE = 45         # frontend_schema _author_units per page
_SECS_PER_ENTITY = 12       # schema + bizlogic_api scale with entity count
_SECS_PER_WORKFLOW = 15     # workflows phase per workflow definition

# Bound the scale factor so a single slow phase doesn't blow the ETA
# to absurd values while still allowing meaningful stretch.
_MIN_SCALE = 0.7
_MAX_SCALE = 2.5


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class ProgressTracker:
    """Emits authoritative `progress` events as the pipeline advances.

    Not thread-safe — the pipeline is a single async task; callers must
    call ``phase_start`` / ``phase_progress`` / ``phase_complete`` from
    the same task that owns the tracker.
    """

    def __init__(
        self,
        emit_fn: Callable[[str, dict], None],
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._emit = emit_fn
        self._now = now_fn
        self._started_at = self._now()
        # Instance-scoped baselines so recalibrate() can rewrite them
        # per-run without cross-run contamination.
        self._phase_baselines: list[tuple[str, int]] = list(DEFAULT_PHASE_BASELINES)
        self._rebuild_indexes()
        # Current phase state.
        self._cur_idx: int = -1
        self._cur_phase_percent: float = 0.0
        self._cur_started_at: float = self._started_at
        self._done = False

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def phase_start(self, phase_key: str) -> None:
        """Enter a phase by name. Unknown keys are silently ignored so
        callers can add new phases opportunistically without crashing
        older backends."""
        idx = self._index_by_key.get(phase_key)
        if idx is None:
            return
        # If we're jumping forward past phases we never explicitly
        # completed, mark them completed silently (their baseline is
        # already banked into the overall_percent calc via prefix sum).
        self._cur_idx = idx
        self._cur_phase_percent = 0.0
        self._cur_started_at = self._now()
        self._emit_progress()

    def phase_progress(
        self, percent: float, *, sub_label: Optional[str] = None,
    ) -> None:
        """Update within-phase percent (0..100). No-op if no active phase."""
        if self._cur_idx < 0 or self._done:
            return
        self._cur_phase_percent = _clamp(float(percent), 0.0, 100.0)
        self._emit_progress(sub_label=sub_label)

    def phase_complete(self) -> None:
        """Snap current phase to 100%. Next phase_start advances the
        index. No-op if no active phase."""
        if self._cur_idx < 0 or self._done:
            return
        self._cur_phase_percent = 100.0
        self._emit_progress()

    def recalibrate(
        self,
        *,
        pages: int = 0,
        entities: int = 0,
        workflows: int = 0,
        parallelism: int = 5,
    ) -> None:
        """Rewrite baselines using real plan counts.

        Called once the planner has produced the plan. Without this,
        ``frontend_schema`` estimates 120s regardless of app size — a
        30-page app then shows 51% for ~15 min while the ring waits for
        wall time to catch reality. After this call, the estimate
        matches the actual per-page × parallelism envelope.

        ``pages`` — count of pages the planner produced. Rewrites
        ``frontend_schema`` + ``pages`` phase baselines.
        ``entities`` — entity count. Rewrites ``schema`` + ``bizlogic_api``.
        ``workflows`` — workflow count. Rewrites the ``workflows`` phase.
        ``parallelism`` — how many page authors run at once. Passed by the
        wiring, defaults to 5 (the ``FORGE_PAGE_CONCURRENCY`` default).
        Silent no-op if all counts are zero (no plan available yet).
        """
        if pages <= 0 and entities <= 0 and workflows <= 0:
            return
        parallelism = max(1, int(parallelism))
        overrides: dict[str, int] = {}
        if pages > 0:
            # frontend_schema authors every page (batched by parallelism);
            # the later `pages` phase is a lightweight reconciliation.
            overrides["frontend_schema"] = max(
                DEFAULT_PHASE_BASELINES_MAP["frontend_schema"],
                int(round((pages * _SECS_PER_PAGE) / parallelism)),
            )
            overrides["pages"] = max(
                DEFAULT_PHASE_BASELINES_MAP["pages"],
                int(round(pages * 1.5)),
            )
        if entities > 0:
            overrides["schema"] = max(
                DEFAULT_PHASE_BASELINES_MAP["schema"],
                int(round(entities * _SECS_PER_ENTITY)),
            )
            overrides["bizlogic_api"] = max(
                DEFAULT_PHASE_BASELINES_MAP["bizlogic_api"],
                int(round(entities * _SECS_PER_ENTITY)),
            )
        if workflows > 0:
            overrides["workflows"] = max(
                DEFAULT_PHASE_BASELINES_MAP["workflows"],
                int(round(workflows * _SECS_PER_WORKFLOW)),
            )
        if not overrides:
            return
        self._phase_baselines = [
            (k, overrides.get(k, s)) for (k, s) in self._phase_baselines
        ]
        self._rebuild_indexes()
        # Emit fresh progress so the frontend picks up the new ETA
        # immediately rather than waiting for the next phase_start.
        if self._cur_idx >= 0 and not self._done:
            self._emit_progress()

    def finalize(self) -> None:
        """Emit terminal overall_percent=100, eta_seconds=0. Idempotent."""
        if self._done:
            return
        self._done = True
        # Snap to the LAST phase for the terminal emit (frontend uses
        # phase_index to render which step is highlighted).
        if not self._phase_baselines:
            return
        last_idx = len(self._phase_baselines) - 1
        last_key, _ = self._phase_baselines[last_idx]
        self._emit(
            "progress",
            {
                "phase":           last_key,
                "phase_index":     last_idx,
                "phase_total":     len(self._phase_baselines),
                "phase_percent":   100,
                "overall_percent": 100,
                "eta_seconds":     0,
            },
        )

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _rebuild_indexes(self) -> None:
        """Recompute index_by_key + prefix sums + total baseline. Called
        on init and after recalibrate() rewrites the baselines."""
        self._index_by_key = {k: i for i, (k, _) in enumerate(self._phase_baselines)}
        self._total_baseline = float(sum(s for _, s in self._phase_baselines))
        cum = 0
        self._prefix: list[float] = []
        for _, s in self._phase_baselines:
            self._prefix.append(float(cum))
            cum += s

    def _virtual_done_seconds(self) -> float:
        """Sum of baselines for completed phases + current partial."""
        if self._cur_idx < 0:
            return 0.0
        prior = self._prefix[self._cur_idx]
        cur_baseline = self._phase_baselines[self._cur_idx][1]
        return prior + cur_baseline * (self._cur_phase_percent / 100.0)

    def _overall_percent(self) -> int:
        if self._total_baseline <= 0:
            return 0
        pct = (self._virtual_done_seconds() / self._total_baseline) * 100.0
        # Cap at 99 until the LAST phase actually hits 100% — we don't
        # want a middle-phase overrun to visually claim done.
        is_last_phase_done = (
            self._cur_idx == len(self._phase_baselines) - 1
            and self._cur_phase_percent >= 100.0
        )
        cap = 100.0 if is_last_phase_done else 99.0
        return int(round(_clamp(pct, 0.0, cap)))

    def _eta_seconds(self) -> int:
        elapsed = max(0.0, self._now() - self._started_at)
        virtual_done = self._virtual_done_seconds()
        # Not enough signal yet — return the raw remaining baseline
        # to avoid a huge scale factor on tiny virtual_done.
        remaining_baseline = max(0.0, self._total_baseline - virtual_done)
        if virtual_done < 15.0:
            return int(round(remaining_baseline))
        scale = _clamp(elapsed / virtual_done, _MIN_SCALE, _MAX_SCALE)
        return int(round(remaining_baseline * scale))

    def _emit_progress(self, *, sub_label: Optional[str] = None) -> None:
        if self._cur_idx < 0:
            return
        key, _ = self._phase_baselines[self._cur_idx]
        payload: dict = {
            "phase":           key,
            "phase_index":     self._cur_idx,
            "phase_total":     len(self._phase_baselines),
            "phase_percent":   int(round(self._cur_phase_percent)),
            "overall_percent": self._overall_percent(),
            "eta_seconds":     self._eta_seconds(),
        }
        if sub_label:
            payload["sub_label"] = sub_label
        self._emit("progress", payload)


# Named lookup used by recalibrate() to floor overrides at the default.
DEFAULT_PHASE_BASELINES_MAP: dict[str, int] = {k: s for k, s in DEFAULT_PHASE_BASELINES}


# ---------------------------------------------------------------------- #
# Back-compat alias                                                       #
# ---------------------------------------------------------------------- #
# Older tests import PHASE_BASELINES directly from this module. Keep the
# alias pointing at the defaults so those tests still pass while the
# instance now owns its own baselines.
PHASE_BASELINES = DEFAULT_PHASE_BASELINES
