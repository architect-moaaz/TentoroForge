"""Connect Figma: a person signs in to Figma, and Forge reads their files as them.

THE SHARED TOKEN OPENS ONLY ITS OWNER'S FILES. Every read went through one
personal access token (`FIGMA_TOKEN`, or the organisation's under Settings →
Integrations). On 2026-10-29 a client's full Figma project answered "not found"
for it, and the person had to copy the design into a file that token could see.
Here each person grants Forge read access with Figma's REST OAuth, and while
they are the one acting (`services.build_usage.acting`) every REST read uses
their token; without one, the shared token as before.

THE FLOW. `authorize_url` sends the browser to figma.com/oauth with a signed
``state`` naming the person; Figma calls `/api/figma/oauth/callback` with a
code that lives thirty seconds; `exchange` trades it for an access token
(ninety days) and a refresh token, `account` asks who signed in, and `save`
seals both tokens into `platform_person_connections`. `person_token` hands the
access token to a read, refreshed first when it is close to expiring.

THE SCOPES ARE READ-ONLY: `current_user:read` for the account's name, and
`file_content:read` for nodes and renders. Nothing here can write to a file.

NOTHING HERE LOGS OR RETURNS A TOKEN. Errors carry Figma's status and a
redacted reason; the API returns the account's name, never the token.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from services.figma.credentials import OAuthAccessToken, redact

logger = logging.getLogger(__name__)

PROVIDER = "figma"
#: The subkey the tokens are sealed under: not the organisation's (`figma`),
#: so a row of one kind can never be decrypted as the other.
SEAL = "figma-oauth"
SCOPES = "current_user:read,file_content:read"
AUTHORIZE_URL = "https://www.figma.com/oauth"
CALLBACK_PATH = "/api/figma/oauth/callback"
#: A token this close to its end is refreshed before it is handed to a read:
#: a build can run an hour, and Figma keeps one live token per person and app.
REFRESH_MARGIN = timedelta(hours=2)
_STATE_TYPE = "figma_oauth"
_STATE_TTL_S = 600

CLIENT_ID_ENV = "FIGMA_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "FIGMA_OAUTH_CLIENT_SECRET"
REDIRECT_URI_ENV = "FIGMA_OAUTH_REDIRECT_URI"


class FigmaOAuthError(RuntimeError):
    """The flow could not finish. The message is safe to show; it holds no token."""

    def __init__(self, message: str, *, status: int = 0) -> None:
        self.status = status
        super().__init__(redact(message))


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: datetime | None
    account_id: str = ""

    def __repr__(self) -> str:  # never the values
        return f"Tokens(expires_at={self.expires_at!r}, account_id={self.account_id!r})"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def _api_base() -> str:
    return (os.environ.get("FIGMA_API_BASE") or "https://api.figma.com").rstrip("/")


def configured() -> bool:
    """The platform has an OAuth app registered with Figma."""
    return bool((os.environ.get(CLIENT_ID_ENV) or "").strip()
                and (os.environ.get(CLIENT_SECRET_ENV) or "").strip())


def _client() -> tuple[str, str]:
    cid = (os.environ.get(CLIENT_ID_ENV) or "").strip()
    secret = (os.environ.get(CLIENT_SECRET_ENV) or "").strip()
    if not (cid and secret):
        raise FigmaOAuthError(
            f"Connect Figma is not set up on this platform: {CLIENT_ID_ENV} and "
            f"{CLIENT_SECRET_ENV} are not configured.")
    return cid, secret


def redirect_uri(request_base: str) -> str:
    """Where Figma sends the browser back: the configured address, else this
    API's own. It must be one of the redirect URLs registered on the app."""
    configured_uri = (os.environ.get(REDIRECT_URI_ENV) or "").strip()
    return configured_uri or f"{request_base.rstrip('/')}{CALLBACK_PATH}"


# --------------------------------------------------------------------------- #
# The state: who asked, and where to go back to
# --------------------------------------------------------------------------- #

def make_state(user_id: uuid.UUID | str, *, return_to: str, redirect: str, popup: bool = False) -> str:
    """A signed, short-lived ``state``: the callback is not signed in (it is
    Figma's redirect), so the state is what says whose connection this is."""
    import jwt

    from config import JWT_ALGORITHM, SECRET_KEY

    now = int(time.time())
    return jwt.encode({"type": _STATE_TYPE, "sub": str(user_id), "ret": return_to, "ruri": redirect,
                       "pop": bool(popup), "n": secrets.token_urlsafe(12), "iat": now, "exp": now + _STATE_TTL_S},
                      SECRET_KEY, algorithm=JWT_ALGORITHM)


