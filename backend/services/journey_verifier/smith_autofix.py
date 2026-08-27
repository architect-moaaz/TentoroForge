"""V&F 2.0 Layer B (Smith side) — Smith-dispatch autofix (Milestone M2).

Deterministic seams handle the well-understood classes cheaply. This
module handles the judgment-call ones — ``smith:render``,
``smith:binding``, ``smith:data-fetch`` — by handing Smith a fault-scoped
prompt with a filtered tool subset, watching him call a mutating tool,
and returning a :class:`DispatchResult`.

Two entry points:

- :func:`dispatch(fault, output_dir, turn_budget=3)` — one fault, one
  Smith turn. Returns a :class:`DispatchResult` with files touched +
  turns used + fixed/error status.
- :func:`dispatch_all(faults, output_dir, run_budget=None)` — many
  faults, priority-ordered, honoring a run-wide turn budget. Faults that
  don't get to run because the budget is exhausted come back as
  ``fixed=False`` residuals labelled ``error="budget-exhausted"``.

Turn budget vs run budget:

- ``turn_budget`` is a per-fault ceiling — the max iters Smith can spend
  on ONE fault. Passed to :func:`agents.smith_agent.run_smith_agent`.
- ``FORGE_AUTOFIX_SMITH_BUDGET`` (env, default 15) is the CUMULATIVE
  turn cap for a whole ``dispatch_all`` invocation. When the next
  fault's ``turn_budget`` would push cumulative use over the cap, we
  short-circuit the rest.

Smith is NOT modified in M2 — its ``scoped_tools`` parameter already
supports subsetting the tool catalog. That's how we constrain fault
handlers to the right narrow surface.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from services.journey_verifier.autofix import DispatchResult
from services.journey_verifier.dedup import FaultAttemptLedger
from services.journey_verifier.fault_classifier import ClassifiedFault
from services.journey_verifier.fault_context import (
    SmithContext,
    build_fault_context,
)

logger = logging.getLogger(__name__)


# ── Config ──────────────────────────────────────────────────────────────────

# Which Smith tools each Smith seam is allowed to use. The seam names
# come from ``fault_classifier.classify_fault`` (search for "smith:").
# Kept narrow — a per-fault Smith call should not need the full 39-tool
# catalog; a smaller surface is easier for the LLM to steer against and
# harder to blast-radius.
TOOL_SUBSETS: dict[str, list[str]] = {
    "smith:render":     ["edit_page", "add_page", "check_data_source"],
    "smith:binding":    ["edit_page", "check_data_source"],
    "smith:data-fetch": ["edit_page", "add_workflow", "wire_form_to_workflow"],
}


# Priority order — high-blast-radius classes go first so if the budget
# runs out, the ones remaining are the cheapest to still hand to the user.
_SEAM_PRIORITY: dict[str, int] = {
    "smith:render":       0,  # render-error → whole page dead
    "smith:binding":      1,  # binding-crash → React #31
    "smith:data-fetch":   2,  # data-fetch-failure → API 5xx
}
# Fine-grained class priority when seams tie (page-unresponsive is a
# smith:render class too, but lower priority than render-error).
_CLASS_PRIORITY: dict[str, int] = {
    "render-error":         0,
    "binding-crash":        1,
    "data-fetch-failure":   2,
    "page-unresponsive":    3,
}

_DEFAULT_TURN_BUDGET = 3
_DEFAULT_RUN_BUDGET_ENV = "FORGE_AUTOFIX_SMITH_BUDGET"
_DEFAULT_RUN_BUDGET = 15


def _default_run_budget() -> int:
    """Cumulative turn cap for one ``dispatch_all`` invocation."""
    raw = os.environ.get(_DEFAULT_RUN_BUDGET_ENV, "")
    try:
        v = int(raw)
        return v if v > 0 else _DEFAULT_RUN_BUDGET
    except (TypeError, ValueError):
        return _DEFAULT_RUN_BUDGET


# ── Public entry ────────────────────────────────────────────────────────────


# Type alias: the fn that actually calls Smith. Async wrapper around the
# sync run_smith_agent — dependency-injected in tests via
# `smith_runner=`.
SmithRunner = Callable[..., Awaitable[dict[str, Any]]]


async def dispatch(
    fault: ClassifiedFault,
    output_dir: Path | str,
    *,
    turn_budget: int = _DEFAULT_TURN_BUDGET,
    smith_runner: Optional[SmithRunner] = None,
) -> DispatchResult:
    """Dispatch ONE Smith-classified fault.

    Builds a fault context, filters the tool catalog by the fault's
    seam, and calls Smith with a turn budget. Returns a DispatchResult
    with ``files_touched``, ``smith_turns_used``, and a ``fixed`` bool
    that reflects whether Smith actually wrote to disk (not whether the
    fault is DEFINITELY resolved — that's convergence's job, not
    dispatch's).
    """
    out = Path(output_dir)
    tool_subset = TOOL_SUBSETS.get(fault.seam, [])
    context = build_fault_context(fault, out, tool_subset=tool_subset)
    prompt = build_smith_prompt(fault, context, turn_budget=turn_budget)

    runner = smith_runner or _default_smith_runner

    try:
        result = await runner(
            user_message=prompt,
            output_dir=str(out),
            scoped_tools=tool_subset,
            turn_budget=turn_budget,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("smith dispatch crashed for %s: %s", fault.class_name, exc)
        return DispatchResult(
            seam=fault.seam,
            ran=True,
            ok=False,
            summary=f"smith crashed: {type(exc).__name__}",
            error=str(exc)[:400],
            class_name=fault.class_name,
            files_touched=[],
            fixed=False,
            smith_turns_used=0,
        )

    files_touched = _extract_files_touched(result)
    turns_used = _extract_turns_used(result, turn_budget=turn_budget)
    fixed = bool(files_touched)

    summary = (
        f"smith[{fault.seam}] turns={turns_used} touched={len(files_touched)}"
    )
    if not fixed:
        summary += " · no files written"

    return DispatchResult(
        seam=fault.seam,
        ran=True,
        ok=True,
        summary=summary,
        error=None,
        class_name=fault.class_name,
        files_touched=list(files_touched),
        fixed=fixed,
        smith_turns_used=turns_used,
    )


async def dispatch_all(
    faults: list[ClassifiedFault],
    output_dir: Path | str,
    *,
    run_budget: int | None = None,
    turn_budget: int = _DEFAULT_TURN_BUDGET,
    smith_runner: Optional[SmithRunner] = None,
    ledger: FaultAttemptLedger | None = None,
) -> list[DispatchResult]:
    """Dispatch a list of classified faults in priority order.

    - Priority: render-error > binding-crash > data-fetch-failure >
      page-unresponsive.
    - Respects a cumulative Smith turn ``run_budget`` (env-driven
      default; see :func:`_default_run_budget`). When the NEXT fault
      would push cumulative use over the cap, it's returned as a
      budget-exhausted residual (``fixed=False``,
      ``error="budget-exhausted"``) — including any faults after it.
    - Non-Smith seams in the input are returned unchanged as residuals
      (safety valve — dispatch_all should only be called with Smith
      faults, but if the caller passes something else, we don't crash).
    """
    if not faults:
        return []
    if run_budget is None:
        run_budget = _default_run_budget()

    ordered = sorted(faults, key=_fault_priority)
    results: list[DispatchResult] = []
    used = 0

    for i, fault in enumerate(ordered):
        # Non-smith seams belong in the deterministic path; we surface
        # them here as a defensive residual rather than dispatching them.
        if not fault.seam.startswith("smith:"):
            results.append(DispatchResult(
                seam=fault.seam,
                ran=False,
                ok=True,
                summary=f"non-smith seam {fault.seam!r} skipped",
                error=None,
                class_name=fault.class_name,
                files_touched=[],
                fixed=False,
                smith_turns_used=0,
            ))
            continue

        # M3 — cross-round dedup: skip faults Smith already tried this
        # run. Surfaced as a residual so the caller sees it in the
        # report and hands it back to the user instead of retrying.
        if ledger is not None and ledger.already_tried(fault):
            results.append(DispatchResult(
                seam=fault.seam,
                ran=False,
                ok=True,
                summary="already attempted this run — skipping",
                error="already-attempted-this-run",
                class_name=fault.class_name,
                files_touched=[],
                fixed=False,
                smith_turns_used=0,
            ))
            continue

        # Budget check — refuse to start this fault if it could bust the cap.
        remaining = run_budget - used
        if remaining <= 0:
            # Every remaining fault becomes a budget-exhausted residual.
            for later in ordered[i:]:
                if later.seam.startswith("smith:"):
                    results.append(DispatchResult(
                        seam=later.seam,
                        ran=False,
                        ok=False,
                        summary="budget exhausted before dispatch",
                        error="budget-exhausted",
                        class_name=later.class_name,
                        files_touched=[],
                        fixed=False,
                        smith_turns_used=0,
                    ))
            break

        # Cap this fault's turn budget to what remains — so if we have 2
        # turns left and turn_budget=3, we ask Smith for 2.
        this_budget = min(turn_budget, remaining)
        result = await dispatch(
            fault, output_dir,
            turn_budget=this_budget,
            smith_runner=smith_runner,
        )
        used += result.smith_turns_used
        results.append(result)
        # M3 — record the attempt regardless of success so a follow-up
        # round in the same run refuses to re-dispatch it.
        if ledger is not None:
            ledger.record_attempt(fault)

    return results


# ── Prompt builder ──────────────────────────────────────────────────────────


def build_smith_prompt(
    fault: ClassifiedFault,
    context: SmithContext,
    *,
    turn_budget: int,
) -> str:
    """The user message we hand Smith for a single dispatched fault.

    Frames the fault as an observed Playwright symptom and instructs
    Smith to fix it via ONE of the available tools (subset already
    filtered by seam). Emphasises "call the tool, don't propose in
    prose" to steer away from Smith's `answer`-terminal shortcut.
    """
    console_block = _render_console(context.console_errors)
    network_block = _render_network(context.network_failures)
    entities_block = ", ".join(context.related_entities) or "(none inferred)"
    edits_block = "\n".join(f"  {ln}" for ln in context.recent_edits[:20]) \
        or "  (no git history available)"
    tools_block = ", ".join(context.available_tools) or "(none)"
    schema_block = context.page_schema or "(page schema not found on disk)"
    code_block = context.page_code or "(page code not found on disk)"

    return (
        "You are fixing an observed Playwright fault in a generated app.\n\n"
        "OBSERVED SYMPTOM\n"
        "----------------\n"
        f"Route: {context.route or '(unknown)'}\n"
        f"Class: {fault.class_name}\n"
        f"Symptom: {context.symptom}\n\n"
        "CONSOLE ERRORS (top 10 err-level)\n"
        f"{console_block}\n\n"
        "NETWORK FAILURES (top 10, status >= 400)\n"
        f"{network_block}\n\n"
        "RELATED ENTITIES\n"
        f"{entities_block}\n\n"
        "RECENT EDITS TO THIS APP\n"
        f"{edits_block}\n\n"
        "PAGE SCHEMA (if available)\n"
        f"{schema_block}\n\n"
        "PAGE CODE (if available)\n"
        f"{code_block}\n\n"
        "TOOLS AVAILABLE TO YOU\n"
        f"{tools_block}\n\n"
        "TASK\n"
        "Read the symptom, understand the root cause, use ONE of the "
        "available tools to fix it. Do NOT propose the fix in prose — "
        "call the tool. Report the file(s) touched.\n"
        f"Turn budget: {turn_budget}.\n"
    )


def _render_console(entries: list[dict]) -> str:
    if not entries:
        return "  (no err-level entries)"
    lines: list[str] = []
    for e in entries:
        text = str(e.get("text") or e.get("message") or "").strip()
        lines.append(f"  - {text[:240]}")
    return "\n".join(lines)


def _render_network(entries: list[dict]) -> str:
    if not entries:
        return "  (no failing requests)"
    lines: list[str] = []
    for e in entries:
        method = str(e.get("method") or "?").upper()
        url = str(e.get("url") or "?")
        status = e.get("status") or "?"
        lines.append(f"  - {status} {method} {url}"[:240])
    return "\n".join(lines)


# ── Priority + result extraction ────────────────────────────────────────────


def _fault_priority(fault: ClassifiedFault) -> tuple[int, int]:
    """(class-priority, seam-priority) — lower is higher priority.

    Class rank dominates so ``render-error`` (class-priority 0) beats
    ``page-unresponsive`` (class-priority 3) even though they share the
    ``smith:render`` seam. Faults outside the priority tables sort last.
    """
    cp = _CLASS_PRIORITY.get(fault.class_name, 99)
    sp = _SEAM_PRIORITY.get(fault.seam, 99)
    return (cp, sp)


def _extract_files_touched(smith_result: dict[str, Any] | None) -> list[str]:
    """Read the ``edited_paths`` list from a Smith agent result."""
    if not isinstance(smith_result, dict):
        return []
    paths = smith_result.get("edited_paths")
    if not isinstance(paths, list):
        return []
    return [p for p in paths if isinstance(p, str) and p]


def _extract_turns_used(
    smith_result: dict[str, Any] | None,
    *,
    turn_budget: int,
) -> int:
    """Best-effort turns-used count. Smith's `trace` list has one entry
    per tool call, which is a fine proxy. Capped at the ceiling we
    passed in so an over-counting trace can't over-count the budget."""
    if not isinstance(smith_result, dict):
        return 0
    trace = smith_result.get("trace")
    if not isinstance(trace, list):
        return 0
    return min(len(trace), turn_budget)


# ── Default smith runner (async wrapper around sync run_smith_agent) ────────


async def _default_smith_runner(
    *,
    user_message: str,
    output_dir: str,
    scoped_tools: list[str],
    turn_budget: int,
    **_extra: Any,
) -> dict[str, Any]:
    """Run ``run_smith_agent`` in a worker thread and return the result.

    Kept a top-level function (not a lambda) so callers can monkeypatch
    it in tests without importing agents.smith_agent themselves. The
    recall/memory blocks are empty on purpose — a V&F autofix turn is a
    scoped one-shot repair, not a conversational continuation, and the
    fault context we hand Smith is already carrying everything relevant.
    """
    from agents.smith_agent import run_smith_agent

    def _sync() -> dict[str, Any]:
        return run_smith_agent(
            user_message=user_message,
            output_dir=output_dir,
            recall_block="",
            memory_block="",
            scoped_tools=scoped_tools,
            max_iters=max(1, int(turn_budget)),
        )

    return await asyncio.to_thread(_sync)
