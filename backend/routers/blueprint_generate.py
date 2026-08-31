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
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db
from models.auth import PlatformUser
from auth import get_current_user
from pathlib import Path

from services.project_paths import project_root
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["generation", "blueprint"])


class BlueprintGenerateRequest(BaseModel):
    """§4.1 — the prompt, and nothing the engine can work out for itself."""

    description: str = Field(..., min_length=1)
    #: §96 — CRM, HRMS, ATS… Left blank when the domain agent should infer it.
    domain: str = ""
    #: §4/§14 — text the user supplied rather than typed: a requirements
    #: document, a spec, a brief. §5 says there is one engine with several ways
    #: of expressing intent, not a second pipeline per input, so evidence joins
    #: the description instead of arriving through a parallel path.
    #:
    #: Text only, and extracted by the client. A .docx or .pdf reader here
    #: would be a second file-format dependency in the request path, and the
    #: requirements agent reads prose either way.
    evidence: list[str] = Field(default_factory=list)
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


def _output_dir(project: Any) -> Path:
    """Where this project's application lives.

    `create_project` makes output/<short-id>, git-initialises it and records
    it on the row; generation derived output/<uuid> instead and wrote there.
    Every project therefore had two directories — an empty git repo the
    product knows about, and the actual application it does not — and
    export_service and git_service both operate on the recorded one. Export
    would have shipped an empty repository.

    The row wins. `project_root` remains the fallback for rows created before
    output_dir was populated, and it validates the id against traversal.
    """
    recorded = getattr(project, "output_dir", None)
    if recorded:
        return Path(recorded)
    return project_root(str(project.id))


def _with_evidence(req: "BlueprintGenerateRequest") -> str:
    """The description, plus whatever the user uploaded.

    Appended rather than carried separately because §5 asks for one engine
    with several ways of expressing intent — a second field would mean a
    second path through every agent that reads the brief. The requirements
    agent already extracts requirements from prose; a specification is prose
    the user did not have to retype.

    Labelled, so the agent can tell what the person said from what a document
    said. An unlabelled concatenation makes a 40-page spec look like it was
    typed into a chat box, and the agent weights it accordingly.
    """
    blocks = [t.strip() for t in (req.evidence or []) if t and t.strip()]
    if not blocks:
        return req.description
    parts = [req.description, "", "SUPPLIED DOCUMENTS — the user provided these "
             "rather than typing them. Treat them as requirements evidence "
             "(\u00a714), not as conversation:"]
    for i, block in enumerate(blocks, start=1):
        parts.append(f"\n--- document {i} ---\n{block}")
    return "\n".join(parts)


