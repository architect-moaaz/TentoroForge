"""Where a generated app's database lives when the platform runs in a container.

On a developer's machine each app boots its own Postgres with Docker
(`start.sh --seed-only`). On forge-v3 the backend runs in a container with no
Docker, so "Verify & fix" stopped at "Docker is not available for the app's
database" and the Preview tab started apps with no database at all
(2026-10-01). There, `FORGE_APPS_DATABASE_URL` names a Postgres server kept for
apps (`postgresql://user:password@apps-db:5432`, no database name): each app
gets its own database on it, created over the network, its schema pushed and
its rows seeded; a review works on a copy made with `CREATE DATABASE … TEMPLATE`,
which needs neither Docker nor pg_dump.

Unset, nothing here applies and every caller keeps its Docker path.
"""

from __future__ import annotations

from services.proc_compat import tool
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SERVER_ENV = "FORGE_APPS_DATABASE_URL"
_NAME = re.compile(r"[^a-z0-9_]")


def server() -> str:
    """The apps' Postgres server URL, without a database name; "" when unset."""
    return os.environ.get(SERVER_ENV, "").strip().rstrip("/")


def name_for(app_root: str | Path) -> str:
    """`app_<project>`: the project's directory names the app (`…/<id>/app`)."""
    root = Path(app_root)
    project = root.parent.name if root.name == "app" else root.name
    return ("app_" + _NAME.sub("_", project.lower()))[:60]


def url_for(name: str) -> str:
    return f"{server()}/{name}"


def _connect(database: str = "postgres") -> Any:
    import psycopg2
    con = psycopg2.connect(url_for(database), connect_timeout=10)
    con.autocommit = True
    return con


def _exists(cur: Any, name: str) -> bool:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    return cur.fetchone() is not None


def _write_url(app_root: Path, url: str) -> None:
    """The app reads its database from `.env.local`, then `.env` — both say
    this one. Replaced, not kept: the address the scaffold wrote
    (`localhost:5432`) is nothing inside the platform's container."""
    for env in (".env.local", ".env"):
        path = app_root / env
        if not path.exists() and env == ".env":
            continue
        lines = path.read_text("utf-8").splitlines() if path.exists() else []
        out, done = [], False
        for line in lines:
            if line.split("=", 1)[0].strip() == "DATABASE_URL":
                if not done:
                    out.append(f"DATABASE_URL={url}")
                    done = True
                continue
            out.append(line)
        if not done:
            out.append(f"DATABASE_URL={url}")
        path.write_text("\n".join(out) + "\n", "utf-8")


def ensure(app_root: str | Path) -> dict | None:
    """The app's database on the apps server: created if missing, the app
    pointed at it, its schema pushed and seeded when it was new. None when no
    server is configured. `{"url", "name", "created", "pushed", "reason"}`."""
    if not server():
        return None
    root = Path(app_root)
    name = name_for(root)
    con = _connect()
    try:
        with con.cursor() as cur:
            created = not _exists(cur, name)
            if created:
                cur.execute(f'CREATE DATABASE "{name}"')
    finally:
        con.close()
    url = url_for(name)
    _write_url(root, url)
    pushed, reason = False, ""
    if created or not _has_tables(name):
        from services.blueprint.schema_push import push_now
        _extensions(root, url)
        out = push_now(root)
        pushed, reason = bool(out.get("applied")), str(out.get("reason") or "")
        if not pushed:
            logger.warning("[apps-db] %s: schema not pushed: %s", name, reason)
    return {"url": url, "name": name, "created": created, "pushed": pushed, "reason": reason}


def _has_tables(name: str) -> bool:
    con = _connect(name)
    try:
        with con.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            return int(cur.fetchone()[0]) > 0
    finally:
        con.close()


def _extensions(root: Path, url: str) -> None:
    """pgvector before the push: an embedding column cannot be created without it."""
    script = root / "src/db/extensions.ts"
    if not script.is_file():
        return
    import subprocess
    subprocess.run([tool("npx"), "tsx", "src/db/extensions.ts"], cwd=str(root), stdin=subprocess.DEVNULL,
                   env={**os.environ, "DATABASE_URL": url}, capture_output=True, timeout=180)


def clone(app_root: str | Path) -> tuple[str, str]:
    """A copy of the app's database for a review to click through: `(name, url)`.
    The copy is made from the database as a template, which Postgres allows
    only while nobody is connected to it — the app's own preview server, if one
    is running, is disconnected for the moment it takes (its pool reconnects)."""
    import psycopg2
    source = name_for(app_root)
    copy = f"{source}_review_{uuid.uuid4().hex[:6]}"
    con = _connect()
    try:
        with con.cursor() as cur:
            for attempt in (1, 2):
                try:
                    cur.execute(f'CREATE DATABASE "{copy}" TEMPLATE "{source}"')
                    break
                except psycopg2.errors.ObjectInUse:
                    if attempt == 2:
                        raise
                    cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                                "WHERE datname = %s AND pid <> pg_backend_pid()", (source,))
    finally:
        con.close()
    return copy, url_for(copy)


def drop(name: str) -> None:
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        con.close()


def query(name: str, sql: str) -> list[list[str]]:
    """Rows of `sql` on one database, every value as text (as `psql -tA` gave)."""
    con = _connect(name)
    try:
        with con.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:          # a statement that returns no rows
                return []
            return [["" if v is None else str(v) for v in row] for row in (cur.fetchall() or [])]
    finally:
        con.close()


__all__ = ["SERVER_ENV", "server", "name_for", "url_for", "ensure", "clone", "drop", "query"]
