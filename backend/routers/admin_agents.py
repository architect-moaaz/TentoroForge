"""The super admin's view of the agents: who works how much, at what cost, how
often their work lands and why it fails (`services.agent_stats`)."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from models.auth import PlatformUser
from platform_admin import require_super_admin
from services import spending
from services.agent_personas import personas

router = APIRouter(prefix="/api/admin/agents", tags=["admin-agents"])

#: A minute's answer is kept: the dashboard polls, and a scan reads every
#: application's run ledgers.
_CACHE_S = 60.0
_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


@router.get("")
async def agents(period: str = Query("month"), at: str | None = Query(None),
                 admin: PlatformUser = Depends(require_super_admin)) -> dict[str, Any]:
    if period not in spending.PERIODS:
        raise HTTPException(status_code=422, detail=f"period must be one of {', '.join(spending.PERIODS)}")
    try:
        when = spending.parse_at(at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    key = (period, at or "")
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_S:
        return hit[1]
    from services.agent_stats import agent_stats
    out = await asyncio.to_thread(agent_stats, period=period, at=when)
    _cache[key] = (time.monotonic(), out)
    return out


@router.get("/personas")
async def agent_personas(admin: PlatformUser = Depends(require_super_admin)) -> dict[str, Any]:
    """Every agent's name, title, room and introduction."""
    return {"personas": personas()}
