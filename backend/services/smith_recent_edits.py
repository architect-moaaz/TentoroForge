"""Smith Auto-Act — per-project sliding window of recently-touched routes.

The Auto-Act scorer awards +20 to any candidate whose route was edited
in the last few turns (see :mod:`services.smith_decide` — ``_W_RECENT_EDIT``).
This module holds that memory: after every mutation, the router pushes
the touched routes onto the project's deque; before every new turn, the
router reads the deque and hands it to Smith (via memory) so
``resolve_target`` can echo it back in its scoring call.

Process-local by design — no persistence. A restart resets the window;
that's acceptable since the +20 is a nudge, not a correctness signal,
and the missing bias only means one more clarify turn once. This lives
in a separate module so it can be unit-tested and swapped for a Redis-
backed variant without touching the router.
"""
from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Iterable

_MAX_ROUTES = 5

# Keyed by project_id (str form of the UUID). Reset on process restart.
_store: dict[str, deque[str]] = {}
_lock = Lock()


def _key(project_id) -> str:
    return str(project_id)


def get(project_id) -> list[str]:
    """Return the most-recent-first list of routes for a project.

    Empty when the project has no history yet. Returned as a plain list
    so callers pass it into ``smith_decide.resolve()`` without exposing
    the underlying deque.
    """
    dq = _store.get(_key(project_id))
    return list(dq) if dq else []


def push(project_id, routes: Iterable[str]) -> None:
    """Prepend ``routes`` (newest first) onto the project's window.

    Duplicates already in the window are moved to the front rather than
    re-added, so a route touched twice in one turn doesn't crowd out the
    others. Anything falsy is ignored silently.
    """
    fresh = [r for r in (routes or []) if isinstance(r, str) and r]
    if not fresh:
        return
    k = _key(project_id)
    with _lock:
        dq = _store.get(k)
        if dq is None:
            dq = deque(maxlen=_MAX_ROUTES)
            _store[k] = dq
        # Move dupes to the front by removing then reinserting.
        existing = list(dq)
        combined: list[str] = []
        seen: set[str] = set()
        for r in fresh + existing:
            if r in seen:
                continue
            seen.add(r)
            combined.append(r)
        dq.clear()
        dq.extend(combined[:_MAX_ROUTES])


def clear(project_id) -> None:
    """Drop the window for a project (test seam)."""
    _store.pop(_key(project_id), None)


def clear_all() -> None:
    """Wipe the entire store (test seam)."""
    with _lock:
        _store.clear()


def _routes_from_edited_paths(paths: Iterable[str]) -> list[str]:
    """Best-effort schema-path → route mapping.

    ``src/schemas/candidates.json`` → ``/candidates``. Nested paths keep
    the nesting: ``src/schemas/candidates/[id]/edit.json`` →
    ``/candidates/[id]/edit``. Non-schema paths return no route. This
    duplicates a tiny bit of :func:`services.smith_tools.list_pages_tool`'s
    logic on purpose — the router already has ``edited_paths`` in-hand
    and we don't want to require the full page index here.
    """
    routes: list[str] = []
    for p in paths or []:
        if not isinstance(p, str) or not p:
            continue
        norm = p.replace("\\", "/")
        marker = "/schemas/"
        idx = norm.find(marker)
        if idx < 0:
            continue
        tail = norm[idx + len(marker):]
        if tail.endswith(".json"):
            tail = tail[: -len(".json")]
        # A page schema at src/schemas/index.json → "/".
        if tail in ("", "index"):
            routes.append("/")
        else:
            routes.append("/" + tail)
    return routes


def record_edit(project_id, edited_paths: Iterable[str]) -> None:
    """Convenience — derive routes from ``edited_paths`` and push."""
    push(project_id, _routes_from_edited_paths(edited_paths))


__all__ = [
    "get",
    "push",
    "clear",
    "clear_all",
    "record_edit",
]
