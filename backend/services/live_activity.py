"""Live activity — a super admin watches what a signed-in person is doing on
the platform as it happens, without their private data.

Why Redis: the backend runs more than one worker, and the person being
watched may be served by a different worker than the admin's live stream, so
the feed crosses workers over Redis pub/sub. Each worker keeps a local view
of who is being watched, kept current over a control channel, so the hot
path — every authenticated request — only tests a set in memory and
publishes nothing when nobody is watching.

What is shown: the action (the screen opened, the thing done) and which
record it concerned — never the private values. A path carries ids, not
secrets; the query string is dropped and the label is scrubbed, so a search
someone typed, or a token that found its way into a URL, never reaches the
watcher. No request body is ever read. The admin's own watching is itself
recorded (`live_activity.start` / `.stop`), the same way impersonation is.

Live only: nothing here is stored. An event is published to whoever is
watching at that instant and is gone; close the stream and the watch ends.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from services.smith.secrets_scrub import scrub

logger = logging.getLogger(__name__)

#: Per-person activity channel.
_CHANNEL = "forge:activity:{uid}"
#: Watch control: workers learn who to emit for from this.
_CONTROL = "forge:activity:control"
#: The set of people currently watched, so a worker can seed itself on start.
_WATCHED_SET = "forge:activity:watched"
#: The watchers of one person, for a refcount across workers and admins.
_WATCHERS = "forge:activity:watchers:{uid}"
#: A watcher's membership expires if its stream dies without cleaning up.
_WATCHER_TTL_S = 90

# This worker's view of who is watched. Read on every authenticated request;
# written only by the control listener. Empty until the listener has seeded.
_watched: set[str] = set()
_listener: asyncio.Task | None = None

# Paths worth a human name; anything else reads as "METHOD /clean/path".
_LABELS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/api/projects/[^/]+/smith/(turn|chat)$"), "Chatting with Smith"),
    (re.compile(r"^/api/projects/[^/]+/generate/blueprint$"), "Building an app"),
    (re.compile(r"^/api/projects/[^/]+/publish$"), "Publishing an app"),
    (re.compile(r"^/api/projects/[^/]+/preview/"), "Previewing an app"),
    (re.compile(r"^/api/projects/[^/]+/files?$"), "Reading app code"),
    (re.compile(r"^/api/projects/[^/]+/export"), "Exporting app code"),
    (re.compile(r"^/api/projects/[^/]+/download$"), "Downloading app code"),
    (re.compile(r"^/api/projects/[^/]+/mobile-builds"), "Building a mobile app"),
    (re.compile(r"^/api/orgs/[^/]+/projects"), "Opening the projects list"),
    (re.compile(r"^/api/orgs/[^/]+/drafts-room"), "In the Drafts Room"),
    (re.compile(r"^/api/orgs/[^/]+/discovery"), "In Discover"),
    (re.compile(r"^/api/orgs/[^/]+/integrations"), "Changing integrations"),
    (re.compile(r"^/api/orgs/[^/]+/brand"), "Changing the brand"),
    (re.compile(r"^/api/orgs/[^/]+/members|^/api/orgs/[^/]+/people"), "Managing people"),
    (re.compile(r"^/api/auth/"), "Signing in"),
    (re.compile(r"^/api/data/"), "Reading app data"),
)

#: Never worth streaming: the pings, probes and the live stream itself.
_IGNORE = re.compile(r"^/api/(projects/[^/]+/events|events/|admin/live/|_health|health)|/health$|/metrics$")


def path_label(method: str, path: str) -> str:
    """A short, safe description of what the request does. The query string
    is dropped (it can hold a person's search terms); the result is scrubbed
    of anything secret-shaped before it is ever shown."""
    clean = (path or "").split("?", 1)[0]
    for rx, label in _LABELS:
        if rx.match(clean):
            return label
    verb = {"POST": "", "PUT": "Updating ", "PATCH": "Updating ", "DELETE": "Removing ", "GET": "Opening "}.get(method, "")
    return scrub(f"{verb}{clean}".strip())


def build_event(*, user: str, method: str, path: str, status: int,
                org: str | None = None, by: str | None = None) -> dict[str, Any]:
    """One activity event: what the person did, which organisation it was in,
    and — when the activity is itself the admin acting as them — who. Carries
    no body and no values, only the action and the record ids in the path."""
    return {
        "user": str(user),
        "at": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "path": scrub((path or "").split("?", 1)[0]),
        "status": int(status),
        "label": path_label(method, path),
        "org": str(org) if org else None,
        "by": str(by) if by else None,
    }


def worth_streaming(path: str) -> bool:
    return not _IGNORE.search(path or "")


def is_watched(uid: str | None) -> bool:
    """Whether anyone is watching this person — a set test in memory, so the
    hot path never waits on Redis."""
    return bool(uid) and str(uid) in _watched


async def _redis():
    from cache import get_redis
    return await get_redis()


async def ensure_listener() -> None:
    """Start this worker's control listener once: it seeds `_watched` from
    Redis and keeps it current as watches start and stop on any worker."""
    global _listener
    if _listener is not None and not _listener.done():
        return
    _listener = asyncio.ensure_future(_control_loop())


async def _control_loop() -> None:
    while True:
        try:
            r = await _redis()
            if r is None:
                await asyncio.sleep(10)
                continue
            try:
                seeded = await r.smembers(_WATCHED_SET)
                _watched.clear()
                _watched.update(str(x) for x in (seeded or []))
            except Exception:  # noqa: BLE001
                pass
            pubsub = r.pubsub()
            await pubsub.subscribe(_CONTROL)
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
                if msg is None:
                    # Reconcile periodically so a missed message self-heals.
                    try:
                        current = {str(x) for x in (await r.smembers(_WATCHED_SET) or [])}
                        _watched.clear()
                        _watched.update(current)
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                try:
                    data = json.loads(msg.get("data") or "{}")
                    uid, op = str(data.get("uid") or ""), data.get("op")
                    if not uid:
                        continue
                    if op == "watch":
                        _watched.add(uid)
                    elif op == "unwatch":
                        _watched.discard(uid)
                except Exception:  # noqa: BLE001
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a listener that falls over comes back
            logger.warning("[live-activity] control listener restarting", exc_info=True)
            await asyncio.sleep(5)


async def emit(event: dict[str, Any]) -> None:
    """Publish one event to whoever is watching this person right now. A
    no-op when nobody is, or when Redis is unavailable; never raises."""
    uid = event.get("user")
    if not is_watched(uid):
        return
    try:
        r = await _redis()
        if r is None:
            return
        await r.publish(_CHANNEL.format(uid=uid), json.dumps(event, default=str))
    except Exception:  # noqa: BLE001 — watching must never affect the request
        logger.debug("[live-activity] emit failed", exc_info=True)


async def available() -> bool:
    return await _redis() is not None


async def start_watch(uid: str, watcher: str) -> bool:
    """Begin watching `uid` for `watcher`. True when live activity is on
    (Redis up); False when it is unavailable."""
    r = await _redis()
    if r is None:
        return False
    uid, watcher = str(uid), str(watcher)
    await r.sadd(_WATCHERS.format(uid=uid), watcher)
    await r.expire(_WATCHERS.format(uid=uid), _WATCHER_TTL_S)
    await r.sadd(_WATCHED_SET, uid)
    await r.publish(_CONTROL, json.dumps({"op": "watch", "uid": uid}))
    _watched.add(uid)
    return True


async def refresh_watch(uid: str) -> None:
    """Keep the watcher-set alive while a stream is open, so a stream that
    dies without cleanup is forgotten within the TTL."""
    r = await _redis()
    if r is not None:
        try:
            await r.expire(_WATCHERS.format(uid=str(uid)), _WATCHER_TTL_S)
        except Exception:  # noqa: BLE001
            pass


async def stop_watch(uid: str, watcher: str) -> None:
    """End one watcher's watch; when the last one leaves, stop emitting."""
    r = await _redis()
    if r is None:
        return
    uid, watcher = str(uid), str(watcher)
    try:
        await r.srem(_WATCHERS.format(uid=uid), watcher)
        if await r.scard(_WATCHERS.format(uid=uid)) == 0:
            await r.srem(_WATCHED_SET, uid)
            await r.publish(_CONTROL, json.dumps({"op": "unwatch", "uid": uid}))
            _watched.discard(uid)
    except Exception:  # noqa: BLE001
        logger.debug("[live-activity] stop_watch failed", exc_info=True)


async def stream(uid: str) -> AsyncIterator[dict[str, Any]]:
    """Yield this person's activity events as they are published. Raises
    nothing; ends when the caller stops iterating."""
    r = await _redis()
    if r is None:
        return
    pubsub = r.pubsub()
    await pubsub.subscribe(_CHANNEL.format(uid=str(uid)))
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=25)
            if msg is None:
                yield {"type": "ping"}
                continue
            try:
                yield {"type": "activity", **json.loads(msg.get("data") or "{}")}
            except Exception:  # noqa: BLE001
                continue
    finally:
        try:
            await pubsub.unsubscribe(_CHANNEL.format(uid=str(uid)))
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass
