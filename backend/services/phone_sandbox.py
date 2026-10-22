"""What a phone picture needs to run in a sandbox.

The picture (`/phone/live` and `/phone/serve`) is a generated app's code, and it is served from the platform's own address. The platform keeps
its sign-in in `localStorage`, so code on the same origin could read a viewer's token; the picture's link needs no sign-in, so it can be sent
to anyone signed in (PR #28 review, 2026-10-22). The responses carry `Content-Security-Policy: sandbox allow-scripts` (see
`middleware/security_headers.py`) and the Editor's iframe has `sandbox="allow-scripts"`: the page gets an origin of its own, with no storage and
no cookies.

A sandboxed page that touches `localStorage`, `sessionStorage` or `document.cookie` gets a SecurityError, and a phone app's session and
settings code does (on the web, AsyncStorage is `localStorage`). So the page starts with a small stand-in that keeps those in memory for as long
as the picture is open, which is all a picture needs. It only replaces them where the real ones throw: in a page that is not sandboxed nothing
changes.
"""
from __future__ import annotations

import re

MARK = "forge-sandbox-shim"

SHIM = (
    "<script>/* " + MARK + " */(function () {"
    "function memory() { var data = {}; return {"
    "getItem: function (k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },"
    "setItem: function (k, v) { data[k] = String(v); },"
    "removeItem: function (k) { delete data[k]; },"
    "clear: function () { data = {}; },"
    "key: function (i) { return Object.keys(data)[i] || null; },"
    "get length() { return Object.keys(data).length; } }; }"
    "['localStorage', 'sessionStorage'].forEach(function (name) {"
    "var ok = true; try { void window[name]; window[name].getItem('x'); } catch (e) { ok = false; }"
    "if (!ok) { try { Object.defineProperty(window, name, { value: memory(), configurable: true }); } catch (e) {} } });"
    "try { void document.cookie; } catch (e) {"
    "try { Object.defineProperty(document, 'cookie', { get: function () { return ''; }, set: function () {}, configurable: true }); } catch (e2) {} }"
    "})();</script>"
)


def with_shim(html: str) -> str:
    """The page with the stand-in first in its head, before any script of the app. Once only."""
    if MARK in html:
        return html
    match = re.search(r"<head[^>]*>", html, re.I)
    if match:
        return html[: match.end()] + SHIM + html[match.end():]
    return SHIM + html
