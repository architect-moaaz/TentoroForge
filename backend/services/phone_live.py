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
import posixpath
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

from services import phone_live_registry as reg
from services import phone_preview as pp
from services.phone_preview import PhonePreviewError

logger = logging.getLogger(__name__)

#: A dev server nobody has used for this long is stopped (each one holds about half a gigabyte).
IDLE_SECONDS = int(os.environ.get("FORGE_PHONE_LIVE_IDLE", "600"))
#: How many run at once on the platform; a start beyond it is refused (the editor keeps the built picture).
MAX_SERVERS = int(os.environ.get("FORGE_PHONE_LIVE_MAX", "4"))
#: How many one organisation may run; starting one more stops that organisation's least recently used.
MAX_PER_ORG = int(os.environ.get("FORGE_PHONE_LIVE_PER_ORG", "2"))
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


#: Expo's router handles its base path (the path a page is served from) only in a production build: the two guards below say
#: `if (process.env.NODE_ENV !== 'development')` around stripping it from an address and adding it back. In development it expects to be at the
#: top of the host. Under the live path it found no screen, and the first answer (move the page's address to the top) made a full reload, which
#: a change that cannot be hot-swapped causes, load the platform's own home page inside the phone frame (reported 2026-10-22). With the guard lifted
#: in the live copy the page keeps its real address, a reload lands on the same screen, and nothing about the address is faked.
_ROUTER_GUARD = "if (process.env.NODE_ENV !== 'development') {"
_ROUTER_FILES = (("getStateFromPath.js", "stripBaseUrl"), ("getPathFromState.js", "appendBaseUrl"))


def _absolute_requires(text: str, directory: str) -> str:
    """The copy lives in the project, not beside the files it reads from: what it requires from its neighbours is named in full."""
    def swap(m: "re.Match[str]") -> str:
        return f'require("{posixpath.normpath(posixpath.join(directory, m.group(2)))}")'
    return re.sub(r"""require\((["'])(\.{1,2}/[^"']+)\1\)""", swap, text)


def patched_runtime(modules: Path) -> dict[str, str]:
    """`{file name: its text}` for the Expo files the live copy swaps: the two sockets (they read the page's prefix), the router's two
    base-path guards (lifted), and the "Refreshing" bar (silenced). Refuses when a file is not as expected."""
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
        out[name] = _absolute_requires(text, "@expo/metro-runtime/build")
    router = modules / "expo-router" / "build" / "fork"
    for name, function in _ROUTER_FILES:
        try:
            text = (router / name).read_text(encoding="utf-8")
        except OSError as exc:
            raise LiveUnavailable(f"Expo Router's {name} could not be read, so the live preview cannot be set up here.") from exc
        if text.count(_ROUTER_GUARD) != 1:
            raise LiveUnavailable(f"Expo Router's {name} is not the version the live preview knows how to adjust ({function}). "
                                  "The preview is drawn the slower way.")
        out[name] = _absolute_requires(text.replace(_ROUTER_GUARD, "if (true) {", 1), "expo-router/build/fork")
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
    const m = /@expo[\\\\/]metro-runtime[\\\\/]build[\\\\/](HMRClient|messageSocket|LoadingView)\\.js$/.exec(found.filePath)
      || /expo-router[\\\\/]build[\\\\/]fork[\\\\/](getStateFromPath|getPathFromState)\\.js$/.exec(found.filePath);
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

# WHICH SERVERS RUN, AND WHERE, IS WRITTEN ON DISK (`phone_live_registry`), one answer for every backend worker. What is here is only
# what the worker that STARTED a server holds: its process handle, its start task and its watcher. A request that reaches another worker
# reads the record, finds the port, and passes the request to the same Metro itself (PR #28 review, 2026-10-22).

@dataclass
class Server:
    short_id: str
    output_dir: str
    token: str                             # the registry record this worker claimed
    port: int = 0
    process: Optional[asyncio.subprocess.Process] = None
    stage: Optional[Path] = None
    tasks: list[asyncio.Task] = field(default_factory=list)
    synced: str = ""


_servers: dict[str, Server] = {}           # only the servers THIS worker started
_sync_locks: dict[str, asyncio.Lock] = {}
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


def _off(short_id: str) -> dict[str, Any]:
    return {"state": "off", "path": live_path(short_id), "error": ""}


def status(short_id: str) -> dict[str, Any]:
    """`state`: off | starting | ready | failed. `path` is where the browser loads it from, through the backend. The same from any worker."""
    _ensure_reaper()
    rec = reg.get(short_id)
    if rec is None:
        return _off(short_id)
    path = live_path(short_id)
    if reg.alive(rec):
        return {"state": rec["state"], "path": path, "error": rec.get("error", "")}
    if rec.get("state") == "failed":
        return {"state": "failed", "path": path, "error": rec.get("error", "")}
    if rec.get("state") == "ready":
        return {"state": "failed", "path": path, "error": "The live preview stopped."}
    return _off(short_id)                  # a start whose worker is gone: the next start clears it


def port_of(short_id: str) -> Optional[int]:
    """The port of a running server. None when there is none.

    It does NOT mark the server as used. The picture's own requests come from a page nobody has to sign in for, so anyone who kept
    asking would have kept a server (about 300 MB) alive forever; what marks a server as used is the editor's signed-in calls
    (`touch`, called from the editor's status poll, and start and sync) (PR #28 review, 2026-10-22)."""
    _ensure_reaper()
    rec = reg.live(short_id)
    if rec is None or rec.get("state") != "ready" or not rec.get("port"):
        return None
    return int(rec["port"])


def touch(short_id: str) -> None:
    """The editor is open on this project: the server is in use."""
    reg.touch(short_id)


def entry_of(short_id: str) -> Optional[str]:
    """The address of the app's one entry bundle, as the dev server's own page names it (the only bundle the picture may ask for)."""
    rec = reg.live(short_id)
    return str(rec["entry"]) if rec and rec.get("entry") else None


def mark_unreachable(short_id: str) -> None:
    """The dev server did not answer: it is no longer ready, so the editor falls back to the build and the reaper stops what is left."""
    rec = reg.get(short_id)
    if rec is not None and rec.get("state") == "ready":
        reg.update(short_id, rec.get("token"), state="failed", error="The live preview stopped answering.")


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


class _Superseded(Exception):
    """The record this start claimed is gone (it was stopped, or ended to make room): stop, writing nothing."""


def _still_mine(server: Server) -> None:
    if not reg.mine(server.short_id, server.token):
        raise _Superseded()


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
        _still_mine(server)
        server.stage = await asyncio.to_thread(pp._stage_here, real, stage)
        await asyncio.to_thread(reg.update, server.short_id, server.token, stage=str(server.stage))
        await asyncio.to_thread(pp._prepare_copy, server.stage, doc, server.short_id, live_path(server.short_id))
        from services.phone_env import phone_env
        env = phone_env(server.output_dir)                                   # not the platform's secrets (phone_env)
        env.pop("CI", None)                                                  # CI turns file watching off
        env.update({"EXPO_NO_TELEMETRY": "1", "EXPO_NO_GIT_STATUS": "1", "EXPO_OFFLINE": "1", "BROWSER": "none"})
        await pp._ensure_packages(server.output_dir, real, server.stage, env)
        await asyncio.to_thread(write_live_files, server.stage)
        _still_mine(server)
        server.port = _free_port()
        log = open(stage.parent / "live.log", "wb")
        kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
        server.process = await asyncio.create_subprocess_exec(
            npx, "expo", "start", "--web", "--port", str(server.port), "--localhost", *(["--clear"] if fresh else []),
            cwd=str(server.stage), env=env, stdout=log, stderr=asyncio.subprocess.STDOUT, **kwargs)
        log.close()
        if not await asyncio.to_thread(reg.update, server.short_id, server.token, port=server.port, pid=server.process.pid,
                                       pidStarted=reg._started(server.process.pid)):
            raise _Superseded()
        html = await _wait_until_up(server)
        await asyncio.to_thread(reg.update, server.short_id, server.token, entry=_entry_script(html) or "")
        await _warm(server, html)
        server.synced = pp._fingerprint(server.output_dir)
        if not await asyncio.to_thread(reg.update, server.short_id, server.token, state="ready"):
            raise _Superseded()
        server.tasks.append(asyncio.create_task(_watch(server)))
        logger.info("[phone_live] %s is live on port %s", server.short_id, server.port)
    except _Superseded:
        _kill(server.process)
    except PhonePreviewError as exc:
        reg.update(server.short_id, server.token, state="failed", error=str(exc))
        _kill(server.process)
    except Exception as exc:  # noqa: BLE001 - said as a reason, not a traceback
        logger.exception("[phone_live] start failed for %s", server.short_id)
        reg.update(server.short_id, server.token, state="failed",
                   error=f"The live preview could not start ({type(exc).__name__}: {str(exc)[:160]}).")
        _kill(server.process)


