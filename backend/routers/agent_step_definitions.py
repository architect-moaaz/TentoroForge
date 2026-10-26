"""The assistants a workflow step uses: make one from a brief, and say which workflows use one.

Two platform routes under the project's agent definitions, answered with the same project-access rule as the rest of
them (`get_project_with_auth`: a member of the project's organisation). Registered BEFORE the agent-definitions router
in `main.py`, so the paths below are read here first and can never be mistaken for `GET /{agent_id}`.

* ``POST /api/projects/{id}/agent-definitions/from-brief`` draws the workflow-only assistant a step needs from the step's
  brief, exactly as the build's `workflow_agents` stage does (`services/agent_suggest.agent_for_brief`), and saves it
  beside the project's other assistants. Nothing is installed into the app: Apply (or the next build) does that, as for
  every assistant.
* ``GET /api/projects/{id}/agent-definitions/{agent_id}/used-by`` lists the workflows whose assistant steps run it, for
  "Used by N workflows" and for the warning before one is deleted.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from schemas.agent_builder import AgentFromBrief
from services.features import feature_gate
from services.project_service import get_project_with_auth

router = APIRouter(tags=["agent-builder"], dependencies=[Depends(feature_gate("agents"))])


def _blueprint(output_dir: str) -> dict[str, Any] | None:
    """The project's Blueprint as it stands, or None when it has none."""
    path = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _the_step(doc: dict[str, Any], workflow_ref: str | None, step_id: str | None) -> tuple[dict | None, dict | None]:
    """The workflow and step a caller names, from the Blueprint, when it can tell."""
    from services.agent_suggest import workflow_for_tool

    if not workflow_ref:
        return None, None
    workflow = workflow_for_tool([w for w in doc.get("workflows") or [] if isinstance(w, dict)], workflow_ref)
    step = next((s for s in (workflow or {}).get("steps") or []
                 if isinstance(s, dict) and step_id and str(s.get("key")) == step_id), None)
    return workflow, step


@router.post("/api/projects/{project_id}/agent-definitions/from-brief")
async def agent_from_brief(
    project_id: uuid.UUID,
    req: AgentFromBrief,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Make and save the workflow-only assistant for a step. Answers ``{agentId, name, tools, warnings}`` (``tools`` are
    the assistant's tool names; ``writeTools`` the ones among them that can change data). A brief this app cannot honour
    (a record it does not have, a workflow it cannot run, the workflow the step belongs to) is a plain 400."""
    from services.agent_suggest import BriefError, agent_for_brief
    from services.blueprint import agent_steps

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    doc = _blueprint(project.output_dir)
    if doc is None:
        raise HTTPException(
            status_code=409,
            detail="This project has no Blueprint yet — build the app first, then make an assistant for a step.",
        )
    brief = req.brief.model_dump(exclude_none=True)
    workflow, step = _the_step(doc, req.workflowId, req.stepId)
    if req.workflowId and workflow is None:
        raise HTTPException(status_code=400, detail=f"This app has no workflow called {req.workflowId!r}, so the "
                                                    "assistant cannot be made for it.")
    try:
        made = agent_for_brief(doc, brief, workflow, step or ({"key": req.stepId} if req.stepId else None), name=req.name)
        _refuse_a_loop(doc, workflow, req.stepId, brief)
    except BriefError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # An assistant already saved under this id is the builder's to keep: one the build made and nobody touched is made
    # again from the new brief, anything else gets a new id beside it.
    step_key = req.stepId or ""
    wf_id = str((workflow or {}).get("id") or req.workflowId or "")
    base, aid, n = made["id"], made["id"], 1
    warnings = list(made["warnings"])
    while True:
        existing = agent_steps.read_definition(project.output_dir, aid)
        if existing is None or (agent_steps.untouched(existing) and agent_steps._same_target(
                existing, {"id": wf_id}, step_key)):
            break
        n += 1
        aid = f"{base}-{n}"
    if aid != made["id"]:
        warnings.append(f"An assistant called {made['id']!r} already exists and was left as it is; this one is {aid!r}.")
        made = agent_for_brief(doc, brief, workflow, step or ({"key": req.stepId} if req.stepId else None),
                               name=req.name, agent_id=aid)
    agent_steps.save_assistant(project.output_dir, made["agent"], workflow_id=wf_id, step_key=step_key, brief=brief)
    return {"agentId": made["id"], "name": made["name"], "tools": made["tools"], "readTools": made["readTools"],
            "writeTools": made["writeTools"], "warnings": warnings}


def _refuse_a_loop(doc: dict[str, Any], workflow: dict | None, step_id: str | None, brief: dict[str, Any]) -> None:
    """A brief that lets the step's assistant start (through other assistants' steps, too) the workflow it belongs
    to is refused: the run would call itself."""
    from services.agent_suggest import BriefError
    from services.blueprint import agent_steps

    if workflow is None:
        return
    probe = copy.deepcopy(workflow)
    key = step_id or "__new_step"
    steps = [s for s in probe.get("steps") or [] if not (isinstance(s, dict) and str(s.get("key")) == key)]
    steps.append({"key": key, "type": agent_steps.AGENT_STEP, "config": {"agentBrief": brief}})
    probe["steps"] = steps
    workflows = agent_steps.overlay_workflows(doc, [probe])
    path = agent_steps._reachable(probe, workflows, agent_steps._edges(doc, workflows, None))
    if path:
        raise BriefError(["This assistant could end up starting the workflow it belongs to (" + " -> ".join(path) +
                          "). Take that workflow out of what it may change."])


@router.get("/api/projects/{project_id}/agent-definitions/{agent_id}/used-by")
async def agent_used_by(
    project_id: uuid.UUID,
    agent_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The workflows whose assistant steps run this assistant: ``{workflows: [{workflowId, workflowName, stepId}]}``,
    empty when none. Reads the app's workflow definitions (what the editor shows and changes), or the Blueprint's
    workflows when the app has none yet; cheap."""
    from services.blueprint import agent_steps

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"workflows": []}
    doc = _blueprint(project.output_dir)
    return {"workflows": agent_steps.used_by(project.output_dir, doc, agent_id)}
