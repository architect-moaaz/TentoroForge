"""Write org's platform integrations into a generated app's .env.local.

Called by:
  - the generation pipeline once, right after runtime_injector has laid
    down the initial file skeleton;
  - the manual "sync integrations" endpoint on the project page.

Behaviour:
  * Existing user-supplied lines are preserved (DATABASE_URL,
    NEXTAUTH_SECRET, FORGE_URL, …) — this pass only touches keys the
    spec registry knows about.
  * When a platform integration row is CLEARED (row present but ct=null),
    the corresponding .env line is removed. Distinguishes intentional
    clear from "never set" (row absent → line left alone if present).
  * Idempotent — repeated sync calls converge.

Never raises unless the file itself can't be written; individual decrypt
failures are logged and skipped (that key gets left as-is in .env).

Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.platform_integration import PlatformIntegration
from models.platform_mcp_server import PlatformMcpServer
from services.node_config_specs import all_providers, keys_for_provider
from services.platform_integrations_crypto import CryptoError, decrypt


log = logging.getLogger(__name__)

_MANAGED_MARKER = "# --- managed by Forge platform (integrations) --- do not edit below by hand"

# All MCP-related env vars follow this prefix, so `_key_is_managed`
# below can identify them without a static registry entry per server
# (server rows are dynamic; the registry only lists providers, not
# concrete keys).
_MCP_ENV_PREFIX = "MCP_SERVER_"


def _mcp_id_slug(server_id) -> str:
    """Stable env-var-safe slug for a server row id. UUID hex, first 12
    chars, uppercased — long enough that org-scoped collisions are
    effectively impossible while staying short in .env output."""
    import uuid as _uuid
    if isinstance(server_id, _uuid.UUID):
        return server_id.hex[:12].upper()
    return str(server_id).replace("-", "")[:12].upper()


def _known_keys() -> set[str]:
    """Every env-var name the spec registry declares. Only these are touched
    by the writer; user-supplied keys (DATABASE_URL etc.) are left alone."""
    return {
        entry.key
        for provider in all_providers()
        for entry in keys_for_provider(provider)
    }


async def write_env_local_from_platform(
    output_dir: str | Path,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """Read the org's platform_integrations + platform_mcp_servers rows,
    decrypt each set value, and reconcile them with `<output_dir>/.env.local`.

    Result shape:
        {
          "written":  bool,   — the file was rewritten this call
          "set":      [key, key, …],   — keys that landed with a value
          "cleared":  [key, key, …],   — keys removed because platform cleared
          "skipped":  [{key, reason}], — decrypt failed or key unknown
          "mcp_servers": int,          — count of enabled MCP servers written
        }
    """
    root = Path(output_dir)
    env_path = root / ".env.local"
    known = _known_keys()

    res = await db.execute(
        select(PlatformIntegration).where(PlatformIntegration.org_id == org_id)
    )
    rows = res.scalars().all()

    # Materialise final desired value per known key. Unset = not in map.
    desired: dict[str, str] = {}
    cleared: list[str] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        if row.key not in known:
            skipped.append({"key": row.key, "reason": "not_in_registry"})
            continue
        if not row.value_ct or not row.value_iv:
            # Explicitly cleared.
            cleared.append(row.key)
            continue
        try:
            desired[row.key] = decrypt(row.provider, row.value_ct, row.value_iv)
        except CryptoError as e:
            skipped.append({"key": row.key, "reason": f"decrypt_failed: {e}"})
            log.warning("[env_writer] decrypt failed for %s: %s", row.key, e)

    # --- MCP servers ------------------------------------------------- #
    # Dynamic per-server env vars: one row → up to five env vars
    # (URL, TRANSPORT, AUTH_KIND, SECRET, AUTH_HEADER). Only enabled
    # rows are emitted; disabled rows drop out (their env vars will be
    # stripped by the managed-block rewrite below).
    mcp_res = await db.execute(
        select(PlatformMcpServer).where(
            PlatformMcpServer.org_id == org_id,
            PlatformMcpServer.enabled.is_(True),
        )
    )
    mcp_rows = mcp_res.scalars().all()
    mcp_count = 0
    for srv in mcp_rows:
        slug = _mcp_id_slug(srv.id)
        prefix = f"{_MCP_ENV_PREFIX}{slug}_"
        desired[f"{prefix}URL"] = srv.server_url
        desired[f"{prefix}TRANSPORT"] = srv.transport
        desired[f"{prefix}AUTH_KIND"] = srv.auth_kind
        # NAME lets workflow mcp_tool_call resolve by name instead of slug.
        desired[f"{prefix}NAME"] = srv.name
        if srv.auth_kind != "none" and srv.auth_secret_ct and srv.auth_secret_iv:
            try:
                desired[f"{prefix}SECRET"] = decrypt(
                    "mcp", srv.auth_secret_ct, srv.auth_secret_iv,
                )
            except CryptoError as e:
                skipped.append({
                    "key": f"{prefix}SECRET",
                    "reason": f"decrypt_failed: {e}",
                })
                log.warning("[env_writer] mcp decrypt failed for %s: %s", srv.id, e)
        if srv.auth_kind == "apikey_header" and srv.auth_header_name:
            desired[f"{prefix}AUTH_HEADER"] = srv.auth_header_name
        mcp_count += 1

    # Read existing .env.local, filter out managed keys, keep everything else.
    existing_lines: list[str] = []
    if env_path.is_file():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    key_re = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")
    kept: list[str] = []
    for line in existing_lines:
        if line.strip() == _MANAGED_MARKER:
            # Everything from the marker onwards is the previous managed
            # block — drop it; we're about to rewrite.
            break
        m = key_re.match(line)
        if m and (m.group(1) in known or m.group(1).startswith(_MCP_ENV_PREFIX)):
            # Managed key found ABOVE the marker (or marker absent). Drop —
            # the writer will re-append (or omit if cleared / server removed).
            continue
        kept.append(line)

    # Trim trailing blank lines from the kept prefix.
    while kept and not kept[-1].strip():
        kept.pop()

    # Build the managed block.
    managed: list[str] = []
    if desired:
        managed.append("")
        managed.append(_MANAGED_MARKER)
        for k in sorted(desired.keys()):
            managed.append(f"{k}={desired[k]}")

    new_content = "\n".join(kept + managed).rstrip() + "\n"
    old_content = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    if new_content == old_content:
        return {
            "written": False,
            "set": sorted(desired.keys()),
            "cleared": cleared,
            "skipped": skipped,
            "mcp_servers": mcp_count,
        }

    env_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(env_path)

    return {
        "written": True,
        "set": sorted(desired.keys()),
        "cleared": cleared,
        "skipped": skipped,
        "mcp_servers": mcp_count,
    }
