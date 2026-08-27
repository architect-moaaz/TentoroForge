"""Read + write Smith preferences (Phase 1c).

CRUD around ``models.smith_preference.SmithPreference``, plus a helper
to render the loaded set as a prompt block Smith's system prompt
injects at turn ingress.

Design
------
* Preferences are (org, user) scoped and small (dozens per user, not
  hundreds). One-shot ``SELECT ... WHERE org_id AND user_id`` per turn
  is fine.
* The prompt-block renderer intentionally keeps the format terse —
  each preference is one bullet, ordered by key alphabetically so
  ordering is deterministic (helps prompt caching).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.smith_preference import SmithPreference

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Whitelist of preference keys — bounds what Smith stores.                    #
# --------------------------------------------------------------------------- #
#
# Prevents the LLM from storing arbitrary keys (test 82 could otherwise
# poison the pref store with a hallucinated "user_wants_deletion=on"
# entry the tester never confirmed). Whitelist is additive per phase.
KNOWN_KEYS: frozenset[str] = frozenset({
    "confirm_on_delete",   # "yes" | "no"    — Remove-destructive tests
    "preferred_theme",     # freeform label — future
    "default_generation_profile",  # "fast" | "complete"
    "explain_before_edit",  # "yes" | "no"   — narrator verbosity
})


def is_known_key(key: str) -> bool:
    return isinstance(key, str) and key in KNOWN_KEYS


# --------------------------------------------------------------------------- #
# CRUD                                                                         #
# --------------------------------------------------------------------------- #

async def get_all(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID,
) -> dict[str, str]:
    """Return the user's preferences as a plain dict."""
    q = select(SmithPreference).where(
        SmithPreference.org_id == org_id,
        SmithPreference.user_id == user_id,
    )
    result = await db.execute(q)
    rows = list(result.scalars().all())
    return {r.key: r.value for r in rows}


async def set_pref(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    value: str,
) -> bool:
    """Set a single preference. Upserts on (org, user, key). Returns
    True on success, False if the key isn't in KNOWN_KEYS."""
    if not is_known_key(key):
        return False
    stmt = pg_insert(SmithPreference).values(
        org_id=org_id, user_id=user_id, key=key, value=str(value)[:2000],
    ).on_conflict_do_update(
        index_elements=["org_id", "user_id", "key"],
        set_={"value": str(value)[:2000]},
    )
    await db.execute(stmt)
    await db.commit()
    return True


async def clear_all(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID,
) -> int:
    """Delete every preference row for (org, user). Returns row count."""
    stmt = delete(SmithPreference).where(
        SmithPreference.org_id == org_id,
        SmithPreference.user_id == user_id,
    )
    result = await db.execute(stmt)
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


# --------------------------------------------------------------------------- #
# Prompt-block renderer — pure, testable without a DB                          #
# --------------------------------------------------------------------------- #

def render_preferences_block(prefs: dict[str, str]) -> str:
    """Turn a preferences dict into a Smith system-prompt block.

    Returns an empty string if there are no known preferences (so the
    system prompt doesn't grow a stale header). Otherwise::

        ## USER PREFERENCES (persistent across sessions)
        - confirm_on_delete = yes
        - preferred_theme = midnight

    Ordering is deterministic (alphabetical by key) so prompt-cache
    hits are stable across turns.
    """
    if not prefs:
        return ""
    known = [(k, v) for k, v in prefs.items() if k in KNOWN_KEYS]
    if not known:
        return ""
    known.sort(key=lambda kv: kv[0])
    lines = ["## USER PREFERENCES (persistent across sessions)"]
    for k, v in known:
        lines.append(f"- {k} = {v}")
    lines.append(
        "Apply these standing rules on every turn. If the user asks "
        "to change one, use `set_preference`; to see them all, use "
        "`get_preferences`; to reset, use `clear_preferences`."
    )
    return "\n".join(lines)