@router.post("/api/projects/{project_id}/generate/blueprint")
async def generate_via_blueprint(
    project_id: uuid.UUID,
    req: BlueprintGenerateRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an application through the Blueprint engine, streaming progress."""
    project = await get_project_with_auth(project_id, user, db)

    from services.blueprint.executors import (
        RunUsage, make_executor, tiered_router)
    from services.blueprint.orchestrator import (
        DAG, completed_nodes, levels, run)
    from services.blueprint.service import BlueprintService
    from services.smith.smith import domain_nodes

    try:
        output_dir = _output_dir(project)
    except ValueError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    _adopt_design_references(output_dir, str(project_id))
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
                    description=_with_evidence(req),
                )

            from services.blueprint.plan_forecast import forecast

            definition = domain_nodes()
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
            # Effort is per node: thinking bills as output, and a node filling
            # in a constrained shape does not need a frontier thinking budget.
            # The nodes everything downstream derives from stay at `high`.
            usage = RunUsage()
            executor = make_executor(svc, tiered_router(), usage=usage)
            # Two different units, and conflating them made the progress
            # meaningless: `done` counted executor calls while `total` counted
            # nodes, so a fan-out node reported 44 of 22 and kept climbing.
            # A node that fans out is one node and many calls; a reader wants
            # both, and neither can stand in for the other.
            nodes_done: set[str] = set()
            calls_done = 0
            # `traced` is called from the orchestrator's worker threads, and a
            # wave of independent nodes now has several of them in flight at
            # once. `calls_done += 1` is a read and a write, so concurrent
            # calls lose increments and the progress the user watches drifts
            # below the work actually done.
            counted = threading.Lock()

            def traced(spec):
                nonlocal calls_done
                emit("node:start", {"node": spec.node, "agent": spec.agent,
                                    "subject": spec.subject})
                result = executor(spec)
                with counted:
                    calls_done += 1
                    nodes_done.add(spec.node)
                    done_now, calls_now = len(nodes_done), calls_done
                emit("node:done", {
                    "node": spec.node,
                    "subject": spec.subject,
                    # progress through the graph
                    "nodesDone": done_now, "nodesTotal": len(plan),
                    # work done inside it, which a fan-out multiplies
                    "callsDone": calls_now,
                })
                return result

            report = run(svc, traced, plan=plan, commit=True,
                         user_request=req.description, app_root=app_root)

            # §26 — what the finished application should contain, so the run
            # can be checked against the plan rather than only watched.
            counts = forecast(svc.doc)
            emit("forecast", counts)

            # What the run actually cost, per node — so the next question about
            # a bill is answered from the run rather than from prompt sizes.
            emit("usage", usage.summary())

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


@router.get("/api/projects/{project_id}/smith/greeting")
async def smith_greeting(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§107 step 1 — what Smith says before the user says anything.

    A project with no Blueprint yet is not an error here: "nothing yet" is one
    of the two things a greeting has to be able to say, and 404 would push the
    panel back onto the fixed sentence for exactly the case that sentence is
    right for — while giving it nothing for the case it is wrong for.

    Deterministic and cheap (§116): no model, no agents, no DAG. It reads the
    document and §94's state, so it is safe to call on every panel mount.
    """
    project = await get_project_with_auth(project_id, user, db)
    from services.blueprint.service import BlueprintService
    from services.smith.greeting import greet
    from services.smith.clarification import select

    try:
        svc = BlueprintService.load(output_dir=str(_output_dir(project)))
        doc = svc.doc
    except (FileNotFoundError, ValueError):
        doc = {}

    g = greet(doc, open_questions=len(select(doc)) if doc else 0)
    return {
        "state": g.state,
        "headline": g.headline,
        "detail": g.detail,
        "nextAct": g.next_act,
        "openers": [{"kind": o.kind, "example": o.example} for o in g.openers],
        "facts": g.facts,
    }


@router.get("/api/projects/{project_id}/blueprint")
async def read_blueprint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Blueprint as it stands — §110's tree, and what §113 links against."""
    project = await get_project_with_auth(project_id, user, db)
    from services.blueprint.service import BlueprintService

    try:
        # Same directory the generator writes to, or this reads a Blueprint
        # from a path nothing produces.
        svc = BlueprintService.load(output_dir=str(_output_dir(project)))
    except FileNotFoundError:
        raise HTTPException(status_code=404,
                            detail="no Blueprint for this project") from None
    return svc.doc


class SmithChatTurn(BaseModel):
    """One earlier turn, as the client has it."""

    role: str = "user"
    text: str = ""


class SmithChatRequest(BaseModel):
    """One turn of conversation, and the conversation it belongs to.

    IT USED TO BE ONE TURN AND NOTHING ELSE, and the docstring said so. §16
    has Smith ask rather than assume, so it asks "you want priority removed
    entirely — is that right?", and the next request arrives carrying the word
    "yes" and no question for it to be a yes to. Smith answered "your message
    just says yes, could you let me know what you'd like to change", which is
    the only honest reply available to a turn with no past.

    §8 makes conversation the first of Smith's four memory layers and nothing
    reads it — `smith_chat` persists no turn, so the server cannot recover
    what it asked a moment ago. The client has the transcript, so it sends it.
    That is transport, not storage: persisting turns server-side stays the
    right fix, and this stops clarifying questions being useless in the
    meantime.
    """

    message: str = Field(..., min_length=1)
    #: Recent turns, oldest first. Bounded by the client; a clarifying
    #: question and its answer are adjacent, so a short window is enough.
    history: list[SmithChatTurn] = Field(default_factory=list)
    source: str = "user"
    #: §25 — the definition has been seen and accepted, so build the rest.
    approved: bool = False


@router.post("/api/projects/{project_id}/smith/chat")
async def smith_chat(
    project_id: uuid.UUID,
    req: SmithChatRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§6 — Smith decides what to do, says so, and does it. One stream.

    The routing used to live in the panel: it decided whether a message was a
    first build, whether to consult the architect, and whether a verdict should
    start the DAG. §6 makes Smith the Engineering Manager — "delegate
    implementation tasks, monitor agent execution" — and that logic sat in a
    React component, where a second client would have to reimplement it and the
    two would drift.

    So the decision moves here and the panel renders what arrives. Smith emits
    `message` for what it is doing, `asked` when §16 says ask first, and the
    generator's own events — plan, node:start, node:done, forecast, usage —
    when it runs the DAG. One protocol, so the client needs no rules of its own.

    §116 keeps the lifecycle deterministic: Smith INVOKES `run()`, it never
    chooses the node order. §28's graph stays authoritative.
    """
    project = await get_project_with_auth(project_id, user, db)

    from services.blueprint.executors import (
        RunUsage, make_executor, tiered_router)
    from services.blueprint.orchestrator import (
        DAG, completed_nodes, levels, run)
    from services.blueprint.service import BlueprintService
    from services.smith.smith import domain_nodes
    from services.blueprint.plan_forecast import forecast
    from services.smith_chat_v2 import ChatV2Request, handle_chat_v2

    try:
        output_dir = _output_dir(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    _adopt_design_references(output_dir, str(project_id))
    app_root = str(output_dir / "app")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event: str, data: dict) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"event": event, "data": json.dumps(data)})

    async def turn() -> None:

        def work() -> dict:
            existing = output_dir / ".forge" / "blueprint" / "current.json"
            defined = False
            if existing.is_file():
                svc = BlueprintService.load(output_dir=str(output_dir))
                # WHETHER THERE IS ANYTHING TO REASON OVER, which is not the
                # same as whether anything is built. This asked for `pages`,
                # so between the define run and approval — the window where
                # §25 is explicitly inviting the user to talk — every message
                # bypassed the architect and was treated as a fresh brief.
                #
                # Asking "is it going to store the data into a database?" at
                # the approval gate re-ran define, reported "2 stages already
                # complete", and showed the gate again. The answer was sitting
                # in the requirements the run had just written; Smith was
                # never given the chance to read them.
                #
                # A definition is enough to reason over. The DAG stays the
                # only thing that builds: an intent chat_v2 will not serve
                # comes back `handoff` or `not_enabled` and falls through to
                # it below, which is exactly what used to happen immediately.
                defined = bool(svc.doc.get("requirements")
                               or svc.doc.get("pages"))

            # AN APPROVAL IS A COMMAND, NOT A MESSAGE TO REASON ABOUT. §25's
            # gate is answered by pressing the button, and the answer means
            # build — there is nothing to clarify and nothing to ask back.
            #
            # Routing it through the architect made the gate unreachable once a
            # definition existed: chat_v2 handles every message, hands off only
            # on `handoff`/`not_enabled`, and a clarifying question ends the
            # turn. So the definition was written, the gate was shown, and
            # pressing approve started a conversation instead of a build.
            if req.approved:
                return _run_dag(str(output_dir), app_root, req.message,
                                approved=True, emit=emit)

            if not defined:
                # §16 BEFORE THE EXPENSIVE PART. Whatever the brief leaves
                # unsaid gets decided by twenty agents, each inventing an
                # answer, and every later node builds on it. A question worth
                # thirty seconds here saves a rebuild.
                #
                # Only on the opening message. `history` is empty exactly once
                # per conversation, so this asks once and then defines —
                # whether or not the answer was any good. A clarifier that can
                # fire twice can fire forever.
                if not req.history:
                    from services.smith.clarify_brief import clarify_brief

                    asked = clarify_brief(req.message)
                    if asked.get("question"):
                        emit("message", {
                            "text": asked["question"],
                            "options": asked.get("options") or [],
                            "status": "asked",
                        })
                        return {"status": "asked"}

                emit("message", {
                    "text": "Let me define that first — I'll show you what I "
                            "understood before building anything.",
                })
                return _run_dag(str(output_dir), app_root, req.message,
                                approved=req.approved, emit=emit)

            # An application exists, so Smith reasons about it.
            turn_result = handle_chat_v2(ChatV2Request(
                project_id=str(project_id), output_dir=str(output_dir),
                message=req.message,
                history=[(t.role, t.text) for t in req.history if t.text],
            ))
            emit("message", {
                "text": turn_result.answer,
                "options": turn_result.options,
                "diffSummary": turn_result.diff_summary,
                "status": turn_result.status,
                "intent": turn_result.intent,
            })

            # `asked` and `needs_user` are the conversation doing its job —
            # §16 holds rather than guessing. `resolved` already changed the
            # Blueprint. Only a handoff needs the graph.
            if turn_result.status in ("handoff", "not_enabled"):
                return _run_dag(str(output_dir), app_root, req.message,
                                approved=req.approved, emit=emit)
            return {"status": turn_result.status}

        try:
            emit("started", {"projectId": str(project_id)})
            emit("done", await loop.run_in_executor(None, work))
        except Exception as exc:  # noqa: BLE001 - the client needs the reason
            logger.exception("smith turn failed for %s", project_id)
            emit("error", {"message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def stream():
        task = asyncio.create_task(turn())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    return EventSourceResponse(stream())


def _adopt_design_references(output_dir: Path, project_id: str) -> list[str]:
    """Copy the project's designated design references into the application.

    §5 — an application can be described by showing as well as by telling, and
    the designation already exists: `PUT /design-references` is how a user says
    which of their uploads is direction rather than a bug report. It fed the
    legacy brief author and stopped there, so the Blueprint agents never saw
    what the user had pointed at.

    Copied rather than read in place, because `services.blueprint` is
    constructible from an output_dir and nothing else — that is what lets a
    Blueprint load from a fixture or an export with no attachment store in the
    process. Re-adopted on every run so a change of designation takes effect,
    and best-effort throughout: a reference that cannot be read is a reference
    the run proceeds without, not a failed generation.
    """
    from services import chat_attachments, design_reference
    from services.blueprint import references

    try:
        root = chat_attachments.attachments_root()
        ids = design_reference.read_design_references(root, project_id)
    except Exception:                                    # noqa: BLE001
        logger.info("[references] %s: no designation readable", project_id)
        return []

    references.clear(output_dir)
    adopted: list[str] = []
    for att_id in ids:
        got = chat_attachments.read_attachment(root, project_id, att_id)
        if got is None:
            continue
        data, media = got
        rec = chat_attachments.describe(root, project_id, [att_id])
        name = (rec[0].get("filename") if rec else "") or att_id
        stored = references.adopt_bytes(
            output_dir, name, data, media_type=media, fallback=att_id)
        if stored is not None:
            adopted.append(stored.name)
    if adopted:
        logger.info("[references] %s: %s", project_id, ", ".join(adopted))
    return adopted


def _run_dag(output_dir: str, app_root: str, description: str, *,
             approved: bool, emit) -> dict:
    """Invoke §28's graph and narrate it. Never reorders it (§116)."""
    from services.blueprint.executors import (
        RunUsage, make_executor, tiered_router)
    from services.blueprint.orchestrator import completed_nodes, levels, run
    from services.blueprint.plan_forecast import forecast
    from services.blueprint.service import BlueprintService
    from services.smith.smith import domain_nodes

    existing = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    if existing.is_file():
        svc = BlueprintService.load(output_dir=output_dir)
        if description:
            svc.doc.setdefault("application", {})["description"] = description
            svc.validate()
            svc.save()
    else:
        svc = BlueprintService.create(
            output_dir=output_dir, app_id=Path(output_dir).name,
            name="Application", domain="unknown", description=description)

    plan = [k for lvl in levels() for k in lvl]
    if not approved:
        # §25 — the definition is two calls, what follows is a dozen more.
        # `domain_nodes` rather than a list spelled out here: the gate is one
        # fact about the lifecycle, and three copies of it drift.
        plan = domain_nodes()
    already = completed_nodes(svc.doc)
    plan = [k for k in plan if k not in already]

    emit("plan", {"nodes": plan, "total": len(plan),
                  "alreadyComplete": sorted(already),
                  "awaitingApproval": not approved})

    usage = RunUsage()
    executor = make_executor(svc, tiered_router(), usage=usage)
    done: set[str] = set()
    calls = 0
    counted = threading.Lock()

    def traced(spec):
        nonlocal calls
        emit("node:start", {"node": spec.node, "agent": spec.agent,
                            "subject": spec.subject})
        result = executor(spec)
        with counted:
            calls += 1
            done.add(spec.node)
            n, c = len(done), calls
        emit("node:done", {"node": spec.node, "subject": spec.subject,
                           "nodesDone": n, "nodesTotal": len(plan),
                           "callsDone": c})
        return result

    report = run(svc, traced, plan=plan, commit=True,
                 user_request=description, app_root=app_root)
    counts = forecast(svc.doc)
    emit("forecast", counts)
    emit("usage", usage.summary())
    return {"awaitingApproval": not approved, "forecast": counts,
            "report": _report_payload(report)}
