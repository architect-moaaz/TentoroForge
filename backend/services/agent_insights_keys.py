"""The keys an app signs its events with: made here once, stored only as a hash, looked up on every ingest request.

* a key is ``fik_`` plus 40 letters and digits; the platform keeps its sha256 and its first 8 characters (to show "fik_ab12" in the
  UI), never the key. The key is returned ONCE, when it is made;
* one ACTIVE key per project (the database enforces it): making a new one revokes the old one in the same transaction;
* the ingest route asks ``authenticate`` on every request, so a hit is a dictionary lookup. A key found (or found missing) is
  remembered for a few seconds; rotating or removing a key forgets it at once in THIS process, and in the other backend process within
  that few seconds.
"""
from __future__ import annotations

import hashlib
import secrets
import string
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_insights import ROLLUP_TABLES, AgentInsightKey

KEY_RE_PREFIX = "fik_"
KEY_LENGTH = 4 + 40
_ALPHABET = string.ascii_letters + string.digits
CACHE_SECONDS = 15.0
MISSING_CACHE_SECONDS = 5.0


@dataclass(frozen=True)
class KeyIdentity:
    project_id: uuid.UUID
    key_id: uuid.UUID
    key_hash: str


def generate_key() -> str:
    return KEY_RE_PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(40))


def looks_like_key(token: str) -> bool:
    return len(token) == KEY_LENGTH and token.startswith(KEY_RE_PREFIX) and all(c in _ALPHABET for c in token[4:])


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


_cache: dict[str, tuple[float, KeyIdentity | None]] = {}
_touched: dict[uuid.UUID, datetime] = {}


def forget_cache() -> None:
    _cache.clear()


async def authenticate(token: str) -> KeyIdentity | None:
    """The project this key belongs to, or None when it is unknown or revoked (the caller answers 401)."""
    if not looks_like_key(token):
        return None
    h = hash_key(token)
    hit = _cache.get(h)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    from database import async_session

    async with async_session() as db:
        row = (await db.execute(select(AgentInsightKey.id, AgentInsightKey.project_id).where(
            and_(AgentInsightKey.key_hash == h, AgentInsightKey.revoked_at.is_(None))))).first()
    ident = KeyIdentity(row.project_id, row.id, h) if row else None
    if len(_cache) > 5000:  # a flood of made-up keys must not grow memory without limit
        _cache.clear()
    _cache[h] = (now + (CACHE_SECONDS if ident else MISSING_CACHE_SECONDS), ident)
    return ident


def touch(key_id: uuid.UUID, when: datetime | None = None) -> None:
    """Remember that this key was just used; written to the database in a batch (``flush_touches``), not on every request."""
    _touched[key_id] = when or datetime.now(timezone.utc)


async def flush_touches(session_factory=None) -> int:
    if not _touched:
        return 0
    if session_factory is None:
        from database import async_session as session_factory
    batch = dict(_touched)
    _touched.clear()
    async with session_factory() as db, db.begin():
        for key_id, when in batch.items():
            col = AgentInsightKey.last_used_at
            await db.execute(update(AgentInsightKey).where(AgentInsightKey.id == key_id)
                             .values(last_used_at=case((or_(col.is_(None), col < when), when), else_=col)))
    return len(batch)


async def create_or_rotate(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID | None) -> tuple[str, str]:
    """Make the project's key, revoking the current one. Returns (key, prefix); the key is not recoverable afterwards."""
    for attempt in range(2):
        key = generate_key()
        try:
            await db.execute(update(AgentInsightKey).where(and_(AgentInsightKey.project_id == project_id, AgentInsightKey.revoked_at.is_(None)))
                             .values(revoked_at=datetime.now(timezone.utc)))
            db.add(AgentInsightKey(project_id=project_id, key_hash=hash_key(key), prefix=key[:8], created_by=user_id))
            await db.commit()
            forget_cache()
            return key, key[:8]
        except IntegrityError:
            # two people pressed "create" at the same moment: the other one won the unique slot; try once more on top of theirs
            await db.rollback()
            if attempt:
                raise
    raise RuntimeError("unreachable")


async def remove(db: AsyncSession, project_id: uuid.UUID) -> bool:
    r = await db.execute(update(AgentInsightKey).where(and_(AgentInsightKey.project_id == project_id, AgentInsightKey.revoked_at.is_(None)))
                         .values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    forget_cache()
    return bool(r.rowcount)


async def active_key(db: AsyncSession, project_id: uuid.UUID) -> AgentInsightKey | None:
    return (await db.execute(select(AgentInsightKey).where(and_(AgentInsightKey.project_id == project_id,
                                                                AgentInsightKey.revoked_at.is_(None))))).scalar_one_or_none()


async def has_ever_had_key(db: AsyncSession, project_id: uuid.UUID) -> bool:
    return (await db.execute(select(func.count()).select_from(AgentInsightKey).where(AgentInsightKey.project_id == project_id))).scalar() > 0


async def describe(db: AsyncSession, project_id: uuid.UUID, *, now: datetime | None = None) -> dict[str, Any]:
    """The key's public face: whether one exists, its first 8 characters, when it was made and last used, and the events of the last 24 hours."""
    now = now or datetime.now(timezone.utc)
    k = await active_key(db, project_id)
    if k is None:
        return {"exists": False, "prefix": None, "createdAt": None, "lastUsedAt": None, "eventsLast24h": 0}
    hour = ROLLUP_TABLES["hour"]
    since = (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    turns = (await db.execute(select(func.coalesce(func.sum(hour.c.turns), 0)).where(
        and_(hour.c.project_id == project_id, hour.c.bucket >= since)))).scalar() or 0
    return {"exists": True, "prefix": k.prefix, "createdAt": _iso(k.created_at), "lastUsedAt": _iso(k.last_used_at),
            "eventsLast24h": int(turns)}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
