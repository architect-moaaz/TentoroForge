"""A preview is served at an origin of its own, never at the platform's.

The preview runs the application's code — written by a model, with packages
it installed. Served under the platform's own address, in a frame the
browser let act as that address, that code could read the signed-in
person's token from the platform's storage (audit, 2026-11-01). It is served
only at ``FORGE_PREVIEW_ORIGIN`` now: another origin, so the platform's
storage is out of its reach, and on the same site (a sub-domain in
production, another port on a developer's machine) so the app's own sign-in
cookies still work inside the frame.

The editor works across that line by message. Every HTML page the preview
serves carries a small loader (`LOADER`) that takes the editor's bridge from
the editor's origin only; the instant pages run in a host page on the same
origin (`frame_host`), handed their script the same way. Nothing reaches into
the frame's document from outside it.

Who may be served preview content: a browser at the preview's origin, or the
platform's own checks calling the backend directly (no forwarding header, a
private address). Anything that came through the platform's origin — the
frontend's rewrite of ``/api/projects/*`` — is refused.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from urllib.parse import urlparse

from fastapi import Request

_FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip")


def origin() -> str:
    import config

    return config.PREVIEW_ORIGIN


def configured() -> bool:
    """The platform named its preview origin (production). On a developer's
    machine it is the backend's own port, which also serves the platform's API."""
    return bool(os.environ.get("FORGE_PREVIEW_ORIGIN", "").strip())


def _host(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    return (forwarded or request.headers.get("host") or "").lower()


def on_preview_origin(request: Request) -> bool:
    return _host(request) == urlparse(origin()).netloc.lower()


def from_a_check(request: Request) -> bool:
    """The platform's own checks (Verify & fix, a page review) call the
    backend directly: nothing forwarded it, and it is not a public address."""
    if any(h in request.headers for h in _FORWARDED):
        return False
    host = request.client.host if request.client else ""
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a named in-process client (a test's)


def may_serve(request: Request) -> bool:
    return on_preview_origin(request) or from_a_check(request)


_PREVIEW_PATH = re.compile(r"^/api/projects/[^/]+/preview/(serve(/.*)?|frame)$|^/drawn/|^/api/preview/origin$")


def is_preview_path(path: str) -> bool:
    return bool(_PREVIEW_PATH.match(path or ""))


def editor_origins() -> list[str]:
    import config

    return [o.strip().rstrip("/") for o in config.ALLOWED_ORIGINS if o.strip()]


def _script(body: str) -> str:
    return body.replace("__EDITORS__", json.dumps(editor_origins()).replace("</", "<\\/"))


#: In every HTML page the preview serves. It runs the editor's bridge when the
#: editor sends it — from an editor origin only — and tells the bridge which
#: origin the editor is. Outside an editor's frame it does nothing.
LOADER = _script("""(function(){
if(window.__forgeLoader||window.parent===window)return;window.__forgeLoader=1;
var O=__EDITORS__;
addEventListener("message",function(e){
 if(O.indexOf(e.origin)<0||e.source!==window.parent)return;
 var d=e.data||{};
 if(d.type==="forge-editor:bridge"&&!window.__forgeEditorBridge&&d.payload&&d.payload.code){
  window.__forgeEditorParent=e.origin;
  var s=document.createElement("script");s.textContent=d.payload.code;(document.head||document.documentElement).appendChild(s);
 }
});
function ready(){window.parent.postMessage({type:"forge-editor:loader-ready",payload:{}},"*");}
if(document.readyState==="loading")addEventListener("DOMContentLoaded",ready);else ready();
})();""")


def inject_loader(html: bytes) -> bytes:
    tag = b"<script>" + LOADER.encode() + b"</script>"
    low = html.lower()
    at = low.find(b"</head>")
    if at < 0:
        at = low.find(b"<body")
    if at < 0:
        return tag + html
    return html[:at] + tag + html[at:]


def frame_host() -> str:
    """The page an instant page runs in: the editor sends the shared script,
    the page's own and the bridge (`mount`), later builds of the same page
    (`swap`). It was a blob of the editor's own origin, so the page's code ran
    as the platform."""
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style id="forge-page-css"></style></head><body><div id="root"></div><script>""" + _script("""(function(){
var O=__EDITORS__,parentOrigin=null;
function run(code){if(!code)return;var s=document.createElement("script");s.textContent=code;document.body.appendChild(s);s.remove();}
function css(text){document.getElementById("forge-page-css").textContent=text||"";}
addEventListener("message",function(e){
 if(O.indexOf(e.origin)<0||e.source!==window.parent)return;
 var d=e.data||{},p=d.payload||{};
 if(d.type==="forge-editor:mount"&&!parentOrigin){
  parentOrigin=e.origin;window.__forgeEditorParent=e.origin;
  css(p.css);run(p.vendor);run(p.js);run(p.bridge);
 }else if(d.type==="forge-editor:swap"&&parentOrigin===e.origin){
  css(p.css);run(p.js);window.parent.postMessage({type:"forge-editor:swapped",payload:{}},e.origin);
 }
});
window.parent.postMessage({type:"forge-editor:host-ready",payload:{}},"*");
})();""") + "</script></body></html>"


__all__ = ["origin", "configured", "on_preview_origin", "from_a_check", "may_serve", "is_preview_path", "editor_origins",
           "LOADER", "inject_loader", "frame_host"]
