"""A live phone preview: a dev server (Metro) kept running for a project, so a change shows in the picture in under a second.

The build in `phone_preview` makes the whole picture again for every change (about 10 seconds). This keeps the bundler running on its own
copy of the phone project instead: a change to a screen file is copied across and the bundler swaps just that piece into the page that is
already open (hot reload), measured at 0.3 to 0.4 seconds for words and for a colour.

How it is served. The browser never talks to the dev server. It is started on `127.0.0.1` and a free port, inside the same machine as the
backend, and the backend passes requests to it under `/api/projects/{short_id}/phone/live/` (see `routers/phone_live.py`). That is the same
`/api/*` door the proxy in front of the platform already opens, so a hosted setup needs no new port, host name or certificate.

The one thing that does not pass through unchanged. The dev server's web page opens its live-update sockets at the top of the host
(`/hot` and `/message`), written into Expo's runtime with no way to add a path. The live copy swaps those two files for patched ones that read
a prefix from the page (`window.__FORGE_LIVE__`), which the proxy sets. If the files do not look as expected (a different Expo), the live
preview says it is unavailable and the editor keeps using the build.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from services import phone_preview as pp
from services.phone_preview import PhonePreviewError

logger = logging.getLogger(__name__)

#: A dev server nobody has used for this long is stopped (each one holds about half a gigabyte).
IDLE_SECONDS = int(os.environ.get("FORGE_PHONE_LIVE_IDLE", "600"))
#: How many run at once; starting one more stops the one used least recently.
MAX_SERVERS = int(os.environ.get("FORGE_PHONE_LIVE_MAX", "3"))
START_TIMEOUT = 180
WATCH_EVERY = 0.3

#: Files the live copy keeps its own version of: the preview's sample backend and the connection code it patches.
OVERLAY_OWNED = frozenset({"src/sdk/api.ts", "src/sdk/preview.ts", "src/sdk/preview-data.json"})


class LiveUnavailable(PhonePreviewError):
    """The live preview cannot run here; the message says why. The editor keeps using the build."""


def live_path(short_id: str) -> str:
    return f"/api/projects/{short_id}/phone/live"


def live_dir(output_dir: str | Path) -> Path:
    return pp.work_dir(output_dir) / "live"


# ---------------------------------------------------------------------------
# The two files that open sockets at the top of the host
# ---------------------------------------------------------------------------

_SOCKETS = (("HMRClient.js", "${window.location.host}/hot"), ("messageSocket.js", "${window.location.host}/message"))
_PREFIXED = "${window.location.host}${window.__FORGE_LIVE__ || ''}"


#: Expo shows a "Refreshing... Using Fast Refresh" bar over the bottom of the page for every update. In the picture of a phone it covers the
#: tab bar each time a change is made, so the live copy swaps the module that announces it for one that says nothing.
_QUIET_LOADING = 'Object.defineProperty(exports, "__esModule", { value: true });\nexports.default = { showMessage() {}, hide() {} };\n'


def patched_runtime(modules: Path) -> dict[str, str]:
    """`{file name: its text}` for Expo's two socket files, reading the page's prefix. Refuses when they are not as expected."""
    base = modules / "@expo" / "metro-runtime" / "build"
    out: dict[str, str] = {}
    for name, needle in _SOCKETS:
        try:
            text = (base / name).read_text(encoding="utf-8")
        except OSError as exc:
            raise LiveUnavailable(f"Expo's {name} could not be read, so the live preview cannot be set up here.") from exc
        if text.count(needle) != 1:
            raise LiveUnavailable(f"Expo's {name} is not the version the live preview knows how to adjust. The preview is drawn the slower way.")
        text = text.replace(needle, needle.replace("${window.location.host}", _PREFIXED, 1))
        # The copy lives in the project, not beside the files it reads from: what it requires from its neighbours is named in full.
        out[name] = re.sub(r"""require\((["'])\./([^"']+)\1\)""", lambda m: f'require("@expo/metro-runtime/build/{m.group(2)}")', text)
    out["LoadingView.js"] = _QUIET_LOADING
    return out


_METRO_CONFIG = """const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const config = getDefaultConfig(__dirname);
const resolve = config.resolver.resolveRequest;
// Expo's two live-update sockets open at the top of the host; the live preview's copies read a prefix from the page.
config.resolver.resolveRequest = (context, moduleName, platform) => {
  const found = (resolve || context.resolveRequest)(context, moduleName, platform);
  if (found && found.type === "sourceFile") {
    const m = /@expo[\\\\/]metro-runtime[\\\\/]build[\\\\/](HMRClient|messageSocket|LoadingView)\\.js$/.exec(found.filePath);
    if (m) return { type: "sourceFile", filePath: path.join(__dirname, "forge-live", m[1] + ".js") };
  }
  return found;
};
module.exports = config;
"""


def write_live_files(stage: Path) -> None:
    """The metro config and the patched socket files, in the live copy."""
    patched = patched_runtime(stage / "node_modules")
    folder = stage / "forge-live"
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in patched.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    (stage / "metro.config.js").write_text(_METRO_CONFIG, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# Keeping the live copy up to date
# ---------------------------------------------------------------------------

def sync_files(real: Path, stage: Path) -> int:
    """Copy what changed in the phone project's screens and generated files into the live copy; remove what is gone. Returns how many files
    were written or removed. The preview's own files are never touched."""
    changed = 0
    seen: set[str] = set()
    for top in ("app", "src"):
        base = real / top
        if not base.is_dir():
            continue
        for source in base.rglob("*"):
            if not source.is_file():
                continue
            rel = source.relative_to(real).as_posix()
            if rel in OVERLAY_OWNED:
                continue
            seen.add(rel)
            dest = stage / rel
            data = source.read_bytes()
            if dest.is_file() and dest.read_bytes() == data:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(data)
            except PermissionError:
                os.chmod(dest, 0o666)
                dest.write_bytes(data)
            changed += 1
    for top in ("app", "src"):
        base = stage / top
        if not base.is_dir():
            continue
        for existing in list(base.rglob("*")):
            if existing.is_file():
                rel = existing.relative_to(stage).as_posix()
                if rel not in seen and rel not in OVERLAY_OWNED:
                    existing.unlink()
                    changed += 1
    return changed


def _refresh_sample_data(doc: dict, stage: Path) -> int:
    target = stage / "src" / "sdk" / "preview-data.json"
    text = json.dumps(pp.sample_data(doc))
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return 0
    target.write_text(text, encoding="utf-8")
    return 1


# ---------------------------------------------------------------------------
# The servers
# ---------------------------------------------------------------------------

@dataclass
class Server:
    short_id: str
    output_dir: str
    state: str = "starting"                # starting | ready | failed
    error: str = ""
    port: int = 0
    process: Optional[asyncio.subprocess.Process] = None
    stage: Optional[Path] = None
    last_used: float = field(default_factory=time.monotonic)
    tasks: list[asyncio.Task] = field(default_factory=list)
    synced: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_servers: dict[str, Server] = {}
_reaper: Optional[asyncio.Task] = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _kill(process: Optional[asyncio.subprocess.Process]) -> None:
    """The dev server and what it started: `npx` is a shell around node, so a plain kill leaves the bundler running."""
    if process is None or process.returncode is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def status(short_id: str) -> dict[str, Any]:
    """`state`: off | starting | ready | failed. `path` is where the browser loads it from, through the backend."""
    server = _servers.get(short_id)
    if server is None:
        return {"state": "off", "path": live_path(short_id), "error": ""}
    if server.state == "ready" and server.process is not None and server.process.returncode is not None:
        server.state, server.error = "failed", "The live preview stopped."
    return {"state": server.state, "path": live_path(short_id), "error": server.error}


def port_of(short_id: str) -> Optional[int]:
    """The port of a running server, and a mark that it was just used. None when there is none."""
    server = _servers.get(short_id)
    if server is None or server.state != "ready" or not server.port:
        return None
    if server.process is not None and server.process.returncode is not None:
        server.state, server.error = "failed", "The live preview stopped."
        return None
    server.last_used = time.monotonic()
    return server.port


def mark_unreachable(short_id: str) -> None:
    """The dev server did not answer: it is no longer ready, so the editor falls back to the build and the reaper stops what is left."""
    server = _servers.get(short_id)
    if server is not None and server.state == "ready":
        server.state, server.error = "failed", "The live preview stopped answering."


def _entry_script(html: str) -> Optional[str]:
    m = re.search(r'<script[^>]+src="([^"]+)"', html)
    return m.group(1) if m else None


async def _wait_until_up(server: Server) -> str:
    """Poll the dev server's page until it answers; returns the page."""
    deadline = time.monotonic() + START_TIMEOUT
    async with httpx.AsyncClient(timeout=5) as client:
        while time.monotonic() < deadline:
            if server.process is None or server.process.returncode is not None:
                raise PhonePreviewError("The live preview's server stopped while starting.")
            try:
                r = await client.get(f"http://127.0.0.1:{server.port}/")
                if r.status_code == 200:
                    return r.text
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise PhonePreviewError("The live preview's server did not start in time.")


async def _warm(server: Server, html: str) -> None:
    """Fetch the page's bundle once, so the first time the picture opens it is already built (about 11 seconds cold)."""
    src = _entry_script(html)
    if not src:
        return
    async with httpx.AsyncClient(timeout=150) as client:
        try:
            await client.get(f"http://127.0.0.1:{server.port}{src}")
        except httpx.HTTPError as exc:                       # the first picture will say it; the server itself is up
            logger.warning("[phone_live] the first bundle did not build: %s", exc)


async def _start(server: Server) -> None:
    from services.blueprint.service import BlueprintService
    try:
        if not pp.has_screens(server.output_dir):
            raise PhonePreviewError("This app has no phone screens to preview.")
        npx = shutil.which("npx")
        if npx is None:
            raise LiveUnavailable("Node.js is not installed where the platform runs, so the live preview cannot start.")
        doc = BlueprintService.load(output_dir=server.output_dir).doc
        real = pp.native_dir(server.output_dir)
        stage = live_dir(server.output_dir)
        fresh = not stage.exists()
        server.stage = await asyncio.to_thread(pp._stage_here, real, stage)
        await asyncio.to_thread(pp._prepare_copy, server.stage, doc, server.short_id, live_path(server.short_id))
        env = {k: v for k, v in os.environ.items() if k != "CI"}              # CI turns file watching off
        env.update({"EXPO_NO_TELEMETRY": "1", "EXPO_NO_GIT_STATUS": "1", "EXPO_OFFLINE": "1", "BROWSER": "none"})
        await pp._ensure_packages(server.output_dir, real, server.stage, env)
        await asyncio.to_thread(write_live_files, server.stage)
        server.port = _free_port()
        log = open(stage.parent / "live.log", "wb")
        kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
        server.process = await asyncio.create_subprocess_exec(
            npx, "expo", "start", "--web", "--port", str(server.port), "--localhost", *(["--clear"] if fresh else []),
            cwd=str(server.stage), env=env, stdout=log, stderr=asyncio.subprocess.STDOUT, **kwargs)
        log.close()
        html = await _wait_until_up(server)
        await _warm(server, html)
        server.synced = pp._fingerprint(server.output_dir)
        server.state = "ready"
        server.tasks.append(asyncio.create_task(_watch(server)))
        logger.info("[phone_live] %s is live on port %s", server.short_id, server.port)
    except PhonePreviewError as exc:
        server.state, server.error = "failed", str(exc)
        _kill(server.process)
    except Exception as exc:  # noqa: BLE001 - said as a reason, not a traceback
        logger.exception("[phone_live] start failed for %s", server.short_id)
        server.state, server.error = "failed", f"The live preview could not start ({type(exc).__name__}: {str(exc)[:160]})."
        _kill(server.process)


async def sync(short_id: str) -> int:
    """Bring the live copy up to date now. Returns how many files changed."""
    server = _servers.get(short_id)
    if server is None or server.state != "ready" or server.stage is None:
        return 0
    server.last_used = time.monotonic()
    async with server.lock:
        from services.blueprint.service import BlueprintService
        real = pp.native_dir(server.output_dir)
        changed = await asyncio.to_thread(sync_files, real, server.stage)
        try:
            changed += await asyncio.to_thread(_refresh_sample_data, BlueprintService.load(output_dir=server.output_dir).doc, server.stage)
        except Exception:  # noqa: BLE001 - the screens matter more than the sample data
            logger.warning("[phone_live] sample data was not refreshed", exc_info=True)
        server.synced = pp._fingerprint(server.output_dir)
        return changed


async def _watch(server: Server) -> None:
    """Whatever changes the phone project (the editor, Smith, a build) reaches the live copy within a moment."""
    while server.state == "ready":
        await asyncio.sleep(WATCH_EVERY)
        try:
            if pp._fingerprint(server.output_dir) != server.synced:
                await sync(server.short_id)
        except Exception:  # noqa: BLE001 - keep watching
            logger.warning("[phone_live] sync failed", exc_info=True)


async def _reap() -> None:
    while True:
        await asyncio.sleep(30)
        now = time.monotonic()
        for sid, server in list(_servers.items()):
            if server.state == "failed" or (server.state == "ready" and now - server.last_used > IDLE_SECONDS):
                logger.info("[phone_live] stopping %s (%s)", sid, "failed" if server.state == "failed" else "idle")
                stop(sid)


def start(output_dir: str | Path, short_id: str) -> dict[str, Any]:
    """Start the live preview if it is not running; answers where it stands. Must be called from the running event loop."""
    global _reaper
    server = _servers.get(short_id)
    if server is not None and server.state in ("starting", "ready") and (server.process is None or server.process.returncode is None):
        server.last_used = time.monotonic()
        return status(short_id)
    if server is not None:
        stop(short_id)
    # One more than the limit stops the one used least recently.
    while len(_servers) >= MAX_SERVERS:
        stop(min(_servers, key=lambda s: _servers[s].last_used))
    server = Server(short_id=short_id, output_dir=str(output_dir))
    _servers[short_id] = server
    server.tasks.append(asyncio.create_task(_start(server)))
    if _reaper is None or _reaper.done():
        _reaper = asyncio.create_task(_reap())
    return status(short_id)


def stop(short_id: str) -> None:
    server = _servers.pop(short_id, None)
    if server is None:
        return
    server.state = "failed"
    for task in server.tasks:
        task.cancel()
    _kill(server.process)


def stop_all() -> None:
    for sid in list(_servers):
        stop(sid)
