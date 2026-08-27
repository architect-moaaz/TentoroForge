"""In-memory SSE event buffer with asyncio signaling for generation sessions.

Allows generation to continue running after client disconnect, and clients
to reconnect and replay missed events.
"""

import asyncio
import time
from dataclasses import dataclass, field

MAX_EVENTS_PER_SESSION = 50_000
SESSION_TTL_SECONDS = 3600  # 1 hour

_sessions: dict[str, "GenerationSession"] = {}


@dataclass
class GenerationSession:
    session_id: str
    project_id: str
    status: str = "running"  # "running" | "completed" | "failed"
    events: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    notify: asyncio.Event = field(default_factory=asyncio.Event)


def create_session(session_id: str, project_id: str) -> GenerationSession:
    """Create a new generation session and register it. Lazily prunes expired."""
    _cleanup_expired()
    session = GenerationSession(session_id=session_id, project_id=project_id)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> GenerationSession | None:
    return _sessions.get(session_id)


def get_active_session_for_project(project_id: str) -> GenerationSession | None:
    """Find a running generation session for a project.

    Used by the frontend to auto-reconnect after login.
    Returns the most recent running session, or None.
    """
    for session in reversed(list(_sessions.values())):
        if session.project_id == project_id and session.status == "running":
            return session
    return None


def append_event(session_id: str, event: dict) -> int:
    """Append an event to the session buffer. Returns its index. Signals waiters."""
    session = _sessions.get(session_id)
    if session is None:
        return -1
    if len(session.events) >= MAX_EVENTS_PER_SESSION:
        return len(session.events) - 1
    idx = len(session.events)
    session.events.append(event)
    # Signal then clear so next wait blocks again
    session.notify.set()
    session.notify.clear()
    return idx


def get_events_since(session_id: str, since: int) -> list[tuple[int, dict]]:
    """Return (index, event) pairs for all events with index >= since."""
    session = _sessions.get(session_id)
    if session is None:
        return []
    start = max(0, since)
    return [(i, session.events[i]) for i in range(start, len(session.events))]


def mark_complete(session_id: str, status: str = "completed") -> None:
    """Mark the session as completed/failed. Signals waiters one last time."""
    session = _sessions.get(session_id)
    if session is None:
        return
    session.status = status
    session.notify.set()


async def wait_for_events(session_id: str, timeout: float = 10.0) -> bool:
    """Wait for new events or completion. Returns True if events may be available."""
    session = _sessions.get(session_id)
    if session is None:
        return False
    if session.status != "running":
        return True  # drain remaining
    try:
        await asyncio.wait_for(session.notify.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


def _cleanup_expired() -> None:
    """Remove sessions older than TTL."""
    now = time.time()
    expired = [
        sid for sid, s in _sessions.items()
        if now - s.created_at > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _sessions[sid]
