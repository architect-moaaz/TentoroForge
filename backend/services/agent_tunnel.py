"""Reaching the app that runs on the builder's OWN computer, when the platform is on a server.

Watch live needs the platform to talk to the app the builder is running. When the platform runs on the builder's computer
that is a plain localhost address; when it runs on a server (EC2) the server cannot see the builder's localhost at all.
So the builder's computer opens a REVERSE SSH tunnel to the server and the server reaches the app through it:

    builder's computer                         the server
    [app :3001] <-- ssh -R 0.0.0.0:P:127.0.0.1:3001 -- [tunnel sshd] <-- [platform backend] http://tunnel:P

This module is the platform's half of that, with no network code of its own except one TCP check:

* a PAIRING: the signed-in builder asks for a one-time code (10 minutes, one use); the connector program on the builder's
  computer redeems it together with its OWN public key and a fresh debug secret. Nothing secret ever travels the other way.
* a REGISTRY (``registry.json``, private) of one tunnel per project: its port, its key, its secret, who connected from where.
* the SSH server's ``authorized_keys`` (written from the registry, atomically): each key may ONLY open the one listening
  port it was given, run no command and open no shell, so a key for one project can never reach another project's port.

Off unless ``FORGE_TUNNEL_DIR`` names a folder shared with the tunnel service: on the builder's own computer there is
nothing to tunnel and the platform talks to localhost as before.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:  # POSIX only; on Windows (a builder's own computer, no tunnel service) the in-process lock is all there is
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

#: A pairing code lasts this long, works once, and each project may have a few open at a time.
PAIR_TTL_S = 600
MAX_PENDING_PER_PROJECT = 5
#: No unambiguous-looking pairs (0/O, 1/I): codes are read off a screen and typed.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
#: Wrong guesses allowed from one address in a minute before it is told to wait.
MAX_BAD_GUESSES = 10

# An ed25519 public key is always this long: type, then the base64 of 51 bytes. Nothing else may reach authorized_keys:
# no options, no comment, no second line (that is how a key line becomes a command).
_KEY_RX = re.compile(r"^ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+/]{43}$")
_SECRET_RX = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_PROJECT_RX = re.compile(r"^[A-Za-z0-9-]{8,64}$")

_lock = threading.Lock()
_bad: dict[str, list[float]] = {}


class TunnelError(Exception):
    """Something the builder or the connector can act on, in plain words, with the HTTP status it deserves."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# where things are
# ---------------------------------------------------------------------------

def settings() -> dict[str, Any]:
    return {
        "dir": os.getenv("FORGE_TUNNEL_DIR") or None,
        #: how the platform reaches the tunnel service's listeners (its name on the server's private network)
        "host": os.getenv("FORGE_TUNNEL_HOST", "tunnel"),
        #: how the builder's computer reaches the tunnel service's SSH port from outside
        "public_host": os.getenv("FORGE_TUNNEL_PUBLIC_HOST") or None,
        "ssh_port": int(os.getenv("FORGE_TUNNEL_SSH_PORT", "2222")),
        "lo": int(os.getenv("FORGE_TUNNEL_PORT_LO", "22000")),
        "hi": int(os.getenv("FORGE_TUNNEL_PORT_HI", "22999")),
        "user": "tunnel",
    }


def enabled() -> bool:
    d = settings()["dir"]
    return bool(d) and Path(d).is_dir()


def _dir() -> Path:
    s = settings()
    if not s["dir"] or not Path(s["dir"]).is_dir():
        raise TunnelError("This platform has no tunnel service, so it cannot reach a computer outside it.", 503)
    return Path(s["dir"])


def _read(d: Path) -> dict[str, Any]:
    try:
        reg = json.loads((d / "registry.json").read_text(encoding="utf-8"))
        if isinstance(reg, dict):
            reg.setdefault("projects", {})
            reg.setdefault("pending", {})
            return reg
    except (OSError, ValueError):
        pass
    return {"projects": {}, "pending": {}}


def _atomic(path: Path, text: str, mode: int) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def authorized_keys(reg: dict[str, Any]) -> str:
    """The SSH server's key list: one line per project, each limited to its own port and nothing else."""
    lines = []
    for pid, p in sorted(reg.get("projects", {}).items()):
        if not _KEY_RX.match(str(p.get("publicKey", ""))) or not _PROJECT_RX.match(pid):
            continue  # a damaged entry is never written out
        opts = f'restrict,port-forwarding,permitlisten="0.0.0.0:{int(p["port"])}",command="/bin/false"'
        lines.append(f"{opts} {p['publicKey']} ttf-{pid}")
    return "\n".join(lines) + ("\n" if lines else "")


