"""Ambiguity-ledger endpoints (REL-S1).

Serves the ``open_decisions.json`` artifact — every ambiguous pick the
pipeline made, with confidence + alternatives — and accepts confirm/swap
writes that update ``bindings.json`` (which feeds the next generation).

Namespaced under ``/api/projects/{project_id}/open-decisions`` to
avoid collision with the older ``/decisions`` router (business-rule
DMN tables). Endpoints:

  GET  /api/projects/{project_id}/open-decisions
       → { decisions: [...], pending_count: N }
  POST /api/projects/{project_id}/open-decisions/{decision_id}/confirm
       Body: { target: string }
       → { ok: true, decision_id, target }
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_service import get_project_with_auth
from services import decision_ledger as _dl

router = APIRouter(tags=["open-decisions"])


class ConfirmBody(BaseModel):
    """POST body for confirming a pending decision.

    ``target`` is either the current ``target_picked`` (accept the
    pipeline's pick) or any alternative from ``alternatives[].target``
    (swap). Free-form string is allowed — the frontend can offer a
    manual entry when neither the pick nor alternatives are what the
    user wants.
    """
    decision_id: str = Field(..., min_length=1, max_length=400)
    target: str = Field(..., min_length=1, max_length=400)


def _decision_by_id(decisions: list[dict], decision_id: str) -> dict | None:
    for d in decisions:
        if isinstance(d, dict) and d.get("decision_id") == decision_id:
            return d
    return None


def _split_binding_key(decision_id: str) -> tuple[str, str, str] | None:
    """Reverse the decision_id encoding so we can rebuild the (kind, scope,
    identity) tuple :func:`save_binding` requires. Format is
    ``kind:scope:identity`` — scope itself may contain a colon (e.g.
    ``page:/docs``) so we split ONLY on the first and last colons.
    """
    parts = decision_id.split(":")
    if len(parts) < 3:
        return None
    kind = parts[0]
    identity = parts[-1]
    scope = ":".join(parts[1:-1])
    return kind, scope, identity


@router.get("/api/projects/{project_id}/open-decisions")
async def list_open_decisions(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return every ledger row for the project, plus a pending count for
    the chip-badge. Pending = medium/low confidence AND not yet resolved."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir or not Path(project.output_dir).exists():
        return {"decisions": [], "pending_count": 0}

    decisions = _dl.load_ledger(project.output_dir)
    pending = sum(
        1 for d in decisions
        if isinstance(d, dict)
        and d.get("confidence") in {_dl.BAND_MEDIUM, _dl.BAND_LOW}
        and not d.get("resolved")
    )
    return {"decisions": decisions, "pending_count": pending}


# `decision_id` rides in the BODY, not the path. Ids are `kind:scope:identity`
# and the scope routinely embeds an app route — `file-documents/new-json` —
# so they contain slashes. Starlette's `{param}` never matches `/`, and the
# ASGI layer decodes `%2F` before routing, so a path-param id 404'd with a
# bare "Not Found". `{decision_id:path}` is not the answer either: the greedy
# converter eats the trailing `/confirm`. Keeping the id out of the URL makes
# the whole class impossible instead of patching one id shape.
@router.post("/api/projects/{project_id}/open-decisions/confirm")
async def confirm_decision(
    project_id: uuid.UUID,
    body: ConfirmBody,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist a confirmed pick to ``bindings.json`` and flip the
    ledger row's ``resolved`` flag so the chip stops surfacing.

    The next generation's emitter (see ``orphan_wiring_pass``) checks
    ``bindings.json`` first via :func:`decision_ledger.resolve_binding`
    and short-circuits with the confirmed target — no re-scoring.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir or not Path(project.output_dir).exists():
        raise HTTPException(status_code=404, detail="Project output directory not found")

    decision_id = body.decision_id
    decisions = _dl.load_ledger(project.output_dir)
    row = _decision_by_id(decisions, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Decision not found: {decision_id}")

    parts = _split_binding_key(decision_id)
    if parts is None:
        raise HTTPException(
            status_code=400,
            detail=f"Malformed decision_id (need kind:scope:identity): {decision_id}",
        )
    kind, scope, identity = parts

    _dl.save_binding(
        project.output_dir,
        kind=kind,
        scope=scope,
        identity=identity,
        target=body.target,
    )
    return {
        "ok": True,
        "decision_id": decision_id,
        "target": body.target,
    }
