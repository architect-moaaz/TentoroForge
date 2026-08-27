"""Auto-fix dispatcher for journey-gate remediation hints.

Given a list of ``RemediationHint`` (as dicts, from the gate), route each
hint to the seam most likely to fix it. Return a summary of what ran so
the caller can decide whether to re-verify or hand the residual to Smith.

Design principles:
  - Deterministic seams first (post_generate_fixes, orphan_wiring_pass) —
    they're cheap, idempotent, and their fixes are well-understood.
  - Group hints by target_seam so we don't run the same guard N times.
  - V&F 2.0 (M2): Smith seams (``smith:*``) are dispatched too, via
    :mod:`services.journey_verifier.smith_autofix` — after the
    deterministic pass and under a whole-run turn budget.
  - Every dispatch call is wrapped — one failing seam doesn't stop the
    others.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    seam: str
    ran: bool
    summary: str
    ok: bool = True
    error: str | None = None
    # V&F 2.0 additions (M1). Optional so pre-existing callers that
    # construct DispatchResult(seam=..., ran=..., summary=...) keep
    # working without touching the new fields.
    class_name: str | None = None      # taxonomy class this fix served
    files_touched: list[str] = field(default_factory=list)
    smith_turns_used: int = 0          # 0 for deterministic handlers
    fixed: bool = False                 # did the handler actually fix anything

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutoFixReport:
    dispatched: list[DispatchResult] = field(default_factory=list)
    skipped_seams: list[str] = field(default_factory=list)
    residual_hints: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatched": [d.to_dict() for d in self.dispatched],
            "skipped_seams": self.skipped_seams,
            "residual_hints": self.residual_hints,
        }


# ---------------------------------------------------------------------------
# Seam wrappers
# ---------------------------------------------------------------------------

def _fix_workflow_definition(output_dir: str | Path) -> DispatchResult:
    """Missing trigger nodes, unwired workflows, disconnected graphs → run
    the orphan-wiring pass + the graph gate rewriter."""
    try:
        from services.orphan_wiring_pass import wire_orphan_workflows
        res = wire_orphan_workflows(str(output_dir))
        wired = getattr(res, "wired", 0) or 0
        unresolved = getattr(res, "unresolved", 0) or 0
        return DispatchResult(
            seam="workflow-definition",
            ran=True,
            summary=f"orphan_wiring_pass wired {wired}, unresolved {unresolved}",
        )
    except Exception as exc:
        logger.warning("autofix workflow-definition failed: %s", exc)
        return DispatchResult(
            seam="workflow-definition",
            ran=True, ok=False,
            summary=f"orphan_wiring_pass failed",
            error=str(exc)[:400],
        )


def _fix_workflow_output_mapping(output_dir: str | Path) -> DispatchResult:
    """Row never landed → workflow's insert node isn't wired to inputs.
    workflow_completeness_guard is the pre-existing post-gen backstop
    that reports these; running it again after another seam moved
    upstream state will re-emit fresh findings."""
    try:
        from services.submit_authority_guards import workflow_completeness_guard
        res = workflow_completeness_guard(str(output_dir))
        # GuardResult has `messages: list[str]` — count only.
        count = len(getattr(res, "messages", []) or [])
        return DispatchResult(
            seam="workflow-output-mapping",
            ran=True,
            summary=f"workflow_completeness_guard: {count} finding(s)",
        )
    except Exception as exc:
        logger.warning("autofix workflow-output-mapping failed: %s", exc)
        return DispatchResult(
            seam="workflow-output-mapping",
            ran=True, ok=False,
            summary="workflow_completeness_guard failed",
            error=str(exc)[:400],
        )


def _fix_auth_seed(output_dir: str | Path) -> DispatchResult:
    """Login failed → seed didn't write a real user. Rerun the seed
    synthesizer, which is idempotent + guarantees at least one admin."""
    try:
        from services.seed_synthesizer import synthesize_seed_rows
        result = synthesize_seed_rows(str(output_dir))
        rows_written = result.get("rows_written", 0) if isinstance(result, dict) else 0
        return DispatchResult(
            seam="auth-seed",
            ran=True,
            summary=f"seed synthesizer wrote {rows_written} row(s)",
        )
    except Exception as exc:
        logger.warning("autofix auth-seed failed: %s", exc)
        return DispatchResult(
            seam="auth-seed",
            ran=True, ok=False,
            summary="seed synthesizer failed",
            error=str(exc)[:400],
        )


def _fix_form_or_page_or_component(output_dir: str | Path) -> DispatchResult:
    """Page/form/component-level bugs → run the whole post-gen fix suite
    again. It's the sink for form-scaffold, page-schema, and component
    wiring backstops; cheap to rerun because every pass is idempotent."""
    try:
        from services.post_generate_fixes import apply_post_generate_fixes
        n = apply_post_generate_fixes(str(output_dir))
        return DispatchResult(
            seam="post-generate-fixes",
            ran=True,
            summary=f"post_generate_fixes applied ({n} pass(es))",
        )
    except Exception as exc:
        logger.warning("autofix post_generate_fixes failed: %s", exc)
        return DispatchResult(
            seam="post-generate-fixes",
            ran=True, ok=False,
            summary="post_generate_fixes failed",
            error=str(exc)[:400],
        )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_SEAM_HANDLERS: dict[str, Callable[[str | Path], DispatchResult]] = {
    "workflow-definition": _fix_workflow_definition,
    "workflow-output-mapping": _fix_workflow_output_mapping,
    "auth-seed": _fix_auth_seed,
    # Page/form/component all funnel through the same rerun-the-suite
    # handler — the post-gen pipeline already knows which of its subpasses
    # to run, and running the full sweep is cheaper than reimplementing
    # per-seam heuristics here.
    "form-scaffold": _fix_form_or_page_or_component,
    "component-wiring": _fix_form_or_page_or_component,
    "page-schema": _fix_form_or_page_or_component,
    "runtime-binding": _fix_form_or_page_or_component,
}


# ---------------------------------------------------------------------------
# V&F 2.0 (M1) — classified-fault handlers.
# ---------------------------------------------------------------------------
#
# These take a ClassifiedFault instead of a raw hint dict, so the
# dispatcher can hand each handler a route + evidence slice + the raw
# fault. Keys use the fully-qualified seam name emitted by
# ``fault_classifier.classify_fault``.
#
# The classifier can produce ``smith:*`` seams too, but M1 does NOT
# dispatch them — those land in residuals and Smith-tier dispatch is M2's
# work. We register them here as ``None`` so the dispatcher can
# distinguish "known Smith seam, deferred to M2" from "unknown seam".

def _make_classified_seam_handlers() -> dict[str, Callable[..., DispatchResult] | None]:
    """Lazy-import — the handler module imports DispatchResult from us."""
    from services.journey_verifier import deterministic_handlers as dh

    return {
        "deterministic:add-page":          dh.handle_add_page,
        "deterministic:router-regen":      dh.handle_router_regen,
        "deterministic:db-migrate":        dh.handle_db_migrate,
        "deterministic:rewire-datasource": dh.handle_rewire_datasource,
        "deterministic:orphan-wiring":     dh.handle_orphan_wiring,
        # M1 keeps the existing auth-seed handler for the classifier's
        # auth-broken class. Adapter below drops the ClassifiedFault (the
        # legacy handler only takes output_dir).
        "deterministic:auth-seed":         None,  # patched at dispatch time
        # Smith seams — routed to the Smith dispatcher (M2), not through
        # this deterministic table. They're intentionally absent here so
        # the deterministic loop skips them; ``apply_autofix_v2`` queues
        # them for the batched Smith pass.
    }


_CLASSIFIED_SEAM_HANDLERS: dict[str, Any] | None = None


def _classified_handlers() -> dict[str, Any]:
    """Cache + return the classified-fault handler table."""
    global _CLASSIFIED_SEAM_HANDLERS
    if _CLASSIFIED_SEAM_HANDLERS is None:
        _CLASSIFIED_SEAM_HANDLERS = _make_classified_seam_handlers()
    return _CLASSIFIED_SEAM_HANDLERS


# The set of seams a human should look at rather than an automated pass.
# Emitted as residual_hints so the caller (chat UI / Smith) can decide.
_HUMAN_LOOP_SEAMS = {"unknown"}


def apply_autofix(
    output_dir: str | Path,
    hints: list[dict[str, Any]],
) -> AutoFixReport:
    """Run one auto-fix pass over a batch of remediation hints.

    Groups by ``target_seam`` so we invoke each fixer once per pass, even
    when multiple hints share a target. Returns a structured report the
    caller can serialize to SSE or persist to disk.
    """
    report = AutoFixReport()
    if not hints:
        return report

    # Dedup on target_seam. First-wins on ordering — hints[0] represents
    # the first failing journey, which is usually the earliest step in the
    # user's declared flow (login before scan before assert-row), so
    # running its seam first tends to unblock later ones on re-verify.
    seams_seen: list[str] = []
    residual: list[dict[str, Any]] = []
    for h in hints:
        seam = (h.get("target_seam") or "unknown").strip()
        if seam in _HUMAN_LOOP_SEAMS:
            residual.append(h)
            continue
        if seam in seams_seen:
            continue
        seams_seen.append(seam)

    for seam in seams_seen:
        handler = _SEAM_HANDLERS.get(seam)
        if handler is None:
            report.skipped_seams.append(seam)
            # Preserve the hints that mapped to unknown seams so the caller
            # sees them in the residual list.
            residual.extend(h for h in hints if (h.get("target_seam") or "") == seam)
            continue
        report.dispatched.append(handler(output_dir))

    report.residual_hints = residual
    return report


# ---------------------------------------------------------------------------
# V&F 2.0 (M1) — classified-fault dispatcher.
# ---------------------------------------------------------------------------


@dataclass
class AutofixV2Report:
    """V&F 2.0 (M2) — combined deterministic + Smith autofix report.

    Distinct from :class:`AutoFixReport` (the legacy hint-driven type)
    so consumers can distinguish "old world" vs "V&F 2.0" results.
    Serializable via :meth:`to_dict`.
    """
    deterministic_results: list[DispatchResult] = field(default_factory=list)
    smith_results: list[DispatchResult] = field(default_factory=list)
    residuals: list[dict[str, Any]] = field(default_factory=list)
    skipped_seams: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic_results": [r.to_dict() for r in self.deterministic_results],
            "smith_results": [r.to_dict() for r in self.smith_results],
            "residuals": list(self.residuals),
            "skipped_seams": list(self.skipped_seams),
        }


async def apply_autofix_v2(
    output_dir: str | Path,
    faults: list[dict[str, Any]],
    *,
    route_registry: set[str] | None = None,
    run_budget: int | None = None,
    ledger: Any = None,
) -> AutofixV2Report:
    """Classify raw faults, run deterministic handlers, then dispatch
    Smith seams.

    This is the V&F 2.0 entry point behind ``FORGE_AUTOFIX_V2=1``. Runs
    alongside the legacy hint-driven :func:`apply_autofix` — callers
    switch into this path by handing us raw runner FaultRaw dicts.

    Behaviour:
      - Each raw fault is classified via
        :func:`fault_classifier.classify_fault`.
      - ``class_name="unknown"`` faults skip dispatch → residuals.
      - Deterministic seams run first, deduped by ``(seam, route)`` so
        five ``missing-page`` faults on the same route trigger one call.
      - Smith seams then run via
        :func:`services.journey_verifier.smith_autofix.dispatch_all`,
        priority-ordered, honoring ``run_budget`` (env-driven default).
      - Handler errors are caught per-fault; one failing handler never
        stops the others.

    Returns an :class:`AutofixV2Report` with separate deterministic /
    Smith result lists + a residuals list for unrepresented classes and
    budget-exhausted Smith faults.
    """
    from services.journey_verifier.fault_classifier import classify_fault
    from services.journey_verifier.smith_autofix import dispatch_all

    report = AutofixV2Report()
    if not faults:
        return report

    handlers = _classified_handlers()
    dispatched_keys: set[str] = set()  # (seam, route) dedupe
    residual: list[dict[str, Any]] = []
    smith_queue: list[Any] = []  # ClassifiedFault list, deferred to Smith tier
    smith_seen_keys: set[str] = set()

    for raw in faults:
        try:
            cf = classify_fault(raw, route_registry=route_registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("classify_fault crashed on %s: %s",
                           (raw.get("id") if isinstance(raw, dict) else "?"), exc)
            residual.append(_to_residual(raw, class_name="classifier-error",
                                         seam="residual", detail=str(exc)[:200]))
            continue

        if cf.class_name == "unknown" or cf.seam == "residual":
            residual.append(_to_residual(raw, class_name=cf.class_name,
                                         seam=cf.seam, detail=cf.evidence_slice))
            continue

        # Smith seams: queue for the batched dispatch after deterministic pass.
        if cf.seam.startswith("smith:"):
            dedupe_key = f"{cf.seam}::{cf.route}"
            if dedupe_key in smith_seen_keys:
                continue
            smith_seen_keys.add(dedupe_key)
            smith_queue.append(cf)
            continue

        handler = handlers.get(cf.seam)
        # Adapter for `deterministic:auth-seed` — reuses `_fix_auth_seed`.
        if cf.seam == "deterministic:auth-seed":
            handler = lambda cf_, od, _fx=_fix_auth_seed: _fx(od)

        if handler is None:
            report.skipped_seams.append(cf.seam)
            residual.append(_to_residual(raw, class_name=cf.class_name,
                                         seam=cf.seam,
                                         detail="no handler registered"))
            continue

        # Dedupe: multiple faults on the same route/seam fire once.
        dedupe_key = f"{cf.seam}::{cf.route}"
        if dedupe_key in dispatched_keys:
            continue
        dispatched_keys.add(dedupe_key)

        try:
            result = handler(cf, output_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("handler %s crashed: %s", cf.seam, exc)
            result = DispatchResult(
                seam=cf.seam, ran=True, ok=False,
                summary=f"{cf.seam} raised {type(exc).__name__}",
                error=str(exc)[:400],
                class_name=cf.class_name,
                files_touched=[], fixed=False, smith_turns_used=0,
            )
        report.deterministic_results.append(result)

    # ── Smith dispatch pass ────────────────────────────────────────────────
    if smith_queue:
        try:
            smith_results = await dispatch_all(
                smith_queue, output_dir,
                run_budget=run_budget,
                ledger=ledger,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("smith dispatch_all crashed: %s", exc)
            smith_results = []
            residual.append({
                "journey_slug": "?",
                "failing_step": None,
                "likely_cause": f"smith dispatch_all crashed: {exc}",
                "target_seam": "smith:*",
                "class_name": "dispatcher-error",
                "route": "",
                "hint": str(exc)[:200],
                "tags": [],
            })
        # Smith results that didn't produce a fix become residuals too,
        # so the caller can hand them back to the user.
        for r in smith_results:
            report.smith_results.append(r)
            if not r.fixed and r.error == "budget-exhausted":
                residual.append({
                    "journey_slug": "?",
                    "failing_step": None,
                    "likely_cause": "smith turn budget exhausted",
                    "target_seam": r.seam,
                    "class_name": r.class_name or "unknown",
                    "route": "",
                    "hint": r.summary,
                    "tags": ["budget-exhausted"],
                })
            elif not r.fixed and r.error == "already-attempted-this-run":
                residual.append({
                    "journey_slug": "?",
                    "failing_step": None,
                    "likely_cause": "smith already attempted this fault "
                                     "earlier in the run",
                    "target_seam": r.seam,
                    "class_name": r.class_name or "unknown",
                    "route": "",
                    "hint": r.summary,
                    "tags": ["already-attempted"],
                })

    report.residuals = residual
    return report


def apply_autofix_v2_sync(
    output_dir: str | Path,
    faults: list[dict[str, Any]],
    *,
    route_registry: set[str] | None = None,
    run_budget: int | None = None,
) -> AutofixV2Report:
    """Sync wrapper for :func:`apply_autofix_v2` — spins up a private
    event loop. Handy for tests + CLI harnesses; production callers on
    the async self_verify path should await the async version directly.
    """
    return asyncio.run(apply_autofix_v2(
        output_dir, faults,
        route_registry=route_registry,
        run_budget=run_budget,
    ))


def _to_residual(
    raw: dict[str, Any],
    *,
    class_name: str,
    seam: str,
    detail: str,
) -> dict[str, Any]:
    """Shape a raw fault into a residual-hint dict the summary formatter
    can read. Non-breaking — extra keys are ignored by legacy consumers."""
    interaction = raw.get("interaction") if isinstance(raw, dict) else {}
    interaction = interaction or {}
    return {
        "journey_slug": str(interaction.get("id") or raw.get("id") or "?"),
        "failing_step": None,
        "likely_cause": detail,
        "target_seam": seam,
        "class_name": class_name,
        "route": str(interaction.get("route") or raw.get("route") or ""),
        "hint": detail,
        "tags": [],
    }