def _write(d: Path, reg: dict[str, Any]) -> None:
    _atomic(d / "registry.json", json.dumps(reg, indent=2), 0o600)
    _atomic(d / "authorized_keys", authorized_keys(reg), 0o644)


@contextmanager
def _exclusive(d: Path) -> Iterator[None]:
    """One writer at a time, across threads AND across the backend's worker processes: the registry is read, changed and written
    back, and two workers doing that at once would lose one of the changes (a code just made, a computer just paired)."""
    with _lock:
        if fcntl is None:
            yield
            return
        with open(d / ".lock", "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _purge(reg: dict[str, Any], now: float) -> None:
    reg["pending"] = {h: v for h, v in reg.get("pending", {}).items() if v.get("expires", 0) > now}


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------

def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normal_code(code: str) -> str:
    """What was typed, as the code it means: capitals, no dashes or spaces."""
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def new_pairing(project_id: str, *, now: float | None = None) -> dict[str, Any]:
    """A one-time code for this project's owner to give the connector. Shown as ABCD-EFGH."""
    if not _PROJECT_RX.match(str(project_id)):
        raise TunnelError("Not a valid project.", 400)
    now = time.time() if now is None else now
    d = _dir()
    with _exclusive(d):
        reg = _read(d)
        _purge(reg, now)
        mine = [h for h, v in reg["pending"].items() if v.get("project") == project_id]
        for h in mine[: max(0, len(mine) - MAX_PENDING_PER_PROJECT + 1)]:
            reg["pending"].pop(h, None)  # the oldest go, so asking again always works
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        reg["pending"][_hash(raw)] = {"project": project_id, "expires": now + PAIR_TTL_S}
        _write(d, reg)
    return {"code": f"{raw[:4]}-{raw[4:]}", "expiresAt": int(now + PAIR_TTL_S)}


def _too_many(ip: str, now: float) -> bool:
    recent = [t for t in _bad.get(ip, []) if now - t < 60]
    _bad[ip] = recent
    return len(recent) >= MAX_BAD_GUESSES


def _allocate(reg: dict[str, Any], project_id: str) -> int:
    s = settings()
    span = s["hi"] - s["lo"] + 1
    taken = {int(p["port"]) for pid, p in reg["projects"].items() if pid != project_id}
    if project_id in reg["projects"]:
        return int(reg["projects"][project_id]["port"])  # a project keeps its port when it pairs again
    start = int(hashlib.sha256(project_id.encode()).hexdigest(), 16) % span
    for i in range(span):
        port = s["lo"] + (start + i) % span
        if port not in taken:
            return port
    raise TunnelError("The tunnel service has no free ports left.", 503)


def host_key() -> str:
    """The tunnel service's SSH host key, which the connector pins so it can never be tricked into talking to someone else."""
    try:
        key = (_dir() / "host_key.pub").read_text(encoding="utf-8").strip().split("\n")[0]
    except OSError:
        raise TunnelError("The tunnel service is not ready yet (it has not published its host key). Try again in a moment.", 503)
    parts = key.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519" or not re.fullmatch(r"[A-Za-z0-9+/=]+", parts[1]):
        raise TunnelError("The tunnel service published a host key this platform cannot read.", 503)
    return f"{parts[0]} {parts[1]}"


def info() -> dict[str, Any]:
    """Where a computer connects and which server identity to trust: public by design (an address and a PUBLIC key), so the
    connector can test that it can reach the server BEFORE it spends its one-time code."""
    s = settings()
    if not enabled():
        raise TunnelError("This platform has no tunnel service, so it cannot reach a computer outside it.", 503)
    if not s["public_host"]:
        raise TunnelError("This platform does not know its own public address (FORGE_TUNNEL_PUBLIC_HOST is not set).", 503)
    return {"sshHost": s["public_host"], "sshPort": s["ssh_port"], "sshUser": s["user"], "hostKey": host_key()}


def public_address(ip: str) -> str | None:
    """The address if it is one a person could be reached on from the internet. Behind a proxy or a container network the platform
    often sees only a private gateway address (172.x, 10.x): showing that as "your address" would be wrong, so it is left out."""
    try:
        return ip if ipaddress.ip_address(ip).is_global else None
    except ValueError:
        return None


def pair(code: str, public_key: str, app_port: Any, secret: str, *, client_ip: str = "", label: str = "",
         now: float | None = None) -> dict[str, Any]:
    """Redeem a code: the connector's own public key and a fresh debug secret in, where to connect and how to trust it out.
    The code is used up even by a pairing that fails after it was accepted, so a code is never tried twice."""
    now = time.time() if now is None else now
    ip = client_ip or "unknown"
    d = _dir()
    with _exclusive(d):
        if _too_many(ip, now):
            raise TunnelError("Too many wrong codes from this address. Wait a minute and try again.", 429)
        reg = _read(d)
        _purge(reg, now)
        entry = reg["pending"].get(_hash(normal_code(code)))
        if not entry:
            _bad.setdefault(ip, []).append(now)
            raise TunnelError("That code is not valid, or it has expired. Ask for a new one in Watch live.", 404)
        project_id = entry["project"]
        # A computer that is connected RIGHT NOW is never disturbed by a newer pairing: replacing its key and secret would break the
        # tunnel that works, and the newcomer could not even open the port. The code is kept, so it works once the first has gone.
        current = reg["projects"].get(project_id)
        if current and listener_open(current["port"]):
            who = current.get("label") or "another computer"
            raise TunnelError(f"{who} is already connected to this project. Close its connector first (or wait up to a minute if that "
                              "computer is gone), then run this again. Your code has not been used.", 409)
        reg["pending"].pop(_hash(normal_code(code)), None)  # one use
        key = " ".join(str(public_key or "").split())
        if not _KEY_RX.match(key):
            _write(d, reg)
            raise TunnelError("The connector sent a key that is not an ed25519 public key.", 400)
        try:
            port_of_app = int(app_port)
            if not 1 <= port_of_app <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            _write(d, reg)
            raise TunnelError("The connector did not say which port the app runs on.", 400)
        if not _SECRET_RX.match(str(secret or "")):
            _write(d, reg)
            raise TunnelError("The connector sent a debug secret that is too short or has odd characters.", 400)
        # The SSH server honours the FIRST line that matches a key, so one key on two projects would give the second project the
        # first one's port and refuse it. A key belongs to one project; the connector makes a fresh key for each.
        if any(pid != project_id and v.get("publicKey") == key for pid, v in reg["projects"].items()):
            _write(d, reg)
            raise TunnelError("This computer's key is already connected to another project. Run the connector again (it makes a new key for each project).", 409)
        port = _allocate(reg, project_id)
        reg["projects"][project_id] = {
            "port": port, "publicKey": key, "secret": secret, "appPort": port_of_app,
            "clientIp": public_address(ip), "label": re.sub(r"[^\w .@-]", "", str(label))[:64], "pairedAt": int(now),
        }
        _write(d, reg)
    return {"port": port, "projectId": project_id, "yourAddress": public_address(ip), **info()}


# ---------------------------------------------------------------------------
# using it
# ---------------------------------------------------------------------------

def get(project_id: str) -> dict[str, Any] | None:
    return _read(_dir()).get("projects", {}).get(project_id) if enabled() else None


def revoke(project_id: str) -> bool:
    """Forget this project's tunnel: its key stops being accepted for new connections at once."""
    d = _dir()
    with _exclusive(d):
        reg = _read(d)
        gone = reg["projects"].pop(project_id, None) is not None
        for h in [h for h, v in reg["pending"].items() if v.get("project") == project_id]:
            reg["pending"].pop(h, None)
        _write(d, reg)
    return gone


def listener_open(port: int, timeout: float = 1.5) -> bool:
    """Is the builder's computer connected right now? Its listener exists exactly as long as its SSH session does."""
    try:
        with socket.create_connection((settings()["host"], int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def target_url(project_id: str) -> str | None:
    """Where the platform reaches this project's app through its tunnel, or None when it was never paired."""
    reg = get(project_id)
    return f"http://{settings()['host']}:{int(reg['port'])}" if reg else None


def describe(project_id: str) -> dict[str, Any]:
    """What Watch live shows about the tunnel. Never the secret."""
    if not enabled():
        return {"enabled": False, "registered": False, "connected": False}
    reg = get(project_id)
    if not reg:
        return {"enabled": True, "registered": False, "connected": False}
    return {"enabled": True, "registered": True, "connected": listener_open(reg["port"]), "port": reg["port"],
            "appPort": reg.get("appPort"), "clientIp": reg.get("clientIp"), "label": reg.get("label"), "pairedAt": reg.get("pairedAt")}
