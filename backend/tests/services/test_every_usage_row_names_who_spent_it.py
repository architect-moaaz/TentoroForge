"""Every usage row names the person and the organisation it was spent for:
a row written under `acting`, a scope flushed after the request ended, a
run's ledger taken where the run starts, and a row written from a pool's
worker thread through `carrying` — side by side, each in its own context."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from services import build_usage


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))

    def rows() -> list[dict]:
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    return rows


def test_a_row_written_under_acting_names_them(ledger):
    with build_usage.acting(user="asha@example.com", org="org-a"):
        build_usage.record_usage(project="app1", agent="a", model="claude-sonnet-5",
                                 usage={"input_tokens": 10, "output_tokens": 5})
    build_usage.record_usage(project="app1", agent="a", model="claude-sonnet-5",
                             usage={"input_tokens": 10, "output_tokens": 5})
    rows = ledger()
    assert (rows[0]["user"], rows[0]["org"]) == ("asha@example.com", "org-a")
    assert (rows[1]["user"], rows[1]["org"]) == ("", "")
    assert build_usage.actor() == {}


def test_a_scope_keeps_the_actor_it_opened_under(ledger):
    usage = SimpleNamespace(model="claude-sonnet-5", as_ledger_dict=lambda: {"input_tokens": 3, "output_tokens": 3})
    with build_usage.acting(user="ravi@example.com", org="org-b"):
        with build_usage.usage_scope(agent="smith", project="app2", phase="change"):
            build_usage.spent(usage, elapsed_s=0.1)
    rows = ledger()
    assert len(rows) == 1 and (rows[0]["user"], rows[0]["org"]) == ("ravi@example.com", "org-b")
    assert rows[0]["agent"] == "smith" and rows[0]["phase"] == "change"


def test_a_runs_ledger_takes_the_actor_where_it_starts(ledger):
    from services.blueprint.executors import RunUsage, Usage
    svc = SimpleNamespace(doc={"application": {"id": "app3"}})
    with build_usage.acting(user="asha@example.com", org="org-a"):
        run = RunUsage.for_app(svc, phase="build")
    assert (run.user, run.org) == ("asha@example.com", "org-a")
    usage = Usage(model="claude-sonnet-5", input_tokens=4, output_tokens=4)
    run.record(node="page_code", agent="ui_engineer", usage=usage, elapsed_s=1.0)
    rows = ledger()
    assert rows and (rows[0]["user"], rows[0]["org"], rows[0]["project"]) == ("asha@example.com", "org-a", "app3")


def test_a_pools_worker_carries_the_actor_and_a_bare_one_does_not(ledger):
    def write(tag: str) -> None:
        build_usage.record_usage(project="app1", agent=tag, model="claude-sonnet-5",
                                 usage={"input_tokens": 1, "output_tokens": 1})

    with build_usage.acting(user="asha@example.com", org="org-a"):
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(build_usage.carrying(write), ["carried-1", "carried-2"]))
            list(pool.map(write, ["bare"]))
    rows = {r["agent"]: r for r in ledger()}
    assert rows["carried-1"]["user"] == "asha@example.com" and rows["carried-2"]["org"] == "org-a"
    assert rows["bare"]["user"] == ""
