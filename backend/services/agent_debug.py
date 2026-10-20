"""Watching a running app's real chats live: the platform's side.

The generated app has a debug route that streams every chat its own people have, step by step (see
``templates/runtime/api-agent/debug-route.ts``). It shows what a customer's chat hides (what the tools returned), so
it is shut unless the platform presents a secret kept in a file in the app's folder, and it only answers in
development. The browser never gets that secret: it asks the platform, and the platform asks the app.

This module keeps the secret, checks where the app is, and passes the stream through. It does not run an agent.

Where the app is: on the same computer as the platform (a plain localhost address, found by looking on the usual ports), or,
when the platform is on a server, on the builder's own computer behind a reverse SSH tunnel (services/agent_tunnel.py), which
has its own secret and its own address that the platform chose, never one a person typed.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from services import agent_tunnel

SECRET_FILE = ".forge-debug-secret"
HEADER = "x-forge-debug-secret"

# The secret is sent to whatever address the builder names, so only this computer is allowed: an address typed
# or pasted from somewhere else must never receive it.
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class DebugError(Exception):
    """Something the builder can act on, in plain words."""


def ensure_debug_secret(app_root: Path) -> str:
    """The app's debug secret, made on first use. Kept out of git."""
    p = Path(app_root) / SECRET_FILE
    if p.is_file():
        existing = p.read_text(encoding="utf-8").strip()
        if existing:
            _git_ignore(Path(app_root))
            return existing
    token = secrets.token_urlsafe(32)
    p.write_text(token + "\n", encoding="utf-8")
    _git_ignore(Path(app_root))
    return token


def read_debug_secret(app_root: Path) -> str | None:
    p = Path(app_root) / SECRET_FILE
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _git_ignore(app_root: Path) -> None:
    gi = app_root / ".gitignore"
    try:
        text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
        if SECRET_FILE not in text.split():
            gi.write_text(text.rstrip("\n") + ("\n" if text else "") + SECRET_FILE + "\n", encoding="utf-8")
    except OSError:
        pass


async def hosting(db: Any, project_id: Any) -> dict[str, Any]:
    """Where the platform knows this project's app is hosted: ``{"vercel": {"url": ..., "environment": ...}}`` when its latest
    live deployment is on Vercel, else ``{}``. An app run on the builder's own computer is not recorded anywhere."""
    from sqlalchemy import select

    from models.deployment import LIVE_STATUSES, Deployment

    row = (await db.execute(
        select(Deployment).where(Deployment.project_id == project_id, Deployment.status.in_(LIVE_STATUSES))
        .order_by(Deployment.created_at.desc()).limit(1))).scalars().first()
    if row is None or row.target != "vercel":
        return {}
    return {"vercel": {"url": row.url or row.deployment_url, "environment": row.environment}}


def clean_app_url(url: str) -> str:
    """The app's address, only if it is on this computer."""
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise DebugError("Enter the app's address, like http://localhost:3000.")
    host = u.hostname.lower()
    if host not in _LOOPBACK and not host.endswith(".localhost"):
        raise DebugError("The live run only talks to an app running on this computer (localhost).")
    return f"{u.scheme}://{u.netloc}"


def _unreachable(url: str) -> DebugError:
    return DebugError(f"Could not reach the app at {url}. Is it running?")


def _off() -> DebugError:
    return DebugError(
        "The app at that address did not accept the live run. Either it is another project's app (each app has its own "
        "key), or this app needs the latest agent runtime (Apply the agent once) and has to be running in development "
        "mode: a production build refuses it on purpose."
    )


#: The ports a development app usually runs on. Only this computer, only these.
_USUAL_PORTS = range(3000, 3011)


async def find_app(secret: str) -> str | None:
    """This project's app, if it is running on one of the usual ports: the one that accepts its key. An app answers
    a wrong key exactly as it answers nothing (a plain 404), so the key is the only way to tell them apart."""
    async def probe(port: int) -> str | None:
        url = f"http://localhost:{port}"
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{url}/api/agent/debug", headers={HEADER: secret})
            if r.status_code != 200:
                return None
            # Not just any 200: a web page or another program's JSON is not this project's app.
            body = r.json()
            return url if isinstance(body, dict) and isinstance(body.get("agents"), list) else None
        except (httpx.HTTPError, ValueError):
            return None

    found = await asyncio.gather(*(probe(p) for p in _USUAL_PORTS))
    return next((u for u in found if u), None)


