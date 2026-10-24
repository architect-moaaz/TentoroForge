"""Receiving events from an app: size limits, checking each event, the per-key rate limit, and counting what was turned away.

An app posts ``{"schema": 1, "events": [...]}`` (JSON, optionally gzip). Every event is checked on its own and either accepted in a
shortened form (``normalize_event``: the short keys the stream and the writer use) or rejected with a one-sentence reason that goes
back to the app. One bad event never costs the rest of its batch.

Short keys (turn): id, at (epoch seconds), a agent, c conversation, u user key, r role ("" for none), e env, m model ("" for none),
i input tokens, o output tokens, ms, s status, tc tool calls, te tool errors, tl [[name, ok 0/1, ms], ...], h handed off 0/1, n turn
number, p None or [reason, message, detail]. Rating: tid turn id, v 1 or -1, nt note. Handoff: a, c, s status, rm resolve minutes.
"""
from __future__ import annotations

import gzip
import math
import re
import time
import uuid
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.agent_insights_bus import loads as _loads

SCHEMA = 1
MAX_EVENTS = 500
MAX_BODY_BYTES = 1_000_000
MAX_AGE_DAYS = 90
MAX_FUTURE_SECONDS = 300
MAX_REJECTED_LISTED = 20
RATE_PER_SECOND = 200.0
RATE_BURST = 400.0
#: Counters and times are capped so a made-up number cannot overflow a sum.
MAX_COUNT = 10 ** 9

_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_HEX = re.compile(r"^[0-9a-fA-F]{16,64}$")
_PROBLEM_REASONS = ("error", "blocked", "tool_failed", "handed_off", "slow", "thumbs_down")
_HANDOFF_STATUSES = ("open", "claimed", "resolved")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class IngestError(Exception):
    """The whole request is refused. ``status`` is the HTTP code, ``message`` a plain sentence for the person reading the app's log."""

    def __init__(self, status: int, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}


class Reject(Exception):
    """One event is refused; the reason is one plain sentence."""


# ---------------------------------------------------------------------------
# checking one event
# ---------------------------------------------------------------------------

def _whole(v: Any, name: str, lo: int = 0, hi: int = MAX_COUNT) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and (not math.isfinite(v) or not v.is_integer())):
        raise Reject(f"The '{name}' must be a whole number of {lo} or more.")
    n = int(v)
    if n < lo:
        raise Reject(f"The '{name}' must be a whole number of {lo} or more.")
    if n > hi:
        raise Reject(f"The '{name}' is too large (the most allowed is {hi}).")
    return n


def _word(v: Any, name: str, limit: int, *, nullable: bool = False) -> str:
    """Text that identifies something (an agent, a role, a model): refused, not cut, when too long, because a cut name would be a different name."""
    if v is None and nullable:
        return ""
    if not isinstance(v, str) or not v.strip():
        raise Reject(f"The '{name}' must be text of 1 to {limit} characters{' or null' if nullable else ''}.")
    v = _CONTROL.sub(" ", v).strip()
    if len(v) > limit:
        raise Reject(f"The '{name}' is longer than {limit} characters.")
    return v


