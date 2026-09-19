"""The data model proven in a real database, while it is still cheap to fix.

Nothing in a build touched a database: `assemble` compiled the app and started
it, and "a database is not required to run it". So a data model the database
refuses — and demo rows it refuses — reached the person running the app as a
wall of PostgresErrors and an app nobody could sign in to (0l133sp2).

Here the Blueprint's own projection is pushed into a throwaway database on a
shared, platform-owned Postgres (pgvector, like the apps), and — at the build,
where the whole app is on disk — seeded. Each error the database raises becomes
a Finding against the entity whose table or column it names, which the
observer (after `entity_fields`) and the build's repair round send back to the
data-model agent with the database's own words.

Docker unavailable, or the app's tools not installed yet: the gate says it was
skipped and why. It never fails a build by being unable to look.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

GATE_CONTAINER = "forge-gate-postgres"
GATE_IMAGE = "pgvector/pgvector:pg16"
#: The extensions the apps' own start script switches on (src/db/extensions.ts).
EXTENSIONS = ("vector",)
EDGE = "Data↔Database"

_GATE_CONFIG = """import { defineConfig } from "drizzle-kit";
// Written by the data gate (services/blueprint/data_gate.py) — not the app's.
export default defineConfig({
  schema: "./src/db/schema",
  dialect: "postgresql",
  dbCredentials: { url: process.env.DATABASE_URL! },
  tablesFilter: ["!_forge_seed_meta"],
});
"""


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _psql(sql: str, db: str = "postgres") -> subprocess.CompletedProcess:
    return _docker("exec", GATE_CONTAINER, "psql", "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1",
                   "-tAc", sql)


def gate_server() -> tuple[str | None, str]:
    """``(base url, "")`` for the gate's Postgres, starting it if need be, or
    ``(None, why)`` when there is none to be had."""
    if shutil.which("docker") is None:
        return None, "docker is not installed"
    try:
        state = _docker("inspect", "-f", "{{.State.Running}}", GATE_CONTAINER)
        if state.returncode != 0:
            run = _docker("run", "-d", "--name", GATE_CONTAINER, "-e", "POSTGRES_PASSWORD=postgres",
                          "-p", "127.0.0.1::5432", GATE_IMAGE, timeout=180)
            if run.returncode != 0:
                return None, f"could not start {GATE_IMAGE}: {run.stderr.strip()[:200]}"
        elif state.stdout.strip() != "true":
            start = _docker("start", GATE_CONTAINER)
            if start.returncode != 0:
                return None, f"could not start {GATE_CONTAINER}: {start.stderr.strip()[:200]}"
        # A first start runs initdb and restarts the server once; ready means a
        # query answers twice, a second apart, not that the socket opened.
        answered = 0
        for _ in range(90):
            answered = answered + 1 if _psql("SELECT 1").returncode == 0 else 0
            if answered >= 2:
                break
            time.sleep(1)
        else:
            return None, "the gate database did not become ready"
        port = _docker("port", GATE_CONTAINER, "5432").stdout.strip().splitlines()
        if not port:
            return None, "the gate database has no published port"
        host_port = port[0].rsplit(":", 1)[-1]
        return f"postgresql://postgres:postgres@127.0.0.1:{host_port}", ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"docker did not answer: {exc}"


@contextmanager
def throwaway_database() -> Iterator[tuple[str | None, str]]:
    """A fresh, empty database for one look; dropped afterwards."""
    base, why = gate_server()
    if base is None:
        yield None, why
        return
    name = f"gate_{uuid.uuid4().hex[:12]}"
    made = _psql(f'CREATE DATABASE "{name}"')
    if made.returncode != 0:
        yield None, f"could not create a throwaway database: {made.stderr.strip()[:200]}"
        return
    try:
        for ext in EXTENSIONS:
            _psql(f'CREATE EXTENSION IF NOT EXISTS "{ext}"', db=name)
        yield f"{base}/{name}", ""
    finally:
        _psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _failed_push(rc: int, text: str) -> bool:
    return rc != 0 or bool(re.search(r"PostgresError|DrizzleError|^Error:|error: |created or renamed", text, re.M))


def _error_lines(text: str) -> str:
    keep = [l.strip() for l in text.splitlines()
            if re.search(r"error|refused|does not exist|violates|invalid|created or renamed|SEED MISMATCH|↳", l, re.I)
            and not l.strip().startswith("at ")]
    return "\n".join(dict.fromkeys(keep))[:1500] or text.strip()[-1500:]


def run(app_root: str | Path, *, seed: bool, timeout: int = 300) -> dict[str, Any]:
    """Push the app's schema (and, with ``seed``, its demo rows) into a
    throwaway database. ``{"ok", "skipped", "push": {...}, "seed": {...}}``."""
    import os

    root = Path(app_root)
    if not (root / "node_modules" / ".bin" / "drizzle-kit").exists():
        return {"ok": True, "skipped": "the app's tools are not installed yet"}
    if not (root / "src" / "db" / "schema").is_dir():
        return {"ok": True, "skipped": "no schema projected yet"}
    config = root / ".forge-gate.drizzle.config.ts"
    config.write_text(_GATE_CONFIG, "utf-8")
    try:
        with throwaway_database() as (url, why):
            if url is None:
                return {"ok": True, "skipped": why}
            env = {**os.environ, "DATABASE_URL": url, "FORCE_SEED": "1"}
            push = subprocess.run(["npx", "drizzle-kit", "push", "--force", f"--config={config.name}"],
                                  cwd=root, capture_output=True, text=True, timeout=timeout, env=env,
                                  stdin=subprocess.DEVNULL)
            text = (push.stdout or "") + (push.stderr or "")
            out: dict[str, Any] = {"push": {"ok": not _failed_push(push.returncode, text),
                                            "error": _error_lines(text) if _failed_push(push.returncode, text) else ""}}
            if not out["push"]["ok"] or not seed or not (root / "src" / "db" / "seed.ts").exists():
                out["ok"] = out["push"]["ok"]
                return out
            run_seed = subprocess.run(["npx", "tsx", "src/db/seed.ts"], cwd=root, capture_output=True,
                                      text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
            stext = (run_seed.stdout or "") + (run_seed.stderr or "")
            failed = []
            lines = stext.splitlines()
            for i, line in enumerate(lines):
                m = re.search(r"SEED MISMATCH: (\w+)", line)
                if m:
                    reason = next((l.split("first row error:", 1)[-1].strip() for l in lines[i + 1:i + 3]
                                   if "first row error:" in l), "")
                    failed.append({"table": m.group(1), "error": reason})
            out["seed"] = {"ok": not failed and run_seed.returncode == 0, "failed": failed,
                           "error": "" if run_seed.returncode == 0 else _error_lines(stext)}
            out["ok"] = out["push"]["ok"] and out["seed"]["ok"]
            return out
    except subprocess.TimeoutExpired as exc:
        return {"ok": True, "skipped": f"the gate timed out: {exc}"}
    finally:
        config.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# What the database said, as findings against the entity it concerns
# ---------------------------------------------------------------------------

def _entities(doc: dict) -> list[dict]:
    return [e for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("status") != "DEPRECATED"]


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(name or "")).lower()


def _named(doc: dict, text: str, app_root: str | Path | None = None) -> list[dict]:
    """The entities the error is about: whose table or column it names, else
    whose generated table file holds a value it quotes (`"many"` from
    `invalid input syntax for type integer: "many"` names no table at all)."""
    low = text.lower()
    hits = []
    for e in _entities(doc):
        table = str(e.get("table") or "").lower()
        cols = {_snake(f.get("name")) for f in e.get("fields") or [] if isinstance(f, dict)}
        if (table and re.search(rf'\b"?{re.escape(table)}"?\b', low)) or \
                any(c and re.search(rf'"{re.escape(c)}"', low) for c in cols):
            hits.append(e)
    if hits or app_root is None:
        return hits
    from services.blueprint.projection import _module_name

    quoted = {q for q in re.findall(r'"([^"\n]{1,80})"', text) if q.lower() not in ("error",)}
    for e in _entities(doc):
        module = Path(app_root) / "src" / "db" / "schema" / f"{_module_name(e)}.ts"
        try:
            src = module.read_text("utf-8")
        except OSError:
            continue
        if any(q in src for q in quoted):
            hits.append(e)
    return hits


def findings(doc: dict, result: dict, app_root: str | Path | None = None) -> list[Any]:
    """Findings for the data-model agent from one gate run."""
    from services.blueprint.verification import Finding

    out = []
    push = result.get("push") or {}
    if push and not push.get("ok"):
        error = push.get("error") or "the database refused the schema"
        named = _named(doc, error, app_root)
        for e in named or [{}]:
            out.append(Finding(EDGE, section="data.entities", artifact_id=str(e.get("id") or ""),
                               detail=f"the database refused to create "
                                      f"{('the ' + str(e.get('name')) + ' table') if e else 'the tables'}: {error}"))
    seed = result.get("seed") or {}
    by_table = {str(e.get("table")): e for e in _entities(doc)}
    for f in seed.get("failed") or []:
        e = by_table.get(str(f.get("table")))
        out.append(Finding(EDGE, section="data.entities", artifact_id=str((e or {}).get("id") or ""),
                           detail=f"the database refused every demo row of {f.get('table')}: "
                                  f"{f.get('error') or 'no reason given'} — a required field no row "
                                  f"can fill, or a value the column type cannot hold"))
    return out


def early_findings(doc: dict, app_root: str | Path) -> list[Any]:
    """After the data model is written: project its tables and push them.
    No seed yet — the rest of the app is not on disk."""
    from services.blueprint.projection import project_data_layer

    try:
        project_data_layer(doc, app_root)
    except Exception as exc:  # noqa: BLE001 — a projection fault is reported, not raised here
        logger.warning("[data_gate] could not project the data layer: %s", exc)
        return []
    result = run(app_root, seed=False)
    if result.get("skipped"):
        logger.info("[data_gate] skipped: %s", result["skipped"])
        return []
    return findings(doc, result, app_root)


__all__ = ["EDGE", "early_findings", "findings", "gate_server", "run", "throwaway_database"]
