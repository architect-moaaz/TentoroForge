"""SV-STRICT-5 — write FaultRecord rows from a verify run.

Public surface
--------------

* :func:`build_records` — pure. ``(run_id, project_id, report, narrated,
  generation_hash) → list[dict]``. Test-covered end-to-end without a DB.
* :func:`persist_records` — async. Takes an AsyncSession + the dict list
  from ``build_records`` and inserts one :class:`FaultRecord` row per
  entry.
* :func:`mark_fix_outcomes` — async. After a Smith round completes,
  update ``fix_applied`` / ``fix_stuck`` on the previous round's rows by
  comparing round-N ids to round-(N+1) ids.

The writer never raises. The verify pipeline calls it best-effort — a
DB error here must not fail a verify run.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.fault_record import FaultRecord

logger = logging.getLogger(__name__)


# ── Pure build ───────────────────────────────────────────────────────────


def build_records(
    *,
    run_id: uuid.UUID | str,
    project_id: uuid.UUID | str,
    report: dict[str, Any],
    narrated: dict[str, Any] | None = None,
    generation_hash: str | None = None,
) -> list[dict[str, Any]]:
    """Return one dict per fault, ready to pass to :func:`persist_records`.

    ``report`` is the raw ``row.report`` dict (whose ``faults`` list may
    contain runtime faults, promise-gate synthetic faults, or a mix).
    ``narrated`` is the payload from :mod:`services.verify_narration`
    (may be empty). Missing / malformed inputs degrade to an empty list.
    """
    faults = (report or {}).get("faults") or []
    if not faults:
        return []

    # Index narratives by component_id for cheap join.
    narratives: dict[str, dict[str, Any]] = {}
    for n in ((narrated or {}).get("narratives") or []):
        cid = n.get("component_id")
        if cid:
            narratives[cid] = n

    out: list[dict[str, Any]] = []
    for f in faults:
        try:
            out.append(_row_from_fault(
                run_id=str(run_id),
                project_id=str(project_id),
                fault=f,
                narrative=narratives.get(f.get("interaction_id") or ""),
                generation_hash=generation_hash,
            ))
        except Exception as exc:  # noqa: BLE001 — skip individual bad rows
            logger.debug("[fault_record_writer] skipped bad fault: %s", exc)
            continue
    return out


def _row_from_fault(
    *,
    run_id: str,
    project_id: str,
    fault: dict[str, Any],
    narrative: dict[str, Any] | None,
    generation_hash: str | None,
) -> dict[str, Any]:
    interaction = fault.get("interaction") or {}
    signature = str(fault.get("signature") or "UNCLASSIFIED")
    priority = str(fault.get("priority") or "BROKEN")
    layer = str(fault.get("layer") or "http")
    w_slot = str(fault.get("w_slot") or "what")

    component_id = fault.get("interaction_id") or interaction.get("id") or ""
    contract_id = fault.get("contract_id")
    route = interaction.get("route") or ""
    # kind → component_type mapping (mirrors contract_fault_join)
    kind = interaction.get("kind") or ""
    component_type = {
        "route": "page", "button": "button", "form": "form",
        "list": "table", "detail": "detail",
    }.get(kind)

    # Compact evidence — keep the classifier-relevant fields only.
    ev = fault.get("evidence") or {}
    evidence = {
        k: ev.get(k) for k in (
            "status", "url_after_click", "rows_returned", "timed_out",
        ) if ev.get(k) is not None
    }
    # Cap body_excerpt / stack for storage.
    if ev.get("body_excerpt"):
        evidence["body_excerpt"] = str(ev["body_excerpt"])[:400]
    if ev.get("stack_trace"):
        evidence["stack_trace"] = str(ev["stack_trace"])[:600]

    narrative_text = None
    if narrative and narrative.get("text"):
        narrative_text = str(narrative["text"])[:1024]

    return {
        "run_id": run_id,
        "project_id": project_id,
        "signature": signature[:64],
        "priority": priority[:16],
        "layer": layer[:16],
        "w_slot": w_slot[:8],
        "component_id": (str(component_id) or None) and str(component_id)[:255],
        "contract_id": contract_id and str(contract_id)[:255],
        "component_type": component_type,
        "route": (str(route) or None) and str(route)[:255],
        "generation_hash": generation_hash and str(generation_hash)[:64],
        "evidence": evidence or None,
        "narrative": narrative_text,
        "fix_applied": False,
        "fix_stuck": None,
    }


# ── Persistence (async) ──────────────────────────────────────────────────


async def persist_records(
    session: AsyncSession, rows: Iterable[dict[str, Any]],
) -> int:
    """Insert one FaultRecord per row dict. Returns the count inserted.

    Coerces string ``run_id`` / ``project_id`` to :class:`uuid.UUID`
    for SQLAlchemy's UUID column type. Never raises: on any DB error
    the count is 0 and the exception is logged. The verify pipeline
    treats this as best-effort learning substrate, not part of the
    fault-fix loop's success criterion.
    """
    inserted = 0
    try:
        for r in rows:
            payload = dict(r)
            for uuid_key in ("run_id", "project_id"):
                val = payload.get(uuid_key)
                if isinstance(val, str):
                    payload[uuid_key] = uuid.UUID(val)
            session.add(FaultRecord(**payload))
            inserted += 1
        if inserted:
            await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fault_record_writer] persist failed: %s", exc)
        return 0
    return inserted


# ── Fix-outcome update (post Smith round) ────────────────────────────────


async def mark_fix_outcomes(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | str,
    fixed_component_ids: Iterable[str],
    still_failing_component_ids: Iterable[str],
) -> None:
    """After a Smith round, mark which rows' fixes stuck vs regressed.

    ``fixed_component_ids``: components that disappeared from the fault
    set between rounds → ``fix_applied=True``, ``fix_stuck=True``.

    ``still_failing_component_ids``: components that reappeared after a
    fix attempt → ``fix_applied=True``, ``fix_stuck=False``.

    Fail-open on error.
    """
    try:
        fixed_set = {str(x) for x in fixed_component_ids if x}
        failed_set = {str(x) for x in still_failing_component_ids if x}
        if fixed_set:
            await session.execute(
                update(FaultRecord)
                .where(FaultRecord.run_id == run_id,
                       FaultRecord.component_id.in_(fixed_set))
                .values(fix_applied=True, fix_stuck=True),
            )
        if failed_set:
            await session.execute(
                update(FaultRecord)
                .where(FaultRecord.run_id == run_id,
                       FaultRecord.component_id.in_(failed_set))
                .values(fix_applied=True, fix_stuck=False),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fault_record_writer] mark_fix_outcomes failed: %s", exc)