def read_state(state: str) -> dict[str, str]:
    import jwt

    from config import JWT_ALGORITHM, SECRET_KEY

    try:
        payload = jwt.decode(state or "", SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise FigmaOAuthError("The Figma sign-in took too long. Try Connect Figma again.") from exc
    except jwt.PyJWTError as exc:
        raise FigmaOAuthError("The Figma sign-in came back with a state Forge did not issue.") from exc
    if payload.get("type") != _STATE_TYPE or not payload.get("sub"):
        raise FigmaOAuthError("The Figma sign-in came back with a state Forge did not issue.")
    return {"user_id": str(payload["sub"]), "return_to": str(payload.get("ret") or ""),
            "redirect_uri": str(payload.get("ruri") or ""), "popup": bool(payload.get("pop"))}


def authorize_url(user_id: uuid.UUID | str, *, return_to: str, redirect: str, popup: bool = False) -> str:
    from urllib.parse import urlencode

    cid, _ = _client()
    return f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": cid, "redirect_uri": redirect, "scope": SCOPES,
        "state": make_state(user_id, return_to=return_to, redirect=redirect, popup=popup),
        "response_type": "code",
    })


# --------------------------------------------------------------------------- #
# Figma's endpoints
# --------------------------------------------------------------------------- #

def _basic() -> str:
    cid, secret = _client()
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode("ascii")


