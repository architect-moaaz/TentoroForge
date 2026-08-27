# backend/services/fidelity_loop.py
"""FidelityLoopRunner — orchestrates render → score → patch → re-render → re-score
across all pages of a generated project. Runs as a phase in routers/generate.py."""
from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import httpx

from agents.patch_agent import PatchAgentContext, propose_patches
from config import (
    FIDELITY_LOOP_CONCURRENCY,
    FIDELITY_LOOP_ENABLED,
    FIDELITY_LOOP_MAX_ITERATIONS,
    FIDELITY_LOOP_PAGE_TIMEOUT_MS,
    FIDELITY_LOOP_PROJECT_COST_CAP_USD,
    REFERENCE_GROUNDING_ENABLED,
)
from services.cost_tracker import BudgetExhausted, CostTracker
from services.fidelity_log import append_fidelity_entry
from services.patch_applier import (
    PatchApplyError,
    ValidationError,
    apply_patches_transactional,
    validate_patches,
)
from services.vision_evaluator import EvaluatorContext, evaluate_page
from services.vision_evaluator.types import Critique


logger = logging.getLogger(__name__)


PageStatus = Literal[
    "pass", "plateau", "budget", "failed", "timeout",
    "render_failed", "schema_reprompt_used",
]


@dataclass
class PageRef:
    short_id: str
    page_path: str        # e.g. "users/list"
    page_route: str       # e.g. "/users/list"
    page_type: str        # output of infer_page_type


@dataclass
class IterationOutcome:
    iter: int | str       # int for normal iters, "fallback" for schema-reprompt
    score: float
    score_delta: float
    issues_input: int
    patches_proposed: int
    patches_rejected: int
    patches_applied: int
    patch_summary: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    status: str = "continue"  # continue|pass|plateau|regressed|patch_invalid|schema_invalid|render_failed|vision_invalid


@dataclass
class PageOutcome:
    page: PageRef
    final_score: float
    passed: bool
    iterations: list[IterationOutcome]
    exit_status: PageStatus
    failed_fidelity: bool
    wall_clock_ms: int
    cost_usd: float


@dataclass
class FidelityReport:
    outcomes: list[PageOutcome]
    total_cost: float
    wall_clock_s: float
    flags: dict[str, Any]

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.failed_fidelity)

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.exit_status == "budget")

    def summary(self) -> dict[str, Any]:
        scores = [o.final_score for o in self.outcomes if o.final_score > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        iters = [len(o.iterations) for o in self.outcomes]
        avg_iters = sum(iters) / len(iters) if iters else 0.0
        return {
            "phase": "fidelity_loop",
            "passed": self.passed, "failed": self.failed, "skipped": self.skipped,
            "avg_score": round(avg_score, 2), "avg_iters": round(avg_iters, 2),
            "total_cost_usd": round(self.total_cost, 4),
            "wall_clock_s": round(self.wall_clock_s, 1),
            "flags": self.flags,
        }


@dataclass
class ProjectContext:
    """Carried through the loop for vision evaluator + patch agent prompts."""
    domain: str
    app_name: str
    description: str
    tone: str


SseEmit = Callable[[str, dict[str, Any]], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# Module-level indirection wrappers — thin so tests can patch them
# ---------------------------------------------------------------------------

async def _render_page(*, scaffold_url: str, project_id: str, page_route: str, viewport: str = "desktop") -> tuple[bytes, str]:
    """Render via render-service; returns (png_bytes, a11y_tree)."""
    render_service = "http://localhost:6502"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{render_service}/render", json={
            "projectId": project_id, "pageRoute": page_route, "viewport": viewport,
        })
    if r.status_code != 200:
        raise RuntimeError(f"render failed: {r.status_code}")
    body = r.json()
    return base64.b64decode(body["pngBase64"]), body.get("accessibilityTree", "")


async def _evaluate_page(*, png_bytes: bytes, a11y_tree: str, ctx: EvaluatorContext) -> Critique:
    return await evaluate_page(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)


