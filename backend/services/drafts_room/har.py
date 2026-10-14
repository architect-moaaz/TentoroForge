"""The person's own recording of their signed-in session, as a study.

Forge never signs in for anyone and never holds a password: when a product
only shows itself to a signed-in user, the person records their own session
in their browser (a HAR file) and drops it on the reference. The file is
read in memory, every credential is taken out — cookies, the Authorization
and Set-Cookie headers, any header or query parameter named like a token,
anything `secrets_scrub` recognises in a URL or a body — and only the
calls' SHAPES are written down, as `calls.py` keeps them. The raw upload
is never written to disk.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from services.drafts_room import calls as callrec

logger = logging.getLogger(__name__)

MAX_UPLOAD = 50 * 1024 * 1024


class BadRecording(ValueError):
    pass


def _same_site(host: str, site: str) -> bool:
    host, site = str(host or "").lower(), str(site or "").lower()
    root = ".".join(site.split(".")[-2:]) if site.count(".") >= 1 else site
    return bool(host) and (host == site or host.endswith("." + root) or host == root)


def _body(content: dict | None) -> Any:
    if not content:
        return None
    text = content.get("text")
    if not isinstance(text, str) or not text:
        return None
    if content.get("encoding") == "base64":
        return None                                   # pictures and the like: not a shape
    if len(text) > callrec.MAX_BODY:
        text = text[:callrec.MAX_BODY]
    try:
        return json.loads(text)
    except ValueError:
        return None


def scrub_har(data: bytes, site: str) -> list[dict]:
    """The recording's calls to `site` (and its subdomains), shaped and
    scrubbed; everything else — other hosts, pictures, scripts, every
    credential — is dropped before anything is returned."""
    if len(data) > MAX_UPLOAD:
        raise BadRecording("that recording is larger than 50 MB")
    try:
        har = json.loads(data.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise BadRecording("that is not a HAR file (not JSON)") from exc
    entries = (har.get("log") or {}).get("entries") if isinstance(har, dict) else None
    if not isinstance(entries, list):
        raise BadRecording("that is not a HAR file (no log.entries)")
    site_host = urlparse(site if "://" in site else "https://" + site).hostname or site
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        req = e.get("request") or {}
        res = e.get("response") or {}
        url = str(req.get("url") or "")
        host = urlparse(url).hostname or ""
        if not _same_site(host, site_host):
            continue
        mime = str((res.get("content") or {}).get("mimeType") or "")
        post = req.get("postData") or {}
        request_body = None
        if isinstance(post, dict) and isinstance(post.get("text"), str):
            try:
                request_body = json.loads(post["text"])
            except ValueError:
                request_body = {p.get("name"): "" for p in post.get("params") or [] if isinstance(p, dict)} or None
        row = callrec.record(str(req.get("method") or "GET"), url, res.get("status"), mime,
                             request_body=request_body, response_body=_body(res.get("content")),
                             page=str((e.get("pageref") or ""))[:80], source="har",
                             at=_when(e.get("startedDateTime")))
        if row is not None:
            out.append(row)
    return out


def _when(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


__all__ = ["scrub_har", "BadRecording", "MAX_UPLOAD"]
