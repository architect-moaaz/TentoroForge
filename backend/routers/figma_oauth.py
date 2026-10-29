"""Connect Figma: the person's own sign-in to Figma (`services.figma.oauth`).

  GET    /api/me/figma                 whether this person is connected, and as whom
  POST   /api/me/figma/connect         the figma.com address to sign in at
  DELETE /api/me/figma                 forget this person's Figma tokens
  GET    /api/figma/oauth/callback     where Figma sends the browser back

The callback is not signed in: it is Figma's redirect, opened in the window the
panel popped up. The signed ``state`` says whose connection it is. It answers
with a small page that tells the panel which opened it and closes, or, opened
on its own, goes back to where the person started.

No route returns a token: the account's name is what the person sees.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.figma import oauth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["figma"])


class ConnectRequest(BaseModel):
    #: The page to come back to. Kept only when it is on an allowed origin.
    return_to: str = ""
    #: The sign-in runs in a window the panel opened: it closes at the end
    #: rather than going back to `return_to`.
    popup: bool = False


def _origin(url: str) -> str:
    parts = urlparse(url or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") and parts.netloc else ""


def _allowed(origin: str) -> bool:
    import config

    return bool(origin) and origin in {o.strip().rstrip("/") for o in config.ALLOWED_ORIGINS}


def _return_to(asked: str, request: Request) -> str:
    """Where the browser goes after the sign-in: the page asked for, the
    caller's origin, or nowhere — never an address on another site."""
    if _allowed(_origin(asked)):
        return asked
    origin = str(request.headers.get("origin") or "").rstrip("/")
    return origin if _allowed(origin) else ""


@router.get("/api/me/figma")
async def figma_status(user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await oauth.status(db, user.id)


@router.post("/api/me/figma/connect")
async def figma_connect(body: ConnectRequest, request: Request,
                        user: PlatformUser = Depends(get_current_user)) -> dict[str, str]:
    if getattr(request.state, "impersonated_by", None):
        # The Figma account would be theirs, kept as the person's.
        raise HTTPException(status_code=403, detail="Connect Figma as yourself, not while viewing as someone else.")
    if not oauth.configured():
        raise HTTPException(status_code=503, detail=(
            "Connect Figma is not set up on this platform yet: an administrator registers Forge as a "
            "Figma OAuth app. Paste a Figma access token instead."))
    redirect = oauth.redirect_uri(str(request.base_url))
    url = oauth.authorize_url(user.id, return_to=_return_to(body.return_to, request), redirect=redirect,
                              popup=body.popup)
    return {"url": url}


@router.delete("/api/me/figma")
async def figma_disconnect(user: PlatformUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    removed = await oauth.disconnect(db, user.id)
    return {"connected": False, "removed": removed}


def _finish(return_to: str, outcome: dict[str, str], *, popup: bool = False) -> HTMLResponse:
    """The page the sign-in window lands on. In the window the panel opened it
    tells the panel and closes — Figma's pages may have cut the window off from
    its opener, so the panel also asks for the status itself; in the person's
    own tab it goes back to ``return_to``."""
    target = ""
    if return_to:
        sep = "&" if "?" in return_to else "?"
        target = f"{return_to}{sep}{urlencode({'figma': outcome['figma']})}"
    # `</` cannot close the script from inside a JSON string.
    data = json.dumps({"source": "forge-figma", **outcome}).replace("</", "<\\/")
    origin = json.dumps(_origin(return_to) or "*").replace("</", "<\\/")
    back = json.dumps(target).replace("</", "<\\/")
    said = ("Figma is connected. You can close this window." if outcome["figma"] == "connected"
            else f"Figma was not connected: {outcome.get('reason') or 'the sign-in did not finish'}")
    from html import escape

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Connect Figma</title></head>
<body style="font-family:system-ui,sans-serif;padding:2rem">
<p>{escape(said)}</p>
<script>
(function () {{
  var data = {data}, origin = {origin}, back = {back}, popup = {json.dumps(bool(popup))};
  if (window.opener && !window.opener.closed) {{
    try {{ window.opener.postMessage(data, origin); }} catch (e) {{}}
  }}
  if (popup) {{
    window.close();
  }} else if (back) {{
    window.location.replace(back);
  }}
}})();
</script></body></html>"""
    return HTMLResponse(page, status_code=200 if outcome["figma"] == "connected" else 400)


@router.get(oauth.CALLBACK_PATH)
async def figma_callback(request: Request, code: str = "", state: str = "", error: str = "",
                         db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    try:
        claimed = oauth.read_state(state)
    except oauth.FigmaOAuthError as exc:
        return _finish("", {"figma": "error", "reason": str(exc)})
    return_to, popup = claimed["return_to"], claimed["popup"]
    if error or not code:
        return _finish(return_to, {"figma": "error", "reason": "Figma did not grant access."}, popup=popup)
    try:
        user_id = uuid.UUID(claimed["user_id"])
        tokens = await asyncio.to_thread(oauth.exchange, code, claimed["redirect_uri"])
        me = await asyncio.to_thread(oauth.account, tokens.access_token)
        await oauth.save(db, user_id, tokens, me)
    except oauth.FigmaOAuthError as exc:
        logger.warning("[figma-oauth] callback for %s failed: %s", claimed.get("user_id"), exc)
        return _finish(return_to, {"figma": "error", "reason": str(exc)}, popup=popup)
    except Exception as exc:  # noqa: BLE001 — said to the person, never the token
        logger.warning("[figma-oauth] callback failed: %s", type(exc).__name__)
        return _finish(return_to, {"figma": "error", "reason": "Forge could not keep the connection."},
                       popup=popup)
    logger.info("[figma-oauth] %s connected Figma as %s", claimed.get("user_id"), me.get("handle") or "-")
    return _finish(return_to, {"figma": "connected", "account": me.get("handle") or me.get("email") or ""},
                   popup=popup)