async def status(app_url: str, secret: str | None) -> dict[str, Any]:
    """Whether the running app at this address can be watched: something answers, it is one of this project's apps
    (it accepts the key), and it is in development. Every way it can fail comes back as a reason in plain words, and
    when this project's app is running at another address on this computer, that address is offered."""
    url = clean_app_url(app_url)
    if not secret:
        return {"ok": False, "appUrl": url, "reason": "This app has no live-run key yet. Apply the agent once to create it."}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            info = await client.get(f"{url}/api/agent/debug", headers={HEADER: secret})
    except httpx.ConnectError:
        return await _not_here(url, secret, str(_unreachable(url)), said=f"Nothing is running at {url}.")
    except httpx.HTTPError as e:
        return await _not_here(url, secret, f"The connection to {url} broke: {e}", said=f"The connection to {url} broke.")
    if info.status_code == 404:
        return await _not_here(url, secret, str(_off()), said=f"Nothing at {url} accepted this project's key.")
    if info.status_code >= 400:
        said = f"Something at {url} answered with an error ({info.status_code}), so it does not look like one of your apps."
        return await _not_here(url, secret, said, said=said)
    try:
        body = info.json()
        agents = body.get("agents", []) if isinstance(body, dict) else None
    except ValueError:
        agents = None
    if agents is None:
        said = f"Something answered at {url}, but it is not one of your apps: it did not answer the way a generated app does."
        return await _not_here(url, secret, said, said=said)
    return {"ok": True, "appUrl": url, "agents": agents}


# ---------------------------------------------------------------------------
# the app on the builder's own computer, behind its reverse SSH tunnel
# ---------------------------------------------------------------------------

NOT_PAIRED = ("This computer has not been connected yet. Press Connect your computer, run the one command it shows on the computer "
              "where the app is running, then press Connect again.")
TUNNEL_DOWN = ("Your computer is not connected right now: the tunnel to it is down (the connector stopped, the computer slept, or "
               "its network dropped). Start the connector again; it reconnects by itself after that.")


WRONG_KEY = ("An app is answering on your computer, but it does not accept Watch live's key. Most likely the connector was run from a "
             "different folder than the app (it puts the key in the folder it is run from): run it again from the app's own folder. "
             "Otherwise it is another project's app, a production build (a Docker image refuses on purpose), or it needs the latest "
             "agent runtime (Apply the agent once and download the app again).")


def _nothing_answers(app_port: Any) -> str:
    where = f"port {app_port}" if app_port else "the port it was paired with"
    return (f"Your computer is connected, but nothing answered on {where} there. Start the app on that computer "
            "(for example `npm run dev`) and press Connect again.")


async def tunnel_status(project_id: str) -> dict[str, Any]:
    """Can the app on the builder's computer be watched? Checked in the order a builder can fix things: is a computer paired,
    is its tunnel up, does the app answer behind it, does the app accept this project's key. Each failure is one plain
    sentence. Returns the same shape as ``status``, plus the tunnel's state."""
    state = await asyncio.to_thread(agent_tunnel.describe, project_id)
    if not state["enabled"]:
        return {"ok": False, "reason": "This platform runs on your own computer, so there is nothing to connect: use the app's address.", "tunnel": state}
    if not state["registered"]:
        return {"ok": False, "reason": NOT_PAIRED, "tunnel": state}
    if not state["connected"]:
        return {"ok": False, "reason": TUNNEL_DOWN, "tunnel": state}
    reg = agent_tunnel.get(project_id) or {}
    url = agent_tunnel.target_url(project_id)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            info = await client.get(f"{url}/api/agent/debug", headers={HEADER: reg.get("secret", "")})
    except httpx.ConnectError:
        return {"ok": False, "reason": TUNNEL_DOWN, "tunnel": {**state, "connected": False}}
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout, httpx.WriteError):
        # the tunnel accepted the request and the builder's computer had nothing to give it to
        return {"ok": False, "reason": _nothing_answers(state.get("appPort")), "tunnel": state}
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"The connection to your computer broke: {e}", "tunnel": state}
    if info.status_code == 404:
        return {"ok": False, "reason": WRONG_KEY, "tunnel": state}
    if info.status_code >= 400:
        return {"ok": False, "tunnel": state,
                "reason": f"Something on your computer answered with an error ({info.status_code}), so it does not look like one of your apps."}
    try:
        body = info.json()
        agents = body.get("agents") if isinstance(body, dict) else None
    except ValueError:
        agents = None
    if not isinstance(agents, list):
        return {"ok": False, "tunnel": state,
                "reason": "Something answered on your computer, but it is not one of your apps: it did not answer the way a generated app does."}
    return {"ok": True, "appUrl": f"your computer, port {state.get('appPort')}", "agents": agents, "tunnel": state}


