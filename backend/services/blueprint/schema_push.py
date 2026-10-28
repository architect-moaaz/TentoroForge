"""The running application's database, brought up to its schema now.

`drizzle-kit push` ran only when a preview started. A record Smith added to a
built application therefore existed in the code and not in the database:
"the table lands as a migration on the next install" (Test2, 2026-09-28) —
and a screen built for it next had nowhere to save until someone restarted
the preview. When the application's own database answers, the schema is
pushed and the seed run here, the same two commands a preview start runs.

The seed is idempotent (the admin upserts; a table that already has rows is
skipped), so running it after a push only fills what is new. It runs the
publish's own chain — prepare-schema, `drizzle-kit push --force`,
verify-schema — so what Smith changed locally lands the way it will land
when published, and a removal keeps its data in `forge_retired.rows`.
"""
from __future__ import annotations

from services.proc_compat import tool
import logging
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

TIMEOUT_S = 150


def database_url(app_root: str | Path) -> str:
    """The application's own DATABASE_URL, as its env files state it."""
    for name in (".env.local", ".env"):
        try:
            for line in (Path(app_root) / name).read_text("utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "DATABASE_URL" and value.strip():
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _answers(url: str) -> bool:
    try:
        parsed = urlparse(url)
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 5432), timeout=2):
            return True
    except (OSError, ValueError):
        return False


def database_exists(url: str) -> bool:
    """Whether the database itself accepts a connection — not only its port.
    A Postgres on 5432 answered for a database it did not have (Test4,
    2026-09-28)."""
    if not url or not _answers(url):
        return False
    try:
        import psycopg2
        psycopg2.connect(url, connect_timeout=3).close()
        return True
    except Exception:  # noqa: BLE001 — any refusal means it is not there to use
        return False


def push_now(app_root: str | Path) -> dict:
    """``{"applied": bool, "reason": str}`` — pushed and seeded, or why not."""
    root = Path(app_root)
    url = database_url(root)
    if not (root / "drizzle.config.ts").is_file() or not (root / "node_modules").is_dir():
        return {"applied": False, "reason": "the application is not installed yet"}
    if not url or not _answers(url):
        return {"applied": False, "reason": "its database is not running"}
    out = run_chain(root, url)
    if out["applied"]:
        logger.info("[schema_push] %s: schema pushed and seeded", root.parent.name)
    return out


#: What a publish's build runs against its database, after the reset.
PUBLISH_CHAIN = (("npx", "tsx", "src/db/prepare-schema.ts"), ("npx", "drizzle-kit", "push", "--force"),
                 ("npx", "tsx", "src/db/verify-schema.ts"), ("npx", "tsx", "src/db/seed.ts"))


def run_chain(app_root: str | Path, url: str, *, extra_env: dict[str, str] | None = None) -> dict:
    """The publish chain against the database at `url`: ``{"applied", "reason",
    "lines"}`` — `lines` are what the step that refused said, in its words."""
    root = Path(app_root)
    env = {**os.environ, **(extra_env or {}), "DATABASE_URL": url}
    # THE SAME CHAIN AS A PUBLISH. A plain `drizzle-kit push` here answered
    # nothing it asked, exited 0 having changed nothing, and this said
    # "pushed" — for a renamed field, a required one, a changed type, every
    # removal (database tests, 2026-10-01). Now: prepare (renames, required
    # columns filled, types converted, removed data kept), push, then the
    # database itself is asked whether it matches; any step that refuses is
    # the reason, in its own words.
    for cmd in map(list, PUBLISH_CHAIN):
        if cmd[1] == "tsx" and not (root / cmd[2]).is_file():
            continue
        cmd[0] = tool(cmd[0])
        try:
            proc = subprocess.run(cmd, cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("[schema_push] %s: %s", " ".join(cmd), exc)
            # THE CHAIN COULD NOT RUN — a program or folder missing, a step
            # that never ended. Said apart from a refusal: nothing about the
            # data is known from it.
            return {"applied": False, "reason": f"`{' '.join(cmd[1:])}` did not finish ({type(exc).__name__})",
                    "lines": [], "error": True}
        if proc.returncode != 0:
            said = (proc.stderr or proc.stdout or "").strip().splitlines()
            marked = [l for l in said if l.startswith(("[prepare-schema]", "[verify-schema]", "  - "))]
            tail = marked[-6:] if marked else said[-3:]
            logger.warning("[schema_push] %s exited %s: %s", " ".join(cmd), proc.returncode, " | ".join(tail))
            return {"applied": False, "reason": f"`{' '.join(cmd[1:])}` failed: {' '.join(tail)[:300]}",
                    "lines": marked or said[-12:]}
    return {"applied": True, "reason": "", "lines": []}


__all__ = ["PUBLISH_CHAIN", "database_exists", "database_url", "push_now", "run_chain"]
