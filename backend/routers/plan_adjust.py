"""Adjust-strategy endpoint.

``POST /api/projects/{project_id}/plan/adjust``

Loads the current pending plan from the project's most recent
assistant plan-message, applies the user's Adjust-strategy chat
message via :mod:`services.plan_adjust_intent`, and stores the new
plan as a fresh assistant message so ``[APPROVE_PLAN]`` naturally
picks up the adjusted version.

Returns a JSON payload with the new plan, the structured diff,
narrative, and any warnings so the frontend can render the delta
inline without polling.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import async_session, get_db
from models.auth import PlatformUser
from models.project import Conversation, Project
from services.discovery_adjust_intent import adjust_dossier_via_llm
from services.plan_adjust_intent import adjust_plan_via_llm

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plan-adjust"])


# --------------------------------------------------------------------------- #
# Request / response schemas                                                   #
# --------------------------------------------------------------------------- #

class AdjustRequest(BaseModel):
    """One turn of the Adjust-strategy conversation."""
    message: str
    """What the user typed this turn."""


class AdjustResponse(BaseModel):
    plan: dict
    """Full new plan document, to render on the client."""
    diff: dict
    """Structured added/removed lists keyed by kind."""
    applied_ops: list[dict]
    """The exact ops that landed, in order. Useful for undo / analytics."""
    narrative: str
    """Human-readable summary Smith produced."""
    warnings: list[str]
    """Non-fatal issues (dangling refs, skipped ops, etc.)."""
    error: Optional[str] = None
    """Set when the whole turn couldn't proceed (empty message, LLM
    outage, invalid response). ``plan`` is preserved unchanged."""


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

async def _load_pending_plan(
    project_id: uuid.UUID,
) -> tuple[Optional[dict], Optional[Conversation]]:
    """Return the most-recent pending plan + the conversation row it's
    attached to (so we can back-fill after mutation)."""
    async with async_session() as sess:
        stmt = (
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == "assistant",
                Conversation.message_type == "plan",
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        result = await sess.execute(stmt)
        conv = result.scalar_one_or_none()
    if conv is None:
        return None, None
    plan = None
    if conv.metadata_ and isinstance(conv.metadata_, dict):
        plan = conv.metadata_.get("plan")
    return plan, conv


async def _load_prior_adjust_turns(
    project_id: uuid.UUID,
    limit: int = 12,
    *,
    target: str = "plan",
) -> list[dict]:
    """Fetch the last N adjust conversation turns so the intent parser
    can keep multi-turn asks coherent. Filters to the ``adjust`` chat
    metadata so we don't pollute with unrelated chat.

    ``target`` selects "plan" vs "discovery" turns so the two Adjust
    conversations don't cross-pollinate history."""
    async with async_session() as sess:
        stmt = (
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit * 2)  # room for user+assistant pairs
        )
        result = await sess.execute(stmt)
        rows = list(result.scalars().all())
    turns: list[dict] = []
    for c in reversed(rows):
        meta = c.metadata_ or {}
        if meta.get("adjust") is not True:
            continue
        # Historical rows didn't set adjust_target — default them to "plan"
        # so the older plan-adjust conversations keep working.
        row_target = meta.get("adjust_target") or "plan"
        if row_target != target:
            continue
        turns.append({"role": c.role, "content": c.content or ""})
    return turns[-limit:]


async def _load_pending_discovery(
    project_id: uuid.UUID,
) -> tuple[Optional[dict], Optional[Conversation]]:
    """Return the latest DiscoveryCard-backing dossier + its conversation
    row. The dossier lives in ``metadata_["discovery"]`` on a chat-type
    row (see generate.py line 4335)."""
    async with async_session() as sess:
        stmt = (
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.role == "assistant",
            )
            .order_by(Conversation.created_at.desc())
            .limit(20)  # walk back a few messages in case Smith answered mid-flow
        )
        result = await sess.execute(stmt)
        rows = list(result.scalars().all())
    for row in rows:
        meta = row.metadata_ or {}
        dossier = meta.get("discovery") if isinstance(meta, dict) else None
        if isinstance(dossier, dict) and dossier:
            return dossier, row
    return None, None


async def _persist_adjust_turn(
    project_id: uuid.UUID,
    user_message: str,
    narrative: str,
    new_plan: dict,
) -> None:
    """Store the user turn + assistant reply in the conversation so
    the timeline reflects the adjustment. The assistant reply carries
    the new plan in ``metadata_["plan"]`` — that's what ``[APPROVE_PLAN]``
    picks up on Begin Quest."""
    async with async_session() as sess:
        sess.add(Conversation(
            project_id=project_id,
            role="user",
            message_type="chat",
            content=user_message,
            metadata_={"adjust": True, "adjust_target": "plan"},
        ))
        sess.add(Conversation(
            project_id=project_id,
            role="assistant",
            message_type="plan",
            content=narrative,
            metadata_={"adjust": True, "adjust_target": "plan", "plan": new_plan},
        ))
        await sess.commit()


