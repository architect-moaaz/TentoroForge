"""Followup-2 — the first queries built on :class:`FaultRecord`.

Four canonical aggregations answering questions the log was designed
to feed:

  * :func:`top_signatures` — which fault signatures dominate for a
    project (or fleet-wide).
  * :func:`fix_stuck_rate` — of the rows where a fix was attempted,
    what fraction stuck (didn't regress on the next verify round).
  * :func:`signature_count_by_component_type` — cross-tab so the
    caller can see e.g. "buttons account for 80% of BUTTON_* faults."
  * :func:`promise_gaps_count` — how often PROMISE_NOT_DELIVERED
    fired (deterministic gate signal, distinct from runtime faults).

All pure SQL aggregations. No LLM. Fail-open on DB error.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.fault_record import FaultRecord

logger = logging.getLogger(__name__)


async def top_signatures(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str | None = None,
    limit: int = 10,
) -> list[tuple[str, int]]:
    """Return ``[(signature, count), ...]`` ordered desc by count.

    When ``project_id`` is None, aggregates across all projects
    (fleet-wide baseline). Limit clamps result size.
    """
    try:
        stmt = (
            select(FaultRecord.signature, func.count().label("n"))
            .group_by(FaultRecord.signature)
            .order_by(func.count().desc(), FaultRecord.signature)
            .limit(max(1, min(int(limit), 100)))
        )
        if project_id is not None:
            stmt = stmt.where(FaultRecord.project_id == _uuid(project_id))
        rows = (await session.execute(stmt)).all()
        return [(str(sig), int(n)) for sig, n in rows]
    except Exception as exc:  # noqa: BLE001
        logger.debug("[fault_analytics] top_signatures failed: %s", exc)
        return []


async def fix_stuck_rate(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str | None = None,
) -> float | None:
    """Return ``stuck / attempted`` as a float in ``[0.0, 1.0]``, or
    ``None`` when no fix was attempted (denominator=0).

    Only rows with ``fix_applied=True`` count. ``fix_stuck=True`` →
    fix survived to the next round. ``fix_stuck=False`` → regressed.
    """
    try:
        stmt = select(
            func.sum(case((FaultRecord.fix_stuck.is_(True), 1), else_=0)),
            func.count(),
        ).where(FaultRecord.fix_applied.is_(True))
        if project_id is not None:
            stmt = stmt.where(FaultRecord.project_id == _uuid(project_id))
        stuck, total = (await session.execute(stmt)).one()
        total = int(total or 0)
        if total == 0:
            return None
        return float(int(stuck or 0)) / total
    except Exception as exc:  # noqa: BLE001
        logger.debug("[fault_analytics] fix_stuck_rate failed: %s", exc)
        return None


async def signature_count_by_component_type(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str | None = None,
) -> dict[str, dict[str, int]]:
    """``{component_type: {signature: count}}``.

    Rows with ``component_type IS NULL`` (workflows, entities,
    promise-gate synthetic faults) group under ``"unknown"``.
    """
    try:
        stmt = (
            select(
                FaultRecord.component_type,
                FaultRecord.signature,
                func.count().label("n"),
            )
            .group_by(FaultRecord.component_type, FaultRecord.signature)
        )
        if project_id is not None:
            stmt = stmt.where(FaultRecord.project_id == _uuid(project_id))
        rows = (await session.execute(stmt)).all()
        out: dict[str, dict[str, int]] = {}
        for ctype, sig, n in rows:
            key = ctype or "unknown"
            out.setdefault(key, {})[str(sig)] = int(n)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("[fault_analytics] signature_count_by_component_type failed: %s", exc)
        return {}


async def promise_gaps_count(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str | None = None,
) -> int:
    """Count of PROMISE_NOT_DELIVERED faults (deterministic gate)."""
    try:
        from services.fault_classifier import FaultSignature
        stmt = select(func.count()).where(
            FaultRecord.signature == FaultSignature.PROMISE_NOT_DELIVERED,
        )
        if project_id is not None:
            stmt = stmt.where(FaultRecord.project_id == _uuid(project_id))
        return int((await session.execute(stmt)).scalar() or 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[fault_analytics] promise_gaps_count failed: %s", exc)
        return 0


# ── Helpers ──────────────────────────────────────────────────────────────


def _uuid(x: Any) -> uuid.UUID:
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))
