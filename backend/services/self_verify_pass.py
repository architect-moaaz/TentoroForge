"""Self-Verify Pass orchestrator (SV-5 skeleton, grown by SV-6/7).

SV-5 scope: diagnose-only. Extract interactions, kick the runner,
persist the report. No Smith loop yet — that lands in SV-6.

Public entry:
    await run_self_verify(project_id, target='preview',
                          scope='*', fix=False, invoked_by='auto_post_gen')
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select

from database import async_session
from models.project import Project
from models.verify_run import VerifyRun
from services.forge_verify_client import ForgeVerifyClient, ForgeVerifyError
from services.interaction_extractor import extract_interactions

logger = logging.getLogger(__name__)

InvokedBy = Literal["auto_post_gen", "user_ui", "user_chat", "smith_edit"]


def is_enabled() -> bool:
    """Master feature flag. Off by default until UAT-validated.

    Routed through :mod:`services.flag_profile` so ``FORGE_QUALITY=full``
    turns this on without needing the per-flag env var.
    """
    from services.flag_profile import is_on
    return is_on("FORGE_SELF_VERIFY")


def is_smith_fix_enabled() -> bool:
    """Fix-loop flag. Diagnostic-only when off."""
    from services.flag_profile import is_on
    return is_on("FORGE_VERIFY_SMITH_FIX")


async def run_self_verify(
    project_id: str | uuid.UUID,
    *,
    target: Literal["preview", "deploy"] = "preview",
    scope: str = "*",
    fix: bool = False,      # SV-6 flips default via is_smith_fix_enabled()
    invoked_by: InvokedBy = "auto_post_gen",
    triggered_by: uuid.UUID | None = None,
    max_rounds: int = 3,    # honoured by SV-7 convergence loop
    existing_row_id: uuid.UUID | None = None,
) -> dict:
    """Run the pass end-to-end. Returns a RemediationReport-shaped dict.

    On any failure (runner unreachable, project not found), records the
    error on the VerifyRun row and returns without raising — callers are
    fire-and-forget in the auto-post-gen path.
    """
    proj_id = uuid.UUID(str(project_id)) if not isinstance(project_id, uuid.UUID) else project_id

    async with async_session() as db:
        project = (await db.execute(
            select(Project).where(Project.id == proj_id),
        )).scalar_one_or_none()
        if not project:
            logger.warning("[self-verify] project %s not found", proj_id)
            return {"error": "project not found"}

        # Extract interactions from the on-disk output tree.
        try:
            interactions = extract_interactions(project.output_dir or "", scope=scope)
        except Exception as e:
            logger.exception("[self-verify] extractor failed for %s", proj_id)
            return {"error": f"extractor failed: {e}"}
        if not interactions:
            logger.info("[self-verify] no interactions extractable for %s", proj_id)
            return {"error": "no interactions extractable"}

        # Reuse the pre-created row when the caller already committed one
        # (POST /verify does this so the endpoint can return an ID
        # synchronously). Otherwise create it here.
        if existing_row_id is not None:
            row = (await db.execute(
                select(VerifyRun).where(VerifyRun.id == existing_row_id),
            )).scalar_one_or_none()
            if row is None:
                logger.warning("[self-verify] existing row %s missing; creating fresh",
                               existing_row_id)
        else:
            row = None
        if row is None:
            # JV-11 — retention: keep at most VERIFY_RUN_RETENTION most
            # recent rows per project. Delete oldest before insert so a
            # long-lived project doesn't accumulate hundreds of rows.
            # Configurable via env; 20 is a reasonable default (covers a
            # week of daily verifies + a couple of manual ones).
            try:
                await _trim_verify_runs(db, proj_id)
            except Exception:
                logger.warning("[self-verify] retention trim failed", exc_info=True)

            row = VerifyRun(
                project_id=proj_id,
                triggered_by=triggered_by,
                invoked_by=invoked_by,
                target=target,
                scope=scope,
                status="running",
                interactions_run=len(interactions),
            )
            db.add(row)
        else:
            row.status = "running"
            row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)

        # JV-21 — publish verify_start so a subscribed UI can flip its
        # progress card from "waiting" to "kick off" the instant we begin.
        try:
            from services.verify_events import publish_lifecycle
            publish_lifecycle(
                proj_id, "verify_start",
                target=target, invoked_by=invoked_by, run_id=str(row.id),
            )
        except Exception:
            pass

        try:
            if target == "deploy":
                base_url = await resolve_deploy_base_url(db, proj_id)
            else:
                base_url = _base_url_for(project, target)
                # Preview target: make sure the generated app's dev server is
                # actually running before we hand its URL to Playwright.
                # Without this, /preview/serve 503s on every interaction and
                # every fault is misattributed as "app broken" when it's
                # really "app not started". `start_project_environment` is
                # idempotent — a no-op if the environment is already up.
                #
                # Skip when a FORGE_APP_URL override is in play: the user
                # is responsible for starting that URL themselves, and
                # burning 5-60s spinning up a platform preview we won't
                # hand to the runner is pure waste.
                if _project_app_url_override(project) is None:
                    await _ensure_preview_running(project)
            async with ForgeVerifyClient() as client:
                runner_available = await client.healthz()

                # These get populated by whichever pass(es) actually run.
                report: dict = {}
                runner_id: str | None = None
                remediation = None

                if runner_available:
                    runner_id = await client.run(
                        project_id=str(proj_id),
                        target=target,
                        base_url=base_url,
                        interactions=interactions,
                    )
                    row.runner_run_id = runner_id
                    await db.commit()

                    # JV-27 features #1 + #3 — stream progress + faults to
                    # subscribed UIs. `seen_fault_ids` de-dupes across the
                    # 1.5s poll cadence (the runner keeps faults cumulative
                    # in the report). Every poll fires `verify_progress`
                    # with the latest {done,total,currentUrl} so the chip's
                    # counter advances instead of sitting on a spinner.
                    seen_fault_ids: set[str] = set()

                    def _on_progress(resp: dict) -> None:
                        try:
                            import json as _json
                            from services.verify_events import publish as _pub
                            prog = resp.get("progress") or {}
                            if prog:
                                _pub(proj_id, {
                                    "event": "verify_progress",
                                    "data": _json.dumps({
                                        "done": prog.get("done", 0),
                                        "total": prog.get("total", 0),
                                        "currentUrl": prog.get("currentUrl"),
                                    }),
                                })
                            report_now = resp.get("report") or {}
                            faults_now = report_now.get("faults") or []
                            for f in faults_now:
                                fid = _fault_key(f)
                                if fid in seen_fault_ids:
                                    continue
                                seen_fault_ids.add(fid)
                                _pub(proj_id, {
                                    "event": "verify_fault",
                                    "data": _json.dumps(
                                        _summarize_fault_for_stream(f),
                                    ),
                                })
                        except Exception:  # noqa: BLE001
                            pass  # never let progress publish crash the poll

                    async def _should_cancel() -> bool:
                        # JV-27/#4 — user hit Cancel. Re-read the DB row's
                        # status column in an independent session so the
                        # bail-out sees the very latest state without
                        # racing the outer transaction's flush.
                        try:
                            from database import async_session as _asess
                            async with _asess() as _s:
                                cur = (await _s.execute(
                                    select(VerifyRun.status).where(
                                        VerifyRun.id == row.id,
                                    ),
                                )).scalar_one_or_none()
                                return cur == "cancelled"
                        except Exception:  # noqa: BLE001
                            return False

                    resp = await client.poll_until_done(
                        runner_id,
                        on_progress=_on_progress,
                        should_cancel=_should_cancel,
                    )
                    report = resp.get("report") or {}

                    # SV-STRICT-4: run the deterministic promise gate —
                    # add PROMISE_NOT_DELIVERED synthetic faults to the
                    # report BEFORE narration so they flow through the
                    # same summary + chat surface as runtime faults.
                    try:
                        from services.blueprint_promises import load_promises
                        from services.component_contract import (
                            extract_component_contracts,
                        )
                        from services.promise_gate import check_promises

                        if project.output_dir:
                            promises = load_promises(project.output_dir)
                            contracts = extract_component_contracts(
                                project.output_dir,
                            )
                            gate_faults = check_promises(contracts, promises)
                            if gate_faults:
                                # Prepend so they surface with equal weight
                                # in the runtime-fault priority sort.
                                report["faults"] = (
                                    gate_faults + (report.get("faults") or [])
                                )
                    except Exception:  # noqa: BLE001 — never break the run
                        pass

                    # SV-STRICT-3b: precompute plain-English narration
                    # for the chat card. Never fails the run — the
                    # module fail-opens to an empty payload on error.
                    try:
                        from services.verify_narration import (
                            narrate_from_row_report,
                        )
                        report["narrated"] = narrate_from_row_report(
                            report, output_dir=project.output_dir or None,
                        )
                    except Exception:  # noqa: BLE001
                        report.setdefault("narrated", {})

                    row.report = report
                    row.interactions_passed = report.get("interactions_passed")
                    row.faults_count = len(report.get("faults") or [])
                    row.rounds_run = 1  # SV-7 bumps this per Smith round

                    # SV-STRICT-5: persist one FaultRecord per fault for
                    # cross-run analytics + self-learning. Best-effort —
                    # a DB error here must not fail the verify run.
                    try:
                        from services.fault_record_writer import (
                            build_records,
                            persist_records,
                        )
                        rows_to_persist = build_records(
                            run_id=row.id,
                            project_id=proj_id,
                            report=report,
                            narrated=report.get("narrated") or {},
                        )
                        if rows_to_persist:
                            await persist_records(db, rows_to_persist)
                    except Exception:  # noqa: BLE001
                        pass
                    row.status = resp.get("status") or "done"

                    # SV-6/7: Smith fix loop. Diagnose-only when disabled.
                    if fix and is_smith_fix_enabled() and row.faults_count:
                        remediation = await _run_smith_rounds(
                            project=project,
                            runner_report=report,
                            client=client,
                            row=row,
                            db=db,
                            max_rounds=max_rounds,
                        )
                        row.remediation = remediation
                else:
                    # Interaction-runner sidecar (docker-compose.prod.yml
                    # `forge-verify:6600`) isn't up. That's expected on a
                    # local dev box — the sidecar only ships in prod. Skip
                    # the interaction pass and fall through to the journey
                    # gate, which is self-contained via containerized_app
                    # and works locally with Docker. A run with only the
                    # journey signal is still useful.
                    logger.info(
                        "[self-verify] runner sidecar unreachable; "
                        "skipping interaction pass, journey gate will still run",
                    )
                    report = {
                        "interaction_pass": {
                            "skipped": True,
                            "reason": "runner sidecar unreachable "
                                     "(expected on local dev, prod-only service)",
                        },
                    }
                    row.report = report
                    row.interactions_passed = 0
                    row.faults_count = 0
                    row.rounds_run = 0
                    row.status = "done"

                # JV-6 — Journey gate + autofix. Runs whether or not the
                # interaction pass ran. Dispatches deterministic seams on
                # failure and re-runs the gate once. All best-effort — a
                # broken journey pipeline never fails the SV run.
                if fix:
                    journey_summary = await _run_journey_and_autofix(
                        output_dir=project.output_dir or "",
                        base_url=base_url,
                        project_id=proj_id,
                    )
                    if journey_summary:
                        row.report = {**(row.report or {}), "journey": journey_summary}

                    # V&F 2.0 (M1+M2) — classifier-first autofix over the
                    # runner's raw fault list. Off by default; opt-in via
                    # FORGE_AUTOFIX_V2=1 so we can land it without
                    # disturbing existing runs. Runs alongside (not in
                    # place of) the legacy hint-driven autofix — its
                    # output is a separate report block. M2 adds Smith
                    # dispatch + a second Playwright pass for
                    # convergence bookkeeping.
                    if os.environ.get("FORGE_AUTOFIX_V2") == "1":
                        v2_summary = await _run_faults_through_classifier(
                            output_dir=project.output_dir or "",
                            faults=(row.report or {}).get("faults") or [],
                            client=client,
                            project=project,
                            base_url=base_url,
                            target=target,
                            project_id=proj_id,
                        )
                        if v2_summary:
                            row.report = {**(row.report or {}), "autofix_v2": v2_summary}

                # Spec E Wave 2 — accessibility audit (flag-gated on
                # FORGE_A11Y_GATE, default off). When on, writes
                # verify-run/accessibility.json and attaches a summary
                # to row.report. Best-effort — never fails the pass.
                try:
                    from services.accessibility_audit import (
                        is_enabled as _a11y_gate_on,
                        run_axe_audit,
                    )
                    if _a11y_gate_on() and (project.output_dir or ""):
                        a11y_summary = run_axe_audit(
                            project.output_dir,
                            urls=[base_url] if base_url else [],
                        )
                        row.report = {
                            **(row.report or {}),
                            "accessibility": {
                                "engine": a11y_summary.get("engine"),
                                "pages_audited": a11y_summary.get("pages_audited"),
                                "total_violations": a11y_summary.get("total_violations"),
                                "critical": a11y_summary.get("critical"),
                                "serious": a11y_summary.get("serious"),
                                "would_fail_build": a11y_summary.get("would_fail_build"),
                            },
                        }
                except Exception:  # noqa: BLE001
                    logger.warning("[self-verify] a11y audit failed", exc_info=True)

                # Blueprint drift — flag when the on-disk BLUEPRINT.md no
                # longer matches what a rebuild would produce (e.g. a
                # schema or contract was edited outside a wire-in seam).
                # Gated on FORGE_BLUEPRINT so the check inherits the same
                # flag as the writer. Best-effort — never fails the pass.
                from services.flag_profile import is_on as _flag_on
                if _flag_on("FORGE_BLUEPRINT", default=True):
                    try:
                        from services.blueprint_drift import check_drift
                        drift = check_drift(project.output_dir or "")
                        row.report = {**(row.report or {}), "blueprint_drift": drift}
                        if drift.get("stale"):
                            logger.warning(
                                "[self-verify] blueprint drift: %s",
                                drift.get("diff_summary") or "stale",
                            )
                            try:
                                import json as _json
                                from services.verify_events import publish as _pub
                                _pub(proj_id, {
                                    "event": "verify_warning",
                                    "data": _json.dumps({
                                        "kind": "blueprint_drift",
                                        "summary": drift.get("diff_summary") or "",
                                        "changed_sections": drift.get("changed_sections") or [],
                                    }),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "[self-verify] blueprint drift check failed",
                            exc_info=True,
                        )

                row.completed_at = datetime.now(timezone.utc)
                row.updated_at = row.completed_at

                # SV-10 metric event — structured for future Prometheus
                # extraction. Grep: `verify_metric total=` for aggregation.
                dur_ms = int((row.completed_at - row.created_at.replace(
                    tzinfo=timezone.utc)).total_seconds() * 1000) if row.created_at else 0
                logger.info(
                    "verify_metric event=run_done target=%s invoked_by=%s "
                    "faults=%d passed=%d total=%d duration_ms=%d "
                    "interaction_pass=%s",
                    row.target, row.invoked_by, row.faults_count or 0,
                    row.interactions_passed or 0, row.interactions_run or 0,
                    dur_ms, "ran" if runner_available else "skipped",
                )

                await db.commit()

                # JV-21 — publish verify_end so subscribed UIs can close
                # the progress card and unsubscribe. Include the final
                # summary so the card can flip to green/orange without a
                # follow-up fetch.
                try:
                    from services.verify_events import publish_lifecycle
                    # SV-STRICT Followup-3: piggyback the narrated payload
                    # onto verify_end so the chat card can render English
                    # fault sentences without a second fetch.
                    narrated = (row.report or {}).get("narrated") or {}
                    publish_lifecycle(
                        proj_id, "verify_end",
                        run_id=str(row.id),
                        status=row.status,
                        interactions_run=row.interactions_run,
                        interactions_passed=row.interactions_passed,
                        faults_count=row.faults_count,
                        interaction_pass_skipped=not runner_available,
                        narrated=narrated,
                    )
                except Exception:
                    pass

                return {
                    "run_id": str(row.id),
                    "runner_run_id": runner_id,
                    "status": row.status,
                    "interactions_run": row.interactions_run,
                    "interactions_passed": row.interactions_passed,
                    "faults_count": row.faults_count,
                    "remediation": remediation,
                }

        except ForgeVerifyError as e:
            # JV-27/#4 — if this was a user-triggered cancel bail-out,
            # the row is already 'cancelled' with the proper error; don't
            # overwrite it with 'failed'. Just fire verify_end + return.
            msg = str(e)
            was_cancelled = "cancelled" in msg.lower()
            logger.warning("[self-verify] runner error for %s: %s", proj_id, e)
            if not was_cancelled:
                row.status = "failed"
                row.error = msg
                row.updated_at = datetime.now(timezone.utc)
                await db.commit()
            try:
                from services.verify_events import publish_lifecycle
                publish_lifecycle(
                    proj_id, "verify_end", run_id=str(row.id),
                    status=row.status,
                    error=(None if was_cancelled else msg[:200]),
                )
            except Exception:
                pass
            return {"error": msg}
        except Exception as e:
            logger.exception("[self-verify] unexpected failure for %s", proj_id)
            row.status = "failed"
            row.error = f"{type(e).__name__}: {e}"
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()
            try:
                from services.verify_events import publish_lifecycle
                publish_lifecycle(proj_id, "verify_end", run_id=str(row.id),
                                  status="failed", error=row.error[:200])
            except Exception:
                pass
            return {"error": row.error}


def _fault_key(f: dict) -> str:
    """Stable id for de-duping faults across polls. Prefer the runner's
    fault id; fall back to interaction id + first line of the stack.
    """
    fid = f.get("id")
    if fid:
        return str(fid)
    interaction = f.get("interaction") or {}
    iid = interaction.get("id") or interaction.get("route") or ""
    evidence = f.get("evidence") or {}
    stack = (evidence.get("stack_trace") or "").splitlines()[:1]
    return f"{iid}|{stack[0][:80] if stack else ''}"


def _summarize_fault_for_stream(f: dict) -> dict:
    """Streaming-fault payload — small, JSON-safe, human-readable.

    Reuses the classifier logic from ``verify_summary._classify_from_stack``
    so the chip's row matches what the final report will show.
    """
    try:
        from services.verify_summary import _classify_from_stack
    except Exception:  # pragma: no cover
        _classify_from_stack = lambda s: None  # noqa: E731
    interaction = f.get("interaction") or {}
    evidence = f.get("evidence") or {}
    label = (
        interaction.get("id")
        or interaction.get("route")
        or f.get("route")
        or "?"
    )
    stack = evidence.get("stack_trace") or ""
    classification = (
        f.get("signature")
        or f.get("classification")
        or f.get("kind")
        or _classify_from_stack(stack)
        or "unclassified"
    )
    raw = (
        (stack.splitlines()[0].strip() if stack else "")
        or evidence.get("body_excerpt")
        or f.get("summary")
        or f.get("message")
        or ""
    )
    return {
        "id": _fault_key(f),
        "interaction_id": str(label),
        "classification": str(classification),
        "summary": raw.strip()[:160],
    }


async def _run_smith_rounds(
    *,
    project: Project,
    runner_report: dict,
    client: ForgeVerifyClient,
    row: VerifyRun,
    db,
    max_rounds: int,
) -> dict:
    """Round-driven Smith fix loop (SV-6 base; SV-7 adds regression revert).

    Each round:
      1. Build FaultReport from the latest runner_report + classify.
      2. Render as markdown prompt, invoke Smith with mode='verify'.
      3. Re-run the runner against the still-failing interaction ids.
      4. Terminate when faults==0, rounds==max, or Smith made no
         on-disk changes (stall detection).
    """
    from services.fault_report import build_report_from_runner, render_for_smith
    # Smith invocation is lazily imported to keep the module loadable
    # without the Claude Agent SDK at import time (tests, CI).
    from agents.smith_agent import run_smith_agent
    from services.app_recall import assemble_recall

    fixed: list[str] = []
    escalated: list[dict] = []
    rounds = 1
    latest_report = runner_report

    while rounds <= max_rounds:
        report = build_report_from_runner(
            latest_report, round_=rounds,
            # SV-STRICT-2b: pin contracts + join contract_id on every fault.
            # No-op when output_dir is missing.
            output_dir=project.output_dir or None,
        )
        if not report.faults:
            break
        prompt = render_for_smith(report)

        # Best-effort recall block — Smith's own memory pipeline. If
        # unavailable, ship an empty recall (won't crash).
        try:
            recall_block = assemble_recall(project.output_dir).to_prompt_block()
        except Exception:
            recall_block = ""

        # Snapshot commit before Smith mutates so SV-7 can revert.
        pre_commit = _git_head(project.output_dir)

        try:
            result = run_smith_agent(
                user_message=prompt,
                output_dir=project.output_dir,
                recall_block=recall_block,
            )
        except Exception as e:
            logger.exception("[self-verify] Smith round %d failed", rounds)
            escalated.append({"round": rounds, "error": f"{type(e).__name__}: {e}"})
            break

        post_commit = _git_head(project.output_dir)
        if post_commit == pre_commit:
            # Stall — Smith didn't change anything. Escalate remaining.
            escalated.extend([{"id": f.id, "signature": f.signature,
                              "reason": "smith stalled"} for f in report.faults])
            break

        # Stamp the round commit so it's identifiable in git log / UX-1 timeline.
        # Amend the message (Smith just wrote it) with a [verify:...] tag.
        _stamp_verify_commit(
            project.output_dir,
            f"[verify:{row.runner_run_id}:round_{rounds}]",
        )

        # Re-run failing subset via the runner. Build a scoped interactions
        # list from the previous round's fault ids so we're not re-verifying
        # the whole app on rounds 2/3.
        failing_ids = {f.id for f in report.faults}
        prior_interactions = [
            f["interaction"] for f in (latest_report.get("faults") or [])
            if f.get("interaction_id") in failing_ids
        ]
        if not prior_interactions:
            break
        rounds += 1
        if row.target == "deploy":
            base_url = await resolve_deploy_base_url(db, project.id)
        else:
            base_url = _base_url_for(project, row.target)
        try:
            new_runner_id = await client.run(
                project_id=str(project.id),
                target=row.target,
                base_url=base_url,
                interactions=prior_interactions,
            )
            resp = await client.poll_until_done(new_runner_id)
            latest_report = resp.get("report") or {}
        except ForgeVerifyError as e:
            escalated.append({"round": rounds, "error": str(e)})
            break

        # SV-7 regression detection: if Smith's fix INTRODUCED faults
        # (round N+1 count > round N count on the *same subset*), revert
        # the round commit and escalate — the fixer regressed.
        prior_fault_count = len(report.faults)
        new_fault_count = len(latest_report.get("faults") or [])
        if new_fault_count > prior_fault_count:
            logger.warning(
                "[self-verify] round %d regressed (%d → %d faults); reverting",
                rounds - 1, prior_fault_count, new_fault_count,
            )
            _git_revert_head(project.output_dir)
            escalated.append({
                "round": rounds - 1, "reason": "regression",
                "prior_faults": prior_fault_count,
                "new_faults": new_fault_count,
            })
            break

        # Track which of the prior round's faults survived
        surviving_ids = {
            f.get("interaction_id") for f in (latest_report.get("faults") or [])
        }
        fixed_ids = [fid for fid in failing_ids if fid not in surviving_ids]
        fixed.extend(fixed_ids)

        # SV-STRICT-5: mark fix outcomes on the FaultRecord rows this run
        # emitted at t=0. Best-effort — DB writes here are learning
        # substrate, not part of the fix loop's success criterion.
        try:
            from services.fault_record_writer import mark_fix_outcomes
            still_failing_ids = [
                fid for fid in failing_ids if fid in surviving_ids
            ]
            await mark_fix_outcomes(
                db, run_id=row.id,
                fixed_component_ids=fixed_ids,
                still_failing_component_ids=still_failing_ids,
            )
        except Exception:  # noqa: BLE001
            pass

        # Dedup: same signature+id seen twice → escalate that specific fault
        # so we don't loop on it. Continues on others.
        surviving_sig_pairs = {
            (f.get("interaction_id"), _sig_from_raw_fault(f))
            for f in (latest_report.get("faults") or [])
        }
        for f in report.faults:
            if (f.id, f.signature) in surviving_sig_pairs:
                escalated.append({
                    "id": f.id, "signature": f.signature,
                    "reason": "signature persisted across smith round",
                })

        # Persist round-level progress
        row.rounds_run = rounds - 1
        row.faults_count = len(latest_report.get("faults") or [])
        row.report = latest_report  # keep the latest snapshot as the report
        await db.commit()

    return {
        "rounds_run": rounds - 1,
        "fixed": fixed,
        "escalated": escalated,
        "final_fault_count": len(latest_report.get("faults") or []),
    }


def _stamp_verify_commit(output_dir: str, tag: str) -> None:
    """Amend the just-created commit with a `[verify:...]` tag in the
    message so git log + UX-1 timeline can identify it. Best-effort."""
    import subprocess
    try:
        # Read the current commit message
        r = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=output_dir, capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return
        msg = (r.stdout or "").rstrip()
        if tag in msg:
            return  # already stamped
        new_msg = f"{msg}\n\n{tag}"
        subprocess.run(
            ["git", "commit", "--amend", "-m", new_msg, "--no-verify"],
            cwd=output_dir, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _git_revert_head(output_dir: str) -> bool:
    """Undo the last commit while keeping the working tree clean.

    Uses `git reset --hard HEAD~1` because the round commit is
    self-contained (Smith writes files, commits, we amended the message).
    Returns True on success.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            cwd=output_dir, capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sig_from_raw_fault(raw: dict) -> str:
    """Re-classify a raw fault to get its signature (cheap — no I/O)."""
    from services.fault_classifier import classify
    from services.fault_report import _hydrate_evidence, _hydrate_interaction
    try:
        interaction = _hydrate_interaction(raw.get("interaction") or {})
        evidence = _hydrate_evidence(raw.get("evidence") or {})
        return classify(interaction, evidence).signature
    except Exception:
        return "UNCLASSIFIED"


