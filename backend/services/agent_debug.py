"""The builder's live run: the platform's side.

The generated app has a debug route that runs its REAL chat loop as a chosen person and streams every step
(see ``templates/runtime/api-agent/debug-route.ts``). It sees what a customer's chat hides and can act as any
user, so it is shut unless the platform presents a secret kept in a file in the app's folder, and it only answers
in development. The browser never gets that secret: it asks the platform, and the platform asks the app.

This module keeps the secret, checks where the app is, and passes the stream through. It does not run an agent.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

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
            return url if r.status_code == 200 else None
        except httpx.HTTPError:
            return None

    found = await asyncio.gather(*(probe(p) for p in _USUAL_PORTS))
    return next((u for u in found if u), None)


async def status(app_url: str, secret: str | None) -> dict[str, Any]:
    """Whether the live run works against this app, who it can run as, and which agents are installed."""
    url = clean_app_url(app_url)
    if not secret:
        return {"ok": False, "appUrl": url, "reason": "This app has no live-run key yet. Apply the agent once to create it."}
    headers = {HEADER: secret}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            info = await client.get(f"{url}/api/agent/debug", headers=headers)
            if info.status_code == 404:
                return await _not_here(url, secret, str(_off()))
            info.raise_for_status()
            users = await client.get(f"{url}/api/agent/debug", params={"users": "1"}, headers=headers)
            users.raise_for_status()
    except httpx.ConnectError:
        return await _not_here(url, secret, str(_unreachable(url)))
    except httpx.HTTPError as e:
        return {"ok": False, "appUrl": url, "reason": f"The app answered with an error: {e}"}
    body, people = info.json(), users.json()
    return {"ok": True, "appUrl": url, "agents": body.get("agents", []), "users": people.get("users", []),
            "usersNote": people.get("note")}


async def _not_here(url: str, secret: str, reason: str) -> dict[str, Any]:
    """The address did not work. If this project's app is running somewhere else on this computer, say where."""
    other = await find_app(secret)
    if other and other.rstrip("/") != url.rstrip("/"):
        return {"ok": False, "appUrl": url, "suggestedUrl": other,
                "reason": f"Nothing at {url} accepted this project's key, but this project's app is running at {other}."}
    return {"ok": False, "appUrl": url, "reason": reason}


async def stream_run(app_url: str, secret: str | None, payload: dict[str, Any]) -> AsyncIterator[bytes]:
    """The app's event stream, passed through as it arrives. Failures become one ``error`` event, so the screen
    can show them next to the run instead of the stream just stopping."""
    def event(message: str) -> bytes:
        return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n".encode()

    try:
        url = clean_app_url(app_url)
    except DebugError as e:
        yield event(str(e))
        return
    if not secret:
        yield event("This app has no live-run key yet. Apply the agent once to create it.")
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
            async with client.stream("POST", f"{url}/api/agent/debug", json=payload, headers={HEADER: secret}) as r:
                if r.status_code == 404:
                    body = (await r.aread()).decode("utf-8", "ignore")
                    yield event(_message_of(body) or str(_off()))
                    return
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "ignore")
                    yield event(_message_of(body) or f"The app answered {r.status_code}.")
                    return
                async for chunk in r.aiter_bytes():
                    yield chunk
    except httpx.ConnectError:
        yield event(str(_unreachable(url)))
    except httpx.HTTPError as e:
        yield event(f"The connection to the app broke: {e}")


def _message_of(body: str) -> str | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    err = data.get("error") if isinstance(data, dict) else None
    return err if isinstance(err, str) and err != "Not found." else None