async def sync(short_id: str) -> int:
    """Bring the live copy up to date now, from any worker. Returns how many files changed."""
    rec = reg.live(short_id)
    if rec is None or rec.get("state") != "ready" or not rec.get("stage"):
        return 0
    reg.touch(short_id)
    async with _sync_locks.setdefault(short_id, asyncio.Lock()):
        from services.blueprint.service import BlueprintService
        output_dir = rec["outputDir"]
        stage = Path(rec["stage"])
        changed = await asyncio.to_thread(sync_files, pp.native_dir(output_dir), stage)
        try:
            changed += await asyncio.to_thread(_refresh_sample_data, BlueprintService.load(output_dir=output_dir).doc, stage)
        except Exception:  # noqa: BLE001 - the screens matter more than the sample data
            logger.warning("[phone_live] sample data was not refreshed", exc_info=True)
        local = _servers.get(short_id)
        if local is not None and local.token == rec.get("token"):
            local.synced = pp._fingerprint(output_dir)
        return changed


async def _watch(server: Server) -> None:
    """Whatever changes the phone project (the editor, Smith, a build) reaches the live copy within a moment. Runs in the worker that
    started the server; a sync asked for on another worker copies the same files, which is safe to do twice."""
    beats = 0
    while True:
        await asyncio.sleep(WATCH_EVERY)
        beats += 1
        try:
            if beats % 20 == 0 and not await asyncio.to_thread(reg.mine, server.short_id, server.token):
                return
            if pp._fingerprint(server.output_dir) != server.synced:
                await sync(server.short_id)
                server.synced = pp._fingerprint(server.output_dir)
        except Exception:  # noqa: BLE001 - keep watching
            logger.warning("[phone_live] sync failed", exc_info=True)


def _drop_local(short_id: str) -> None:
    """Forget what this worker holds for a server, and end its process here (it is the parent of it)."""
    local = _servers.pop(short_id, None)
    if local is None:
        return
    for task in local.tasks:
        task.cancel()
    _kill(local.process)


async def _reap() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(reg.reap, IDLE_SECONDS)
            for sid, local in list(_servers.items()):         # one the registry no longer holds as ours (stopped, evicted, ended)
                if not reg.mine(sid, local.token):
                    _drop_local(sid)
        except Exception:  # noqa: BLE001 - the reaper never takes a worker down
            logger.warning("[phone_live] reap failed", exc_info=True)


def _ensure_reaper() -> None:
    """Every worker runs one, so what a worker that died left behind is cleared by whichever worker is still there."""
    global _reaper
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _reaper is None or _reaper.done() or _reaper.get_loop() is not loop:
        _reaper = loop.create_task(_reap())


def start(output_dir: str | Path, short_id: str, org: str = "") -> dict[str, Any]:
    """Start the live preview if it is not running anywhere; answers where it stands. Must be called from the running event loop.

    Under the registry's lock a server that is live or starting (on this worker or another) is used and nothing is started or deleted;
    otherwise the organisation's own least recently used server is ended if it holds `MAX_PER_ORG`, and a start that would pass
    `MAX_SERVERS` on the platform is refused: the picture stays the built one, and nobody else's server is ended."""
    _ensure_reaper()
    try:
        rec, created = reg.claim(short_id, output_dir, org=org, per_org_cap=MAX_PER_ORG, global_cap=MAX_SERVERS)
    except reg.CapReached:
        raise LiveUnavailable("Too many live previews are running right now, so this one is not started. The built picture is shown; "
                              "try again in a few minutes.")
    if not created:
        return status(short_id)
    _drop_local(short_id)                  # an earlier server of this worker's, failed or replaced
    server = Server(short_id=short_id, output_dir=str(output_dir), token=rec["token"])
    _servers[short_id] = server
    server.tasks.append(asyncio.create_task(_start(server)))
    return status(short_id)


def stop(short_id: str) -> None:
    """Stop the live preview, from any worker."""
    _drop_local(short_id)
    rec = reg.get(short_id)
    if rec is not None:
        reg.end(rec, "stopped")


def stop_all() -> None:
    """This worker is going away: end the servers IT started (another worker's are its own)."""
    for sid, local in list(_servers.items()):
        _drop_local(sid)
        reg.release(sid, local.token)