def _git_head(output_dir: str) -> str | None:
    """Cheap HEAD lookup so we can detect whether Smith made a commit.

    Returns None if the dir isn't a repo (verify still works, we just
    lose stall-detection precision).
    """
    import subprocess
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=output_dir, capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


async def _ensure_preview_running(project: Project, ready_timeout_s: int = 45) -> None:
    """Ensure the generated app's preview server is up before V&F points
    Playwright at it. Idempotent — calls into :mod:`services.preview_manager`
    which no-ops if the environment is already healthy.

    Raises :class:`ForgeVerifyError` if the preview can't be started or
    doesn't come up within ``ready_timeout_s`` seconds. Caller writes that
    as the run's ``error`` field; the user gets "preview couldn't start"
    instead of "0/93 passed" (which is what happens today when the URL
    503s on every interaction).
    """
    from services.preview_manager import (
        start_project_environment,
        health_check_preview,
    )

    short_id = project.short_id
    output_dir = project.output_dir
    if not short_id or not output_dir:
        raise ForgeVerifyError(
            f"project {project.id} missing short_id or output_dir; "
            "cannot start preview",
        )

    try:
        await start_project_environment(short_id, output_dir)
    except Exception as e:  # noqa: BLE001
        raise ForgeVerifyError(
            f"preview failed to start for project {short_id}: {e}",
        ) from e

    # Poll until healthy — start_project_environment returns as soon as
    # the process is spawned; next dev takes ~5-15s to bind its port and
    # even longer to compile the first request. Playwright timing out on
    # early 503s during compile is the exact fault we're trying to prevent.
    loop = asyncio.get_event_loop()
    deadline = loop.time() + ready_timeout_s
    while loop.time() < deadline:
        health = await health_check_preview(short_id)
        if health.get("healthy"):
            return
        await asyncio.sleep(1)
    raise ForgeVerifyError(
        f"preview for project {short_id} didn't become healthy within "
        f"{ready_timeout_s}s — check /tmp/tentoroforge-backend.log for the "
        "next dev subprocess output",
    )


