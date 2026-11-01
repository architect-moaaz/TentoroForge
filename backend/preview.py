"""Dev server manager for live previews of generated Next.js projects.

Includes health checks, auto-restart with exponential backoff, and crash recovery.
"""

import asyncio
import logging
import os
import re
import signal
import random
from pathlib import Path

import httpx

from services import dev_servers

from services import process_groups  # noqa: E402

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


#: The Preview's own build directory. `next dev` compiles into `distDir`, and
#: the build's trials start the same app without the Preview's base path into
#: the default `.next` — the Preview then served client code compiled for no
#: prefix: every link and router push lost `/api/projects/<id>/preview/serve`,
#: and signing in landed on the platform's 404 (live, 2026-10-09). The review
#: server keeps its own (`page_review.REVIEW_DIST_DIR`) for the same reason.
PREVIEW_DIST_DIR = ".next-preview"
#: Half-second polls before a start is given up on — three minutes.
_READY_POLLS = 360

#: What an app's processes are given from the platform's environment: only
#: what a toolchain needs to run — finding its programs, its home and caches,
#: its locale, a proxy, the Docker the app's database runs in. Nothing else.
_TOOLCHAIN = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "COLORTERM", "TZ",
    "TMPDIR", "TMP", "TEMP", "HOSTNAME", "CI", "NODE_ENV", "NODE_OPTIONS", "NODE_PATH",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "NEXT_TELEMETRY_DISABLED",
    "PLAYWRIGHT_BROWSERS_PATH", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SYSTEMROOT", "SystemRoot", "PATHEXT", "COMSPEC", "WINDIR", "APPDATA", "LOCALAPPDATA",
    # A phone project's native toolchain.
    "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_NDK_HOME", "GRADLE_USER_HOME", "DEVELOPER_DIR",
})
_TOOLCHAIN_PREFIXES = ("LC_", "XDG_", "npm_config_", "NPM_CONFIG_", "NVM_", "VOLTA_", "COREPACK_", "PNPM_")
#: A name that says it holds a secret — refused even under a toolchain prefix
#: (`npm_config_//registry…/:_authToken`).
_SECRET_NAME = re.compile(r"(?:^|_)(?:KEY|KEYS|SECRET|SECRETS|TOKEN|TOKENS|PASSWORD|PASSWD|PWD|CREDENTIAL|CREDENTIALS|DSN)(?:_|$)"
                          r"|AUTH|DATABASE_URL|CONNECTION_STRING|PRIVATE", re.I)


def _toolchain(name: str) -> bool:
    if name in _TOOLCHAIN:
        return True
    return name.startswith(_TOOLCHAIN_PREFIXES) and not _SECRET_NAME.search(name)


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError:
        return keys
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].removeprefix("export ").strip()
        if key:
            keys.add(key)
    return keys


def app_env(output_dir: str | Path, **extra: str) -> dict[str, str]:
    """The environment an app's own processes run in: its dev server, its
    build, its package scripts, a check that boots it.

    It used to be the platform's (``{**os.environ}``), and Next.js lets the
    process environment win over the app's ``.env`` files — so a Preview read
    FORGE'S ``DATABASE_URL`` and every sign-in answered 401 (2026-10-09). A
    list of the platform's names to take out followed, and missed what the
    list did not know: on forge-v3 the integrations key, the deploy and
    database providers' tokens and the apps database reached code a model
    wrote and packages it installed (audit, 2026-11-01). So it is the other
    way round now: only what a toolchain needs (`_TOOLCHAIN`), never a name
    the app's own files set — those decide — and then ``extra``.
    """
    own: set[str] = set()
    for name in (".env", ".env.local", ".env.development", ".env.development.local"):
        own |= _env_keys(Path(output_dir) / name)
    env = {k: v for k, v in os.environ.items() if _toolchain(k) and k not in own}
    env.update(extra)
    return env


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
                "bash", "start.sh", "--seed-only", cwd=output_dir, env=app_env(output_dir),
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
    # ROOM FIRST. Each Preview grows to three gigabytes or more, and four
    # left open on forge-v3 starved the host until its workers died
    # (2026-10-05). The stalest goes before another one starts.
    await asyncio.to_thread(dev_servers.make_room, keep=dev_servers.MAX_PREVIEWS - 1)

    # basePath so Next generates page + asset URLs under the platform
    # proxy path. Reads next.config.ts (env-gated PREVIEW_BASE_PATH).
    # The proxy at /api/projects/<id>/preview/serve/... forwards to
    # this dev server, so the generated app must know the prefix or
    # its <Link>/asset hrefs point at the wrong origin from the iframe.
    prefix = f"/api/projects/{project_id}/preview/serve"
    env = app_env(
        output_dir,
        NEXT_BASE_PATH=prefix,
        NEXT_ASSET_PREFIX=prefix,
        # SIGN-IN UNDER THE PREFIX. next-auth's client posts to /api/auth at
        # the origin's root unless told the base path; behind the proxy that
        # reached the platform, and every preview sign-in ended on
        # /api/auth/error (Test4, 2026-09-28). Inlined by next dev.
        NEXT_PUBLIC_BASE_PATH=prefix,
        NEXT_DIST_DIR=PREVIEW_DIST_DIR,
    )
    _session_under_prefix(output_dir)

    # Start the dev server
    proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(port),
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        # Use process group so we can kill the whole tree
        **process_groups.own_group(),
    )

    _previews[project_id] = {
        "proc": proc,
        "port": port,
        "output_dir": output_dir,
        "restart_count": 0,
    }
    dev_servers.track(proc.pid, port=port, root=output_dir, kind="preview", key=project_id)

    # Poll until the server is ready. A first start compiles from nothing —
    # its own build directory is empty (PREVIEW_DIST_DIR) — and that took
    # longer than the 30 seconds this used to allow: the server was answering
    # pages when it was stopped as "failed to start" (live, 2026-10-09).
    url = f"http://localhost:{port}"
    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(_READY_POLLS):
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
    dev_servers.forget(proc.pid)
    if proc.returncode is None:
        try:
            process_groups.stop_group(proc)
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
            process_groups.stop_group(proc)
        except (ProcessLookupError, OSError):
            pass

    # Start new Next.js dev server on same port — under the same prefix it
    # was first started with: restarted without it, every page and asset URL
    # it emitted missed the proxy, and the Preview it was meant to heal died.
    prefix = f"/api/projects/{project_id}/preview/serve"
    new_proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(port),
        cwd=output_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=app_env(output_dir, NEXT_BASE_PATH=prefix, NEXT_ASSET_PREFIX=prefix,
                    NEXT_PUBLIC_BASE_PATH=prefix, NEXT_DIST_DIR=PREVIEW_DIST_DIR),
        **process_groups.own_group(),
    )

    if proc is not None:
        dev_servers.forget(proc.pid)
    entry["proc"] = new_proc
    entry["restart_count"] = restart_count + 1
    dev_servers.track(new_proc.pid, port=port, root=output_dir, kind="preview", key=project_id)

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

            entry = _previews.get(project_id)
            if (status["status"] in ("crashed", "unhealthy") and entry
                    and dev_servers.was_reaped(entry["proc"].pid)):
                # ENDED ON PURPOSE, not crashed: nobody had opened it for a
                # while, or a newer one needed the room. Restarting it here
                # would undo the reaper; the next request for it starts it.
                _previews.pop(project_id, None)
                break
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
