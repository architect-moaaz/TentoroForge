"""The Foundry hears every job a project runs, from the jobs' own ledgers.

It heard only the build the Smith panel was streaming: a Smith turn, a fix,
the checks after a build, the process trials, a publish, a self-heal — and any
build started in the background or picked up after a restart — moved no one.
Every long job keeps a run ledger, so the Foundry's feed follows those
(`services.office_feed`) and each agent works when their work happens.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.office_feed import ProjectFeed


def _write(path: Path, *events: dict, partial: str = "") -> None:
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
        fh.write(partial)


@pytest.fixture
def runs(tmp_path):
    d = tmp_path / ".forge" / "runs"
    d.mkdir(parents=True)
    return d


def _types(events: list[dict], agent: str | None = None) -> list[str]:
    return [e["type"] for e in events if agent is None or e.get("agent") == agent]


def test_a_build_is_bob_todd_and_otto_at_work(runs, tmp_path):
    ledger = runs / "20261028-100000-abc123.jsonl"
    _write(ledger, {"event": "run:start", "phase": "build"},
           {"event": "plan", "nodes": ["data_model", "entity_fields", "workflow_steps"], "total": 3})
    feed = ProjectFeed(tmp_path)
    first = feed.poll()                                  # an open build is replayed on connect
    assert first[0]["type"] == "run_plan" and "data_model" in first[0]["agents"]
    _write(ledger, {"event": "node:start", "node": "entity_fields", "subjects": 1},
           {"event": "observer:verdict", "node": "entity_fields", "ok": False, "findings": 2},
           {"event": "observer:repair", "node": "entity_fields", "round": 1, "of": 2, "reason": "a field is missing"},
           {"event": "node:done", "node": "entity_fields", "artifacts": 4})
    more = feed.poll()
    assert _types(more, "data_model")[:2] == ["agent_start", "agent_status"]          # Bob starts
    assert "agent_start" in _types(more, "observer")                                # Otto reviews
    assert any(e["type"] == "agent_status" and e.get("agent") == "observer" and "2 findings" in e["status"]
               for e in more)
    assert any(e["type"] == "agent_retry" and e["agent"] == "data_model" and "Sent back" in e["reason"]
               for e in more)                                                        # …and sends it back
    assert "agent_complete" in _types(more, "data_model")
    _write(ledger, {"event": "run:end", "completed": ["data_model", "entity_fields", "workflow_steps"]})
    assert _types(feed.poll()) == ["build_success"]
    assert feed.poll() == []


def test_a_finished_run_is_history_and_is_not_replayed(runs, tmp_path):
    _write(runs / "20261028-090000-abc.jsonl", {"event": "run:start"},
           {"event": "node:start", "node": "data_model"}, {"event": "run:end"})
    assert ProjectFeed(tmp_path).poll() == []


def test_the_checks_are_tess_and_trey_and_end_without_a_party(runs, tmp_path):
    feed = ProjectFeed(tmp_path)
    assert feed.poll() == []
    check = runs / "20261028-110000-checks.jsonl"
    _write(check, {"event": "run:start", "phase": "checking"}, {"event": "node:start", "node": "checks"},
           {"event": "node:start", "node": "process_trials"}, {"event": "node:done", "node": "checks"},
           {"event": "run:end", "completed": ["checks"]})
    events = feed.poll()                                  # a ledger that appears later is followed too
    assert "agent_start" in _types(events, "testing")
    assert "agent_start" in _types(events, "process_trials")
    assert "build_success" not in _types(events) and "run_complete" not in _types(events)


def test_a_turn_is_smith_saying_his_step(runs, tmp_path):
    feed = ProjectFeed(tmp_path)
    feed.poll()
    turn = runs / "20261028-120000-smith-turn.jsonl"
    _write(turn, {"event": "run:start", "phase": "change"}, partial='{"event": "turn:step", "te')
    first = feed.poll()
    assert _types(first, "smith") == ["agent_start", "agent_status"]
    assert first[1]["status"] == "Working on your message"
    with turn.open("a") as fh:
        fh.write('xt": "Reading the Orders page"}\n')     # the half-written line completes
    step = feed.poll()
    assert [e["status"] for e in step if e["type"] == "agent_status"] == ["Reading the Orders page"]
    _write(turn, {"event": "run:end"})
    assert "agent_complete" in _types(feed.poll(), "smith")


def test_a_publish_is_dex_and_a_cut_off_one_is_said(runs, tmp_path):
    feed = ProjectFeed(tmp_path)
    feed.poll()
    pub = runs / "20261028-130000-publish.jsonl"
    _write(pub, {"event": "run:start", "phase": "publish"})
    assert _types(feed.poll(), "deployment") == ["agent_start", "agent_status"]
    _write(pub, {"event": "run:crashed", "error": "the platform restarted while it ran"})
    err = [e for e in feed.poll() if e["type"] == "agent_error"]
    assert err and err[0]["agent"] == "deployment" and "restarted" in err[0]["message"]


def test_a_fix_and_a_self_heal_are_smith_too(runs, tmp_path):
    feed = ProjectFeed(tmp_path)
    feed.poll()
    _write(runs / "20261028-140000-smith-fix.jsonl", {"event": "run:start"})
    _write(runs / "20261028-140001-self-heal.jsonl", {"event": "run:start"})
    said = [e["status"] for e in feed.poll() if e["type"] == "agent_status" and e["agent"] == "smith"]
    assert said == ["Looking into what went wrong", "Fixing a fault the app reported"]


def test_a_paused_build_for_credit_says_so(runs, tmp_path):
    ledger = runs / "20261028-150000-abc.jsonl"
    _write(ledger, {"event": "run:start"}, {"event": "run:paused", "reason": "Your credit balance is too low"})
    assert _types(ProjectFeed(tmp_path).poll()) == ["credits_exhausted"]


@pytest.mark.asyncio
async def test_no_one_signed_out_hears_the_foundry(client):
    assert (await client.get("/api/projects/abc12345/office")).status_code == 401


@pytest.mark.asyncio
async def test_a_project_that_is_not_yours_is_not_heard(auth_client):
    assert (await auth_client.get("/api/projects/nosuchapp/office")).status_code in (403, 404)


def test_the_foundry_on_screen_reads_the_feed_and_the_build_panel_no_longer_tells_it():
    root = Path(__file__).resolve().parents[3] / "frontend" / "src"
    office = (root / "components" / "virtual-office" / "VirtualOffice.tsx").read_text()
    assert "watchFoundry(projectId)" in office
    page = (root / "app" / "org" / "[orgId]" / "projects" / "[projectId]" / "page.tsx").read_text()
    assert "projectId={projectId}" in page.split("<VirtualOffice", 1)[1].split("/>", 1)[0]
    assert "OfficeBridge" not in (root / "hooks" / "useBlueprintRun.ts").read_text()