def _project_app_url_override(project: Project) -> str | None:
    """Per-project preview-URL override.

    When set, the runner points at this URL directly and the platform's
    preview-manager path (``start_project_environment`` + ``/preview/serve``
    proxy) is skipped entirely. Two knobs, in precedence order:

    - ``FORGE_APP_URL_<SHORT_ID>`` (uppercased, dashes→underscores)
        Per-project override — the common local-dev case where a
        specific generated app is being hand-run on a known port.
    - ``FORGE_APP_URL`` — global fallback.

    Returns the URL (trailing slash stripped) or ``None`` if neither
    env var is set. A blank value counts as unset.
    """
    short = (project.short_id or "").strip()
    if short:
        key = "FORGE_APP_URL_" + short.upper().replace("-", "_")
        val = (os.environ.get(key) or "").strip().rstrip("/")
        if val:
            return val
    val = (os.environ.get("FORGE_APP_URL") or "").strip().rstrip("/")
    return val or None


def _base_url_for(project: Project, target: str) -> str:
    """Where the runner should point its browser."""
    if target == "deploy":
        # SV-8: resolve to the latest succeeded Deployment's URL.
        # Sync lookup (blocking DB call) is fine here — this runs inside
        # an already-async orchestrator and the query is a single row.
        # Callers should prefer resolve_deploy_base_url() when they
        # already have a DB session in scope.
        raise ForgeVerifyError(
            "deploy target: use resolve_deploy_base_url() with an active "
            "DB session, or pass base_url explicitly.",
        )
    # Preview: env-override wins over the platform reverse-proxy.
    # Local devs frequently run the generated app themselves (bash start.sh
    # on some port); a per-project override lets the runner hit that
    # directly and skip the platform-managed preview entirely — otherwise
    # the /preview/serve proxy 503s on every click and every fault is
    # misattributed.
    override = _project_app_url_override(project)
    if override:
        return override
    # JV-27/A1 — hostname is env-configurable so local dev boxes don't
    # send Playwright at `backend:6500` (docker-compose hostname) and
    # count every net::ERR_NAME_NOT_RESOLVED as a runtime fault.
    host = os.environ.get("FORGE_INTERNAL_BASE_URL", "http://localhost:6500").rstrip("/")
    return f"{host}/api/projects/{project.id}/preview/serve"