async def _not_here(url: str, secret: str, reason: str, said: str | None = None) -> dict[str, Any]:
    """The address did not work. If this project's app is running somewhere else on this computer, say where: `said`
    is what is true of this address, then where the app is. Otherwise the fuller `reason` stands alone."""
    other = await find_app(secret)
    if other and other.rstrip("/") != url.rstrip("/"):
        return {"ok": False, "appUrl": url, "suggestedUrl": other,
                "reason": f"{said or reason} This project's app is running at {other}."}
    return {"ok": False, "appUrl": url, "reason": reason}


async def watch_stream(app_url: str, secret: str | None, role: str | None = None,
                       user_id: str | None = None, *, trusted: bool = False) -> AsyncIterator[bytes]:
    """The app's chats as they happen, passed through as the app sends them. Stays open until the builder closes it;
    a failure or a dropped connection is one ``error`` event, so the screen can say so and reconnect.

    With ``role`` or ``user_id`` (a person outranks a role) the APP only sends that role's or that person's chats:
    the builder watching one role is never sent another's."""
    def event(message: str) -> bytes:
        return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n".encode()

    try:
        # ``trusted``: the address was chosen by the platform (a tunnel it set up), not typed by a person
        url = app_url.rstrip("/") if trusted else clean_app_url(app_url)
    except DebugError as e:
        yield event(str(e))
        return
    if not secret:
        yield event("This app has no live-run key yet. Apply the agent once to create it.")
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10)) as client:
            params = {"watch": "1", **({"user": user_id} if user_id else {"role": role} if role else {})}
            async with client.stream("GET", f"{url}/api/agent/debug", params=params, headers={HEADER: secret}) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "ignore")
                    yield event(_message_of(body) or str(_off()))
                    return
                async for chunk in r.aiter_bytes():
                    yield chunk
    except httpx.ConnectError:
        yield event(TUNNEL_DOWN if trusted else str(_unreachable(url)))
    except httpx.HTTPError as e:
        yield event(f"The connection to your computer broke ({type(e).__name__}). Check that the app and the connector are still running."
                    if trusted else f"The connection to the app broke: {e}")


def flow_map(graph: dict[str, Any]) -> dict[str, Any]:
    """Which box on the canvas each thing the runtime does belongs to, so the live view can light the right one.

    ``tools`` maps a tool's compiled name to its box; ``toolInfo`` says what each tool accepts (so a call's input can
    be checked); ``kinds`` lists the boxes of each other kind (the runtime
    checks the message and the answer with the guardrail box(es), loads memory with the memory box, asks the model
    with the system-prompt box, and hands over with the human-handoff box). The runtime works in a fixed order and
    does not walk the arrows; this says which box stands for each step of it."""
    from services.agent_check import _kind, _tool_nodes_by_name
    from services.agent_runtime_config import compile_agent

    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    kinds: dict[str, list[str]] = {}
    for n in nodes:
        k = _kind(n)
        if k and k != "tool":
            kinds.setdefault(k, []).append(str(n.get("id")))
    tool_info = {
        t["name"]: {"kind": t.get("kind"), "description": t.get("description"), "confirm": bool(t.get("confirm")),
                    "inputSchema": t.get("inputSchema")}
        for t in compile_agent(graph).config.get("tools", [])
    }
    return {"tools": _tool_nodes_by_name(nodes), "kinds": kinds, "toolInfo": tool_info}


def _message_of(body: str) -> str | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    err = data.get("error") if isinstance(data, dict) else None
    return err if isinstance(err, str) and err != "Not found." else None
