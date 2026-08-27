"""PipelineState — the shared mutable state a generation run carries
through its phases.

The legacy `_run_relay_pipeline` and `_run_figma_relay_pipeline` in
:mod:`routers.generate` each defined `_stream_phase` and `_write_timing`
as **nested** functions closing over locals: `total_cost`, `total_turns`,
`total_duration`, `_phase_timings`, `_pipeline_last_phase`, `_progress`,
`_pending_progress`. That state can't be shared with extracted phase
functions living in a separate module without either passing every
variable individually (ugly + fragile) or bundling them into one object.

This module is the bundle. Every extracted phase in
:mod:`services.pipeline.phases` takes a :class:`PipelineState` and calls
its methods instead of the legacy nested helpers.

Behaviour preservation (Phase 1's non-negotiable): :meth:`stream_phase`
is a byte-for-byte lift of the text pipeline's `_stream_phase` — the
same idle-timeout wrap, the same cost accumulation, the same
phase-trace logging, the same `finally`-block timing that always fires
(even on exception). The Figma pipeline's version had a bug where
timing leaked on exception; that bug does NOT propagate to this class.
Every code path routes through the correct implementation.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterator, Optional

from sse_helpers import sse_event
from services.pipeline.source import PlanSource

logger = logging.getLogger(__name__)


# ProgressTracker phase-key mapping — same table both pipelines used
# inline. Lifted here so `stream_phase` can look it up without the caller
# having to pass it every time.
_STREAM_PHASE_TO_KEY: dict[str, str] = {
    "Design":        "design",
    "Contract":      "contract",
    "Contract-Fix":  "contract",
    "Schema":        "schema",
    "BusinessLogic": "bizlogic_api",
    "API":           "bizlogic_api",
    "Component":     "components",
    "Component-Fix": "components",
    "Page":          "pages",
    "Page-Fix":      "pages",
    "UX-Fix":        "pages",
    "Workflow":      "workflows",
    "Workflow-Fix":  "workflows",
    "Auth-Fix":      "auth",
}


@dataclass
class PipelineState:
    """Shared mutable state for one generation run.

    Construct via :meth:`create` — that wires the ProgressTracker's
    emit callback to the internal buffer correctly. Direct
    ``PipelineState(...)`` construction bypasses that wiring and will
    make :meth:`drain_progress` return nothing.
    """

    output_dir: str
    source: PlanSource
    # Progress tracker's emit callback appends to this list; drain reads
    # and clears. Kept next to the tracker so the wiring stays visible.
    _pending_progress: list = field(default_factory=list)
    progress: Any = None  # services.progress.ProgressTracker — Any to avoid circular

    # Cost accumulators — updated on every agent_result event.
    total_cost: float = 0.0
    total_turns: int = 0
    total_duration_ms: float = 0.0

    # Per-phase wall-clock timings (seconds).
    phase_timings: dict[str, float] = field(default_factory=dict)

    # Tracing — for the "pipeline crashed in phase X" post-mortem log.
    started_at: float = field(default_factory=time.perf_counter)
    last_phase: str = "(none)"

    # ---- construction --------------------------------------------------

    @classmethod
    def create(cls, *, output_dir: str, source: PlanSource) -> "PipelineState":
        """Factory — creates state + wires the ProgressTracker's emit
        callback to the internal buffer that :meth:`drain_progress` reads.
        This is the ONLY safe way to construct a state — direct
        ``PipelineState(...)`` leaves the tracker unwired.
        """
        from services.progress import ProgressTracker

        pending: list = []
        state = cls(
            output_dir=output_dir,
            source=source,
            _pending_progress=pending,
        )
        state.progress = ProgressTracker(
            emit_fn=lambda k, d: pending.append(sse_event(k, d)),
        )
        return state

    # ---- progress drain -----------------------------------------------

    def drain_progress(self) -> Iterator[dict]:
        """Pop every pending progress event the tracker has buffered.

        The tracker's `emit_fn` appends to `_pending_progress`; phase
        code calls this after every checkpoint to flush events downstream.
        """
        while self._pending_progress:
            yield self._pending_progress.pop(0)

    # ---- phase wrapper -------------------------------------------------

    async def stream_phase(
        self,
        name: str,
        messages: AsyncIterator[dict],
    ) -> AsyncIterator[dict]:
        """Stream a single agent phase, accumulating costs + timing.

        Byte-for-byte lift of `_stream_phase` from the text pipeline
        (see extraction rationale in the module docstring). Wraps the
        agent iterator with an idle timeout so a wedged
        `claude_agent_sdk` subprocess (no events for
        ``AGENT_TIMEOUT_SECONDS``) fails fast with `AgentTimeoutError`
        instead of hanging the pipeline.
        """
        from services.parallel_runner import stream_with_idle_timeout

        t0 = time.perf_counter()
        self.last_phase = name
        logger.info("[phase-trace] START %s", name)

        # Emit authoritative progress at phase entry (Fix #3/#4/#7).
        phase_key = _STREAM_PHASE_TO_KEY.get(name)
        if phase_key and self.progress is not None:
            self.progress.phase_start(phase_key)
            for pe in self.drain_progress():
                yield pe

        phase_ok = False
        try:
            async for evt in stream_with_idle_timeout(name, self.output_dir, messages):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    self.total_cost += data.get("cost_usd", 0)
                    self.total_turns += data.get("num_turns", 0)
                    self.total_duration_ms += data.get("duration_ms", 0)
                else:
                    yield evt
            phase_ok = True
        finally:
            elapsed = time.perf_counter() - t0
            self.phase_timings[name] = self.phase_timings.get(name, 0.0) + elapsed
            if phase_ok:
                logger.info(
                    "[phase-trace] END %s ok elapsed=%.1fs", name, elapsed,
                )
            else:
                logger.warning(
                    "[phase-trace] EXIT %s early (cancel/error) elapsed=%.1fs",
                    name, elapsed,
                )
            try:
                yield sse_event("log", {"text": f"[Timing] {name}: {elapsed:.1f}s"})
            except Exception:  # noqa: BLE001
                pass

    # ---- timing persistence -------------------------------------------

    def write_timing(self) -> None:
        """Persist phase-timing snapshot to ``generation-timing.json``.

        Called at pipeline end (and any intermediate checkpoint the
        legacy code called ``_write_timing()``). Best-effort — a write
        failure is swallowed so it can't crash the pipeline.
        """
        try:
            total = sum(self.phase_timings.values())
            (Path(self.output_dir) / "generation-timing.json").write_text(
                json.dumps(
                    {
                        "phases": self.phase_timings,
                        "total_seconds": round(total, 2),
                    },
                    indent=2,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    # ---- convenience --------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        """Wall-clock seconds since :meth:`create` was called."""
        return time.perf_counter() - self.started_at
