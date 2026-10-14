"""The DNS accounts an organisation connected (Settings → Integrations), as
providers Forge can write records with (`services.deploy.dns_providers`).

The keys are read from the platform store, decrypted here and handed to the
provider clients; they never enter an app's definition, its files or its
environment (`platform_only` in `node_config_specs`)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: provider → (label, the keys it needs).
ACCOUNTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "cloudflare": ("Cloudflare", ("CLOUDFLARE_API_TOKEN",)),
    "route53": ("Route 53", ("ROUTE53_ACCESS_KEY_ID", "ROUTE53_SECRET_ACCESS_KEY")),
    "godaddy": ("GoDaddy", ("GODADDY_API_KEY", "GODADDY_API_SECRET")),
}


def providers_from(values: dict[str, dict[str, str]]) -> list[Any]:
    """Provider clients for every account whose keys are all there."""
    from services.deploy.dns_providers import Cloudflare, GoDaddy, Route53
    out: list[Any] = []
    for provider, (_, keys) in ACCOUNTS.items():
        got = values.get(provider) or {}
        if not all((got.get(k) or "").strip() for k in keys):
            continue
        if provider == "cloudflare":
            out.append(Cloudflare(got["CLOUDFLARE_API_TOKEN"].strip()))
        elif provider == "route53":
            out.append(Route53(got["ROUTE53_ACCESS_KEY_ID"].strip(), got["ROUTE53_SECRET_ACCESS_KEY"].strip()))
        elif provider == "godaddy":
            out.append(GoDaddy(got["GODADDY_API_KEY"].strip(), got["GODADDY_API_SECRET"].strip()))
    return out


async def _rows(org_id: Any, db: Any) -> list[Any]:
    from sqlalchemy import select

    from models.platform_integration import PlatformIntegration
    return list((await db.execute(select(PlatformIntegration).where(
        PlatformIntegration.org_id == org_id,
        PlatformIntegration.provider.in_(tuple(ACCOUNTS)),
    ))).scalars().all())


async def connected_labels(org_id: Any, db: Any) -> list[str]:
    """The accounts whose keys are all set — names only, nothing decrypted."""
    have: dict[str, set[str]] = {}
    for row in await _rows(org_id, db):
        if row.value_ct:
            have.setdefault(row.provider, set()).add(row.key)
    return [label for provider, (label, keys) in ACCOUNTS.items() if set(keys) <= have.get(provider, set())]


async def load(org_id: Any, db: Any) -> list[Any]:
    """Provider clients for the organisation's connected DNS accounts."""
    from services.platform_integrations_crypto import decrypt
    values: dict[str, dict[str, str]] = {}
    for row in await _rows(org_id, db):
        if not row.value_ct or not row.value_iv:
            continue
        try:
            values.setdefault(row.provider, {})[row.key] = decrypt(row.provider, row.value_ct, row.value_iv)
        except Exception:  # noqa: BLE001 — one bad row reads as "not set"
            logger.warning("[dns] could not decrypt %s for org %s", row.key, org_id)
    return providers_from(values)


async def load_for_output_dir(output_dir: str | Path) -> list[Any]:
    """The same, for the organisation owning the project at `output_dir`
    (Smith's side, which knows the folder, not the organisation)."""
    from services.figma.integrations import _org_for_output_dir, _session_on_this_loop
    org_id = await _org_for_output_dir(output_dir)
    if org_id is None:
        return []
    async with _session_on_this_loop() as db:
        return await load(org_id, db)


async def close_all(providers: list[Any]) -> None:
    for p in providers:
        try:
            await p.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["ACCOUNTS", "close_all", "connected_labels", "load", "load_for_output_dir", "providers_from"]
