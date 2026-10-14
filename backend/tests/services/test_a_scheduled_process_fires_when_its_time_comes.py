"""A process that runs on the clock is projected as a contract the runtime's
scheduler reads, the app's tick runs as often as the finest schedule needs,
and the clock check proves it fires by firing it (2026-10-12)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint import clock_check as cc
from services.blueprint.projection import _trigger_contract, project_workflows

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Invoice", "table": "invoices", "fields": []}]},
    "workflows": [
        {"id": "FLOW-001", "name": "Nightly digest", "status": "ACTIVE",
         "trigger": {"kind": "schedule", "detail": "every night at six", "cron": "0 18 * * *", "timezone": "Asia/Dubai"},
         "steps": [{"key": "start", "type": "trigger", "config": {"type": "schedule"}},
                   {"key": "done", "type": "end", "config": {}}]},
        {"id": "FLOW-002", "name": "Quarter sweep", "status": "ACTIVE",
         "trigger": {"kind": "schedule", "detail": "*/5 * * * *", "enabled": False},
         "steps": [{"key": "start", "type": "trigger", "config": {"type": "schedule"}},
                   {"key": "done", "type": "end", "config": {}}]},
        {"id": "FLOW-003", "name": "Pay invoice", "status": "ACTIVE", "trigger": {"kind": "manual"},
         "steps": [{"key": "start", "type": "trigger", "config": {"type": "manual"}},
                   {"key": "done", "type": "end", "config": {}}]},
    ],
}


def test_a_schedule_is_a_contract_the_scheduler_reads():
    assert _trigger_contract(DOC, DOC["workflows"][0]) == {"kind": "schedule", "cron": "0 18 * * *", "timezone": "Asia/Dubai"}
    assert _trigger_contract(DOC, DOC["workflows"][1]) == {"kind": "schedule", "cron": "*/5 * * * *", "enabled": False}, \
        "a cron written in the sentence is read; paused is carried"
    assert _trigger_contract(DOC, DOC["workflows"][2]) is None


def test_the_definition_and_the_tick_are_written(tmp_path):
    out = project_workflows(DOC, tmp_path)
    digest = json.loads((tmp_path / "src/lib/workflows/definitions/nightly-digest.json").read_text())
    assert digest["trigger"] == {"kind": "schedule", "cron": "0 18 * * *", "timezone": "Asia/Dubai"}
    assert digest["definition"]["trigger"]["cron"] == "0 18 * * *", "the legacy shape stays beside it"
    assert "vercel.json" in out["files"]
    tick = next(c for c in json.loads((tmp_path / "vercel.json").read_text())["crons"] if c["path"] == "/api/cron/tick")
    assert tick["schedule"] == "*/5 * * * *", "as often as the finest schedule needs"


def test_clocked_processes_are_the_criterions_total():
    assert [w["id"] for w in cc.clocked(DOC)] == ["FLOW-001", "FLOW-002"]


def _fake_tick(answers):
    calls = []

    def tick(app, app_root, **params):
        calls.append(params)
        return answers.pop(0)
    return tick, calls


def test_the_check_fires_each_schedule_and_reads_that_it_ran(monkeypatch, tmp_path):
    tick, calls = _fake_tick([(200, {"forced": {"workflow": "FLOW-001", "fired": True}}),
                              (200, {"forced": {"workflow": "FLOW-002", "fired": False, "reason": "no workflow 'FLOW-002'"}})])
    monkeypatch.setattr(cc, "tick", tick)
    monkeypatch.setattr(cc, "runs_since", lambda app, slug, since: 3 if slug == "nightly-digest" else 0)
    out = cc.check_clock(object(), DOC, bench=None, app_root=tmp_path)
    assert calls[0]["workflow"] == "FLOW-001" and calls[0]["force"] == "1"
    assert [g["id"] for g in out["green"]] == ["FLOW-001::trigger"]
    assert out["red"][0]["id"] == "FLOW-002::trigger" and "no workflow" in out["red"][0]["why"]
    assert out["total"] == 2 and all(i["cause"] in ("FLOW-001", "FLOW-002") for i in out["green"] + out["red"])


@pytest.mark.parametrize("status,why", [(401, "refused the check's key"), (404, "no tick route")])
def test_a_tick_the_check_cannot_reach_is_untried_not_red(monkeypatch, tmp_path, status, why):
    tick, _ = _fake_tick([(status, {}), (status, {})])
    monkeypatch.setattr(cc, "tick", tick)
    out = cc.check_clock(object(), DOC, bench=None, app_root=tmp_path)
    assert not out["red"] and len(out["untried"]) == 2 and why in out["untried"][0]["why"]


def test_the_tick_carries_the_apps_own_key(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("CRON_SECRET=abc123\nNEXTAUTH_SECRET=x\n")
    seen = {}

    def http(app, method, path, body, cookies):
        seen["path"] = path
        return 200, "", "{}"
    monkeypatch.setattr("services.smith.trials._http", http)
    cc.tick(object(), tmp_path, workflow="FLOW-001", force="1")
    assert seen["path"].startswith("/api/cron/tick?") and "secret=abc123" in seen["path"] and "force=1" in seen["path"]
