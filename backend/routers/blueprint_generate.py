"""Generation through the Living Blueprint (§115, §120).

The platform's existing ``/generate`` drives the chain this rebuild exists to
replace: 6,400 lines of router over 582 services, with a repair pass for every
way an LLM had been observed to get something wrong. Everything built against
the PRD — the Blueprint, the agent DAG, the projections, Smith — has until now
been reachable only from a CLI, which means the product surface and the engine
were two different systems.

This is the seam between them. It is a separate router rather than an edit to
the old one for two reasons: the legacy path keeps working untouched while the
new one is proven, and a caller can see from the URL which engine it is asking
for.

What runs here is §120's pipeline and nothing else::

    INPUT -> LIVING BLUEPRINT -> PLAN -> AGENT DAG -> DESIGN/DATA/LOGIC
          -> GENERATED APPLICATION -> DATABASE -> BUILD -> VERIFY -> PREVIEW

Progress is streamed per node because §111 asks for observable status, and
because a twenty-eight minute run that prints nothing is a run nobody can
review — which is exactly how a silently skipped node went unnoticed until the
endpoint count was diffed by hand.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db
from models.auth import PlatformUser
from auth import get_current_user
from services.project_paths import project_root
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["generation", "blueprint"])


class BlueprintGenerateRequest(BaseModel):
    """§4.1 — the prompt, and nothing the engine can work out for itself."""

    description: str = Field(..., min_length=1)
    #: §96 — CRM, HRMS, ATS… Left blank when the domain agent should infer it.
    domain: str = ""
    #: Stop after the Blueprint. §114 step 4 proposes before it regenerates,
    #: and the same courtesy is worth having on a first build: the definition
    #: is cheap, the dozen agent calls that follow are not.
    define_only: bool = False
    #: Discard an existing Blueprint and start over. Off by default, and
    #: deliberately explicit: a Blueprint carries the decisions the user made
    #: (§20) and the ids every generated artifact is keyed to (§12), so
    #: replacing one silently is not a regeneration, it is amnesia.
    fresh: bool = False
    #: §25 — the user has seen the definition and accepted it.
    #:
    #: The PRD puts a checkpoint between understanding and building: "once the
    #: application definition is accepted, Smith generates the build plan."
    #: Without it a single POST spends forty minutes and a dozen model calls on
    #: an understanding nobody has looked at. Approval applies at meaningful
    #: product boundaries (§25), not per property — so this is one flag, not a
    #: field-by-field diff.
    approved: bool = False


def _report_payload(report: Any) -> dict:
    """The run outcome, including what did *not* run.

    Skipped and blocked nodes are named rather than counted. A plan that
    quietly drops nodes reads exactly like one that ran them and found nothing
    to do, and the Blueprint is left holding whatever it held before.
    """
    return {
        "completed": list(report.completed),
        "skipped": [
            {"node": n, "unmet": getattr(report, "skipped_because", {}).get(n, "")}
            for n in report.skipped
        ],
        "blocked": list(report.blocked),
        "failed": [
            {"node": n,
             "why": getattr(report, "failed_because", {}).get(n, "")}
            for n in report.failed
        ],
    }


@router.post("/api/projects/{project_id}/generate/blueprint")
async def generate_via_blueprint(
    project_id: uuid.UUID,
    req: BlueprintGenerateRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an application through the Blueprint engine, streaming progress."""
    project = await get_project_with_auth(project_id, user, db)

    from services.blueprint.executors import AnthropicModel, make_executor
    from services.blueprint.orchestrator import (
        DAG, completed_nodes, levels, run)
    from services.blueprint.service import BlueprintService

    try:
        output_dir = project_root(str(project_id))
    except ValueError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    # The application is projected beside the Blueprint it comes from, so a
    # later incremental change has somewhere to write. A projection with no
    # app root blocks, and takes every node that depends on it.
    app_root = str(output_dir / "app")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event: str, data: dict) -> None:
        """Push an event from the worker thread into the loop's queue.

        ``Queue.put_nowait`` is not thread-safe. Called directly from the
        executor thread it appends without ever waking the loop, so the
        consumer stays blocked on ``get()`` and every event arrives at once
        when the future resolves — which is what happened: ninety seconds of
        keep-alive pings, then the whole run's progress in a single burst.
        ``call_soon_threadsafe`` is what actually crosses the boundary.
        """
        loop.call_soon_threadsafe(
            queue.put_nowait, {"event": event, "data": json.dumps(data)}
        )

    async def generate() -> None:

        def work() -> dict:
            # Resume if there is something to resume. Creating unconditionally
            # meant a second POST wiped the first Blueprint — with it the
            # recorded decisions, the change history, and the stable ids every
            # projected file is keyed to. The CLI has always resumed; the
            # endpoint did not, which made clicking generate twice destructive.
            existing = output_dir / ".forge" / "blueprint" / "current.json"
            resumed = existing.is_file() and not req.fresh
            if resumed:
                svc = BlueprintService.load(output_dir=str(output_dir))
                # A resumed Blueprint keeps its own description unless this
                # request restates it; the request is the newer intent.
                #
                # It belongs on `application`, not `product` — `product` holds
                # objectives, personas, terminology and capabilities and admits
                # nothing else. Writing it to the wrong section poisoned the
                # document with a field the contract refuses, and every resumed
                # run then failed on the first validate: the requirements node
                # died and all twenty-one behind it were skipped.
                if req.description:
                    svc.doc.setdefault("application", {})["description"] = req.description
                    svc.validate()   # never persist a document that will not load
                    svc.save()
            else:
                svc = BlueprintService.create(
                    output_dir=str(output_dir),
                    app_id=str(project_id),
                    name=getattr(project, "name", "") or "Application",
                    domain=req.domain or "unknown",
                    description=req.description,
                )

            from services.blueprint.plan_forecast import forecast

            definition = ["requirements", "application_model"]
            plan = [k for lvl in levels() for k in lvl]
            awaiting = req.define_only or not req.approved
            if awaiting:
                # §25 — stop at the definition and wait to be accepted. The
                # definition is two calls; what follows is a dozen or more, so
                # the checkpoint costs almost nothing and saves the case where
                # the understanding was wrong.
                plan = definition

            # Resume means continue, not redo. Without this the endpoint
            # re-executed all 22 nodes against a document that was already
            # fourteen nodes in: it paid for them twice and, because a re-run
            # appends to a section rather than replacing it, came back with 39
            # requirements and 34 pages where the first pass had 31 and 30.
            # `fresh` remains the escape hatch for starting over.
            already: set[str] = set()
            if resumed:
                already = completed_nodes(svc.doc)
                plan = [k for k in plan if k not in already]

            emit("plan", {"nodes": plan, "total": len(plan),
                          "alreadyComplete": sorted(already),
                          "awaitingApproval": awaiting and not req.approved})

            # A single client rather than a router: per-node model choice is a
            # tuning decision, and defaulting every node to one model keeps the
            # first wiring honest about what it is doing.
            executor = make_executor(svc, AnthropicModel())
            # Two different units, and conflating them made the progress
            # meaningless: `done` counted executor calls while `total` counted
            # nodes, so a fan-out node reported 44 of 22 and kept climbing.
            # A node that fans out is one node and many calls; a reader wants
            # both, and neither can stand in for the other.
            nodes_done: set[str] = set()
            calls_done = 0

            def traced(spec):
                nonlocal calls_done
                emit("node:start", {"node": spec.node, "agent": spec.agent,
                                    "subject": spec.subject})
                result = executor(spec)
                calls_done += 1
                nodes_done.add(spec.node)
                emit("node:done", {
                    "node": spec.node,
                    "subject": spec.subject,
                    # progress through the graph
                    "nodesDone": len(nodes_done), "nodesTotal": len(plan),
                    # work done inside it, which a fan-out multiplies
                    "callsDone": calls_done,
                })
                return result

            report = run(svc, traced, plan=plan, commit=True,
                         user_request=req.description, app_root=app_root)

            # §26 — what the finished application should contain, so the run
            # can be checked against the plan rather than only watched.
            counts = forecast(svc.doc)
            emit("forecast", counts)

            return {"resumed": resumed,
                    "awaitingApproval": awaiting and not req.approved,
                    "forecast": counts,
                    "report": _report_payload(report),
                    "version": svc.doc.get("version"),
                    "blueprint": str(svc.current_path)}

        try:
            emit("started", {"projectId": str(project_id),
                             "engine": "blueprint"})
            outcome = await loop.run_in_executor(None, work)
            emit("done", outcome)
        except Exception as exc:  # noqa: BLE001 - the client needs the reason
            logger.exception("blueprint generation failed for %s", project_id)
            emit("error", {"message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def stream():
        task = asyncio.create_task(generate())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    return EventSourceResponse(stream())


@router.get("/api/projects/{project_id}/blueprint")
async def read_blueprint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Blueprint as it stands — §110's tree, and what §113 links against."""
    await get_project_with_auth(project_id, user, db)
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(project_root(str(project_id))))
    except FileNotFoundError:
        raise HTTPException(status_code=404,
                            detail="no Blueprint for this project") from None
    return svc.doc
