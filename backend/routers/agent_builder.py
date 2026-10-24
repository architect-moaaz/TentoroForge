"""Agent Builder endpoints — CRUD for agent definitions, apply pipeline, and test."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import (
    AgentJob,
    AgentJobStatus,
    AgentType,
    Version,
)
from schemas.agent_builder import (
    AgentBlastFixes, AgentBlastInvent, AgentBlastRun, AgentBlastTool, AgentBlastWrite, AgentDefinitionSave, AgentListItem, AgentRecordingSend, AgentScenarioSave,
    AgentTestRequest,
    AgentWatch,
)
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from sse_helpers import sse_event, stream_agent_messages
from services.features import feature_gate

router = APIRouter(tags=["agent-builder"], dependencies=[Depends(feature_gate("agents"))])

AGENT_DEFS_DIR = "agent-definitions"  # relative to project output_dir


def _agent_defs_path(output_dir: str, *, create: bool = False) -> Path:
    """The project's agent-definitions directory.

    Only a WRITE creates it, and with its parents: a project row can outlive its
    folder (a draft whose output directory was removed, a restore from a database
    alone), and creating one level of a missing path raised FileNotFoundError out
    of Save. Reads must not create anything — listing the agents of a project that
    has none is not a reason to put a directory on disk.
    """
    p = Path(output_dir) / AGENT_DEFS_DIR
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Agent definitions (stored as JSON files in the project)
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/agent-definitions", response_model=list[AgentListItem])
async def list_agent_definitions(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all agent definitions for a project."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return []

    defs_dir = _agent_defs_path(project.output_dir)
    items = []
    for f in sorted(defs_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            items.append(AgentListItem(
                id=data.get("id", f.stem),
                name=data.get("name", f.stem),
                description=data.get("description"),
                node_count=len(data.get("nodes", [])),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return items


@router.get("/api/projects/{project_id}/agent-definitions/handoff-options")
async def get_handoff_options(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The roles and people the human-handoff box can name, from this app. Declared BEFORE the `{agent_id}` route,
    which would otherwise read "handoff-options" as an agent's id."""
    import asyncio

    from services.agent_handoff_options import handoff_options

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"roles": [], "people": [], "peopleNote": "No output directory."}
    return await asyncio.to_thread(handoff_options, project.output_dir)


@router.get("/api/projects/{project_id}/agent-definitions/{agent_id}")
async def get_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single agent definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    return json.loads(agent_file.read_text())


@router.post("/api/projects/{project_id}/agent-definitions/suggest")
async def suggest_agent_definition(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """An agent drawn from this app's own Blueprint (its tables, workflows, rules and who may do
    what). Nothing is saved: the builder loads it onto the canvas to edit, save and Apply."""
    from services.agent_suggest import suggest_agent

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    path = Path(project.output_dir) / ".forge" / "blueprint" / "current.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="This project has no Blueprint yet — build the app first, then suggest an agent for it.",
        )
    return suggest_agent(doc)


