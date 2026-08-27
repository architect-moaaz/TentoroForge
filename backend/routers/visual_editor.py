"""Visual editor endpoints — bridge injection, direct edits, AI edits."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import AgentJob, AgentJobStatus, AgentType, Version
from schemas.visual_edit import (
    VisualEditRequest,
    AIEditRequest,
    AddSectionRequest,
    ReorderSectionRequest,
)
from services.project_service import get_project_with_auth
from services.git_service import git_commit, git_revert, git_log, git_get_head
from services.bridge_injector import inject_bridge, remove_bridge
from services.source_annotator import annotate_source_files, strip_source_annotations
from services.visual_edit_service import (
    apply_tailwind_edit,
    apply_text_edit,
    apply_prop_edit,
)
from sse_helpers import sse_event, stream_agent_messages

router = APIRouter(tags=["visual-editor"])


@router.post("/api/projects/{project_id}/bridge/inject")
async def inject_bridge_endpoint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inject bridge script into the generated app for visual editing."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    inject_bridge(project.output_dir)
    await annotate_source_files(project.output_dir)
    return {"injected": True}


@router.post("/api/projects/{project_id}/bridge/remove")
async def remove_bridge_endpoint(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove bridge script from the generated app."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")
    remove_bridge(project.output_dir)
    await strip_source_annotations(project.output_dir)
    return {"removed": True}


@router.post("/api/projects/{project_id}/visual-edit")
async def direct_edit(
    project_id: uuid.UUID,
    req: VisualEditRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply direct Tailwind class and text edits to source files."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    # Strip annotations before editing
    await strip_source_annotations(project.output_dir)

    modified = []
    for edit in req.tailwind_edits:
        ok = apply_tailwind_edit(
            project.output_dir,
            edit.file,
            edit.line,
            edit.action,
            edit.class_name,
            edit.replace_with,
        )
        if ok:
            modified.append(edit.file)

    for edit in req.text_edits:
        ok = apply_text_edit(
            project.output_dir,
            edit.file,
            edit.line,
            edit.old_text,
            edit.new_text,
        )
        if ok:
            modified.append(edit.file)

    for edit in req.prop_edits:
        ok = apply_prop_edit(
            project.output_dir,
            edit.file,
            edit.line,
            edit.prop_name,
            edit.old_value,
            edit.new_value,
        )
        if ok:
            modified.append(edit.file)

    # Commit and re-annotate
    if modified:
        # S24-9/SX-3: attributed so "undo that" can tell a user save from a
        # Smith commit, and scoped to the files this request touched so a
        # user's unrelated in-progress work is not swept in.
        await git_commit(
            project.output_dir,
            f"visual: edit {', '.join(set(modified))}",
            actor="editor",
            paths=sorted(set(modified)),
        )

    await annotate_source_files(project.output_dir)
    return {"modified": list(set(modified))}


@router.post("/api/projects/{project_id}/visual-edit/undo")
async def undo_edit(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revert the last visual edit commit."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    # Strip annotations before reverting
    await strip_source_annotations(project.output_dir)

    new_hash = await git_revert(project.output_dir)
    if not new_hash:
        raise HTTPException(status_code=400, detail="Nothing to undo")

    # Re-annotate after revert
    await annotate_source_files(project.output_dir)

    return {"commit_hash": new_hash}


@router.get("/api/projects/{project_id}/visual-edit/history")
async def edit_history(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent git log entries for undo context."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    edits = await git_log(project.output_dir, limit=10)
    head = await git_get_head(project.output_dir)
    return {"edits": edits, "head": head}


@router.post("/api/projects/{project_id}/visual-edit/ai")
async def ai_edit(
    project_id: uuid.UUID,
    req: AIEditRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply an AI-mediated edit — streams progress via SSE."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    # Strip annotations before AI edit
    await strip_source_annotations(project.output_dir)

    # Determine if we can use a scoped (faster) edit
    from services.component_extractor import extract_component_context

    use_scoped = False
    scoped_ctx = None
    if req.file and req.line:
        scoped_ctx = extract_component_context(
            project.output_dir, req.file, req.line
        )
        if scoped_ctx:
            use_scoped = True

    # Build instruction
    if use_scoped and scoped_ctx:
        parts = [req.instruction]
        parts.append(f"\n## Target Component: {scoped_ctx['component_name']}")
        parts.append(f"File: {scoped_ctx['file']} (lines {scoped_ctx['start_line']}-{scoped_ctx['end_line']})")
        if req.context_element:
            parts.append(f"Selected element: {req.context_element}")
        parts.append(f"\n## Current Component Code:\n```tsx\n{scoped_ctx['source']}\n```")
        instruction = "\n".join(parts)
    else:
        parts = [req.instruction]
        if req.file:
            parts.append(f"\nTarget file: {req.file}")
        if req.line:
            parts.append(f"Around line: {req.line}")
        if req.context_element:
            parts.append(f"Selected element: {req.context_element}")
        instruction = "\n".join(parts)

    async def event_stream():
        yield sse_event("status", {"message": f"Applying: {req.instruction}"})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            if use_scoped and scoped_ctx:
                from agents.code_editor import run_code_editor

                agent_stream = run_code_editor(
                    output_dir=project.output_dir,
                    instruction=instruction,
                    target_file=scoped_ctx["file"],
                )
            else:
                from agents.refiner import run_refiner

                agent_stream = run_refiner(
                    output_dir=project.output_dir,
                    instruction=instruction,
                )

            async for evt in stream_agent_messages(
                agent_stream,
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Commit
            commit_hash = await git_commit(
                project.output_dir,
                f"visual: ai edit — {req.instruction[:80]}",
                actor="editor",   # S24-9
            )

            # Re-annotate
            await annotate_source_files(project.output_dir)

            # Record job
            from database import async_session

            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "VISUAL_AI_EDIT",
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
                        message=f"visual: ai edit — {req.instruction[:80]}",
                        agent_job_id=job.id,
                    )
                    sess.add(version)
                await sess.commit()

            yield sse_event("complete", {
                "commit_hash": commit_hash,
                "cost_usd": total_cost,
                "num_turns": total_turns,
                "duration_ms": total_duration,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


# --- New endpoints ---


@router.get("/api/projects/{project_id}/visual-edit/page-sections")
async def get_page_sections(
    project_id: uuid.UUID,
    route: str = Query(default="/"),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return AST-parsed section data for a given route."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    from services.page_section_parser import parse_page_sections

    result = await parse_page_sections(project.output_dir, route)
    return result


@router.get("/api/projects/{project_id}/visual-edit/element-props")
async def get_element_props(
    project_id: uuid.UUID,
    file: str = Query(),
    line: int = Query(),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return JSX element props at a given file/line."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    from services.element_props_extractor import extract_element_props

    result = extract_element_props(project.output_dir, file, line)
    if result is None:
        return {
            "props": {},
            "classes": [],
            "component_name": None,
            "text_content": None,
            "self_closing": False,
        }
    return result


@router.get("/api/projects/{project_id}/visual-edit/section-templates")
async def get_section_templates(
    project_id: uuid.UUID,
    category: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return available section kinds, optionally filtered by category."""
    # Auth check
    await get_project_with_auth(project_id, user, db)

    from services.section_authoring import list_section_kinds

    kinds = list_section_kinds()
    if category:
        kinds = [k for k in kinds if k["category"] == category]
    # Already in the frontend-safe {id, name, category, description} shape.
    return kinds


