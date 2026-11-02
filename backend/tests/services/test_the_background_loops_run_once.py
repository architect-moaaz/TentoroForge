"""Two workers ran every startup hook: a due timer fired twice (audit, 2026-11-01).
One worker leads (`services.leader`) and only it starts the loops."""
from __future__ import annotations

import asyncio
import inspect


def test_alone_on_sqlite_this_worker_leads_and_starts_every_loop_once():
    from services import leader

    started: list[str] = []

    async def a():
        started.append("a")

    async def b():
        raise RuntimeError("one loop failing to start leaves the others")

    async def c():
        started.append("c")

    asyncio.run(leader.run_when_leading([a, b, c], retry_s=0.01))
    assert started == ["a", "c"] and leader.leading()


def test_the_loops_are_started_by_the_leader_and_by_no_startup_hook():
    import main

    src = inspect.getsource(main)
    assert "leader.run_when_leading([" in src
    for loop in ("_start_timer_scheduler", "_follow_open_mobile_builds", "_start_lost_run_watch",
                 "_start_dev_server_reaper", "_start_domain_watch"):
        before = src[:src.index(f"async def {loop}(")]
        assert not before.rstrip().endswith('@app.on_event("startup")'), loop
