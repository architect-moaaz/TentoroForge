"""The application on a phone, proven on a running copy.

Installable: the manifest answers as JSON with its icons, each icon is a
PNG of the size it declares, the service worker is served, the offline
page answers, and a page carries the manifest link and the theme colour.
Push: a device subscribed through the app's own route — its endpoint a
listener the check runs — receives a signed (`vapid t=`), encrypted
(`aes128gcm`) message when a notifying process runs for its person, and
nothing once it has unsubscribed. The copy signs with the app's own keys;
the check holds none.
"""
from __future__ import annotations

import base64
import http.server
import json
import logging
import secrets
import socketserver
import struct
import threading
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)


def installable(doc: dict) -> bool:
    from services.blueprint.projection import mobile_policy
    return bool(mobile_policy(doc)["installable"])


def pushing(doc: dict) -> list[dict]:
    """The workflows with a `send_notification` step that names `push`."""
    from services.blueprint.projection import mobile_policy
    if not mobile_policy(doc)["push"]:
        return []
    out = []
    for wf in doc.get("workflows") or []:
        if not isinstance(wf, dict) or str(wf.get("status") or "").upper() in ("DEPRECATED", "REMOVED"):
            continue
        for step in wf.get("steps") or []:
            cfg = step.get("config") if isinstance(step, dict) and isinstance(step.get("config"), dict) else {}
            if str(cfg.get("actionType") or step.get("type") or "") == "send_notification" and "push" in [str(c) for c in cfg.get("channels") or []]:
                out.append(wf)
                break
    return out


def _get(app: Any, path: str, cookies: list[dict] | None = None) -> tuple[int, dict, bytes]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(app.base + path, headers={"cookie": "; ".join(f"{c['name']}={c['value']}" for c in cookies or [])})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _png_size(raw: bytes) -> tuple[int, int] | None:
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return int(w), int(h)


