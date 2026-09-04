"""The Figma credential, from the platform's secrets store rather than .env.

`credentials.py` describes `EnvSecretResolver` as the stand-in written "for
local development and live verification **before the platform secrets service
exists**". It exists: `platform_integrations` is per-org, encrypted at rest with
a per-provider HKDF subkey, and already holds the Anthropic and Resend keys.

A token in a shared `.env` is a token every project and every developer on the
machine holds, with no owner and no rotation story — which is how the one in
this repository came to be annotated as leaked. A token in the store is scoped
to one organisation, write-only through the settings API (`kind="password"` is
never echoed back), and resolvable only at the moment of a call.

WHAT THIS RESOLVES, AND WHEN
----------------------------
`SecretResolver.resolve` is synchronous and the only database engine here is
async, so the values are fetched ONCE per extraction and handed to a resolver
that holds just them. That is deliberate rather than a workaround: the raw
secret then lives for one extraction inside one object, instead of being
reachable from anything holding a session.

The environment stays as the fallback, so a developer with `FIGMA_TOKEN`
exported keeps working and nothing has to be migrated before this is useful.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The keys `__figma__` declares in `node_config_specs`.
TOKEN_KEY = "FIGMA_TOKEN"
ENDPOINT_KEY = "FIGMA_MCP_URL"
PROVIDER = "figma"


class MappingResolver:
    """A :class:`SecretResolver` over values already fetched.

    Holds the raw secret for the life of one extraction and nothing longer.
    `resolve` raises the same error `EnvSecretResolver` raises, so callers
    cannot tell which backend answered — which is the point of the seam.
    """

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    def resolve(self, ref: str) -> str:
        from services.figma.credentials import FigmaCredentialError

        value = (self._values.get(ref) or "").strip()
        if not value:
            raise FigmaCredentialError(
                f"{ref} is not set for this organisation. Add it under "
                f"Settings → Integrations → Figma."
            )
        return value


def _run(coro: Any) -> Any:
    """Bridge one async query into a synchronous caller."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _fetch(org_id: Any) -> dict[str, str]:
    from sqlalchemy import select

    from database import async_session
    from models.platform_integration import PlatformIntegration
    from services.platform_integrations_crypto import decrypt

    out: dict[str, str] = {}
    async with async_session() as db:
        rows = (await db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.org_id == org_id,
                PlatformIntegration.provider == PROVIDER,
            )
        )).scalars().all()

    for row in rows:
        if not row.value_ct or not row.value_iv:
            continue
        try:
            out[row.key] = decrypt(row.provider, row.value_ct, row.value_iv)
        except Exception:  # noqa: BLE001 — one bad row reads as "not set"
            logger.warning("[figma] could not decrypt %s for org %s",
                           row.key, org_id)
    return out


async def _org_for_output_dir(output_dir: str | Path) -> Any:
    """The organisation owning the project at ``output_dir``, or None.

    Matched on `output_dir` rather than on the directory name: a project whose
    folder is not named after its `short_id` is legal — `refund-cases` is one —
    and the column is the fact.
    """
    from sqlalchemy import select

    from database import async_session
    from models.project import Project

    target = str(output_dir).rstrip("/")
    async with async_session() as db:
        row = (await db.execute(
            select(Project).where(Project.output_dir == target)
        )).scalars().first()
    return getattr(row, "org_id", None)


def config_for(output_dir: str | Path) -> dict[str, str]:
    """Figma settings for the org owning this project, environment as fallback.

    Never raises: a project with no database row, a database that is down, or
    an organisation that has configured nothing all mean "fall back", and a
    developer with the variables exported keeps working throughout.
    """
    values: dict[str, str] = {}
    try:
        org_id = _run(_org_for_output_dir(output_dir))
        if org_id is not None:
            values = _run(_fetch(org_id))
    except Exception as exc:  # noqa: BLE001 — the store is an optimisation here
        logger.info("[figma] integrations lookup unavailable (%s); using the "
                    "environment", type(exc).__name__)

    for key in (TOKEN_KEY, ENDPOINT_KEY):
        if not values.get(key):
            from_env = (os.environ.get(key) or "").strip()
            if from_env:
                values[key] = from_env
    return values


def endpoint_from(values: dict[str, str]) -> str:
    """The MCP endpoint to call, or the documented remote default.

    The desktop app's Dev Mode server (127.0.0.1:3845) only exists while Figma
    is open on someone's own machine, so it is a legitimate setting and a poor
    default — a backend that assumes it fails with a connection error rather
    than an explanation.
    """
    from services.figma.gateway import DEFAULT_ENDPOINT

    return (values.get(ENDPOINT_KEY) or "").strip() or DEFAULT_ENDPOINT