@router.post("/api/projects/{project_id}/agent-definitions/check")
async def check_agent_definition(
    project_id: uuid.UUID,
    req: AgentDefinitionSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What is wrong with this agent, before Apply: the compiler's notes and the app's own rules, each pinned
    to the box it is about. Nothing is saved or installed."""
    from services.agent_check import check_agent
    from services.agent_runtime_install import resolve_roots

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    _, app_root = resolve_roots(project.output_dir)
    return check_agent(req.model_dump(), app_root)


@router.post("/api/projects/{project_id}/agent-definitions/suggest-scenarios")
async def suggest_agent_scenarios(
    project_id: uuid.UUID,
    req: AgentDefinitionSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A starting set of test conversations drawn from what this agent can do. Nothing is saved."""
    from services.agent_scenarios import suggest_scenarios

    await get_project_with_auth(project_id, user, db)
    return {"scenarios": suggest_scenarios(req.model_dump())}


@router.get("/api/projects/{project_id}/agent-definitions/{agent_id}/tests")
async def get_agent_scenarios(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The agent's saved test conversations."""
    from services.agent_scenarios import load_scenarios

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"scenarios": []}
    return {"scenarios": load_scenarios(project.output_dir, agent_id)}


@router.put("/api/projects/{project_id}/agent-definitions/{agent_id}/tests")
async def save_agent_scenarios(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentScenarioSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the agent's test conversations (cleaned: only fields that mean something are kept)."""
    from services.agent_scenarios import save_scenarios

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    return {"scenarios": save_scenarios(project.output_dir, agent_id, req.scenarios)}


def _debug_roots(project) -> Path:
    """The app folder of a project, for the live run. A project that was never built has none."""
    from services.agent_runtime_install import resolve_roots

    if not project.output_dir:
        raise HTTPException(status_code=400, detail="This project has not been built yet, so there is no app to run.")
    return resolve_roots(project.output_dir)[1]


@router.get("/api/projects/{project_id}/agent-definitions/debug/status")
async def debug_status(
    project_id: uuid.UUID,
    app_url: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Whether the running app can be watched live: it is running, it accepts this project's key, and it is in
    development. If the address is another project's, says where this project's app is."""
    from services.agent_debug import DebugError, read_debug_secret, status, tunnel_status

    project = await get_project_with_auth(project_id, user, db)
    if app_url.strip().lower() == "tunnel":
        # the app is on the builder's own computer, behind its reverse SSH tunnel: the platform chose that address itself
        return await tunnel_status(str(project.id))
    app_root = _debug_roots(project)
    try:
        return await status(app_url, read_debug_secret(app_root))
    except DebugError as e:
        return {"ok": False, "reason": str(e)}


@router.post("/api/projects/{project_id}/agent-definitions/debug/watch")
async def debug_watch(
    project_id: uuid.UUID,
    req: AgentWatch,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every chat the running app has, live, as the app's own people have them: who wrote what, each step the
    runtime takes, each model call, each tool and the real request behind it. The first event says which box on
    the canvas each tool belongs to. Stays open until the builder closes it."""
    import json as _json

    from fastapi.responses import StreamingResponse

    from services import agent_tunnel
    from services.agent_debug import NOT_PAIRED, flow_map, read_debug_secret, watch_stream

    project = await get_project_with_auth(project_id, user, db)
    via_tunnel = req.app_url.strip().lower() == "tunnel"
    if via_tunnel:
        reg = agent_tunnel.get(str(project.id))
        target, secret = (agent_tunnel.target_url(str(project.id)), (reg or {}).get("secret")) if reg else (None, None)
    else:
        target, secret = req.app_url, read_debug_secret(_debug_roots(project))

    async def events():
        if req.graph is not None:
            yield f"data: {_json.dumps({'type': 'platform_map', **flow_map(req.graph.model_dump())})}\n\n".encode()
        if not target:
            yield f"data: {_json.dumps({'type': 'error', 'message': NOT_PAIRED})}\n\n".encode()
            return
        async for chunk in watch_stream(target, secret, role=req.role, user_id=req.user_id, trusted=via_tunnel):
            yield chunk

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/api/projects/{project_id}/agent-definitions/blast/bombs")
async def blast_bombs(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The kinds of bomb that can be thrown at an agent, and the limits on one blast."""
    from services.agent_blast import BOMBS, MAX_REPEATS, MAX_TESTS, PER_BOMB_DEFAULT, TOOL_ANGLES, TOOL_PER_ANGLE_DEFAULT

    await get_project_with_auth(project_id, user, db)
    return {"bombs": BOMBS, "maxTests": MAX_TESTS, "maxRepeats": MAX_REPEATS, "perBomb": PER_BOMB_DEFAULT,
            "toolAngles": [{"key": a["key"], "title": a["title"]} for a in TOOL_ANGLES], "perAngle": TOOL_PER_ANGLE_DEFAULT}


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/blast/invent")
async def blast_invent(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentBlastInvent,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Have an AI invent tricky tests for this agent as drawn. Nothing is run or saved."""
    from services.agent_blast import invent_bombs

    await get_project_with_auth(project_id, user, db)
    try:
        return {"tests": await invent_bombs(req.graph.model_dump(), req.bombs, req.per_bomb)}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/blast/tool-tests")
async def blast_tool_tests(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentBlastTool,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Have an AI study ONE tool and write the tests that would break it, with a short analysis of what the tool does and how
    it could go wrong. One model call. Nothing is run or saved here: the builder runs them with the blast."""
    from services.agent_blast import invent_tool_tests

    await get_project_with_auth(project_id, user, db)
    try:
        return await invent_tool_tests(req.graph.model_dump(), req.tool, req.angles, req.per_angle)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/write-tests")
async def write_agent_tests(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentBlastWrite,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Have an AI write everyday test cases for this agent as drawn, each with a note on what a good reply does. One
    model call. Nothing is run or saved here: the builder keeps them in My tests."""
    from services.agent_blast import write_tests

    await get_project_with_auth(project_id, user, db)
    try:
        return {"tests": await write_tests(req.graph.model_dump(), req.count)}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/blast/run")
async def blast_run(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentBlastRun,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run tests against the agent as drawn (a real model call each; the tools it asks for are reported, never
    executed) and report each as it finishes: ``start``, a ``result`` per test (defused or exploded, with why),
    then ``done`` with the totals. Saved tests and invented bombs alike."""
    import json as _json

    from fastapi.responses import StreamingResponse

    from services.agent_blast import blast

    await get_project_with_auth(project_id, user, db)

    async def events():
        async for e in blast(req.graph.model_dump(), req.tests, repeats=req.repeats):
            yield f"data: {_json.dumps(e)}\n\n".encode()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/blast/fixes")
async def blast_fixes(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentBlastFixes,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Proposed fixes for the tests that exploded: a sentence for the instructions, a clearer tool description,
    or "ask first". Nothing is applied: the builder decides."""
    from services.agent_blast import propose_fixes

    await get_project_with_auth(project_id, user, db)
    try:
        return {"fixes": await propose_fixes(req.graph.model_dump(), req.results)}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/recordings/send")
async def send_recorded_chats(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentRecordingSend,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Chats recorded in Watch live: keep them with all their details, add each as a saved test in Find problems, and (when
    ``fix`` is set) have the fixer propose fixes from what really happened. Nothing is applied: the builder decides."""
    from services.agent_recording import send

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="This project has not been built yet, so there is nowhere to keep the chats.")
    try:
        return await send(project.output_dir, agent_id, req.chats, graph=req.graph.model_dump() if req.graph else None, fix=req.fix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:  # the model could not be reached: said in plain words
        raise HTTPException(status_code=400, detail=str(e))


def _verified_for_save(project, graph: dict[str, Any], force: bool) -> None:
    """The drawing is verified BEFORE anything is written, and a save that fails says why (HTTP 422 with the problems).

    * A drawing that is corrupt (an unsafe id, two boxes with one id, an arrow to nowhere...) is never saved, even when
      the builder says to: it could not be loaded back, and the id becomes a file name.
    * A drawing with errors (no System Prompt box, a tool for a table the app does not have...) is held back unless
      ``force`` is set, which is the builder saying "save it anyway, on purpose". Apply does that, because it asks its
      own question about the same problems first.
    Warnings and notes never hold a save back."""
    from services.agent_check import check_agent, verify_graph
    from services.agent_runtime_install import resolve_roots

    sound = verify_graph(graph)
    if sound["corrupt"]:
        raise HTTPException(status_code=422, detail={
            "msg": "This drawing cannot be saved: " + sound["corrupt"][0]["message"], "kind": "corrupt", "problems": sound["corrupt"]})
    if force:
        return
    _, app_root = resolve_roots(project.output_dir)
    errors = [f for f in check_agent(graph, app_root)["findings"] if f["severity"] == "error"]
    if errors:
        n = len(errors)
        raise HTTPException(status_code=422, detail={
            "msg": f"Not saved: {n} problem{'s' if n != 1 else ''} to fix first. {errors[0]['message']}", "kind": "problems", "problems": errors})


@router.post("/api/projects/{project_id}/agent-definitions", status_code=201)
async def save_agent_definition(
    project_id: uuid.UUID,
    req: AgentDefinitionSave,
    force: bool = False,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update an agent definition, after verifying the drawing (see ``_verified_for_save``)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = req.model_dump()
    _verified_for_save(project, data, force)
    agent_file = _agent_defs_path(project.output_dir, create=True) / f"{req.id}.json"
    agent_file.write_text(json.dumps(data, indent=2))
    return {"id": req.id, "saved": True}


@router.put("/api/projects/{project_id}/agent-definitions/{agent_id}")
async def update_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentDefinitionSave,
    force: bool = False,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing agent definition, after verifying the drawing (see ``_verified_for_save``)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = req.model_dump()
    data["id"] = agent_id
    _verified_for_save(project, data, force)
    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    agent_file.write_text(json.dumps(data, indent=2))
    return {"id": agent_id, "saved": True}


@router.delete("/api/projects/{project_id}/agent-definitions/{agent_id}", status_code=204)
async def delete_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an agent definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if agent_file.exists():
        agent_file.unlink()


# ---------------------------------------------------------------------------
# Apply agent definition to generated app code
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/apply")
async def apply_agent_definition(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Install an agent into the generated app: compile its definition, lay down the runtime, validate, index (SSE streaming)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    agent_data = json.loads(agent_file.read_text())
    # What is recorded against the version: the definition, in the builder's words.
    instruction = _build_agent_instruction(agent_data)

    async def event_stream():
        yield sse_event("status", {"message": f"Applying agent: {agent_data.get('name', agent_id)}..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            # The runtime is fixed code and the definition is data, so installing an
            # agent is a compile + copy — no model writes it, and applying twice gives
            # the same files.
            import asyncio

            from services.agent_runtime_install import install_agent_runtime

            yield sse_event("status", {"message": "Installing agent runtime..."})
            install = await asyncio.to_thread(install_agent_runtime, project.output_dir)
            if not install.get("installed"):
                # Saved is saved: the definition is on disk and is installed by the
                # build. Say that, rather than a bare failure — there is nothing
                # wrong with the agent, there is just no app to put it in yet.
                if install.get("no_app"):
                    yield sse_event("error", {"message": (
                        "This project has no generated app yet. Your agent is saved and will be "
                        "installed when the app is built.")})
                else:
                    yield sse_event("error", {"message": "Nothing to install — the project has no agent definition."})
                return
            for w in install.get("warnings", []):
                yield sse_event("log", {"text": f"[Agent] ⚠ {w}"})
            yield sse_event("log", {"text": (
                f"[Agent] installed {len(install['agents'])} agent(s), "
                f"{len(install['written'])} file(s) written"
                + ("" if install.get("widget_mounted") else "; the floating widget was not mounted (see /assistant)")
            )})

            from agents.validator import run_validator
            yield sse_event("status", {"message": "Validating build..."})

            async for evt in stream_agent_messages(
                run_validator(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Validator] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            from agents.indexer import run_indexer
            yield sse_event("status", {"message": "Indexing application..."})

            async for evt in stream_agent_messages(
                run_indexer(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Indexer] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            commit_hash = await git_commit(
                project.output_dir,
                f"agent: apply '{agent_data.get('name', agent_id)}'",
                actor="editor",   # S24-9: an unattributed HEAD can no longer be reverted
            )

            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "AGENT_APPLY",
                        "agent_id": agent_id,
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message=f"agent: apply '{agent_data.get('name', agent_id)}'",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "agent_id": agent_id,
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
                "warnings": install.get("warnings", []),
                "widget_mounted": install.get("widget_mounted", False),
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


# ---------------------------------------------------------------------------
# Test agent
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/agent-definitions/{agent_id}/test")
async def test_agent(
    project_id: uuid.UUID,
    agent_id: str,
    req: AgentTestRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test an agent with a message: a real model call against its compiled definition.

    Tools are shown, not executed (see services/agent_test_run.py)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    agent_file = _agent_defs_path(project.output_dir) / f"{agent_id}.json"
    if not agent_file.exists():
        raise HTTPException(status_code=404, detail="Agent definition not found")

    from services.agent_test_run import run_agent_test

    agent_data = json.loads(agent_file.read_text())
    return await run_agent_test(agent_data, req.message, req.conversation_history)


# ---------------------------------------------------------------------------
# Instruction builder (server-side fallback, mirrors frontend builder)
# ---------------------------------------------------------------------------

def _build_agent_instruction(agent_data: dict) -> str:
    """Convert an agent definition JSON to a natural language instruction."""
    name = agent_data.get("name", "Untitled Agent")
    desc = agent_data.get("description", "")
    nodes = agent_data.get("nodes", [])
    edges = agent_data.get("edges", [])

    parts = [
        f'Implement AI agent "{name}" in the generated application.',
        "",
    ]

    if desc:
        parts.append(f"Description: {desc}")
        parts.append("")

    # Nodes
    if nodes:
        parts.append("## Agent Nodes")
        for node in nodes:
            node_data = node.get("data", {})
            node_type = node_data.get("nodeType", "unknown")
            label = node_data.get("label", node.get("id", ""))
            config = node_data.get("config", {})
            parts.append(f"\n### [{node_type}] {label} (id: {node.get('id', '')})")

            if node_type == "system_prompt":
                if config.get("prompt"):
                    parts.append(f"  Prompt: {config['prompt'][:200]}")
                if config.get("model"):
                    parts.append(f"  Model: {config['model']}")
                if config.get("temperature") is not None:
                    parts.append(f"  Temperature: {config['temperature']}")
            elif node_type == "tool":
                if config.get("tool_name"):
                    parts.append(f"  Tool name: {config['tool_name']}")
                if config.get("tool_type"):
                    parts.append(f"  Type: {config['tool_type']}")
                if config.get("tool_type") == "mcp":
                    # MCP tool node — invocation goes through the
                    # standalone-app template's mcpClientPool at runtime.
                    parts.append("  Tool type: MCP server call")
                    parts.append(f"  MCP server id: {config.get('mcp_server_id', '')}")
                    parts.append(f"  MCP tool name: {config.get('mcp_tool_name', '')}")
                    if config.get("args_mapping"):
                        parts.append(f"  Args mapping: {json.dumps(config['args_mapping'])}")
                else:
                    if config.get("endpoint"):
                        parts.append(f"  Endpoint: {config.get('method', 'GET')} {config['endpoint']}")
                    if config.get("parameters"):
                        parts.append(f"  Parameters: {json.dumps(config['parameters'])}")
            elif node_type == "guardrail":
                if config.get("guardrail_type"):
                    parts.append(f"  Filter type: {config['guardrail_type']}")
                if config.get("rules"):
                    for rule in config["rules"]:
                        parts.append(f"  Rule: {rule.get('name', '')} ({rule.get('type', '')})")
            elif node_type == "memory":
                if config.get("memory_type"):
                    parts.append(f"  Memory type: {config['memory_type']}")
                if config.get("capacity"):
                    parts.append(f"  Capacity: {config['capacity']}")
            elif node_type == "human_handoff":
                conditions = config.get("conditions", {})
                if conditions.get("keyword_triggers"):
                    parts.append(f"  Keywords: {', '.join(conditions['keyword_triggers'])}")
                target = config.get("target", {})
                if target.get("type"):
                    parts.append(f"  Handoff to: {target['type']} ({target.get('value', '')})")
            elif node_type == "router":
                if config.get("strategy"):
                    parts.append(f"  Strategy: {config['strategy']}")
                if config.get("routes"):
                    for route in config["routes"]:
                        parts.append(f"  Route: {route.get('label', '')} → {route.get('condition', 'default')}")
        parts.append("")

    # Edges
    if edges:
        parts.append("## Connections")
        for edge in edges:
            edge_type = edge.get("data", {}).get("edgeType", "default")
            src = edge.get("source", "?")
            tgt = edge.get("target", "?")
            src_node = next((n for n in nodes if n.get("id") == src), None)
            tgt_node = next((n for n in nodes if n.get("id") == tgt), None)
            src_name = src_node.get("data", {}).get("label", src) if src_node else src
            tgt_name = tgt_node.get("data", {}).get("label", tgt) if tgt_node else tgt
            parts.append(f"- {src_name} → {tgt_name} ({edge_type})")
        parts.append("")

    # Requirements
    parts.extend([
        "## Implementation Requirements",
        "1. Create an agent service class (src/agents/agent-service.ts) that orchestrates the node graph",
        "2. For SystemPrompt nodes: use the prompt as the system message when calling the LLM",
        "3. For Tool nodes: implement the tool function (API call, DB query, or custom function)",
        "4. For Guardrail nodes: implement input/output filtering middleware",
        "5. For Memory nodes: implement conversation/vector/key-value storage",
        "6. For Router nodes: implement intent classification or conditional routing",
        "7. For HumanHandoff nodes: implement escalation logic (queue, email, or webhook)",
        "8. Create an API route POST /api/agent/chat for interacting with the agent",
        "9. Store agent configuration in src/agents/config.ts",
        "10. Ensure all tool calls are type-safe and error-handled",
        "",
        "### MCP tool node wiring (authoritative)",
        "For any Tool node with `tool_type: mcp`, import `{ callMcpTool }` from",
        "`@/lib/integrations/mcpClientPool` and invoke it with (server_id, tool_name, args).",
        "The pool is auto-imported at runtime by the standalone-app template; do NOT",
        "instantiate a new MCP client per invocation. Example:",
        "```ts",
        "import { callMcpTool } from '@/lib/integrations/mcpClientPool';",
        "",
        "// tool_type='mcp', mcp_server_id='<uuid>', mcp_tool_name='search'",
        "async function runMcpTool(args: Record<string, unknown>) {",
        "  const result = await callMcpTool(",
        "    '<mcp_server_id>',",
        "    '<mcp_tool_name>',",
        "    args, // shape comes from args_mapping in the node config",
        "  );",
        "  return result; // { content: [...], isError: boolean }",
        "}",
        "```",
        "Credentials live in .env.local as `MCP_SERVER_<id_hex12>_SECRET` / `_URL` /",
        "`_TRANSPORT` / `_AUTH_KIND` / `_AUTH_HEADER` — the pool reads them by",
        "server id and handles connect/reconnect/auth.",
    ])

    return "\n".join(parts)