def _expiry(body: dict[str, Any]) -> datetime | None:
    try:
        seconds = int(body.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    return datetime.now(timezone.utc) + timedelta(seconds=seconds) if seconds > 0 else None


def _post(path: str, form: dict[str, str]) -> dict[str, Any]:
    import httpx

    try:
        r = httpx.post(f"{_api_base()}{path}", data=form, timeout=30.0,
                       headers={"Authorization": _basic(),
                                "Content-Type": "application/x-www-form-urlencoded"})
    except httpx.HTTPError as exc:
        raise FigmaOAuthError(f"Figma could not be reached ({type(exc).__name__}).") from exc
    if r.status_code != 200:
        raise FigmaOAuthError(f"Figma refused the sign-in ({r.status_code}).", status=r.status_code)
    try:
        return r.json() or {}
    except ValueError as exc:
        raise FigmaOAuthError("Figma answered the sign-in with something that is not JSON.") from exc


def exchange(code: str, redirect: str) -> Tokens:
    """The code Figma handed the callback, for an access and a refresh token."""
    body = _post("/v1/oauth/token", {"redirect_uri": redirect, "code": code,
                                     "grant_type": "authorization_code"})
    access = str(body.get("access_token") or "")
    if not access:
        raise FigmaOAuthError("Figma's answer to the sign-in held no access token.")
    return Tokens(access_token=access, refresh_token=str(body.get("refresh_token") or ""),
                  expires_at=_expiry(body),
                  account_id=str(body.get("user_id_string") or body.get("user_id") or ""))


def refresh(refresh_token: str) -> Tokens:
    """A new access token. Figma's refresh answer carries no new refresh token,
    so the one given stays in use unless one comes back."""
    body = _post("/v1/oauth/refresh", {"refresh_token": refresh_token})
    access = str(body.get("access_token") or "")
    if not access:
        raise FigmaOAuthError("Figma's answer to the refresh held no access token.")
    return Tokens(access_token=access, refresh_token=str(body.get("refresh_token") or refresh_token),
                  expires_at=_expiry(body))


def account(access_token: str) -> dict[str, str]:
    """Who signed in: ``{"id", "handle", "email"}`` from `/v1/me`."""
    import httpx

    try:
        r = httpx.get(f"{_api_base()}/v1/me", timeout=30.0,
                      headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as exc:
        raise FigmaOAuthError(f"Figma could not be reached ({type(exc).__name__}).") from exc
    if r.status_code != 200:
        raise FigmaOAuthError(f"Figma would not say who signed in ({r.status_code}).", status=r.status_code)
    me = r.json() or {}
    return {"id": str(me.get("id") or ""), "handle": str(me.get("handle") or ""),
            "email": str(me.get("email") or "")}


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #

def _seal(value: str) -> tuple[str, str]:
    from services.platform_integrations_crypto import encrypt

    return encrypt(SEAL, value)


def _open(ct: str | None, iv: str | None) -> str:
    from services.platform_integrations_crypto import decrypt

    return decrypt(SEAL, ct, iv) if ct and iv else ""


async def save(db: Any, user_id: uuid.UUID, tokens: Tokens, me: dict[str, str]) -> Any:
    """The person's connection, made or replaced. Commits."""
    from sqlalchemy import select

    from models.person_connection import PersonConnection

    row = (await db.execute(select(PersonConnection).where(
        PersonConnection.user_id == user_id, PersonConnection.provider == PROVIDER))).scalars().first()
    if row is None:
        row = PersonConnection(user_id=user_id, provider=PROVIDER, access_ct="", access_iv="")
        db.add(row)
    row.access_ct, row.access_iv = _seal(tokens.access_token)
    if tokens.refresh_token:
        row.refresh_ct, row.refresh_iv = _seal(tokens.refresh_token)
    row.expires_at = tokens.expires_at
    row.scope = SCOPES
    row.account_id = me.get("id") or tokens.account_id or None
    row.account_name = me.get("handle") or None
    row.account_email = me.get("email") or None
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return row


async def status(db: Any, user_id: uuid.UUID) -> dict[str, Any]:
    """What the person may see of their connection: the account, not the token."""
    from sqlalchemy import select

    from models.person_connection import PersonConnection

    row = (await db.execute(select(PersonConnection).where(
        PersonConnection.user_id == user_id, PersonConnection.provider == PROVIDER))).scalars().first()
    out: dict[str, Any] = {"configured": configured(), "connected": row is not None}
    if row is not None:
        out["account"] = {"handle": row.account_name or "", "email": row.account_email or ""}
        out["connected_at"] = (row.updated_at or row.created_at).isoformat() if (row.updated_at or row.created_at) else None
    return out


async def disconnect(db: Any, user_id: uuid.UUID) -> bool:
    """Forget the person's tokens. True when there was a connection."""
    from sqlalchemy import delete

    from models.person_connection import PersonConnection

    res = await db.execute(delete(PersonConnection).where(
        PersonConnection.user_id == user_id, PersonConnection.provider == PROVIDER))
    await db.commit()
    return bool(res.rowcount)


# --------------------------------------------------------------------------- #
# The token a read uses
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PersonToken:
    token: OAuthAccessToken
    account: str

    def __repr__(self) -> str:
        return f"PersonToken(account={self.account!r})"


async def _load(email: str) -> dict[str, Any] | None:
    from sqlalchemy import func as sa_func, select

    from models.auth import PlatformUser
    from models.person_connection import PersonConnection
    from services.figma.integrations import _session_on_this_loop

    async with _session_on_this_loop() as db:
        row = (await db.execute(
            select(PersonConnection).join(PlatformUser, PlatformUser.id == PersonConnection.user_id).where(
                sa_func.lower(PlatformUser.email) == email.strip().lower(),
                PersonConnection.provider == PROVIDER))).scalars().first()
        if row is None:
            return None
        return {"user_id": row.user_id, "access": _open(row.access_ct, row.access_iv),
                "refresh": _open(row.refresh_ct, row.refresh_iv), "expires_at": row.expires_at,
                "account": row.account_name or row.account_email or ""}


async def _store_refreshed(user_id: uuid.UUID, tokens: Tokens) -> None:
    from sqlalchemy import select

    from models.person_connection import PersonConnection
    from services.figma.integrations import _session_on_this_loop

    async with _session_on_this_loop() as db:
        row = (await db.execute(select(PersonConnection).where(
            PersonConnection.user_id == user_id, PersonConnection.provider == PROVIDER))).scalars().first()
        if row is None:  # disconnected while refreshing: stays disconnected
            return
        row.access_ct, row.access_iv = _seal(tokens.access_token)
        if tokens.refresh_token:
            row.refresh_ct, row.refresh_iv = _seal(tokens.refresh_token)
        row.expires_at = tokens.expires_at
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()


def _aware(at: datetime | None) -> datetime | None:
    if at is not None and at.tzinfo is None:
        return at.replace(tzinfo=timezone.utc)
    return at


def _due(at: datetime | None) -> bool:
    at = _aware(at)
    return at is not None and at - datetime.now(timezone.utc) < REFRESH_MARGIN


#: ONE REFRESH PER PERSON AT A TIME. Pages are composed twelve at once, each on
#: its own thread, and Figma keeps one live token per person and app: twelve
#: refreshes would leave eleven threads holding tokens the twelfth revoked.
_REFRESH_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(email: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _REFRESH_LOCKS.setdefault(email, threading.Lock())


def person_token(email: str | None = None) -> PersonToken | None:
    """The acting person's Figma token, refreshed when due — or None.

    ``email`` defaults to the person `build_usage.acting` names, which a
    request sets and a build carries into its threads. None when nobody is
    acting, they have not connected Figma, or the store cannot be read; the
    caller then reads with the shared token. Never raises.
    """
    from services.figma.integrations import _run

    if email is None:
        from services.build_usage import actor

        email = actor().get("user") or ""
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        found = _run(_load(email))
        if not found or not found["access"]:
            return None
        if _due(found["expires_at"]) and found["refresh"] and configured():
            with _lock_for(email):
                found = _run(_load(email)) or found      # another thread may have refreshed it
                if _due(found["expires_at"]) and found["refresh"]:
                    try:
                        tokens = refresh(found["refresh"])
                    except FigmaOAuthError as exc:
                        # The token in hand may still have hours to run: used until it ends.
                        logger.warning("[figma-oauth] refresh failed: %s", exc)
                    else:
                        _run(_store_refreshed(found["user_id"], tokens))
                        found = {**found, "access": tokens.access_token, "expires_at": tokens.expires_at}
        expired = _aware(found["expires_at"])
        if expired is not None and expired <= datetime.now(timezone.utc):
            logger.info("[figma-oauth] the connected token has expired and could not be refreshed")
            return None
        return PersonToken(token=OAuthAccessToken(found["access"]), account=str(found["account"] or ""))
    except Exception as exc:  # noqa: BLE001 — the shared token is the fallback
        logger.info("[figma-oauth] person token unavailable (%s)", type(exc).__name__)
        return None
