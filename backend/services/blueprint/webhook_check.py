"""Talks to the outside — proven by calling in.

For every integration that calls the application, the check does what the
other end would: signs a sample delivery with the secret and posts it to
`/api/webhooks/<slug>`; sends the same delivery again; sends one with a
bad signature; one with a stale one. Green is a signed call accepted and
the processes that listen for its event started, a replay recognised as
the same delivery, and the forged and stale calls refused. The secret on a
copy is the check's own (`signing_secrets`), put into the copy's
environment at boot, so no real value is ever read.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)


def signing_secrets(doc: dict, env: dict[str, str] | None = None) -> dict[str, str]:
    """A fresh secret for every inbound integration's `signingSecretRef`
    the environment does not already hold."""
    from services.blueprint.projection import inbound_services
    env = os.environ if env is None else env
    return {s["signingSecretRef"]: _secrets.token_urlsafe(24)
            for s in inbound_services(doc) if s["signingSecretRef"] not in env}


def sign(raw: str, secret: str, at: int | None = None) -> str:
    t = int(at if at is not None else time.time())
    v1 = hmac.new(secret.encode(), f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def post(app: Any, path: str, raw: str, headers: dict[str, str]) -> tuple[int, dict]:
    req = urllib.request.Request(f"{app.base}{path}", data=raw.encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read().decode("utf-8", "replace")
            status = int(res.status)
    except urllib.error.HTTPError as exc:
        status, body = int(exc.code), exc.read().decode("utf-8", "replace")
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


def listeners(doc: dict, integration_id: str, event: str) -> list[dict]:
    """The live workflows whose webhook trigger names this integration's event."""
    return [w for w in doc.get("workflows") or []
            if isinstance(w, dict) and str(w.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")
            and str((w.get("trigger") or {}).get("kind") or "") == "webhook"
            and str((w.get("trigger") or {}).get("integration") or "") == integration_id
            and str((w.get("trigger") or {}).get("event") or "") == event]


def check_webhooks(app: Any, doc: dict, *, secrets: dict[str, str] | None = None, only: set[str] | None = None,
                   cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}` over every integration that calls in."""
    from services.blueprint.clock_check import runs_since, slug_of
    from services.blueprint.projection import inbound_services
    secrets = secrets or {}
    rows = {str(r.get("id")): r for r in doc.get("integrations") or [] if isinstance(r, dict)}
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    for svc in inbound_services(doc):
        row = next((r for r in rows.values() if str(r.get("name") or "") == svc["name"]), {})
        iid = str(row.get("id") or svc["slug"])
        if only is not None and iid not in only:
            continue
        name = svc["name"] or svc["slug"]
        it = lambda what, why: item(f"{iid}::{what}", name, why, iid)  # noqa: E731
        if cancelled():
            untried.append(it("signed", "stopped by the person"))
            continue
        secret = secrets.get(svc["signingSecretRef"]) or os.environ.get(svc["signingSecretRef"], "")
        if not secret:
            untried.append(it("signed", f"{svc['signingSecretRef']} is not set, so no call could be signed"))
            continue
        if svc["verify"] == "provider":
            untried.append(it("signed", f"{svc['provider']} signs its own way; proven when its adapter lands"))
            continue
        path = f"/api/webhooks/{svc['slug']}"
        event = svc["events"][0] if svc["events"] else "received"
        delivery = f"check-{uuid.uuid4().hex[:12]}"
        raw = json.dumps({"id": delivery, "type": event, "check": True})
        auth = {"Authorization": f"Bearer {secret}"} if svc["verify"] == "bearer" else {"X-Signature": sign(raw, secret)}
        since = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        try:
            status, body = post(app, path, raw, auth)
            if status == 404:
                untried.append(it("signed", "the app has no webhook route for it"))
                continue
            if status == 503:
                untried.append(it("signed", f"{svc['signingSecretRef']} is not set on the copy"))
                continue
            if status != 202:
                red.append(it("signed", f"a signed call was answered {status}: {str(body.get('error') or '')[:120]}"))
                continue
            green.append(it("signed", "a signed call is accepted"))
            for wf in listeners(doc, iid, event):
                wid = str(wf.get("id"))
                if runs_since(app, slug_of(wf), since):
                    green.append(item(f"{wid}::trigger", str(wf.get("name") or wid), f"starts when {name} sends `{event}`", wid))
                else:
                    red.append(item(f"{wid}::trigger", str(wf.get("name") or wid),
                                    f"`{event}` from {name} was accepted and started nothing", wid))
            status, body = post(app, path, raw, auth)
            if status == 200 and body.get("duplicate"):
                green.append(it("replay", "the same delivery again is recognised, not run twice"))
            else:
                red.append(it("replay", f"the same delivery again was answered {status}, not as a duplicate"))
            if svc["verify"] == "bearer":
                status, _ = post(app, path, raw, {"Authorization": "Bearer not-the-secret"})
                (green if status == 401 else red).append(it("forged", "a call with the wrong token is refused" if status == 401
                                                            else f"a call with the wrong token was answered {status}"))
            else:
                status, _ = post(app, path, raw, {"X-Signature": sign(raw, "not-the-secret")})
                (green if status == 401 else red).append(it("forged", "a forged signature is refused" if status == 401
                                                            else f"a forged signature was answered {status}"))
                status, _ = post(app, path, raw, {"X-Signature": sign(raw, secret, at=int(time.time()) - 3600)})
                (green if status == 401 else red).append(it("stale", "a stale signature is refused" if status == 401
                                                            else f"an hour-old signature was answered {status}"))
        except Exception as exc:  # noqa: BLE001 — the check's own shortfall
            logger.warning("[webhook-check] %s could not be tried", name, exc_info=True)
            untried.append(it("signed", f"the check failed: {str(exc)[:160]}"))
    return {"total": len(green) + len(red) + len(untried), "green": green, "red": red, "untried": untried}


__all__ = ["check_webhooks", "listeners", "post", "sign", "signing_secrets"]
