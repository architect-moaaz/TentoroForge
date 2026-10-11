"""The secret NAMES an application declares are settable, and shipped.

An integration's `secretRefs` are names the platform must be able to hold a
value for. The settings page and the env writers used to accept only the
registry's keys (`node_config_specs`), so a name an agent wrote for a
system with no adapter — `XERO_API_KEY` — could never be set, written
locally or carried to a deployment (2026-10-12). Each declared name is a
`ConfigKey` under the synthetic provider `app:<integration slug>`, read
from the application's own Blueprint; the value never leaves the platform
store, as for every other key.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.node_config_specs import ConfigKey

logger = logging.getLogger(__name__)

APP_PROVIDER = "app:"


def declared_keys(doc: dict) -> list[ConfigKey]:
    """One key per declared secret name, in document order."""
    from services.blueprint.projection import declared_services
    out: list[ConfigKey] = []
    seen: set[tuple[str, str]] = set()
    for svc in declared_services(doc):
        provider = f"{APP_PROVIDER}{svc['slug']}"
        for name in svc["keys"]:
            if (provider, name) in seen or not name:
                continue
            seen.add((provider, name))
            out.append(ConfigKey(key=name, provider=provider, label=f"{svc['name'] or svc['slug']} — {name}",
                                 kind="password", required=False))
    return out


def declared_keys_for_output_dir(output_dir: str | Path | None) -> list[ConfigKey]:
    """The application's declared names, from its Blueprint on disk."""
    if not output_dir:
        return []
    path = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    if not path.exists():
        return []
    try:
        return declared_keys(json.loads(path.read_text("utf-8")))
    except Exception:  # noqa: BLE001 — an unreadable document declares nothing
        logger.warning("[declared-secrets] could not read %s", path, exc_info=True)
        return []


async def declared_keys_for_org(db: Any, org_id: Any) -> list[ConfigKey]:
    """Every name declared by any of the org's applications."""
    from sqlalchemy import select

    from models.project import Project
    res = await db.execute(select(Project).where(Project.org_id == org_id))
    out: list[ConfigKey] = []
    seen: set[tuple[str, str]] = set()
    for project in res.scalars().all():
        for key in declared_keys_for_output_dir(getattr(project, "output_dir", None)):
            if (key.provider, key.key) in seen:
                continue
            seen.add((key.provider, key.key))
            out.append(key)
    return out


def is_declared(provider: str, key: str, declared: list[ConfigKey]) -> bool:
    return str(provider).startswith(APP_PROVIDER) and any(e.provider == provider and e.key == key for e in declared)


__all__ = ["APP_PROVIDER", "declared_keys", "declared_keys_for_org", "declared_keys_for_output_dir", "is_declared"]
