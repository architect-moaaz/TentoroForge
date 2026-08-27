"""Look up the structured brief for a project.

Discovery stores the transformer's output in ``DiscoverySession.brief``
(a JSONB column that already exists) and links the session to the project
via ``DiscoverySession.project_id``. The planner router reads it back
here — one place, one query, so future storage moves (Project column,
metadata_ blob, external service) only need to change this file.

Returns ``None`` when there's no discovery session for the project, or
when the session's brief lacks any structured content. Callers should
treat ``None`` as "no authoritative inputs" and fall through to the
legacy path.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def get_structured_brief_for_project(
    sess: Any,
    project_id: uuid.UUID | str,
) -> "StructuredBrief | None":
    """Fetch the discovery session for ``project_id`` and return its brief
    as a :class:`services.structured_brief.StructuredBrief`.

    Signals returned:
      * ``None`` — no session, no brief, empty brief, or parse failure.
        The planner router should render nothing and fall back to normal
        authoring.
      * a ``StructuredBrief`` — a real structured brief, ready to render
        into the AUTHORITATIVE INPUTS block.

    ``sess`` is an ``AsyncSession``; we import :class:`DiscoverySession`
    lazily so this module stays import-safe when the model isn't loaded
    (e.g., in unit tests that don't touch the DB).
    """
    try:
        from sqlalchemy import select
        from models.discovery import DiscoverySession
        from services.structured_brief import StructuredBrief
    except Exception:  # noqa: BLE001 — degrade rather than crash the planner
        logger.exception("brief_lookup: model / structured_brief import failed")
        return None

    try:
        pid = uuid.UUID(str(project_id)) if not isinstance(project_id, uuid.UUID) else project_id
    except (TypeError, ValueError):
        return None

    try:
        result = await sess.execute(
            select(DiscoverySession).where(DiscoverySession.project_id == pid)
        )
        row = result.scalar_one_or_none()
    except Exception:  # noqa: BLE001
        logger.exception("brief_lookup: DB query failed")
        return None

    if row is None or not isinstance(row.brief, dict):
        return None

    try:
        brief = StructuredBrief.parse(row.brief)
    except Exception:  # noqa: BLE001
        logger.exception("brief_lookup: brief parse failed for project %s", pid)
        return None

    return None if brief.is_empty() else brief


def parse_structured_brief_from_dict(payload: Any) -> "StructuredBrief | None":
    """Sync convenience for tests + non-async callsites.

    Same fallback contract as :func:`get_structured_brief_for_project`:
    ``None`` on missing / empty / unparseable input, a
    :class:`StructuredBrief` when there's structural content to honor.
    """
    if payload is None:
        return None
    try:
        from services.structured_brief import StructuredBrief
        brief = StructuredBrief.parse(payload)
    except Exception:  # noqa: BLE001
        return None
    return None if brief.is_empty() else brief