async def _persist_discovery_adjust_turn(
    project_id: uuid.UUID,
    user_message: str,
    narrative: str,
    new_dossier: dict,
    output_dir: Optional[str],
) -> None:
    """Store the user turn + assistant reply carrying the updated
    discovery dossier in ``metadata_["discovery"]`` so DiscoveryCard
    re-renders. Also refreshes ``.pending_discovery.json`` on disk so
    the [APPROVE_DISCOVERY] branch reads the adjusted dossier."""
    async with async_session() as sess:
        sess.add(Conversation(
            project_id=project_id,
            role="user",
            message_type="chat",
            content=user_message,
            metadata_={"adjust": True, "adjust_target": "discovery"},
        ))
        sess.add(Conversation(
            project_id=project_id,
            role="assistant",
            message_type="chat",
            content=narrative,
            metadata_={
                "adjust": True,
                "adjust_target": "discovery",
                "discovery": new_dossier,
                "intent": "DISCOVERY",
            },
        ))
        await sess.commit()

    if output_dir:
        try:
            # Lazy import — generate.py is heavy and we don't want it
            # loaded on every plan-adjust turn.
            from routers.generate import _save_pending_discovery
            _save_pending_discovery(output_dir, new_dossier)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "discovery_adjust: pending-file refresh failed for %s: %s",
                project_id, exc,
            )


# --------------------------------------------------------------------------- #
# Endpoint                                                                     #
# --------------------------------------------------------------------------- #

@router.post("/api/projects/{project_id}/plan/adjust", response_model=AdjustResponse)
async def adjust_plan(
    project_id: uuid.UUID,
    req: AdjustRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdjustResponse:
    """One turn of the Adjust-strategy conversation.

    Auth: user must be a member of the project's org — verified via
    ``get_project_with_auth`` since it already handles the whole chain.

    Behavior:
      * Empty / whitespace-only message → returns ``error=empty_message``,
        no persistence.
      * No pending plan → 404.
      * LLM outage / bad response → returns ``error=<code>`` with the
        original plan preserved.
      * Success → persists a user turn + a fresh assistant "plan" message
        so ``[APPROVE_PLAN]`` picks up the adjusted plan automatically.
    """
    # Auth: use the same helper the rest of the router does.
    from services.project_service import get_project_with_auth
    project: Project = await get_project_with_auth(project_id, user, db)

    plan, plan_conv = await _load_pending_plan(project_id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail="No pending plan found for this project. "
                   "Generate a plan first, then adjust it.",
        )

    prior_turns = await _load_prior_adjust_turns(project_id)
    result = await adjust_plan_via_llm(
        plan,
        req.message,
        prior_turns=prior_turns,
    )

    # Only persist if we actually applied something. On error / no-op the
    # timeline stays clean; the client sees the error field and can retry.
    if result.error is None and not result.diff.is_empty():
        try:
            await _persist_adjust_turn(
                project_id, req.message, result.narrative, result.new_plan,
            )
        except Exception as exc:  # persistence failure shouldn't drop UX
            logger.warning("plan_adjust: persist failed for %s: %s", project_id, exc)
            result.warnings.append(f"couldn't save turn: {exc.__class__.__name__}")

    return AdjustResponse(
        plan=result.new_plan,
        diff=result.diff.to_dict(),
        applied_ops=[{"op": a.op, "args": a.args} for a in result.applied_ops],
        narrative=result.narrative,
        warnings=result.warnings,
        error=result.error,
    )


# --------------------------------------------------------------------------- #
# Discovery-adjust endpoint                                                    #
# --------------------------------------------------------------------------- #

class DiscoveryAdjustResponse(BaseModel):
    """Same shape as :class:`AdjustResponse` but with ``discovery`` in
    place of ``plan`` so the client can distinguish the two cases if
    it renders both cards on the same timeline."""
    discovery: dict
    diff: dict
    applied_ops: list[dict]
    narrative: str
    warnings: list[str]
    error: Optional[str] = None


@router.post(
    "/api/projects/{project_id}/discovery/adjust",
    response_model=DiscoveryAdjustResponse,
)
async def adjust_discovery(
    project_id: uuid.UUID,
    req: AdjustRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoveryAdjustResponse:
    """One turn of the Adjust-strategy conversation on the discovery
    dossier (DiscoveryCard).

    Behavior:
      * Empty message → ``error=empty_message``, no persistence.
      * No dossier attached to the project → 404.
      * LLM outage → ``error=<code>``, dossier preserved unchanged.
      * Success → persists user + assistant turns, updates the
        ``.pending_discovery.json`` on disk so ``[APPROVE_DISCOVERY]``
        picks up the adjusted dossier.
    """
    from services.project_service import get_project_with_auth
    project: Project = await get_project_with_auth(project_id, user, db)

    dossier, _dossier_conv = await _load_pending_discovery(project_id)
    if dossier is None:
        raise HTTPException(
            status_code=404,
            detail="No discovery dossier found for this project. "
                   "Trigger discovery first, then adjust it.",
        )

    prior_turns = await _load_prior_adjust_turns(
        project_id, target="discovery",
    )
    result = await adjust_dossier_via_llm(
        dossier,
        req.message,
        prior_turns=prior_turns,
    )

    if result.error is None and not result.diff.is_empty():
        try:
            await _persist_discovery_adjust_turn(
                project_id,
                req.message,
                result.narrative,
                result.new_dossier,
                getattr(project, "output_dir", None),
            )
        except Exception as exc:
            logger.warning(
                "discovery_adjust: persist failed for %s: %s", project_id, exc,
            )
            result.warnings.append(f"couldn't save turn: {exc.__class__.__name__}")

    return DiscoveryAdjustResponse(
        discovery=result.new_dossier,
        diff=result.diff.to_dict(),
        applied_ops=[{"op": a.op, "args": a.args} for a in result.applied_ops],
        narrative=result.narrative,
        warnings=result.warnings,
        error=result.error,
    )
