"""GATED, read-only runtime probe for the Conversational Fix-Assistant (Task 2-C).

The diagnoser MAY request a probe to confirm a hypothesis BEFORE proposing a fix
(e.g. "is the app actually erroring on this endpoint?" / "what does the recent
server log say?"). This is the slice-2 evidence SEAM only — it is built and
unit-tested here but is NOT auto-invoked in the main diagnose flow yet (wiring is
deferred to a later slice).

Hard guarantees:
- **Read-only.** The probe never writes anything, anywhere.
- **Bounded.** Log reads are capped to ``max_bytes`` (tail) and ``max_lines``;
  endpoint reads use a short ``timeout`` and cap the body to ``max_bytes``.
- **Local-only endpoints.** ``read_endpoint`` refuses any non-localhost URL
  BEFORE issuing a request (no exfiltration to an attacker-suggested host).
- **Honest availability.** Returns ``{"available": bool, "evidence": <obj|None>}``
  — ``available: False`` (with a ``reason``) when the app isn't running or there
  is no log, never a crash.

The network boundary is an injectable ``http_get(url, *, timeout) -> {"status",
"body"}`` so tests (and callers) never hit the real network.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Bounds (defaults — every one is overridable per call).
_MAX_LOG_LINES = 200
_MAX_BYTES = 64 * 1024
_DEFAULT_TIMEOUT = 3.0

# Where an app's recent server/console log tends to live, relative to output_dir.
_LOG_CANDIDATES = (
    "logs/server.log",
    "logs/console.log",
    "logs/dev.log",
    "server.log",
    "dev.log",
    ".next/server.log",
)

# Only these hosts are considered the local app (endpoint probe).
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}

Evidence = dict


def probe(
    output_dir: str,
    request: dict,
    *,
    http_get: Optional[Callable[..., Any]] = None,
    max_lines: int = _MAX_LOG_LINES,
    max_bytes: int = _MAX_BYTES,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict:
    """Run a single read-only probe. Returns ``{"available", "evidence", ...}``.

    ``request`` is one of:
      - ``{"kind": "logs", "path"?: <rel path>}`` — read the tail of the app's
        recent log (best-effort; caps at ``max_bytes`` / ``max_lines``).
      - ``{"kind": "read_endpoint", "url": <localhost url>}`` — a bounded GET to
        the local app (no writes; non-local URLs are refused).
    """
    kind = (request or {}).get("kind")
    try:
        if kind == "logs":
            return _probe_logs(output_dir, request, max_lines=max_lines, max_bytes=max_bytes)
        if kind == "read_endpoint":
            return _probe_endpoint(
                request, http_get=http_get, max_bytes=max_bytes, timeout=timeout
            )
    except Exception:  # noqa: BLE001 — a probe must never crash the caller
        logger.exception("fix_probe: probe kind=%r failed", kind)
        return {"available": False, "evidence": None, "reason": "probe error"}

    return {"available": False, "evidence": None, "reason": f"unknown probe kind: {kind!r}"}


# --------------------------------------------------------------------------- #
# logs
# --------------------------------------------------------------------------- #

def _probe_logs(output_dir: str, request: dict, *, max_lines: int, max_bytes: int) -> dict:
    log_path = _find_log(output_dir, request.get("path"))
    if not log_path:
        return {"available": False, "evidence": None, "reason": "no readable log file found"}

    try:
        lines, truncated = _read_tail(log_path, max_lines=max_lines, max_bytes=max_bytes)
    except OSError:
        return {"available": False, "evidence": None, "reason": "log not readable"}

    return {
        "available": True,
        "evidence": {
            "kind": "logs",
            "path": log_path.replace(os.sep, "/"),
            "lines": lines,
            "truncated": truncated,
        },
    }


def _find_log(output_dir: str, explicit: Any) -> Optional[str]:
    if explicit:
        cand = os.path.join(output_dir, str(explicit))
        return cand if os.path.isfile(cand) else None
    for rel in _LOG_CANDIDATES:
        cand = os.path.join(output_dir, rel)
        if os.path.isfile(cand):
            return cand
    return None


def _read_tail(path: str, *, max_lines: int, max_bytes: int) -> tuple[list[str], bool]:
    """Read at most ``max_bytes`` from the END of ``path``, return the last
    ``max_lines`` lines and whether anything was dropped. Bounded + read-only."""
    size = os.path.getsize(path)
    byte_truncated = size > max_bytes
    with open(path, "rb") as fh:
        if byte_truncated:
            fh.seek(size - max_bytes)
        raw = fh.read(max_bytes)
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # When we seeked into the middle, the first line is likely partial — drop it.
    if byte_truncated and lines:
        lines = lines[1:]
    line_truncated = len(lines) > max_lines
    if line_truncated:
        lines = lines[-max_lines:]
    return lines, bool(byte_truncated or line_truncated)


# --------------------------------------------------------------------------- #
# read_endpoint
# --------------------------------------------------------------------------- #

def _is_local(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOCAL_HOSTS


def _probe_endpoint(
    request: dict,
    *,
    http_get: Optional[Callable[..., Any]],
    max_bytes: int,
    timeout: float,
) -> dict:
    url = request.get("url")
    if not url or not isinstance(url, str):
        return {"available": False, "evidence": None, "reason": "no url given"}
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in ("http", "https"):
        return {"available": False, "evidence": None, "reason": "only http(s) is probed"}
    if not _is_local(url):
        return {
            "available": False,
            "evidence": None,
            "reason": "refused: only the local app (localhost/127.0.0.1) may be probed",
        }

    getter = http_get or _default_http_get
    try:
        resp = getter(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — app down / refused / timeout
        return {
            "available": False,
            "evidence": None,
            "reason": f"endpoint not reachable ({type(exc).__name__})",
        }

    status, body = _coerce_response(resp)
    truncated = False
    if isinstance(body, str) and len(body) > max_bytes:
        body = body[:max_bytes]
        truncated = True

    return {
        "available": True,
        "evidence": {
            "kind": "read_endpoint",
            "url": url,
            "status": status,
            "body": body,
            "truncated": truncated,
        },
    }


def _coerce_response(resp: Any) -> tuple[Optional[int], Any]:
    """Accept a ``{"status","body"}`` dict, a ``(status, body)`` tuple, or an
    object exposing ``.status``/``.read()``."""
    if isinstance(resp, dict):
        return resp.get("status"), resp.get("body")
    if isinstance(resp, tuple) and len(resp) == 2:
        return resp[0], resp[1]
    status = getattr(resp, "status", None) or getattr(resp, "status_code", None)
    body = None
    if hasattr(resp, "read"):
        try:
            body = resp.read()
            if isinstance(body, (bytes, bytearray)):
                body = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = None
    elif hasattr(resp, "text"):
        body = resp.text
    return status, body


def _default_http_get(url: str, *, timeout: float) -> dict:  # pragma: no cover - network
    """Default read-only GET boundary (bounded timeout). Injected over in tests."""
    import urllib.request

    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local only
        raw = resp.read(_MAX_BYTES)
        body = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
        return {"status": getattr(resp, "status", None), "body": body}
