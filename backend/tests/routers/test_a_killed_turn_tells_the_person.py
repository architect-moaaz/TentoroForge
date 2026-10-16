"""A ledger the restart closed is a turn somebody was waiting on: the chat of
that application gets one line saying so and how to go on. The tester of
pcn4owv7 waited an hour on "Still working on it" after the host killed the
worker (2026-10-15)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_the_chat_says_the_turn_was_lost(auth_client, org_id, monkeypatch):
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Finance"})).json()
    root = Path(os.environ["FORGE_OUTPUT_BASE"])
    runs = root / project["short_id"] / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "20261015-024202-smith-turn.jsonl").write_text(
        json.dumps({"event": "run:start", "phase": "define", "at": "2026-10-15T02:42:02Z", "pid": 9}) + "\n"
        + json.dumps({"event": "run:heartbeat", "at": "2026-10-15T03:14:22Z", "elapsedMs": 1941042}) + "\n")
    (runs / "20261015-013000-build1.jsonl").write_text(
        json.dumps({"event": "run:start", "phase": "build", "at": "2026-10-15T01:30:00Z", "pid": 9}) + "\n")

    import main as app_main
    from services import run_registry
    monkeypatch.setattr("services.project_paths.OUTPUT_ROOT", root, raising=False)
    await app_main._close_orphaned_ledgers()

    rows = (await auth_client.get(f"/api/projects/{project['id']}/conversations")).json()
    texts = [r["content"] for r in rows if r["role"] == "assistant"]
    assert any("The platform restarted at" in t and "Say “carry on”" in t for t in texts), texts
    assert any("during the build" in t and "Press Build" in t for t in texts), texts
    # Closed on disk too, and told once: a second start finds nothing to close.
    last = (runs / "20261015-024202-smith-turn.jsonl").read_text().strip().splitlines()[-1]
    assert json.loads(last)["event"] == "run:crashed"
    assert run_registry.close_orphaned_ledgers(root) == []
