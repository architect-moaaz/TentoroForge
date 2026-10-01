"""Dev server manager for live previews of generated Next.js projects.

Includes health checks, auto-restart with exponential backoff, and crash recovery.
"""

import asyncio
import logging
import os
import signal
import random
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Port range reserved for preview servers (separate from screenshot range 3100-3199)
_PORT_MIN = 3200
_PORT_MAX = 3299

# Max auto-restart attempts before giving up
_MAX_RESTART_ATTEMPTS = 3

# Health check interval in seconds
_HEALTH_CHECK_INTERVAL = 30

# {project_id: {"proc": asyncio.subprocess.Process, "port": int,
#                "output_dir": str, "restart_count": int}}
_previews: dict[str, dict] = {}

# Background health-check tasks keyed by project_id
_health_tasks: dict[str, asyncio.Task] = {}


async def _stop_strays(output_dir: str) -> None:
    """A `next dev` left running in this app from before the platform
    restarted. The registry of previews is in memory, so a restart forgot it
    and the next start spawned a second server in the same folder; the two
    shared `.next` and pages came back with unprefixed asset URLs, stuck on
    "Loading…" (Test4, 2026-09-28)."""
    binary = str(Path(output_dir).resolve() / "node_modules" / ".bin" / "next")
    try:
        proc = await asyncio.create_subprocess_exec(
            "pkill", "-f", f"{binary} dev",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await proc.wait() == 0:
            logger.info("[preview] stopped a stray dev server in %s", output_dir)
            await asyncio.sleep(1)
    except OSError:
        pass


_BARE_PROVIDER = "<SessionProvider>"
_PREFIXED_PROVIDER = '<SessionProvider basePath={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/auth`}>'


def _session_under_prefix(output_dir: str) -> None:
    """An app scaffolded before the template carried the base path gets it:
    `providers.tsx` is the platform's file, not the app's content."""
    p = Path(output_dir) / "src" / "app" / "providers.tsx"
    try:
        text = p.read_text("utf-8")
        if _BARE_PROVIDER in text:
            p.write_text(text.replace(_BARE_PROVIDER, _PREFIXED_PROVIDER), "utf-8")
    except OSError:
        pass


async def _ensure_database(output_dir: str) -> None:
    """The app's own database, up, migrated and seeded, before its preview.

    `next dev` alone read a DATABASE_URL nothing was listening on: a fresh
    build's preview showed empty dropdowns and saved nothing (Test4,
    2026-09-28). The app's `start.sh --seed-only` is the one way it boots
    its database (Docker Postgres on a free port, drizzle push, seed) and
    rewrites .env.local to match; it runs here when the database does not
    answer. A preview without Docker still starts, and says why it has no data.
    """
    from services import app_databases
    from services.blueprint.schema_push import database_exists, database_url

    if app_databases.server():
        # No Docker in the platform's container: the apps server holds it.
        try:
            await asyncio.to_thread(app_databases.ensure, output_dir)
        except Exception as exc:  # noqa: BLE001 — a preview still starts, and the log says why
            logger.warning("[preview] %s: apps database not ready: %s", output_dir, exc)
        return
    script = Path(output_dir) / "start.sh"
    if not script.is_file() or database_exists(database_url(output_dir)):
        return
    log = Path(output_dir) / ".forge-preview-db.log"
    try:
        with open(log, "w") as out:
            proc = await asyncio.create_subprocess_exec(
                "bash", "start.sh", "--seed-only", cwd=output_dir,
                stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=out)
            code = await asyncio.wait_for(proc.wait(), timeout=300)
        if code != 0:
            logger.warning("[preview] %s: database did not come up (exit %s); see %s", output_dir, code, log)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("[preview] %s: database did not come up: %s", output_dir, exc)


async def start_preview(project_id: str, output_dir: str) -> int:
    """Spawn `npx next dev` for a project, poll until ready, return port.

    If a preview is already running for this project, returns the existing port.
    """
    # Already running?
    if project_id in _previews:
        existing = _previews[project_id]
        if existing["proc"].returncode is None:
            return existing["port"]
        # Process died -- clean up and restart
        del _previews[project_id]

    # Pick a random free port in range
    used_ports = {v["port"] for v in _previews.values()}
    available = [p for p in range(_PORT_MIN, _PORT_MAX + 1) if p not in used_ports]
    if not available:
        raise RuntimeError("No available preview ports")
    port = random.choice(available)

    # Ensure node_modules exist
    node_modules = Path(output_dir) / "node_modules"
    if not node_modules.exists():
        install = await asyncio.create_subprocess_exec(
            "npm", "install",
            cwd=output_dir,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await install.wait()

    await _ensure_database(output_dir)
    await _stop_strays(output_dir)

    # basePath so Next generates page + asset URLs under the platform
    # proxy path. Reads next.config.ts (env-gated PREVIEW_BASE_PATH).
    # The proxy at /api/projects/<id>/preview/serve/... forwards to
    # this dev server, so the generated app must know the prefix or
    # its <Link>/asset hrefs point at the wrong origin from the iframe.
    prefix = f"/api/projects/{project_id}/preview/serve"
    env = {
        **os.environ,
        "NEXT_BASE_PATH": prefix,
        "NEXT_ASSET_PREFIX": prefix,
        # SIGN-IN UNDER THE PREFIX. next-auth's client posts to /api/auth at
        # the origin's root unless told the base path; behind the proxy that
        # reached the platform, and every preview sign-in ended on
        # /api/auth/error (Test4, 2026-09-28). Inlined by next dev.
        "NEXT_PUBLIC_BASE_PATH": prefix,
    }
    _session_under_prefix(output_dir)

    # Start the dev server
    proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(port),
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        # Use process group so we can kill the whole tree
        preexec_fn=os.setsid,
    )

    _previews[project_id] = {
        "proc": proc,
        "port": port,
        "output_dir": output_dir,
        "restart_count": 0,
    }

    # Poll until the server is ready (max 30s)
    url = f"http://localhost:{port}"
    async with httpx.AsyncClient(timeout=5) as client:
        for _ in range(60):
            await asyncio.sleep(0.5)
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    # Start background health check
                    _start_health_check(project_id)
                    return port
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                continue

    # Server didn't start in time -- clean up
    stop_preview(project_id)
    raise RuntimeError(f"Preview server failed to start on port {port}")


def stop_preview(project_id: str) -> bool:
    """Kill the dev server for a project. Returns True if it was running."""
    # Cancel health check task
    task = _health_tasks.pop(project_id, None)
    if task and not task.done():
        task.cancel()

    entry = _previews.pop(project_id, None)
    if not entry:
        return False

    proc = entry["proc"]
    if proc.returncode is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
    return True


def stop_all_previews() -> None:
    """Stop every running preview server (call on shutdown)."""
    for pid in list(_previews.keys()):
        stop_preview(pid)


def get_preview_port(project_id: str) -> int | None:
    """Return the port for a running preview, or None."""
    entry = _previews.get(project_id)
    if entry and entry["proc"].returncode is None:
        return entry["port"]
    return None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def health_check(project_id: str) -> dict:
    """Perform a health check on a running preview server.

    Returns dict with:
      - healthy: bool
      - port: int | None
      - restart_count: int
      - status: str ("running", "crashed", "not_found", "unhealthy")
    """
    entry = _previews.get(project_id)
    if not entry:
        return {
            "healthy": False,
            "port": None,
            "restart_count": 0,
            "status": "not_found",
        }

    proc = entry.get("proc")
    port = entry["port"]
    restart_count = entry.get("restart_count", 0)

    # Check if process is alive
    if proc is None or proc.returncode is not None:
        return {
            "healthy": False,
            "port": port,
            "restart_count": restart_count,
            "status": "crashed",
        }

    # Check if server responds
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://localhost:{port}")
            if resp.status_code < 500:
                return {
                    "healthy": True,
                    "port": port,
                    "restart_count": restart_count,
                    "status": "running",
                }
    except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
        pass

    return {
        "healthy": False,
        "port": port,
        "restart_count": restart_count,
        "status": "unhealthy",
    }


# ---------------------------------------------------------------------------
# Auto-restart with exponential backoff
# ---------------------------------------------------------------------------

async def _restart_preview(project_id: str) -> bool:
    """Restart a crashed preview server with exponential backoff.

    Returns True if restart succeeded.
    """
    entry = _previews.get(project_id)
    if not entry:
        return False

    restart_count = entry.get("restart_count", 0)
    if restart_count >= _MAX_RESTART_ATTEMPTS:
        logger.warning(
            "Preview %s exceeded max restart attempts (%d), giving up",
            project_id,
            _MAX_RESTART_ATTEMPTS,
        )
        return False

    # Exponential backoff: 2^restart_count seconds (1, 2, 4)
    backoff = 2 ** restart_count
    logger.info(
        "Restarting preview %s (attempt %d/%d) after %ds backoff",
        project_id,
        restart_count + 1,
        _MAX_RESTART_ATTEMPTS,
        backoff,
    )
    await asyncio.sleep(backoff)

    port = entry["port"]
    output_dir = entry.get("output_dir", "")

    if not output_dir or not Path(output_dir).exists():
        logger.error("Preview %s output_dir missing, cannot restart", project_id)
        return False

    # Kill old process if still lingering
    proc = entry.get("proc")
    if proc and proc.returncode is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    # Start new Next.js dev server on same port
    new_proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(port),
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )

    entry["proc"] = new_proc
    entry["restart_count"] = restart_count + 1

    # Poll until ready
    url = f"http://localhost:{port}"
    async with httpx.AsyncClient(timeout=5) as client:
        for _ in range(60):
            await asyncio.sleep(0.5)
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    logger.info("Preview %s restarted successfully on port %d", project_id, port)
                    return True
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                continue

    logger.error("Preview %s failed to restart on port %d", project_id, port)
    return False


def _start_health_check(project_id: str) -> None:
    """Start a background health check task for a preview server."""
    existing = _health_tasks.get(project_id)
    if existing and not existing.done():
        existing.cancel()

    task = asyncio.create_task(_health_check_loop(project_id))
    _health_tasks[project_id] = task


async def _health_check_loop(project_id: str) -> None:
    """Background loop that periodically checks preview health and auto-restarts on crash."""
    try:
        while project_id in _previews:
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

            if project_id not in _previews:
                break

            status = await health_check(project_id)

            if status["status"] in ("crashed", "unhealthy"):
                logger.warning(
                    "Preview %s is %s, attempting auto-restart",
                    project_id,
                    status["status"],
                )
                success = await _restart_preview(project_id)
                if not success:
                    logger.error(
                        "Auto-restart failed for preview %s, stopping health checks",
                        project_id,
                    )
                    break
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Health check loop error for %s", project_id)
