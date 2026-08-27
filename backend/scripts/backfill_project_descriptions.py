"""Backfill Project.description from the first user Conversation message.

Historical projects created via the "New App" dialog with a blank description
field never received one — the user's first chat message was the real project
description all along. Copy it in so the Projects card stops rendering "No
description" for every one of them.

Run:
    cd backend && /usr/local/bin/python3 scripts/backfill_project_descriptions.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as `python scripts/backfill_project_descriptions.py` from
# either the backend/ dir or the repo root without a PYTHONPATH gymnastic.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select, asc

from database import async_session
from models.project import Conversation, MessageRole, Project


DESC_CAP = 500


async def main() -> int:
    updated = 0
    skipped_no_msg = 0
    async with async_session() as sess:
        r = await sess.execute(
            select(Project).where(
                (Project.description.is_(None)) | (Project.description == "")
            )
        )
        projects = list(r.scalars())
        print(f"scanning {len(projects)} project(s) with empty description")

        for p in projects:
            r2 = await sess.execute(
                select(Conversation)
                .where(
                    Conversation.project_id == p.id,
                    Conversation.role == MessageRole.user,
                )
                .order_by(asc(Conversation.created_at))
                .limit(1)
            )
            first = r2.scalar_one_or_none()
            if first is None or not (first.content or "").strip():
                skipped_no_msg += 1
                continue
            p.description = first.content.strip()[:DESC_CAP]
            updated += 1
            print(f"  {p.short_id}  {p.name!r} → {p.description[:80]!r}…")

        await sess.commit()

    print(f"\nupdated={updated}  skipped_no_first_msg={skipped_no_msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
