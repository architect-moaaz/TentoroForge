"""Where a running application says it was slow, and what it has been telling us.

A crash has somewhere to go already: ``/api/projects/:id/runtime-exceptions``
persists a row and wakes the self-heal loop. Slowness has nowhere, because
there is nothing to heal and nothing to dedup — a slow response is not a
defect with a fingerprint, it is a measurement, and four hundred of them is a
different fact from four.

So it lands in the project's own ledger and nowhere else:
``<output_dir>/.forge/incidents.jsonl``, beside the run ledger, one JSON
object per line, readable with `cat` on a host with no database. The crash
endpoint mirrors into the same file. :mod:`services.incident_ledger` owns the
record shape and states, in full, what a report may and may not carry.

Like the crash endpoint, POST here is UNAUTHENTICATED — a generated app has no
session cookie to prove itself with. What that buys an attacker is lines in
one project's own file, which is why the body declares every field it accepts
and rejects the rest.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.project import Project
from services import incident_ledger

logger = logging.getLogger(__name__)
router = APIRouter(tags=["incidents"])


class SlowResponseIn(BaseModel):
    """One server response the application itself timed and thought too long.

    WHAT THIS IS A MEASUREMENT OF: the duration of a handler inside the
    generated app's own server process. Not the browser's render, not the
    network between a customer and the server, not a cold start before that
    code ran. `operation` says which handler, so an answer built on these can
    say what it is and is not talking about.
    """
    kind: str = Field(default=incident_ledger.KIND_SLOW, pattern="^slow$")
    #: What was being done — a workflow id, or a data operation (`create`).
    operation: str = Field(min_length=1, max_length=255)
    ms: int = Field(ge=0, le=3_600_000)
    #: What the app was told to call slow, carried so a reading of the ledger
    #: always knows what the number was compared against.
    thresholdMs: int = Field(default=0, ge=0, le=3_600_000)
    workflow: Optional[str] = Field(default=None, max_length=255)
    entity: Optional[str] = Field(default=None, max_length=255)
    #: A ROUTE PATTERN (`/cases/[id]`), matched by the app against the routes
    #: it declares. Never a concrete path — that carries a record id.
    route: Optional[str] = Field(default=None, max_length=512)
    control: Optional[str] = Field(default=None, max_length=255)
    label: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = Field(default=None, max_length=128)

    #: Nothing else. A field we did not design is a field we cannot promise
    #: carries no customer of theirs.
    model_config = {"extra": "forbid"}


class IncidentAccepted(BaseModel):
    recorded: bool


@router.post("/api/projects/{project_id}/incidents",
             response_model=IncidentAccepted, status_code=202)
async def ingest_incident(
    project_id: uuid.UUID = Path(...),
    body: SlowResponseIn = ...,
    db: AsyncSession = Depends(get_db),
) -> IncidentAccepted:
    """Append one slow-response observation to the project's incident ledger.

    Nothing is collapsed on the way in. For a crash a repeat adds nothing and
    the endpoint counts it; here the repeats ARE the measurement, and an
    average is only worth as much as the observations behind it.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if not project.output_dir:
        # Nothing was ever built, so there is no directory to write beside.
        return IncidentAccepted(recorded=False)
    written = incident_ledger.record(project.output_dir, {
        "kind": incident_ledger.KIND_SLOW,
        "operation": body.operation,
        "ms": body.ms,
        "thresholdMs": body.thresholdMs or None,
        "workflow": body.workflow,
        "entity": body.entity,
        "route": body.route,
        "control": body.control,
        "label": body.label,
        "role": body.role,
    })
    return IncidentAccepted(recorded=written is not None)


@router.get("/api/projects/{project_id}/incidents")
async def read_incidents(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """What this application has been reporting — crashes grouped, slow
    responses averaged. The same two readings Smith answers from, so a screen
    and a sentence never disagree about what happened."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if not project.output_dir:
        return {"crashes": [], "slow": []}
    return {"crashes": [dict(c) for c in incident_ledger.crashes(project.output_dir)],
            "slow": incident_ledger.slow(project.output_dir)}