async def _propose_patches(*, schema, critique, app_ctx, strict=False, validation_errors=None):
    return await propose_patches(
        schema=schema, critique=critique, app_ctx=app_ctx,
        strict=strict, validation_errors=validation_errors,
    )


def _validate_patches(patches, schema):
    return validate_patches(patches, schema)


def _apply_patches_transactional(patches, schema, *, validate_zod: bool = True):
    return apply_patches_transactional(patches, schema, validate_zod=validate_zod)


async def _reprompt_schema_agent(*, page: PageRef, critique, schema, project_ctx) -> dict | None:
    """Fallback when patch agent has been stuck for 2 iterations. v1 stub —
    returns None (no fallback). Future plan can wire this to a real schema-agent
    re-call. Returning None means: accept the page as-is and exit."""
    return None


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _summarize_patch(patch: dict[str, Any]) -> str:
    """Human-readable one-liner for a single patch."""
    op = patch.get("op", "?")
    path = patch.get("path", "")
    parts = path.split("/")
    target = parts[-1] if parts else path
    return f"{op} {target}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class FidelityLoopRunner:
    """Orchestrator for the per-page closed-loop fidelity check."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        project_ctx: ProjectContext,
        sse_emit: SseEmit | None = None,
        concurrency: int | None = None,
        cost_cap_usd: float | None = None,
        page_timeout_ms: int | None = None,
        max_iterations: int | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.project_ctx = project_ctx
        self.sse_emit = sse_emit or (lambda et, d: None)
        self.concurrency = concurrency or FIDELITY_LOOP_CONCURRENCY
        self.cost_cap_usd = cost_cap_usd or FIDELITY_LOOP_PROJECT_COST_CAP_USD
        self.page_timeout_ms = page_timeout_ms or FIDELITY_LOOP_PAGE_TIMEOUT_MS
        self.max_iterations = max_iterations or FIDELITY_LOOP_MAX_ITERATIONS
        self.cost_tracker = CostTracker(cap_usd=self.cost_cap_usd)

    async def run(self, pages: list[PageRef]) -> FidelityReport:
        if not FIDELITY_LOOP_ENABLED:
            return FidelityReport(
                outcomes=[], total_cost=0.0, wall_clock_s=0.0,
                flags={"fidelity_loop": False, "reference_grounding": REFERENCE_GROUNDING_ENABLED},
            )
        await self._sse("phase_start", {"phase": "fidelity_loop", "page_count": len(pages)})
        sem = asyncio.Semaphore(self.concurrency)
        start = time.monotonic()

        async def run_with_sem(page: PageRef) -> PageOutcome:
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self._run_one_page(page),
                        timeout=self.page_timeout_ms / 1000.0,
                    )
                except BudgetExhausted:
                    await self._sse("page_skipped", {"page": page.page_path, "reason": "budget_exhausted"})
                    return self._budget_skipped_outcome(page)
                except asyncio.TimeoutError:
                    await self._sse("page_skipped", {"page": page.page_path, "reason": "timeout"})
                    return self._timeout_outcome(page)
                except Exception as e:
                    logger.exception("fidelity_loop: unexpected error on page %s", page.page_path)
                    return self._error_outcome(page, str(e))

        outcomes = await asyncio.gather(*(run_with_sem(p) for p in pages))
        report = FidelityReport(
            outcomes=list(outcomes),
            total_cost=self.cost_tracker.total,
            wall_clock_s=time.monotonic() - start,
            flags={
                "fidelity_loop": True,
                "reference_grounding": REFERENCE_GROUNDING_ENABLED,
                "loop_version": "v1",
            },
        )
        await self._sse("phase_complete", report.summary())
        return report

    async def _run_one_page(self, page: PageRef) -> PageOutcome:
        page_start = time.monotonic()
        cost_at_start = self.cost_tracker.total
        iterations: list[IterationOutcome] = []
        schema_path = self.output_dir / "src" / "schemas" / f"{page.page_path}.json"
        schema = json.loads(schema_path.read_text())

        evaluator_ctx = EvaluatorContext(
            domain=self.project_ctx.domain,
            app_name=self.project_ctx.app_name,
            description=self.project_ctx.description,
            tone=self.project_ctx.tone,
            route=page.page_route,
            page_type=page.page_type,
            page_role=f"users navigate to {page.page_route}",
            iteration=0,
            max_iter=self.max_iterations,
        )
        patch_agent_ctx = PatchAgentContext(
            domain=self.project_ctx.domain,
            app_name=self.project_ctx.app_name,
            description=self.project_ctx.description,
            tone=self.project_ctx.tone,
        )

        # iter 0 baseline
        try:
            png, a11y = await _render_page(
                scaffold_url="", project_id=page.short_id, page_route=page.page_route,
            )
        except Exception as e:
            iterations.append(IterationOutcome(
                iter=0, score=0.0, score_delta=0.0, issues_input=0,
                patches_proposed=0, patches_rejected=0, patches_applied=0,
                status="render_failed",
                validation_errors=[str(e)],
            ))
            return self._finalize(
                page, iterations, "render_failed", failed=True,
                started_at=page_start, cost_at_start=cost_at_start,
            )

        critique = await _evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=evaluator_ctx)
        self.cost_tracker.add("vision", tokens_in=4000, tokens_out=400)
        await self._save_iteration_screenshot(page, 0, png)
        prev_score = critique.compositeScore
        iterations.append(IterationOutcome(
            iter=0, score=critique.compositeScore, score_delta=0.0,
            issues_input=len(critique.topIssues),
            patches_proposed=0, patches_rejected=0, patches_applied=0,
            status="pass" if critique.pass_ else "continue",
        ))
        await self._sse("page_iter_done", {
            "page": page.page_path, "iter": 0,
            "score": critique.compositeScore,
            "pass": critique.pass_,
            "score_delta": 0.0,
        })
        if critique.pass_:
            return self._finalize(
                page, iterations, "pass", failed=False,
                started_at=page_start, cost_at_start=cost_at_start,
            )

        # patch iterations 1..N
        consecutive_rejects = 0
        for i in range(1, self.max_iterations + 1):
            try:
                proposed = await _propose_patches(
                    schema=schema, critique=critique, app_ctx=patch_agent_ctx,
                )
                self.cost_tracker.add("patch", tokens_in=3500, tokens_out=700)
            except Exception as e:
                iterations.append(IterationOutcome(
                    iter=i, score=prev_score, score_delta=0.0,
                    issues_input=len(critique.topIssues),
                    patches_proposed=0, patches_rejected=0, patches_applied=0,
                    status="patch_invalid_output",
                    validation_errors=[str(e)],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                continue

            errors = _validate_patches(proposed, schema)
            if errors:
                # one strict retry
                try:
                    proposed = await _propose_patches(
                        schema=schema, critique=critique, app_ctx=patch_agent_ctx,
                        strict=True,
                        validation_errors=[f"{e.kind} at idx {e.idx}: {e.msg}" for e in errors],
                    )
                    self.cost_tracker.add("patch", tokens_in=4000, tokens_out=700)
                    errors = _validate_patches(proposed, schema)
                except Exception:
                    errors = [ValidationError(0, "retry_failed", "strict retry produced invalid output")]
                if errors:
                    iterations.append(IterationOutcome(
                        iter=i, score=prev_score, score_delta=0.0,
                        issues_input=len(critique.topIssues),
                        patches_proposed=len(proposed),
                        patches_rejected=len(proposed),
                        patches_applied=0,
                        status="patch_invalid",
                        validation_errors=[f"{e.kind}: {e.msg}" for e in errors],
                    ))
                    consecutive_rejects += 1
                    if consecutive_rejects >= 2:
                        break
                    continue

            try:
                new_schema = _apply_patches_transactional(proposed, schema, validate_zod=True)
            except PatchApplyError as e:
                iterations.append(IterationOutcome(
                    iter=i, score=prev_score, score_delta=0.0,
                    issues_input=len(critique.topIssues),
                    patches_proposed=len(proposed),
                    patches_rejected=len(proposed),
                    patches_applied=0,
                    status="schema_invalid",
                    validation_errors=[str(e)],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                continue

            # Persist new schema
            schema_path.write_text(json.dumps(new_schema, indent=2))
            try:
                png, a11y = await _render_page(
                    scaffold_url="", project_id=page.short_id, page_route=page.page_route,
                )
            except Exception as e:
                # Restore prior schema on render failure
                schema_path.write_text(json.dumps(schema, indent=2))
                iterations.append(IterationOutcome(
                    iter=i, score=prev_score, score_delta=0.0,
                    issues_input=len(critique.topIssues),
                    patches_proposed=len(proposed),
                    patches_rejected=len(proposed),
                    patches_applied=0,
                    status="render_failed",
                    validation_errors=[str(e)],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                continue

            new_critique = await _evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=evaluator_ctx)
            self.cost_tracker.add("vision", tokens_in=4000, tokens_out=400)
            await self._save_iteration_screenshot(page, i, png)

            # Progress gate
            new_score = new_critique.compositeScore
            score_delta = new_score - prev_score
            new_high = any(iss.severity == "high" for iss in new_critique.topIssues)
            old_high = any(iss.severity == "high" for iss in critique.topIssues)
            regressed = (new_score < prev_score - 0.3) or (new_high and not old_high)

            if regressed:
                # Restore prior schema
                schema_path.write_text(json.dumps(schema, indent=2))
                iterations.append(IterationOutcome(
                    iter=i, score=new_score, score_delta=score_delta,
                    issues_input=len(critique.topIssues),
                    patches_proposed=len(proposed),
                    patches_rejected=len(proposed),
                    patches_applied=0,
                    status="regressed",
                    patch_summary=[_summarize_patch(p) for p in proposed],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                # On regression, do NOT update schema/critique/prev_score for next iter
                continue

            # Accepted iter
            schema = new_schema
            critique = new_critique
            consecutive_rejects = 0
            iterations.append(IterationOutcome(
                iter=i, score=new_score, score_delta=score_delta,
                issues_input=len(critique.topIssues),
                patches_proposed=len(proposed),
                patches_rejected=0,
                patches_applied=len(proposed),
                status="pass" if new_critique.pass_ else "continue",
                patch_summary=[_summarize_patch(p) for p in proposed],
            ))
            await self._sse("page_iter_done", {
                "page": page.page_path, "iter": i,
                "score": new_score, "pass": new_critique.pass_,
                "score_delta": score_delta,
            })

            if new_critique.pass_:
                return self._finalize(
                    page, iterations, "pass", failed=False,
                    started_at=page_start, cost_at_start=cost_at_start,
                )

            # Plateau check (between iter i and iter i-1)
            if i >= 2 and abs(score_delta) < 0.3 and abs(iterations[-2].score_delta) < 0.3:
                return self._finalize(
                    page, iterations, "plateau", failed=True,
                    started_at=page_start, cost_at_start=cost_at_start,
                )

            prev_score = new_score

        # Out of iterations — try schema-reprompt fallback if we had 2 consecutive rejects
        if consecutive_rejects >= 2:
            fallback_schema = await _reprompt_schema_agent(
                page=page, critique=critique, schema=schema, project_ctx=self.project_ctx,
            )
            if fallback_schema is not None:
                schema_path.write_text(json.dumps(fallback_schema, indent=2))
                # Render + score the fallback once
                try:
                    png, a11y = await _render_page(
                        scaffold_url="", project_id=page.short_id, page_route=page.page_route,
                    )
                    fb_critique = await _evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=evaluator_ctx)
                    self.cost_tracker.add("vision", tokens_in=4000, tokens_out=400)
                    await self._save_iteration_screenshot(page, "fallback", png)
                    iterations.append(IterationOutcome(
                        iter="fallback", score=fb_critique.compositeScore,
                        score_delta=fb_critique.compositeScore - prev_score,
                        issues_input=len(critique.topIssues),
                        patches_proposed=0, patches_rejected=0, patches_applied=0,
                        status="pass" if fb_critique.pass_ else "continue",
                    ))
                    if fb_critique.pass_:
                        return self._finalize(
                            page, iterations, "schema_reprompt_used", failed=False,
                            started_at=page_start, cost_at_start=cost_at_start,
                        )
                except Exception:
                    schema_path.write_text(json.dumps(schema, indent=2))

        return self._finalize(
            page, iterations, "failed", failed=True,
            started_at=page_start, cost_at_start=cost_at_start,
        )

    # ---- helpers ----

    def _finalize(self, page, iterations, exit_status, *, failed, started_at, cost_at_start) -> PageOutcome:
        final_score = iterations[-1].score if iterations else 0.0
        passed = (exit_status in ("pass",)) and not failed
        wall_clock_ms = int((time.monotonic() - started_at) * 1000)
        cost_usd = round(self.cost_tracker.total - cost_at_start, 4)
        outcome = PageOutcome(
            page=page,
            final_score=final_score,
            passed=passed,
            iterations=iterations,
            exit_status=exit_status,
            failed_fidelity=failed and exit_status != "pass",
            wall_clock_ms=wall_clock_ms,
            cost_usd=cost_usd,
        )
        # Persist all iterations + page-level final state in one pass.
        for it in iterations:
            is_last = (it is iterations[-1])
            iter_num = it.iter if isinstance(it.iter, int) else len(iterations) - 1
            append_fidelity_entry(
                output_dir=str(self.output_dir),
                page_path=page.page_path,
                score=it.score,
                issues=[],
                iteration=iter_num,
                passed=passed and is_last,
                patches=[],  # patch list is implicit in patch_summary
                patch_summary=it.patch_summary,
                validation_errors=it.validation_errors,
                exit_status=exit_status if is_last else None,
                failed_fidelity=outcome.failed_fidelity if is_last else None,
                wall_clock_ms=wall_clock_ms if is_last else None,
                cost_usd=cost_usd if is_last else None,
                flags={"fidelity_loop": True, "reference_grounding": REFERENCE_GROUNDING_ENABLED, "loop_version": "v1"} if is_last else None,
            )
        return outcome

    def _budget_skipped_outcome(self, page: PageRef) -> PageOutcome:
        return PageOutcome(
            page=page, final_score=0.0, passed=False, iterations=[],
            exit_status="budget", failed_fidelity=False, wall_clock_ms=0, cost_usd=0.0,
        )

    def _timeout_outcome(self, page: PageRef) -> PageOutcome:
        return PageOutcome(
            page=page, final_score=0.0, passed=False, iterations=[],
            exit_status="timeout", failed_fidelity=True,
            wall_clock_ms=self.page_timeout_ms, cost_usd=0.0,
        )

    def _error_outcome(self, page: PageRef, msg: str) -> PageOutcome:
        return PageOutcome(
            page=page, final_score=0.0, passed=False, iterations=[],
            exit_status="failed", failed_fidelity=True, wall_clock_ms=0, cost_usd=0.0,
        )

    async def _sse(self, event_type: str, data: dict[str, Any]) -> None:
        result = self.sse_emit(event_type, data)
        if asyncio.iscoroutine(result):
            await result

    async def _save_iteration_screenshot(self, page: PageRef, iter_id: int | str, png: bytes) -> None:
        """Persist iter screenshot to .fidelity-history/<page_path>/iter-N.png."""
        safe_page = page.page_path.replace("/", "_")
        dest_dir = self.output_dir / ".fidelity-history" / safe_page
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"iter-{iter_id}.png"
        dest.write_bytes(png)
