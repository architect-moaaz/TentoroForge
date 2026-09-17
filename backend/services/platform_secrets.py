"""Which secret NAMES the platform holds for a project — never their values.

`services.figma.integrations` reads the same store to RESOLVE a credential at
the moment of a call. This module answers the other question, the one Smith
has to answer in a sentence: *is it set?* — and answers it without decrypting
anything, because a name is all an answer needs and a value in memory is a
value that can be logged.

WHY IT MATTERS THAT THESE ARE TWO FUNCTIONS. `config_for` returns plaintext;
calling it to test a key for emptiness would put every one of an
organisation's credentials into a Smith turn, and a turn is written to the
conversation table. A row with ciphertext is set. That is the whole check.

The environment is the fallback, exactly as it is for a resolution: a
developer with `SMTP_HOST` exported has a connected application, and saying it
was not connected would be false.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def keys_set_for(output_dir: str | Path, keys: list[str] | tuple[str, ...]) -> set[str]:
    """Which of `keys` this project's organisation (or this environment) holds.

    Returns NAMES. Never raises: a project with no row, a store that is down
    and a key that only exists in the environment are all answerable, and an
    unanswerable store means "only what the environment has" rather than an
    error in the middle of a sentence.
    """
    wanted = [str(k) for k in keys if str(k).strip()]
    if not wanted:
        return set()

    found: set[str] = {k for k in wanted if (os.environ.get(k) or "").strip()}

    # THE ONE SYNCHRONOUS BRIDGE, NOT A SECOND ONE. `_run` and
    # `_session_on_this_loop` carry a hard-won fix — a pooled connection whose
    # futures belong to the server's loop reads as "store unavailable" from a
    # worker thread — and re-deriving it here would give two bridges, one of
    # them wrong.
    try:
        from services.figma.integrations import (
            _org_for_output_dir, _run, _session_on_this_loop,
        )

        async def _set_keys(org_id: object) -> set[str]:
            from sqlalchemy import select

            from models.platform_integration import PlatformIntegration

            async with _session_on_this_loop() as db:
                rows = (await db.execute(
                    select(PlatformIntegration.key).where(
                        PlatformIntegration.org_id == org_id,
                        PlatformIntegration.key.in_(wanted),
                        PlatformIntegration.value_ct.isnot(None),
                    )
                )).scalars().all()
            return {str(k) for k in rows}

        org_id = _run(_org_for_output_dir(output_dir))
        if org_id is not None:
            found |= _run(_set_keys(org_id))
    except Exception as exc:  # noqa: BLE001 — the store is one of two sources
        logger.info("[secrets] presence lookup unavailable (%s); the "
                    "environment is what is known", type(exc).__name__)
    return found


__all__ = ["keys_set_for"]
