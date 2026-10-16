"""A ledger that stops pulsing while the platform is up — its worker died,
the container did not — is closed by the watch, its person is told in the
chat, and the incident is on the record for the cockpit."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from services import incidents, lost_runs


@pytest.mark.asyncio
async def test_a_silent_turn_is_closed_told_and_recorded(auth_client, super_admin_client, org_id, monkeypatch):
    root = Path(os.environ["FORGE_OUTPUT_BASE"])
    monkeypatch.setattr("services.project_paths.OUTPUT_ROOT", root, raising=False)
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Finance"})).json()
    runs = root / project["short_id"] / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    silent = runs / "20261015-064436-smith-turn.jsonl"
    silent.write_text(json.dumps({"event": "run:start", "phase": "define", "at": "2026-10-15T06:44:36Z", "pid": 9}) + "\n"
                      + json.dumps({"event": "run:heartbeat", "at": "2026-10-15T07:38:40Z"}) + "\n")
    old = time.time() - 600
    os.utime(silent, (old, old))
    alive = runs / "20261015-101619-smith-turn.jsonl"
    alive.write_text(json.dumps({"event": "run:start", "phase": "define", "at": "2026-10-15T10:16:19Z", "pid": 9}) + "\n")

    closed = lost_runs.scan(root)
    assert closed == [str(silent)]            # the pulsing one is left alone
    assert json.loads(silent.read_text().strip().splitlines()[-1])["event"] == "run:crashed"
    assert lost_runs.scan(root) == []          # closed once

    told = await lost_runs.tell(closed, "stopped responding")
    assert told == 1
    rows = (await auth_client.get(f"/api/projects/{project['id']}/conversations")).json()
    texts = [r["content"] for r in rows if r["role"] == "assistant"]
    assert any("process working on this went away" in t and "Say “carry on”" in t for t in texts), texts

    listed = (await super_admin_client.get("/api/admin/incidents")).json()["incidents"]
    assert listed[0]["kind"] == "turn_lost" and listed[0]["app"] == project["short_id"] and listed[0]["why"] == "stopped responding"
    assert (await auth_client.get("/api/admin/incidents")).status_code == 403
    assert incidents.recent(1)[0]["ledger"] == "20261015-064436-smith-turn"