@router.post("/api/projects/{project_id}/visual-edit/add-section")
async def add_section(
    project_id: uuid.UUID,
    req: AddSectionRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and insert a new section — streams progress via SSE."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    # Strip annotations before editing
    await strip_source_annotations(project.output_dir)

    # Find the page file for this route
    from services.page_section_parser import _route_to_page_file
    from services.section_instruction_builder import build_section_instruction

    page_file = _route_to_page_file(project.output_dir, req.route)
    if not page_file:
        raise HTTPException(
            status_code=400,
            detail=f"No page file found for route: {req.route}",
        )

    instruction = build_section_instruction(
        output_dir=project.output_dir,
        page_file=page_file,
        template_id=req.template_id,
        custom_prompt=req.custom_prompt,
        insert_position=req.insert_position,
    )

    async def event_stream():
        desc = req.custom_prompt or req.template_id or "new section"
        yield sse_event("status", {"message": f"Generating: {desc}"})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            from agents.code_editor import run_code_editor

            agent_stream = run_code_editor(
                output_dir=project.output_dir,
                instruction=instruction,
                target_file=page_file,
            )

            async for evt in stream_agent_messages(
                agent_stream,
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Commit
            commit_msg = f"visual: add section — {desc[:60]}"
            commit_hash = await git_commit(project.output_dir, commit_msg, actor="editor")  # S24-9

            # Re-annotate
            await annotate_source_files(project.output_dir)

            # Record job
            from database import async_session

            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "VISUAL_ADD_SECTION",
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
                        message=commit_msg,
                        agent_job_id=job.id,
                    )
                    sess.add(version)
                await sess.commit()

            yield sse_event("complete", {
                "commit_hash": commit_hash,
                "cost_usd": total_cost,
                "num_turns": total_turns,
                "duration_ms": total_duration,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


@router.post("/api/projects/{project_id}/visual-edit/reorder-section")
async def reorder_section_endpoint(
    project_id: uuid.UUID,
    req: ReorderSectionRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder a section by moving it before/after another section."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    # Strip annotations before editing
    await strip_source_annotations(project.output_dir)

    from services.section_reorder_service import reorder_section

    ok = await reorder_section(
        output_dir=project.output_dir,
        source_file=req.source_file,
        source_line=req.source_line,
        target_file=req.target_file,
        target_line=req.target_line,
        position=req.position,
    )

    if not ok:
        # Re-annotate even on failure
        await annotate_source_files(project.output_dir)
        raise HTTPException(status_code=400, detail="Could not reorder section")

    # Commit and re-annotate
    await git_commit(project.output_dir, "visual: reorder section", actor="editor")  # S24-9
    await annotate_source_files(project.output_dir)

    return {"reordered": True}


# ---------------------------------------------------------------------------
# Auto-fix: runtime error → LLM diagnosis → targeted fix
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class FixErrorRequest(_BaseModel):
    """Error payload from the bridge's error capture."""
    message: str
    file: str = ""
    line: int = 0
    column: int = 0
    stack: str = ""
    type: str = "runtime"  # runtime | unhandled_rejection | nextjs_overlay


@router.post("/api/projects/{project_id}/fix-error")
async def fix_runtime_error(
    project_id: uuid.UUID,
    req: FixErrorRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Auto-fix a runtime error detected in the generated app.

    Runs the fix agent (full-scope LLM) to diagnose and repair the error.
    Returns an SSE stream with progress updates.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    import logging
    logger = logging.getLogger(__name__)

    logger.info(
        "[fix-error] %s — %s at %s:%d",
        project_id, req.message[:80], req.file, req.line,
    )

    async def event_stream():
        yield sse_event("status", {
            "message": f"Error identified in {req.file or 'app'}. Auto-fix in progress...",
            "phase": "diagnosing",
        })

        from agents.fix_agent import run_fix_agent

        files_changed: list[str] = []
        agent_text: list[str] = []

        try:
            async for evt in stream_agent_messages(
                run_fix_agent(
                    output_dir=project.output_dir,
                    error_info=req.model_dump(),
                ),
                output_dir=project.output_dir,
                event_prefix="[Fix] ",
            ):
                event_type = evt.get("event")

                if event_type == "file_created":
                    files_changed.append(evt.get("data", {}).get("path", ""))

                if event_type in ("log", "message"):
                    data = evt.get("data", {})
                    if isinstance(data, str):
                        import json as _json
                        try:
                            data = _json.loads(data)
                        except (ValueError, TypeError):
                            data = {"text": data}
                    text = data.get("text", "")
                    if text:
                        agent_text.append(text)

                # Forward tool_call and file_created events for progress
                if event_type in ("tool_call", "file_created"):
                    yield evt
                elif event_type == "agent_result":
                    pass  # consumed below
                else:
                    yield evt

        except Exception as e:
            logger.exception("[fix-error] Agent failed")
            yield sse_event("fix_error", {
                "success": False,
                "error": str(e),
            })
            return

        # Re-annotate source files so bridge overlays stay accurate
        try:
            await annotate_source_files(project.output_dir)
        except Exception:
            pass

        summary = "\n".join(agent_text[-3:])  # last 3 messages as summary

        yield sse_event("fix_result", {
            "success": True,
            "files_changed": files_changed,
            "summary": summary,
            "error_message": req.message,
            "error_file": req.file,
        })

    return EventSourceResponse(event_stream())
