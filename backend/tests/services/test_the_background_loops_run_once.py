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
                 "_start_dev_server_reaper", "_start_domain_watch", "_start_job_recovery", "_start_insights_worker"):
        before = src[:src.index(f"async def {loop}(")]
        assert not before.rstrip().endswith('@app.on_event("startup")'), loop
    leading = src[src.index("leader.run_when_leading(["):]
    assert "_start_insights_worker" in leading[:leading.index("]))")], "the insights worker runs on the leader"


def test_every_worker_writes_its_own_insight_counts(monkeypatch):
    """#30 review, 2026-11-13: the ingest route counts refusals and key use in
    the memory of whichever worker served it. Only the leader runs the
    insights worker, so each worker flushes its own counts, and does once
    more at shutdown."""
    import main
    from services import agent_insights_worker as W

    src = inspect.getsource(main)
    hook = src[src.index("async def _write_this_workers_insight_counts("):]
    assert src[:src.index("async def _write_this_workers_insight_counts(")].rstrip().endswith('@app.on_event("startup")')
    assert "flush_counts_forever()" in hook[:hook.index("\n\n\n")]
    assert "await agent_insights_worker.flush_counts()" in src[src.index("async def _shutdown("):]

    flushed: list[str] = []

    async def dropped(_f=None):
        flushed.append("dropped")

    async def touches(_f=None):
        raise RuntimeError("a database blip is said and tried again, never raised")

    monkeypatch.setattr(W.ingest.DROPPED, "flush", dropped)
    monkeypatch.setattr(W.keys, "flush_touches", touches)

    async def run():
        task = asyncio.create_task(W.flush_counts_forever(every_s=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(run())
    assert len(flushed) >= 2, flushed
