"""Nothing limited how many builds ran at once, and the host has died of
out-of-memory before (audit, 2026-11-01). A build holds one of
`build_slots.SLOTS` for as long as its graph runs; one that finds them all
taken waits, says so once on its stream, and starts when one is given back —
across both workers, since on Postgres a slot is an advisory lock."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from services import build_slots

BACKEND = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("FORGE_TEST_PG_URL",
                        "postgresql+asyncpg://tentoroforge:tentoroforge@localhost:5432/tentoroforge")
#: Not the platform's own keys: a backend running against the same database keeps its slots.
TEST_KEY_BASE = build_slots.SLOT_KEY_BASE + 0x10000


def test_the_second_of_two_contenders_waits_for_the_first():
    async def go():
        pool = build_slots.Slots(n=1, engine=_sqlite())
        first = await pool.try_take()
        assert first is not None and await pool.try_take() is None

        told: list[str] = []

        async def on_wait():
            told.append("waiting")

        second = asyncio.ensure_future(pool.take(on_wait=on_wait, poll_s=0.01))
        await asyncio.sleep(0.05)
        assert not second.done() and told == ["waiting"], "it waits, and says so once"
        await pool.give_back(first)
        got = await asyncio.wait_for(second, 1)
        assert got.index == 0
        await pool.give_back(got)

    asyncio.run(go())


def test_builds_in_threads_never_run_more_than_the_cap_and_the_waiting_one_is_told(monkeypatch):
    pool = build_slots.Slots(n=1, engine=_sqlite())
    monkeypatch.setattr(build_slots, "_slots", pool)
    monkeypatch.setattr(build_slots, "POLL_S", 0.01)
    said: list[tuple[str, dict]] = []
    running, most = [0], [0]
    lock = threading.Lock()

    def build(name: str):
        with build_slots.held(lambda e, d: said.append((name, d))):
            with lock:
                running[0] += 1
                most[0] = max(most[0], running[0])
            time.sleep(0.1)
            with lock:
                running[0] -= 1

    threads = [threading.Thread(target=build, args=(n,)) for n in ("a", "b")]
    threads[0].start()
    time.sleep(0.02)
    threads[1].start()
    for t in threads:
        t.join(5)
    assert most[0] == 1, "two builds, one slot: never both at once"
    assert [n for n, _ in said] == ["b"] and "waiting its turn" in said[0][1]["text"]
    assert not pool._held, "every slot given back"


def _sqlite():
    from types import SimpleNamespace
    return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


# ---------------------------------------------------------------------------
# Across workers: two processes against the platform's Postgres
# ---------------------------------------------------------------------------

def _postgres_or_skip():
    async def ping():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        eng = create_async_engine(PG_URL)
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await eng.dispose()
    try:
        asyncio.run(asyncio.wait_for(ping(), 5))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Postgres at FORGE_TEST_PG_URL: {exc}")


HOLDER = textwrap.dedent("""
    import asyncio, sys
    sys.path.insert(0, sys.argv[1])
    from sqlalchemy.ext.asyncio import create_async_engine
    from services.build_slots import Slots

    async def main():
        pool = Slots(n=1, engine=create_async_engine(sys.argv[2]), key_base=int(sys.argv[3]))
        slot = await pool.try_take()
        print("held" if slot else "refused", flush=True)
        await asyncio.sleep(3600)            # until killed: a worker that dies holding a slot

    asyncio.run(main())
""")


def test_a_slot_held_by_another_worker_is_refused_here_and_freed_when_that_worker_dies():
    _postgres_or_skip()
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(BACKEND), PG_URL, str(TEST_KEY_BASE)],
                              stdout=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": str(BACKEND)})
    try:
        assert holder.stdout.readline().strip() == "held"

        async def contend():
            from sqlalchemy.ext.asyncio import create_async_engine
            engine = create_async_engine(PG_URL)
            pool = build_slots.Slots(n=1, engine=engine, key_base=TEST_KEY_BASE)
            try:
                assert await pool.try_take() is None, "the other worker holds the only slot"
                told: list[str] = []

                async def on_wait():
                    told.append("waiting")

                waiting = asyncio.ensure_future(pool.take(on_wait=on_wait, poll_s=0.1))
                await asyncio.sleep(0.5)
                assert not waiting.done() and told == ["waiting"]
                holder.kill()                       # the worker dies; its connection, and its lock, go
                slot = await asyncio.wait_for(waiting, 10)
                assert slot.index == 0
                # Held on a connection of its own: a second contender in this process is refused too.
                assert await pool.try_take() is None
                await pool.give_back(slot)
                again = await pool.try_take()
                assert again is not None, "given back, it is free"
                await pool.give_back(again)
            finally:
                await engine.dispose()

        asyncio.run(contend())
    finally:
        holder.kill()
        holder.wait(5)


def test_two_slots_admit_two_workers_and_refuse_a_third():
    _postgres_or_skip()

    async def go():
        from sqlalchemy.ext.asyncio import create_async_engine
        engines = [create_async_engine(PG_URL) for _ in range(3)]
        pools = [build_slots.Slots(n=2, engine=e, key_base=TEST_KEY_BASE) for e in engines]
        try:
            a, b = await pools[0].try_take(), await pools[1].try_take()
            assert {a.index, b.index} == {0, 1}
            assert await pools[2].try_take() is None
            await pools[0].give_back(a)
            c = await pools[2].try_take()
            assert c is not None and c.index == a.index
            await pools[1].give_back(b)
            await pools[2].give_back(c)
        finally:
            for e in engines:
                await e.dispose()

    asyncio.run(go())
