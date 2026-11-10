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
from services.node_config_specs import all_providers, keys_for_provider, platform_only_keys
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


def app_env_dir(output_dir: str | Path) -> Path:
    """Where the app reads its settings. A Blueprint project keeps its app in
    `<project>/app`; the settings written beside it at the project root were
    read by nothing (SnapIT, 2026-09-28: the Firecrawl server landed in
    `ho6irnp6/.env.local`, the app read `ho6irnp6/app/.env.local`)."""
    root = Path(output_dir)
    return root / "app" if (root / "app" / "package.json").is_file() else root


def mcp_env(rows: list, skipped: list[dict[str, str]] | None = None) -> dict[str, str]:
    """The env vars that let an app call each enabled MCP server — up to five
    per server (URL, TRANSPORT, AUTH_KIND, NAME, SECRET, AUTH_HEADER). Used for
    `.env.local` and for a publish, so a published app calls the same servers."""
    out: dict[str, str] = {}
    for srv in rows:
        if getattr(srv, "enabled", True) is False:
            continue
        slug = _mcp_id_slug(srv.id)
        prefix = f"{_MCP_ENV_PREFIX}{slug}_"
        out[f"{prefix}URL"] = srv.server_url
        out[f"{prefix}TRANSPORT"] = srv.transport
        out[f"{prefix}AUTH_KIND"] = srv.auth_kind
        # NAME lets workflow mcp_tool_call resolve by name instead of slug.
        out[f"{prefix}NAME"] = srv.name
        if srv.auth_kind != "none" and srv.auth_secret_ct and srv.auth_secret_iv:
            try:
                out[f"{prefix}SECRET"] = decrypt("mcp", srv.auth_secret_ct, srv.auth_secret_iv)
            except CryptoError as e:
                if skipped is not None:
                    skipped.append({"key": f"{prefix}SECRET", "reason": f"decrypt_failed: {e}"})
                log.warning("[env_writer] mcp decrypt failed for %s: %s", srv.id, e)
        if srv.auth_kind == "apikey_header" and srv.auth_header_name:
            out[f"{prefix}AUTH_HEADER"] = srv.auth_header_name
    return out


#: Keys an application makes for itself and keeps for its life: the sealing
#: key of its sensitive fields and its Web Push pair. Known to the registry (an
#: org may set its own), but never the platform's to remove.
APP_OWNED: frozenset[str] = frozenset({
    "SENSITIVE_ENCRYPTION_KEY", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT",
})


def _known_keys() -> set[str]:
    """Every env-var name the spec registry declares. Only these are touched
    by the writer; user-supplied keys (DATABASE_URL etc.) are left alone.
    A platform-only key is known — so an old managed block's copy is stripped —
    but never written (see `ConfigKey.platform_only`)."""
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
    root = app_env_dir(output_dir)
    env_path = root / ".env.local"
    # THE REGISTRY'S NAMES AND THE APPLICATION'S OWN: a secret an integration
    # declares (`secretRefs`) is written for the app that declares it.
    from services.declared_secrets import declared_keys_for_output_dir
    known = _known_keys() | {e.key for e in declared_keys_for_output_dir(output_dir)}
    platform_only = platform_only_keys()

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
        if row.key in platform_only:
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
    desired.update(mcp_env(mcp_rows, skipped))
    mcp_count = len(mcp_rows)
    # THE APP'S OWN SWITCHES (`app_settings`): whether assistants may connect
    # to it. Managed here too, or this rewrite would drop the line the switch
    # wrote whenever it sat below the marker.
    from services import app_settings
    switches = app_settings.env_for(output_dir)
    desired.update(switches)
    # THE APP'S PAYMENT GATEWAYS, as its owner chose them (Settings → Integrations → Payments):
    # their TEST keys only — a preview never carries a live key — and every
    # payment variable the app should not carry removed (None).
    payment_names: set[str] = set()
    try:
        from services.payments.webhooks import payment_env
        pay = await payment_env(output_dir, org_id, db, side="local")
    except Exception as exc:  # noqa: BLE001 — the rest of the environment is still written
        log.warning("[env_writer] payment keys unavailable: %s", exc)
        pay = None
        # FAILING CLOSED for an app whose payments are Settings → Integrations → Payments':
        # every payment variable is removed rather than left as it was (an old
        # live key from Integrations would have stayed in the preview).
        try:
            from services.payments import app_payments as _AP
            from services.payments.webhooks import governs, load_doc
            if governs(load_doc(output_dir)):
                pay = {name: None for name in _AP.ALL_ENV}
        except Exception:  # noqa: BLE001
            pass
    if pay is not None:
        payment_names = set(pay)
        for k, v in pay.items():
            if v is None:
                desired.pop(k, None)
            else:
                desired[k] = v

    # Read existing .env.local, filter out managed keys, keep everything else.
    existing_lines: list[str] = []
    if env_path.is_file():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    key_re = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")
    kept: list[str] = []
    below = False
    for line in existing_lines:
        if line.strip() == _MANAGED_MARKER:
            # Everything from the marker onwards is the previous managed
            # block — rewritten below. All but a line that is not ours: the
            # app's `start.sh` appends DATABASE_URL to the end of the file,
            # and dropping it with the block left `next dev` on whatever
            # `.env` said (or on nothing).
            below = True
            continue
        m = key_re.match(line)
        if m and m.group(1) in APP_OWNED and m.group(1) not in desired:
            # THE APP'S OWN KEY, KEPT. Its sealing key and push pair are made
            # once per app (runtime_injector) and must outlive every rewrite:
            # dropping them here, as a known key the org had not set, left 38
            # of 42 apps on forge-v3 unable to seal or open a value and every
            # push subscription orphaned (2026-11-03). An org value set on the
            # platform still replaces it, from the managed block.
            kept.append(line)
            continue
        managed_key = bool(m) and (m.group(1) in known or m.group(1).startswith(_MCP_ENV_PREFIX) or m.group(1) in switches
                                   or m.group(1) in payment_names or m.group(1) in desired)
        if managed_key or (below and not m):
            # A managed key (above or below the marker), or the old block's
            # own comments and blanks. Dropped — the writer re-appends (or
            # omits if cleared / server removed).
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
