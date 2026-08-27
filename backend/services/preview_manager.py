"""Enhanced preview manager with Docker PostgreSQL support, health checks, and crash recovery."""

import asyncio
import logging
import os
import signal
import random
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Port ranges for generated project previews
_PREVIEW_PORT_MIN = 3200
_PREVIEW_PORT_MAX = 3299
_DB_PORT_MIN = 5500
_DB_PORT_MAX = 5599

# Max auto-restart attempts before giving up
_MAX_RESTART_ATTEMPTS = 3

# Health check interval in seconds
_HEALTH_CHECK_INTERVAL = 30

# {project_short_id: {"proc": Process, "port": int, "db_port": int | None,
#                      "output_dir": str, "restart_count": int, "with_database": bool}}
_environments: dict[str, dict] = {}

# Background health-check tasks keyed by project_short_id
_health_tasks: dict[str, asyncio.Task] = {}


async def start_project_environment(
    project_short_id: str,
    output_dir: str,
    with_database: bool = True,
) -> dict:
    """Start a project environment: Docker PostgreSQL + Next.js dev server.

    Returns dict with port and db_port.
    """
    # Already running?
    if project_short_id in _environments:
        existing = _environments[project_short_id]
        proc = existing.get("proc")
        if proc and proc.returncode is None:
            return {"port": existing["port"], "db_port": existing.get("db_port")}
        # Process died -- clean up and restart
        await stop_project_environment(project_short_id)

    used_ports = {v["port"] for v in _environments.values()}
    used_db_ports = {v.get("db_port") for v in _environments.values() if v.get("db_port")}

    available_ports = [p for p in range(_PREVIEW_PORT_MIN, _PREVIEW_PORT_MAX + 1) if p not in used_ports]
    if not available_ports:
        raise RuntimeError("No available preview ports")
    port = random.choice(available_ports)

    db_port = None

    # Start Docker PostgreSQL if docker-compose.yml exists and database is needed
    compose_file = Path(output_dir) / "docker-compose.yml"
    if with_database and compose_file.exists():
        available_db_ports = [p for p in range(_DB_PORT_MIN, _DB_PORT_MAX + 1) if p not in used_db_ports]
        if available_db_ports:
            db_port = random.choice(available_db_ports)

            # Set the port in environment and start
            env = os.environ.copy()
            env["DB_PORT"] = str(db_port)
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "up", "-d",
                cwd=output_dir,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

            # Wait for DB to be ready
            for _ in range(30):
                await asyncio.sleep(1)
                check = await asyncio.create_subprocess_exec(
                    "docker", "compose", "exec", "-T", "postgres",
                    "pg_isready", "-U", "postgres",
                    cwd=output_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await check.wait()
                if check.returncode == 0:
                    break

    # npm install if needed. --legacy-peer-deps: next-auth@4.24.15
    # declared a peerOptional bump of nodemailer to ^7 while our template
    # pins ^6. Peer-optional means it only matters if you actually use the
    # Email provider — the flag lets npm ignore the noise. Same flag runs
    # in the generated app's start.sh and Vercel's installCommand.
    #
    # Capture stderr so a fresh failure (a new peer conflict, a missing
    # binary, npm ratelimit) surfaces as an error line in the app log
    # instead of a silent "preview server failed to start" 30s later.
    node_modules = Path(output_dir) / "node_modules"
    if not node_modules.exists():
        install = await asyncio.create_subprocess_exec(
            "npm", "install", "--legacy-peer-deps",
            cwd=output_dir,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await install.communicate()
        if install.returncode != 0:
            logger.error(
                "preview: npm install failed (rc=%d) for %s\nstderr:\n%s",
                install.returncode, project_short_id,
                (stderr or b"").decode(errors="replace")[:2000],
            )
            # Bail early — starting `next dev` without node_modules is a
            # guaranteed 30s wait for the poll to time out.
            raise RuntimeError(
                f"npm install failed for {project_short_id}. "
                f"See backend logs for details."
            )

    # Run drizzle-kit push if schema exists and DB is up
    drizzle_config = Path(output_dir) / "drizzle.config.ts"
    if db_port and drizzle_config.exists():
        env = os.environ.copy()
        env["DATABASE_URL"] = f"postgresql://postgres:postgres@localhost:{db_port}/{project_short_id}"
        push = await asyncio.create_subprocess_exec(
            "npx", "drizzle-kit", "push",
            cwd=output_dir,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await push.wait()

        # Run seed if available
        seed_file = Path(output_dir) / "src" / "db" / "seed.ts"
        if seed_file.exists():
            seed = await asyncio.create_subprocess_exec(
                "npx", "tsx", "src/db/seed.ts",
                cwd=output_dir,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await seed.wait()

    # Start Next.js dev server
    env = os.environ.copy()
    if db_port:
        env["DATABASE_URL"] = f"postgresql://postgres:postgres@localhost:{db_port}/{project_short_id}"

    # Capture stdout+stderr so a crash isn't silent. Log tail is
    # read + shown on poll-timeout so the caller knows WHY the server
    # never came up (missing env, port conflict, template file error).
    proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(port),
        cwd=output_dir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        preexec_fn=os.setsid,
    )

    _environments[project_short_id] = {
        "proc": proc,
        "port": port,
        "db_port": db_port,
        "output_dir": output_dir,
        "with_database": with_database,
        "restart_count": 0,
    }

    # Poll until ready. 60s cap — cold Next.js starts on a fresh
    # node_modules can take 30-45s (Turbopack compile + first request);
    # the old 30s cap killed slow-but-healthy servers.
    url = f"http://localhost:{port}"
    async with httpx.AsyncClient(timeout=5) as client:
        for _ in range(120):
            await asyncio.sleep(0.5)
            # If the process died before we got a response, no amount of
            # polling will help — surface the crash immediately.
            if proc.returncode is not None:
                break
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    _start_health_check(project_short_id)
                    return {"port": port, "db_port": db_port}
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                continue

    # Read whatever the dev server actually wrote so the failure isn't
    # silent. Non-blocking best-effort — if the pipe stalls, we still
    # raise a useful error.
    tail = ""
    try:
        # Give the process a moment to finish flushing on the crash path.
        if proc.stdout is not None:
            try:
                data = await asyncio.wait_for(proc.stdout.read(4096), timeout=1.0)
                tail = (data or b"").decode(errors="replace")
            except asyncio.TimeoutError:
                tail = "<no output captured within 1s>"
    except Exception:  # noqa: BLE001
        tail = "<log read failed>"

    logger.error(
        "preview: server failed to start on :%d for %s (proc.returncode=%s)\ntail:\n%s",
        port, project_short_id, proc.returncode, tail[:2000],
    )
    await stop_project_environment(project_short_id)
    raise RuntimeError(
        f"Preview server failed to start on port {port}. "
        f"Backend log has the dev-server tail."
    )


async def stop_project_environment(project_short_id: str) -> bool:
    """Stop the dev server and Docker containers for a project."""
    # Cancel health check task
    task = _health_tasks.pop(project_short_id, None)
    if task and not task.done():
        task.cancel()

    entry = _environments.pop(project_short_id, None)
    if not entry:
        return False

    # Kill Next.js dev server
    proc = entry.get("proc")
    if proc and proc.returncode is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    return True


def get_environment_status(project_short_id: str) -> dict | None:
    """Return the port info for a running environment, or None."""
    entry = _environments.get(project_short_id)
    if entry and entry.get("proc") and entry["proc"].returncode is None:
        return {"port": entry["port"], "db_port": entry.get("db_port")}
    return None


# ---------------------------------------------------------------------------
# Health check endpoint data
# ---------------------------------------------------------------------------

async def health_check_preview(project_short_id: str) -> dict:
    """Perform a health check on a running preview server.

    Returns dict with:
      - healthy: bool
      - port: int | None
      - db_port: int | None
      - restart_count: int
      - status: str  ("running", "crashed", "not_found", "unhealthy")
    """
    entry = _environments.get(project_short_id)
    if not entry:
        return {
            "healthy": False,
            "port": None,
            "db_port": None,
            "restart_count": 0,
            "status": "not_found",
        }

    proc = entry.get("proc")
    port = entry["port"]
    db_port = entry.get("db_port")
    restart_count = entry.get("restart_count", 0)

    # Check if process is alive
    if proc is None or proc.returncode is not None:
        return {
            "healthy": False,
            "port": port,
            "db_port": db_port,
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
                    "db_port": db_port,
                    "restart_count": restart_count,
                    "status": "running",
                }
    except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
        pass

    return {
        "healthy": False,
        "port": port,
        "db_port": db_port,
        "restart_count": restart_count,
        "status": "unhealthy",
    }


# ---------------------------------------------------------------------------
# Auto-restart with exponential backoff
# ---------------------------------------------------------------------------

async def _restart_preview_server(project_short_id: str) -> bool:
    """Restart a crashed preview server with exponential backoff.

    Returns True if restart succeeded, False if max attempts exceeded.
    """
    entry = _environments.get(project_short_id)
    if not entry:
        return False

    restart_count = entry.get("restart_count", 0)
    if restart_count >= _MAX_RESTART_ATTEMPTS:
        logger.warning(
            "Preview server %s exceeded max restart attempts (%d), giving up",
            project_short_id,
            _MAX_RESTART_ATTEMPTS,
        )
        return False

    # Exponential backoff: 2^restart_count seconds (1, 2, 4, ...)
    backoff = 2 ** restart_count
    logger.info(
        "Restarting preview server %s (attempt %d/%d) after %ds backoff",
        project_short_id,
        restart_count + 1,
        _MAX_RESTART_ATTEMPTS,
        backoff,
    )
    await asyncio.sleep(backoff)

    port = entry["port"]
    db_port = entry.get("db_port")
    output_dir = entry.get("output_dir", "")

    if not output_dir or not Path(output_dir).exists():
        logger.error("Preview server %s output_dir missing, cannot restart", project_short_id)
        return False

    # Kill old process if still lingering
    proc = entry.get("proc")
    if proc and proc.returncode is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    # Start new Next.js dev server on same port
    env = os.environ.copy()
    if db_port:
        env["DATABASE_URL"] = f"postgresql://postgres:postgres@localhost:{db_port}/{project_short_id}"

    new_proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(port),
        cwd=output_dir,
        env=env,
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
                    logger.info(
                        "Preview server %s restarted successfully on port %d",
                        project_short_id,
                        port,
                    )
                    return True
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                continue

    logger.error("Preview server %s failed to restart on port %d", project_short_id, port)
    return False


def _start_health_check(project_short_id: str) -> None:
    """Start a background health check task for a preview server."""
    # Cancel existing task if any
    existing = _health_tasks.get(project_short_id)
    if existing and not existing.done():
        existing.cancel()

    task = asyncio.create_task(_health_check_loop(project_short_id))
    _health_tasks[project_short_id] = task


async def _health_check_loop(project_short_id: str) -> None:
    """Background loop that periodically checks preview health and auto-restarts on crash."""
    try:
        while project_short_id in _environments:
            await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

            entry = _environments.get(project_short_id)
            if not entry:
                break

            status = await health_check_preview(project_short_id)

            if status["status"] in ("crashed", "unhealthy"):
                logger.warning(
                    "Preview server %s is %s, attempting auto-restart",
                    project_short_id,
                    status["status"],
                )
                success = await _restart_preview_server(project_short_id)
                if not success:
                    logger.error(
                        "Auto-restart failed for preview server %s, stopping health checks",
                        project_short_id,
                    )
                    break
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Health check loop error for %s", project_short_id)
