"""The actor of a run is the session or nobody.

The execute route and the event route used to believe a `user` written into
the request body when no session was present, so any caller could run a
process as any role or person. And a run that paused — a wait, an approval
— resumed with nobody acting: `$user.id` empty, owner columns unfilled,
scoped reads returning nothing. The pause now stores who was running and
every resume hands them back (2026-10-12)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_route_reads_an_actor_from_the_body():
    injector = (ROOT / "services" / "runtime_injector.py").read_text()
    assert not re.search(r":\s*body\.user\b", injector), "a route still believes `body.user`"
    assert "NOBODY ACTS AS SOMEONE ELSE BY SAYING SO" in injector


def test_a_pause_stores_the_actor_and_every_resume_hands_them_back():
    index = (ROOT / "templates" / "runtime" / "workflows" / "index.ts").read_text()
    assert "__user: user" in index, "the pause stores who was running in the process variables"
    bus = (ROOT / "templates" / "runtime" / "events" / "bus.ts").read_text()
    resumes = re.findall(r"wfmod\.triggerWorkflow\(task\.workflow_id, input(?:, (.+?))?\);", bus)
    assert len(resumes) == 2 and all(r == "_actorOf(pv)" for r in resumes), resumes