def check_installable(app: Any, doc: dict, *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    if not installable(doc):
        return {"total": 0, "green": green, "red": red, "untried": untried}
    label = "Installs on a phone"
    status, headers, body = _get(app, "/manifest.webmanifest")
    try:
        manifest = json.loads(body.decode("utf-8")) if status == 200 else {}
    except ValueError:
        manifest = {}
    if status != 200 or not isinstance(manifest, dict) or not manifest.get("name"):
        red.append(item("routes", label, f"/manifest.webmanifest answers {status}, not the manifest", "mobile"))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    icons = [i for i in manifest.get("icons") or [] if isinstance(i, dict)]
    if len(icons) < 2:
        red.append(item("routes", label, "the manifest lists fewer than two icons", "mobile"))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    for icon in icons:
        if cancelled():
            break
        s, _h, raw = _get(app, "/" + str(icon.get("src") or "").lstrip("/"))
        size = _png_size(raw) if s == 200 else None
        want = str(icon.get("sizes") or "")
        if size is None or f"{size[0]}x{size[1]}" != want:
            red.append(item("routes", label, f"icon {icon.get('src')} is not a {want} PNG ({s})", "mobile"))
            return {"total": 1, "green": green, "red": red, "untried": untried}
    s, _h, raw = _get(app, "/sw.js")
    if s != 200 or b"forge-shell" not in raw or b"/api/" not in raw:
        red.append(item("routes", label, f"/sw.js answers {s} or is not the shell worker", "mobile"))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    s, _h, _raw = _get(app, "/offline")
    if s != 200:
        red.append(item("routes", label, f"/offline answers {s}; an installed app has nothing to show without a network", "mobile"))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    from services.blueprint.account_model import has_sign_in
    s, _h, html = _get(app, "/login" if has_sign_in(doc) else "/")
    text = html.decode("utf-8", "replace")
    if 'rel="manifest"' not in text or "theme-color" not in text:
        red.append(item("routes", label, "the page does not link the manifest or name a theme colour", "mobile"))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    green.append(item("routes", label, f"manifest, {len(icons)} icons, the shell worker and the offline page all answer", "mobile"))
    return {"total": 1, "green": green, "red": red, "untried": untried}


class _Listener:
    """A push service for the check: records every message it is sent."""

    def __init__(self) -> None:
        self.received: list[dict] = []
        parent = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n) if n else b""
                parent.received.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "size": len(raw)})
                self.send_response(201)
                self.end_headers()

            def log_message(self, *a: Any) -> None:
                pass
        self.server = socketserver.TCPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_Listener":
        self.thread.start()
        return self

    def __exit__(self, *a: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


def device_keys() -> tuple[str, str]:
    """A device's own keys, as a browser would make them: a P-256 public
    point and a 16-byte auth secret, base64url."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return b64(pub), b64(secrets.token_bytes(16))


def _q(s: Any) -> str:
    return str(s).replace("'", "''")


def _rows(app: Any, sql: str) -> list[list[str]]:
    from services.blueprint.page_review import _query
    return _query(app, sql)


def _recipient_role(doc: dict, wf: dict) -> str:
    """The role whose device the message should reach: the step's role,
    else the role that launches the process, else the first role."""
    roles = [str(r.get("name")) for r in doc.get("roles") or [] if isinstance(r, dict) and r.get("name")]
    names = {str(r.get("id")): str(r.get("name")) for r in doc.get("roles") or [] if isinstance(r, dict)}
    for step in wf.get("steps") or []:
        cfg = step.get("config") if isinstance(step, dict) and isinstance(step.get("config"), dict) else {}
        if str(cfg.get("actionType") or "") == "send_notification":
            r = cfg.get("toRole") or cfg.get("recipientRole") or cfg.get("assigneeRole")
            if r and "{{" not in str(r):
                return names.get(str(r), str(r))
    launched = wf.get("launchedFrom") if isinstance(wf.get("launchedFrom"), dict) else {}
    for r in launched.get("roles") or []:
        return names.get(str(r), str(r))
    return roles[0] if roles else ""


def check_push(app: Any, doc: dict, *, bench: Any, cancelled: Callable[[], bool] = lambda: False) -> dict:
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    flows = pushing(doc)
    if not flows:
        return {"total": 0, "green": green, "red": red, "untried": untried}
    wf = flows[0]
    label = f"A push reaches a subscribed device ({wf.get('name')})"
    cause = str(wf.get("id") or "mobile")
    role = _recipient_role(doc, wf)
    rows = _rows(app, f"select id::text from users where role = '{_q(role)}' or account_type = '{_q(role)}' order by created_at limit 1") \
        or _rows(app, f"select id::text from users where role = '{_q(role)}' limit 1")
    if not rows or not rows[0] or not rows[0][0]:
        untried.append(item("systems", label, f"no login of the role {role!r} on the copy to subscribe a device for", cause))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    user_id = rows[0][0]
    p256dh, auth = device_keys()
    from services.smith import trials
    try:
        with _Listener() as listener:
            endpoint = f"http://127.0.0.1:{listener.port}/push/{secrets.token_hex(4)}"
            _rows(app, "insert into forge_push_subscriptions (user_id, endpoint, p256dh, auth, user_agent) values "
                       f"('{_q(user_id)}', '{endpoint}', '{p256dh}', '{auth}', 'forge-check') on conflict (endpoint) do nothing")
            said = trials.try_workflow(bench, doc, str(wf.get("id")), {}, role)
            got = [m for m in listener.received if m["path"].startswith("/push/")]
            if not got:
                red.append(item("systems", label, f"the process ran but no message reached the device ({said[:200]})", cause))
                return {"total": 1, "green": green, "red": red, "untried": untried}
            h = got[0]["headers"]
            if not str(h.get("authorization") or "").lower().startswith("vapid t=") or h.get("content-encoding") != "aes128gcm":
                red.append(item("systems", label, "the message reached the device unsigned or unencrypted", cause))
                return {"total": 1, "green": green, "red": red, "untried": untried}
            _rows(app, f"delete from forge_push_subscriptions where endpoint = '{endpoint}'")
            before = len(listener.received)
            trials.try_workflow(bench, doc, str(wf.get("id")), {}, role)
            if len(listener.received) > before:
                red.append(item("systems", label, "a device that unsubscribed was still sent a message", cause))
                return {"total": 1, "green": green, "red": red, "untried": untried}
    except Exception as exc:  # noqa: BLE001
        red.append(item("systems", label, f"the check crashed: {str(exc)[:200]}", cause))
        return {"total": 1, "green": green, "red": red, "untried": untried}
    green.append(item("systems", label, "signed, encrypted, delivered once; nothing after unsubscribing", cause))
    return {"total": 1, "green": green, "red": red, "untried": untried}


__all__ = ["check_installable", "check_push", "device_keys", "installable", "pushing"]
