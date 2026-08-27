"""Discovery session endpoints — multi-turn requirement exploration."""

import json
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMember, InviteStatus, Organization, Department, OrgPerson
from models.discovery import DiscoverySession, DiscoveryStatus
from models.project import Project
from schemas.discovery import (
    DiscoveryStartRequest,
    DiscoveryMessageRequest,
    DiscoverySessionResponse,
    DiscoveryConvertRequest,
)
from schemas.project import ProjectResponse
from services.project_service import create_project
from sse_helpers import sse_event, stream_agent_messages

router = APIRouter(tags=["discovery"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_org_member_simple(
    org_id: uuid.UUID, user: PlatformUser, db: AsyncSession
) -> None:
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this organization")


async def _get_org_context(org_id: uuid.UUID, db: AsyncSession) -> str:
    """Build a text summary of the org structure for the discovery agent."""
    org = (await db.execute(
        select(Organization).where(Organization.id == org_id)
    )).scalar_one_or_none()

    depts = (await db.execute(
        select(Department).where(Department.org_id == org_id)
    )).scalars().all()

    people_count = (await db.execute(
        select(OrgPerson).where(OrgPerson.org_id == org_id, OrgPerson.is_active == True)
    )).scalars().all()

    # Existing projects
    projects = (await db.execute(
        select(Project).where(Project.org_id == org_id)
    )).scalars().all()

    lines = [f"Organization: {org.name}" if org else "Organization: Unknown"]
    lines.append(f"Total people: {len(people_count)}")

    if depts:
        lines.append("Departments:")
        for d in depts:
            dept_people = [p for p in people_count if p.department_id == d.id]
            lines.append(f"  - {d.name} ({len(dept_people)} people)")

    if projects:
        lines.append("Existing apps:")
        for p in projects:
            lines.append(f"  - {p.name}: {p.description or 'No description'}")

    return "\n".join(lines)


def _extract_brief(text: str) -> dict | None:
    """Extract a discovery-brief JSON from agent output."""
    pattern = r"```discovery-brief\s*([\s\S]*?)```"
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    return None


# ===========================================================================
# Discovery endpoints
# ===========================================================================

@router.post("/api/orgs/{org_id}/discovery/start", response_model=DiscoverySessionResponse, status_code=201)
async def start_discovery(
    org_id: uuid.UUID,
    req: DiscoveryStartRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new discovery session."""
    await _require_org_member_simple(org_id, user, db)

    session = DiscoverySession(
        org_id=org_id,
        user_id=user.id,
        status=DiscoveryStatus.active,
        title=req.message[:100],
        messages=[{"role": "user", "content": req.message}],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.post("/api/orgs/{org_id}/discovery/{session_id}/message")
async def send_discovery_message(
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    req: DiscoveryMessageRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message in a discovery session — streams SSE response."""
    await _require_org_member_simple(org_id, user, db)

    result = await db.execute(
        select(DiscoverySession).where(
            DiscoverySession.id == session_id,
            DiscoverySession.org_id == org_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Discovery session not found")

    # Append user message (skip if /start already stored it as the last message)
    messages = list(session.messages or [])
    already_stored = (
        len(messages) > 0
        and messages[-1].get("role") == "user"
        and messages[-1].get("content") == req.message
    )
    if not already_stored:
        messages.append({"role": "user", "content": req.message})
        session.messages = messages
        await db.commit()

    org_context = await _get_org_context(org_id, db)

    async def event_stream():
        from agents.discovery import run_discovery
        from services.agent_messages import AssistantMessage, TextBlock

        # Notify office that discovery agent is working
        yield sse_event("office", {
            "type": "agent_start",
            "agent": "discovery",
            "room": "planning",
            "action": "Exploring requirements...",
        })

        full_response = ""

        async for message in run_discovery(
            output_dir="/tmp",  # Discovery doesn't need an output dir
            user_message=req.message,
            org_context=org_context,
            conversation_history=messages[:-1],  # Previous history (not current message)
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        full_response += block.text
                        yield sse_event("message", {"text": block.text})

        # Check if a brief was produced
        brief = _extract_brief(full_response)

        # Persist assistant response and brief
        from database import async_session
        async with async_session() as sess:
            from sqlalchemy import select as sel
            result = await sess.execute(
                sel(DiscoverySession).where(DiscoverySession.id == session_id)
            )
            ds = result.scalar_one_or_none()
            if ds:
                msgs = list(ds.messages or [])
                msgs.append({"role": "assistant", "content": full_response})
                ds.messages = msgs
                if brief:
                    ds.brief = brief
                    ds.status = DiscoveryStatus.brief_ready
                    ds.discovery_type = brief.get("discovery_type")
                    ds.title = brief.get("app_name", ds.title)
                await sess.commit()

        if brief:
            yield sse_event("brief_ready", {"brief": brief})

        # Notify office that discovery agent is done
        yield sse_event("office", {
            "type": "agent_complete",
            "agent": "discovery",
        })

        yield sse_event("complete", {"session_id": str(session_id)})

    return EventSourceResponse(event_stream(), ping=15)


@router.get("/api/orgs/{org_id}/discovery/{session_id}", response_model=DiscoverySessionResponse)
async def get_discovery_session(
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific discovery session."""
    await _require_org_member_simple(org_id, user, db)

    result = await db.execute(
        select(DiscoverySession).where(
            DiscoverySession.id == session_id,
            DiscoverySession.org_id == org_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Discovery session not found")
    return session


@router.post("/api/orgs/{org_id}/discovery/{session_id}/preview-brief")
async def preview_structured_brief(
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """JT-T9: Run the transformer WITHOUT converting, so the frontend
    can show the user what actors + journeys we extracted before they
    commit to project creation. If the user rejects or wants to edit,
    they can continue the discovery conversation and preview again.
    """
    await _require_org_member_simple(org_id, user, db)
    result = await db.execute(
        select(DiscoverySession).where(
            DiscoverySession.id == session_id,
            DiscoverySession.org_id == org_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Discovery session not found")

    from services.discovery_transformer import transform_discovery
    try:
        structured = await transform_discovery(session.messages or [])
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "[discovery.preview-brief] transformer crashed"
        )
        raise HTTPException(
            status_code=500,
            detail=f"transformer crashed: {type(exc).__name__}",
        )

    return {
        "session_id":  str(session.id),
        "is_empty":    structured.is_empty(),
        "brief":       structured.to_dict(),
    }


@router.post("/api/orgs/{org_id}/discovery/{session_id}/convert", response_model=ProjectResponse)
async def convert_discovery_to_project(
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    req: DiscoveryConvertRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Convert a discovery session with a ready brief into a project."""
    await _require_org_member_simple(org_id, user, db)

    result = await db.execute(
        select(DiscoverySession).where(
            DiscoverySession.id == session_id,
            DiscoverySession.org_id == org_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Discovery session not found")

    if not session.brief:
        raise HTTPException(status_code=400, detail="No brief ready — continue the discovery conversation")

    name = req.name or session.brief.get("app_name", "New App")
    description = session.brief.get("description", "")

    # JT-T9: run the discovery transformer against the transcript so the
    # session brief also carries the structured actors + user_journeys
    # the planner honors as authoritative. Failure to structure is a
    # soft error — the project is still created, the planner just falls
    # back to auto-derivation.
    try:
        from services.discovery_transformer import transform_discovery
        structured = await transform_discovery(session.messages or [])
        if not structured.is_empty():
            merged = dict(session.brief)
            # merge without overwriting existing keys the old brief owned
            for k, v in structured.to_dict().items():
                if k in ("actors", "user_journeys", "domain_terms",
                         "open_questions", "domain") and v:
                    merged[k] = v
            session.brief = merged
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "[discovery.convert] transformer failed — proceeding with legacy brief"
        )

    project = await create_project(
        org_id=org_id,
        owner_id=user.id,
        name=name,
        description=description,
        db=db,
    )
    session.project_id = project.id
    session.status = DiscoveryStatus.converted
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/api/orgs/{org_id}/discovery", response_model=list[DiscoverySessionResponse])
async def list_discovery_sessions(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all discovery sessions for the org."""
    await _require_org_member_simple(org_id, user, db)

    result = await db.execute(
        select(DiscoverySession)
        .where(DiscoverySession.org_id == org_id)
        .order_by(DiscoverySession.updated_at.desc())
    )
    return result.scalars().all()