async def resolve_deploy_base_url(db, project_id, deployment_id=None) -> str:
    """SV-8 — look up a Vercel URL for `target=deploy` runs.

    If `deployment_id` is given, resolve that specific deploy (used by the
    "Verify deployed app" button on the deployment-history panel).
    Otherwise resolve the latest succeeded Deployment for the project.
    """
    from sqlalchemy import desc, select as _select
    from models.deployment import Deployment

    q = _select(Deployment).where(Deployment.project_id == project_id)
    if deployment_id is not None:
        q = q.where(Deployment.id == deployment_id)
    else:
        q = q.where(Deployment.status == "succeeded")
    q = q.order_by(desc(Deployment.created_at)).limit(1)
    dep = (await db.execute(q)).scalar_one_or_none()
    if not dep or not dep.url:
        raise ForgeVerifyError(
            "no succeeded deployment found for this project — publish first",
        )
    url = dep.url
    if not url.startswith("http"):
        url = f"https://{url}"
    return url.rstrip("/")


async def _run_journey_and_autofix(
    *,
    output_dir: str,
    base_url: str,
    project_id: uuid.UUID | None = None,
) -> dict | None:
    """Run the journey gate, dispatch autofix on failures, run once more.

    Returns a serializable summary suitable for row.report["journey"]:
      {
        "first_run":  {"total": N, "passed": P, "failed": F, "duration_ms": T,
                       "hints": [...]},
        "autofix":    {"dispatched": [...], "residual_hints": [...]},
        "second_run": {...} | None,   # only present if autofix ran
      }

    Best-effort — every layer is wrapped so a broken journey pipeline
    never fails the SV run. FORGE_JOURNEY_GATE=off gets forced to warn
    for user-triggered runs so the click always exercises the gate.
    """
    if not output_dir:
        return None
    try:
        from services.journey_gate import run_journey_gate
        from services.journey_verifier.autofix import apply_autofix
    except Exception as exc:
        logger.info("[self-verify] journey modules unavailable: %s", exc)
        return None

    # User-triggered verify always exercises the gate — no env flag needed.
    # The pipeline-embedded gate keeps its own opt-in via FORGE_JOURNEY_GATE
    # because that path runs on every generation, not just on user click.
    first = await _collect_journey_events(
        run_journey_gate(output_dir, base_url=base_url, force_mode="warn"),
        project_id=project_id,
    )
    # Route sweep results (SMOKE-2/G1) ride the same Playwright run —
    # harvest them whenever they exist. Empty-marker routes are the
    # live-rendered version of what binding_smoke predicts statically.
    sweep = None
    try:
        from services.journey_verifier.sweep import read_sweep_results
        sweep = read_sweep_results(output_dir)
        if sweep and (sweep["summary"]["with_empty_markers"]
                      or sweep["summary"]["nav_failed"]):
            logger.warning(
                "[self-verify] sweep: %d route(s) with empty markers, %d "
                "nav failures", sweep["summary"]["with_empty_markers"],
                sweep["summary"]["nav_failed"],
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("[self-verify] sweep results unavailable: %s", exc)
    # Visual regression (G7): diff this run's sweep captures against the
    # blessed baseline (auto-blessed on the first run). Drift — a skin
    # regression, a collapsed layout — is flagged even when every
    # functional check still passes.
    if sweep is not None:
        try:
            from services.visual_regression import compare_to_baseline
            sweep["regression"] = compare_to_baseline(output_dir)
        except Exception as exc:  # noqa: BLE001
            logger.info("[self-verify] visual regression unavailable: %s", exc)
    # Visual QA critic (G1): LLM design review over the sweep screenshots,
    # judged against the design brief. Findings → contracts/visual-qa.json
    # + attached under "sweep" so the verify report carries them.
    if sweep is not None:
        try:
            from services.visual_qa_critic import (
                critique_screenshots, is_visual_qa_enabled,
            )
            if is_visual_qa_enabled():
                sweep["visual_qa"] = await critique_screenshots(output_dir)
        except Exception as exc:  # noqa: BLE001
            logger.info("[self-verify] visual QA critic unavailable: %s", exc)
    if not first["gate_summary"]:
        # Gate skipped (app unreachable, extractor missing) — nothing to
        # autofix, but surface what we saw as a signal.
        return {"first_run": first, "autofix": None, "second_run": None,
                "sweep": sweep}

    hints = first["hints"]
    if not hints:
        return {"first_run": first, "autofix": None, "second_run": None,
                "sweep": sweep}

    # There were failures — dispatch the fixers.
    try:
        report = apply_autofix(output_dir, hints)
        autofix = report.to_dict()
        # JV-21 — broadcast an autofix marker so a subscribed UI can
        # advance its phase-pip from Walk journeys → Auto-fix.
        if project_id is not None:
            try:
                from services.verify_events import publish_lifecycle
                publish_lifecycle(
                    project_id, "verify_autofix_dispatched",
                    dispatched=autofix.get("dispatched") or [],
                    residual_hints=autofix.get("residual_hints") or [],
                )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("[self-verify] autofix crashed: %s", exc)
        autofix = {"error": str(exc)[:400]}

    # Second walk — did the fixes take?
    second = await _collect_journey_events(
        run_journey_gate(output_dir, base_url=base_url, force_mode="warn"),
        project_id=project_id,
    )
    return {"first_run": first, "autofix": autofix, "second_run": second,
            "sweep": sweep}


async def _run_faults_through_classifier(
    *,
    output_dir: str,
    faults: list[dict],
    client: ForgeVerifyClient | None = None,
    project: Project | None = None,
    base_url: str | None = None,
    target: str = "preview",
    project_id: uuid.UUID | None = None,
) -> dict | None:
    """V&F 2.0 (M1+M2+M3) — classify raw faults, dispatch, re-verify.

    M1: classifier + deterministic handlers.
    M2: Smith dispatch after deterministic pass; if any Smith handler
        actually wrote to disk, run Playwright a second time and mark
        which round-1 faults are healed vs still-broken.
    M3: pre-round git snapshot + auto-revert on regression, in-run
        Smith dispatch de-dup ledger, and a per-class progress event
        the chip UI reads to render "N healed / M residual" strips.

    Only invoked when ``FORGE_AUTOFIX_V2=1`` — see :func:`run_self_verify`.

    Best-effort: any exception degrades to a warning + returns None so
    a broken v2 dispatcher never blocks the legacy path from completing.
    Returns a serializable dict shaped for ``row.report["autofix_v2"]``:

        {
          "deterministic_results": [...],
          "smith_results": [...],
          "residuals": [...],
          "healed_faults": ["<interaction_id>", ...],
          "still_broken": ["<interaction_id>", ...],
          "second_pass_summary": {"faults_count": N, ...} | None,
          "snapshot": {"commit_sha": "...", "pass_count": N, "fault_count": N},
          "revert": {"reverted": bool, "reason": str|None,
                      "newly_broken_ids": [...]},
        }
    """
    if not output_dir or not faults:
        return None
    try:
        from services.journey_verifier.autofix import apply_autofix_v2
        from services.journey_verifier.dedup import FaultAttemptLedger
        from services.journey_verifier.regression_guard import (
            snapshot_before_round,
        )

        # Optional route registry — read on-disk schema slugs so the
        # classifier can distinguish missing-page (route not registered)
        # from catch-all-router-broken (route is registered but 404'd).
        registry: set[str] = _read_route_registry(output_dir)

        # M3 — take a git snapshot BEFORE deterministic + Smith mutate
        # so we can revert if the round makes things worse.
        snap = snapshot_before_round(output_dir, faults_before=faults)

        # M3 — one dedup ledger per run so a fault Smith already tried
        # in an earlier phase of this run doesn't get retried.
        ledger = FaultAttemptLedger()

        report = await apply_autofix_v2(
            output_dir, faults, route_registry=registry or None,
            ledger=ledger,
        )
        result_dict = report.to_dict()
        result_dict["snapshot"] = {
            "commit_sha": snap.commit_sha,
            "pass_count": snap.pass_count,
            "fault_count": snap.fault_count,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[self-verify] autofix_v2 failed: %s", exc)
        return {"error": str(exc)[:400]}

    # M2 convergence — only run the second Playwright pass when a Smith
    # handler actually wrote to disk. Deterministic-only fixes already
    # get re-verified by the legacy journey-gate second run above; a
    # second interaction-runner pass costs a lot and only pays off when
    # Smith did LLM-authored surgery.
    smith_dispatched_files = any(
        (r.get("fixed") and (r.get("smith_turns_used") or 0) > 0)
        for r in result_dict.get("smith_results") or []
    )
    if not smith_dispatched_files or client is None or project is None or not base_url:
        result_dict.update({
            "healed_faults": [],
            "still_broken": [],
            "second_pass_summary": None,
            "revert": {"reverted": False, "reason": None,
                       "newly_broken_ids": []},
        })
        _publish_class_progress(project_id, result_dict, faults, registry)
        return result_dict

    try:
        from services.interaction_extractor import extract_interactions
        from services.journey_verifier.fault_classifier import classify_fault
        from services.journey_verifier.smith_autofix_convergence import (
            mark_healed_faults,
        )

        # Re-run the SAME interactions (scoped to what we already ran)
        # so we can compare like-for-like. Cheaper than a fresh extract.
        interactions = extract_interactions(output_dir, scope="*")
        if not interactions:
            result_dict.update({
                "healed_faults": [],
                "still_broken": [],
                "second_pass_summary": {
                    "skipped": True,
                    "reason": "no interactions extractable for second pass",
                },
            })
            return result_dict

        runner_id_2 = await client.run(
            project_id=str(project.id),
            target=target,
            base_url=base_url,
            interactions=interactions,
        )
        resp = await client.poll_until_done(runner_id_2)
        second_report = resp.get("report") or {}
        round2_faults = second_report.get("faults") or []

        # Re-classify round-1 faults so we can partition them.
        round1_classified = []
        for raw in faults:
            try:
                round1_classified.append(
                    classify_fault(raw, route_registry=registry or None),
                )
            except Exception:  # noqa: BLE001
                continue
        healed, still_broken = mark_healed_faults(round1_classified, round2_faults)

        # M3 — regression guard: if this round made things worse,
        # revert the edits and drop the healed-faults claim.
        from services.journey_verifier.regression_guard import (
            compare_and_maybe_revert,
        )
        revert = compare_and_maybe_revert(snap, round2_faults, output_dir)
        if revert.reverted:
            logger.warning(
                "[self-verify] autofix_v2 round REVERTED "
                "(fault_count %d → %d, newly_broken=%s)",
                snap.fault_count, len(round2_faults), revert.newly_broken_ids,
            )
            # After a revert, no faults are "healed" — the state matches
            # what it was pre-round. Move any previously-claimed healed
            # ids into still-broken so downstream consumers see truth.
            still_broken = list(round1_classified)
            healed = []

        result_dict.update({
            "healed_faults": [cf.interaction_id for cf in healed],
            "still_broken": [cf.interaction_id for cf in still_broken],
            "second_pass_summary": {
                "faults_count": len(round2_faults),
                "interactions_run": second_report.get("interactions_run"),
                "interactions_passed": second_report.get("interactions_passed"),
                "runner_run_id": runner_id_2,
            },
            "revert": {
                "reverted": revert.reverted,
                "reason": revert.reason,
                "newly_broken_ids": list(revert.newly_broken_ids),
            },
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[self-verify] autofix_v2 second pass failed: %s", exc)
        result_dict.update({
            "healed_faults": [],
            "still_broken": [],
            "second_pass_summary": {"error": str(exc)[:400]},
            "revert": {"reverted": False, "reason": None,
                       "newly_broken_ids": []},
        })

    # M3 — broadcast per-class healed/residual tallies so the chip UI
    # can render a per-class strip once the pass wraps.
    _publish_class_progress(project_id, result_dict, faults, registry)
    return result_dict


def _publish_class_progress(
    project_id: uuid.UUID | None,
    result_dict: dict,
    round1_faults: list[dict],
    registry: set[str] | None,
) -> None:
    """Emit `verify_class_progress` — per-class healed vs residual
    counts, keyed off the classifier's ``class_name`` taxonomy. Best-
    effort; a broken publish never crashes the pass.
    """
    if project_id is None:
        return
    try:
        from services.journey_verifier.fault_classifier import classify_fault
        # Build a lookup of interaction_id → class_name from the
        # round-1 faults (same classification the dispatcher used).
        id_to_class: dict[str, str] = {}
        for raw in round1_faults or []:
            try:
                cf = classify_fault(raw, route_registry=registry or None)
            except Exception:  # noqa: BLE001
                continue
            if cf.interaction_id and cf.interaction_id != "?":
                id_to_class[cf.interaction_id] = cf.class_name

        healed_ids = result_dict.get("healed_faults") or []
        still_ids = result_dict.get("still_broken") or []
        healed_by_class: dict[str, int] = {}
        residual_by_class: dict[str, int] = {}
        for iid in healed_ids:
            cls = id_to_class.get(iid, "unknown")
            healed_by_class[cls] = healed_by_class.get(cls, 0) + 1
        for iid in still_ids:
            cls = id_to_class.get(iid, "unknown")
            residual_by_class[cls] = residual_by_class.get(cls, 0) + 1

        # If neither side has entries, don't emit — the chip stays as-is.
        if not healed_by_class and not residual_by_class:
            return

        import json as _json
        from services.verify_events import publish as _pub
        _pub(project_id, {
            "event": "verify_class_progress",
            "data": _json.dumps({
                "healed_by_class": healed_by_class,
                "residual_by_class": residual_by_class,
            }),
        })
    except Exception:  # noqa: BLE001
        pass


def _read_route_registry(output_dir: str) -> set[str]:
    """Best-effort read of the app's schema slugs → routes.

    We scan ``src/schemas/`` for ``*.json`` files (the same source of
    truth ``_regenerate_route_registry`` uses) and derive routes from
    their relative paths. Never raises."""
    import glob
    from services.route_slug import route_from_slug

    routes: set[str] = set()
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return routes
    try:
        for fp in glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True):
            rel = os.path.relpath(fp, sdir)
            slug = os.path.splitext(rel)[0].replace(os.sep, "/")
            try:
                routes.add(route_from_slug(slug))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return routes
    return routes


async def _collect_journey_events(agen, *, project_id: uuid.UUID | None = None) -> dict:
    """Consume the gate's async generator into a flat summary. Extracts
    the journey_result / journey_gate / journey_remediation events into
    typed lists so the report row can be serialized without SSE noise.

    JV-21 — when ``project_id`` is passed, every event is also broadcast
    to the verify-events pubsub so a subscribed UI (the progress card)
    can advance its phase pips live.
    """
    import json as _json
    results: list[dict] = []
    hints: list[dict] = []
    gate_summary: dict | None = None

    # Optional pubsub — best-effort, never blocks or crashes the collector.
    publish = None
    if project_id is not None:
        try:
            from services.verify_events import publish as _pub
            publish = _pub
        except Exception:
            publish = None

    try:
        async for evt in agen:
            # Fan-out FIRST so the UI sees the event before we do any
            # post-processing; publish is non-blocking.
            if publish is not None:
                try:
                    publish(project_id, evt)
                except Exception:
                    pass
            try:
                data = _json.loads(evt["data"])
            except Exception:
                continue
            kind = evt.get("event")
            if kind == "journey_result":
                results.append(data)
            elif kind == "journey_gate":
                gate_summary = data
            elif kind == "journey_remediation":
                hints.append(data)
    except Exception as exc:
        logger.warning("[self-verify] journey stream crashed: %s", exc)
    return {"results": results, "hints": hints, "gate_summary": gate_summary}


async def _trim_verify_runs(db, project_id) -> None:
    """Delete VerifyRun rows older than the retention keep-count.

    Runs before every new-row insert so the table stays bounded. Only
    deletes for the specific project — cheap; index on project_id.
    """
    from sqlalchemy import delete, desc, select
    retention = int(os.environ.get("FORGE_VERIFY_RETENTION", "20"))
    if retention < 1:
        return  # 0 or negative → no cap
    # Find the (retention+1)-th newest row's created_at as the cutoff.
    keep_ids = (await db.execute(
        select(VerifyRun.id)
        .where(VerifyRun.project_id == project_id)
        .order_by(desc(VerifyRun.created_at))
        .limit(retention),
    )).scalars().all()
    if len(keep_ids) < retention:
        return  # fewer rows than the cap — nothing to trim
    await db.execute(
        delete(VerifyRun)
        .where(VerifyRun.project_id == project_id)
        .where(VerifyRun.id.notin_(keep_ids)),
    )
    await db.flush()  # commit happens later with the new row
