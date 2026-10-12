"""A one-line answer to Smith comes back at once, whatever else the server is doing.

On forge-v3 a "Not now" sat under "Thinking… 2m" with the input reading
"Building…" (2026-10-09). Every Smith turn — a whole build included, for up
to an hour — ran on asyncio's DEFAULT thread pool, which on a small host holds
a handful of threads and is shared with everything that calls
`asyncio.to_thread`. A few builds in flight filled it, and a turn that needs a
millisecond waited in its queue while its ledger already said "working".
Turns now run on their own pools; this holds that to the clock with the default
pool fully blocked.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"


async def _built_project(client, org_id) -> dict:
    from services.project_service import OUTPUT_BASE

    res = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Busy server"})
    assert res.status_code == 201, res.text
    body = res.json()
    out = Path(OUTPUT_BASE) / body["short_id"]
    (out / ".forge" / "blueprint").mkdir(parents=True, exist_ok=True)
    (out / ".forge" / "blueprint" / "current.json").write_text(FIXTURE.read_text())
    (out / "app").mkdir(exist_ok=True)
    (out / "app" / "package.json").write_text('{"name": "built"}')
    return body


@pytest.mark.asyncio
async def test_not_now_is_answered_while_the_default_pool_is_full(auth_client, org_id):
    project = await _built_project(auth_client, org_id)

    # The default pool, full: one thread, held by "a build".
    loop = asyncio.get_running_loop()
    release = threading.Event()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(pool)
    held = loop.run_in_executor(None, release.wait, 30)
    try:
        started = time.monotonic()
        res = await asyncio.wait_for(auth_client.post(
            f"/api/projects/{project['id']}/smith/chat",
            json={"message": "Not now", "history": [], "approved": False}), timeout=10)
        took = time.monotonic() - started
        assert res.status_code == 200, res.text
        assert "nothing run" in res.text, res.text[-500:]
        assert took < 5, f"a one-line answer took {took:.1f}s behind a busy pool"
    finally:
        release.set()
        await held
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor())
        pool.shutdown(wait=False)


def test_two_turns_begun_in_the_same_second_keep_their_own_ledgers(tmp_path):
    from services import run_registry
    from services.blueprint.run_ledger import TurnLedger
    a, b = TurnLedger(tmp_path), TurnLedger(tmp_path)
    a.end(); b.end()
    runs = sorted((tmp_path / ".forge" / "runs").glob("*.jsonl"))
    assert len(runs) == 2 and all(run_registry._is_turn(p) for p in runs)
