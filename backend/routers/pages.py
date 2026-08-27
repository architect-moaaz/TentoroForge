"""Page definition endpoints — CRUD for visual page layouts + apply pipeline."""

import json
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.page import PageDefinition
from models.project import (
    AgentJob,
    AgentJobStatus,
    AgentType,
    Conversation,
    MessageRole,
    MessageType,
    Version,
)
from schemas.page import PageCreate, PageUpdate, PageResponse
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from sse_helpers import sse_event, stream_agent_messages

router = APIRouter(tags=["pages"])


@router.get("/api/projects/{project_id}/pages", response_model=list[PageResponse])
async def list_pages(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(PageDefinition)
        .where(PageDefinition.project_id == project_id)
        .order_by(PageDefinition.created_at)
    )
    return result.scalars().all()


@router.post("/api/projects/{project_id}/pages", response_model=PageResponse, status_code=201)
async def create_page(
    project_id: uuid.UUID,
    req: PageCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    page = PageDefinition(
        project_id=project_id,
        name=req.name,
        route=req.route,
        html=req.html,
        css=req.css,
        data_bindings=req.data_bindings,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


@router.get("/api/projects/{project_id}/pages/{page_id}", response_model=PageResponse)
async def get_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(PageDefinition).where(
            PageDefinition.id == page_id,
            PageDefinition.project_id == project_id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    return page


logger = logging.getLogger(__name__)


@router.put("/api/projects/{project_id}/pages/{page_id}", response_model=PageResponse)
async def update_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    req: PageUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(PageDefinition).where(
            PageDefinition.id == page_id,
            PageDefinition.project_id == project_id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(page, field, value)

    await db.commit()
    await db.refresh(page)
    return page


@router.delete("/api/projects/{project_id}/pages/{page_id}", status_code=204)
async def delete_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(PageDefinition).where(
            PageDefinition.id == page_id,
            PageDefinition.project_id == project_id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    await db.delete(page)
    await db.commit()


@router.post("/api/projects/{project_id}/pages/{page_id}/apply")
async def apply_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a page layout to the generated app via code_editor agent (SSE)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    result = await db.execute(
        select(PageDefinition).where(
            PageDefinition.id == page_id,
            PageDefinition.project_id == project_id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    instruction = _build_page_instruction(page)

    async def event_stream():
        yield sse_event("status", {"message": f"Applying page: {page.name}..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            from agents.code_editor import run_code_editor
            yield sse_event("status", {"message": "Generating page component..."})

            async for evt in stream_agent_messages(
                run_code_editor(output_dir=project.output_dir, instruction=instruction),
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

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

            commit_hash = await git_commit(project.output_dir,
                f"ui: apply page layout '{page.name}'",
            actor="editor")

            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "PAGE_APPLY",
                        "page_id": str(page.id),
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
                        message=f"ui: apply page '{page.name}'",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "page_id": str(page.id),
                "commit_hash": commit_hash,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


def _build_page_instruction(page: PageDefinition) -> str:
    """Convert a page definition to natural language for code_editor."""
    from routers.workflows import _extract_form_fields_from_html

    parts = [
        f'Update the page at route "{page.route}" (name: "{page.name}") in the generated application.',
        "",
        "## Page HTML Structure",
        "```html",
        page.html or "<div>Empty page</div>",
        "```",
        "",
    ]

    if page.css:
        parts.extend([
            "## Custom CSS",
            "```css",
            page.css,
            "```",
            "",
        ])

    bindings = page.data_bindings or {}
    if bindings:
        parts.append("## Data Bindings")
        for comp_id, binding in bindings.items() if isinstance(bindings, dict) else []:
            parts.append(f"- Component {comp_id}: bound to {binding}")
        parts.append("")

    # ── Form Fields (extracted from data-* traits) ────────────────────
    form_fields = _extract_form_fields_from_html(page.html or "")
    if form_fields:
        parts.append("## Form Fields")
        parts.append("The following form fields were found in the HTML with data-* attributes.")
        parts.append("Generate proper form handling for each field:")
        parts.append("")
        for f in form_fields:
            field_desc = f"- **{f['fieldName']}**"
            if f.get("type"):
                field_desc += f" (type: {f['type']})"
            parts.append(field_desc)
            if f.get("required"):
                parts.append("  - Required: yes")
            if f.get("processVariable"):
                parts.append(f"  - Process variable: `{f['processVariable']}`")
            if f.get("helpText"):
                parts.append(f"  - Help text: {f['helpText']}")
            if f.get("minLength"):
                parts.append(f"  - Min length: {f['minLength']}")
            if f.get("maxLength"):
                parts.append(f"  - Max length: {f['maxLength']}")
            if f.get("min"):
                parts.append(f"  - Min value: {f['min']}")
            if f.get("max"):
                parts.append(f"  - Max value: {f['max']}")
            if f.get("pattern"):
                parts.append(f"  - Validation pattern: `{f['pattern']}`")
            if f.get("options"):
                parts.append(f"  - Options: {f['options']}")
        parts.append("")

        parts.append("### Form Implementation Requirements")
        parts.append("- Use controlled inputs with React state or react-hook-form")
        parts.append("- Add client-side validation based on the field constraints above")
        parts.append("- Fields with a `processVariable` are bound to workflow variables:")
        parts.append("  - Pre-populate from `task.input_data[processVariable]` if the page is opened from a workflow task")
        parts.append("  - On submit, include `{ [processVariable]: value }` in the POST body to `/api/tasks/:id/complete`")
        parts.append("- Required fields must be validated before submission")
        parts.append("")

    parts.extend([
        "## Requirements",
        "1. Convert the HTML structure above to a React component using Tailwind CSS classes",
        "2. Create or update the page file at the appropriate app route",
        "3. Wire up any data bindings to fetch from the API",
        "4. Ensure the component is responsive and follows existing app patterns",
        "5. Add the route to the app navigation if not already present",
    ])

    if form_fields:
        parts.append("6. Implement form validation and submission as described in the Form Fields section above")

    return "\n".join(parts)