def _free(v: Any, limit: int) -> str | None:
    """Free text (a message, a note): shortened to the limit rather than refused, so a long message never loses its whole turn."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise Reject("A message, detail or note must be text or null.")
    v = _CONTROL.sub(" ", v).strip()
    return (v[:limit] if len(v) > limit else v) or None


def _bool(v: Any, name: str) -> int:
    if not isinstance(v, bool):
        raise Reject(f"The '{name}' must be true or false.")
    return int(v)


def _when(v: Any, now: float) -> float:
    if not isinstance(v, str) or not v.strip() or len(v) > 40:
        raise Reject("The 'at' must be an ISO-8601 time such as 2026-10-22T09:30:00Z.")
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        raise Reject("The 'at' must be an ISO-8601 time such as 2026-10-22T09:30:00Z.") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = dt.timestamp()
    if ts < now - MAX_AGE_DAYS * 86400:
        raise Reject(f"This event is older than {MAX_AGE_DAYS} days, so it is not counted.")
    if ts > now + MAX_FUTURE_SECONDS:
        raise Reject("This event is dated more than 5 minutes in the future, so check the clock of the app that sent it.")
    return ts


def _event_id(v: Any, name: str = "id") -> str:
    if not isinstance(v, str) or not _ID.match(v):
        raise Reject(f"The '{name}' must be 8 to 64 letters, numbers, dashes or underscores.")
    return v


def normalize_event(ev: Any, now: float) -> dict[str, Any]:
    """The event in its short form, or ``Reject`` with the reason."""
    if not isinstance(ev, dict):
        raise Reject("This entry is not a JSON object.")
    kind = ev.get("type")
    if kind == "turn":
        return _turn(ev, now)
    if kind == "rating":
        rating = ev.get("rating")
        if isinstance(rating, bool) or rating not in (1, -1):
            raise Reject("The 'rating' must be 1 (thumbs up) or -1 (thumbs down).")
        return {"t": "rating", "id": _event_id(ev.get("id")), "at": _when(ev.get("at"), now), "tid": _event_id(ev.get("turnId"), "turnId"),
                "v": int(rating), "nt": _free(ev.get("note"), 300)}
    if kind == "handoff":
        status = ev.get("status")
        if status not in _HANDOFF_STATUSES:
            raise Reject("The 'status' of a handoff must be open, claimed or resolved.")
        rm = ev.get("resolveMinutes")
        if rm is not None and (isinstance(rm, bool) or not isinstance(rm, (int, float)) or not math.isfinite(rm) or rm < 0):
            raise Reject("The 'resolveMinutes' must be a number of 0 or more, or null.")
        return {"t": "handoff", "id": _event_id(ev.get("id")), "at": _when(ev.get("at"), now), "a": _word(ev.get("agentId"), "agentId", 80),
                "c": _word(ev.get("conversationId"), "conversationId", 64), "s": status,
                "rm": None if rm is None else min(float(rm), 1e7)}
    raise Reject("The 'type' must be turn, rating or handoff.")


def _turn(ev: dict[str, Any], now: float) -> dict[str, Any]:
    user = ev.get("userKey")
    if not isinstance(user, str) or not _HEX.match(user):
        raise Reject("The 'userKey' must be 16 to 64 hexadecimal characters (a hash of the person, never their email or id).")
    env = ev.get("env")
    if env not in ("production", "development"):
        raise Reject("The 'env' must be production or development.")
    status = ev.get("status")
    if status not in ("ok", "error", "blocked"):
        raise Reject("The 'status' must be ok, error or blocked.")
    tool_calls, tool_errors = _whole(ev.get("toolCalls"), "toolCalls"), _whole(ev.get("toolErrors"), "toolErrors")
    if tool_errors > tool_calls:
        raise Reject("The 'toolErrors' cannot be more than the 'toolCalls'.")
    tools_in = ev.get("tools")
    if tools_in is None:
        tools_in = []
    if not isinstance(tools_in, list):
        raise Reject("The 'tools' must be a list.")
    if len(tools_in) > 20:
        raise Reject("The 'tools' list can hold at most 20 tools.")
    tools = []
    for t in tools_in:
        if not isinstance(t, dict):
            raise Reject("Each entry of 'tools' must be an object with a name, ok and ms.")
        tools.append([_word(t.get("name"), "tools.name", 80), _bool(t.get("ok"), "tools.ok"), _whole(t.get("ms"), "tools.ms")])
    problem = ev.get("problem")
    p = None
    if problem is not None:
        if not isinstance(problem, dict) or problem.get("reason") not in _PROBLEM_REASONS:
            raise Reject("The 'problem' must be null or have a 'reason' of error, blocked, tool_failed, handed_off, slow or thumbs_down.")
        p = [problem["reason"], _free(problem.get("message"), 200), _free(problem.get("detail"), 200)]
    return {
        "t": "turn", "id": _event_id(ev.get("id")), "at": _when(ev.get("at"), now),
        "a": _word(ev.get("agentId"), "agentId", 80), "c": _word(ev.get("conversationId"), "conversationId", 64),
        "u": user.lower(), "r": _word(ev.get("role"), "role", 60, nullable=True), "e": env,
        "m": _word(ev.get("model"), "model", 100, nullable=True),
        "i": _whole(ev.get("inputTokens"), "inputTokens"), "o": _whole(ev.get("outputTokens"), "outputTokens"),
        "ms": _whole(ev.get("ms"), "ms"), "s": status, "tc": tool_calls, "te": tool_errors, "tl": tools,
        "h": _bool(ev.get("handedOff"), "handedOff"), "n": _whole(ev.get("turnNumber"), "turnNumber", lo=1), "p": p,
    }


# ---------------------------------------------------------------------------
# checking a whole request
# ---------------------------------------------------------------------------

@dataclass
class Parsed:
    events: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)   # at most MAX_REJECTED_LISTED listed
    rejected_count: int = 0
    duplicates: int = 0                                            # the same event twice inside this one request


def decode_body(raw: bytes, content_encoding: str | None) -> bytes:
    """The JSON bytes, un-gzipped if needed, refusing anything over 1 MB once expanded (a small gzip can hold a gigabyte)."""
    enc = (content_encoding or "").strip().lower()
    if enc in ("", "identity"):
        if len(raw) > MAX_BODY_BYTES:
            raise IngestError(413, "The request is bigger than 1 MB. Send smaller batches (at most 500 events).")
        return raw
    if enc != "gzip":
        raise IngestError(400, "Content-Encoding must be gzip, or left out.")
    if len(raw) > MAX_BODY_BYTES:
        raise IngestError(413, "The request is bigger than 1 MB. Send smaller batches (at most 500 events).")
    try:
        d = zlib.decompressobj(wbits=31)
        out = d.decompress(raw, MAX_BODY_BYTES + 1)
        if d.unconsumed_tail or len(out) > MAX_BODY_BYTES:
            raise IngestError(413, "The request is bigger than 1 MB once unzipped. Send smaller batches (at most 500 events).")
        return out
    except zlib.error:
        raise IngestError(400, "The body says it is gzip but could not be unzipped.") from None


def parse_body(body: bytes, *, now: float | None = None) -> Parsed:
    now = time.time() if now is None else now
    try:
        doc = _loads(body)
    except ValueError:
        raise IngestError(400, "The body is not valid JSON.") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise IngestError(400, f"The body must be an object with \"schema\": {SCHEMA} and a list of \"events\".")
    events = doc.get("events")
    if not isinstance(events, list):
        raise IngestError(400, "The 'events' must be a list.")
    if len(events) > MAX_EVENTS:
        raise IngestError(413, f"A request can hold at most {MAX_EVENTS} events; this one has {len(events)}. Send smaller batches.")
    out = Parsed()
    seen: set[tuple[str, str]] = set()
    for i, raw in enumerate(events):
        try:
            ev = normalize_event(raw, now)
        except Reject as r:
            out.rejected_count += 1
            if len(out.rejected) < MAX_REJECTED_LISTED:
                out.rejected.append({"index": i, "reason": str(r)})
            continue
        key = (ev["t"], ev["id"])
        if key in seen:
            out.duplicates += 1
            continue
        seen.add(key)
        out.events.append(ev)
    return out


# ---------------------------------------------------------------------------
# per-key rate limit
# ---------------------------------------------------------------------------

class KeyRateLimiter:
    """A token bucket per key: ``rate`` requests a second sustained, ``burst`` at once. Kept in this process's memory (the backend
    runs two processes, so a key can in the worst case use twice the rate: the limit protects the platform, it is not a quota)."""

    def __init__(self, rate: float = RATE_PER_SECOND, burst: float = RATE_BURST, clock=time.monotonic) -> None:
        self.rate, self.burst, self.clock = rate, burst, clock
        self._b: dict[str, list[float]] = {}   # key -> [tokens, last time]

    def allow(self, key: str) -> tuple[bool, float]:
        """(allowed, seconds until a request would be allowed)."""
        now = self.clock()
        b = self._b.get(key)
        if b is None:
            if len(self._b) > 5000:
                self._b = {k: v for k, v in self._b.items() if now - v[1] < 60}
            b = self._b[key] = [self.burst, now]
        b[0] = min(self.burst, b[0] + (now - b[1]) * self.rate)
        b[1] = now
        if b[0] >= 1:
            b[0] -= 1
            return True, 0.0
        return False, (1 - b[0]) / self.rate


RATE_LIMITER = KeyRateLimiter()


# ---------------------------------------------------------------------------
# counting what was turned away
# ---------------------------------------------------------------------------

class DroppedCounter:
    """Events refused (invalid) and requests turned away (rate limited), per project per hour. Kept in memory and written to the database
    every few seconds by the worker: a flood of 429s must not become a flood of writes."""

    def __init__(self) -> None:
        self.pending: dict[tuple[uuid.UUID, int], list[int]] = defaultdict(lambda: [0, 0])

    def add(self, project_id: uuid.UUID, *, rejected: int = 0, rate_limited: int = 0, now: float | None = None) -> None:
        hour = int((time.time() if now is None else now) // 3600 * 3600)
        c = self.pending[(project_id, hour)]
        c[0] += rejected
        c[1] += rate_limited

    async def flush(self, session_factory=None) -> int:
        if not self.pending:
            return 0
        from models.agent_insights import agent_insight_dropped
        from services.agent_insights_store import _upsert

        if session_factory is None:
            from database import async_session as session_factory
        batch, self.pending = self.pending, defaultdict(lambda: [0, 0])
        rows = [{"project_id": p, "hour": datetime.fromtimestamp(h, timezone.utc), "rejected": r, "rate_limited": limited}
                for (p, h), (r, limited) in batch.items()]
        try:
            async with session_factory() as s, s.begin():
                await _upsert(s, agent_insight_dropped, rows, ["project_id", "hour"], add=["rejected", "rate_limited"])
        except Exception:  # noqa: BLE001 — put them back: a database blip must not erase the count
            for (p, h), (r, limited) in batch.items():
                c = self.pending[(p, h)]
                c[0] += r
                c[1] += limited
            raise
        return len(rows)


DROPPED = DroppedCounter()


def gzip_bytes(data: bytes) -> bytes:
    """For callers (the load test, tests) that want to send a gzip body."""
    return gzip.compress(data, 1)
