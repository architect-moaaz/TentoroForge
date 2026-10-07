"""Every model call reaches the usage ledger — Smith's, the reviewer's and the
trials' as well as the build's — once each.

The ledger held build nodes only, and on forge-v3 it stopped on 2026-09-23:
the compose file never handed the backend `FORGE_USAGE_LOG`, so the ledger
lived inside the container and every cutover erased it. "What does checking
an app cost?" had no answer (2026-10-03).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import build_usage
from services.blueprint.executors import RunUsage, Usage

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))

    def rows():
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    return rows


def _app(tmp_path, app_id="fxa532bj"):
    out = tmp_path / app_id
    (out / ".forge" / "blueprint").mkdir(parents=True)
    (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps({"application": {"id": app_id}}))
    return str(out)


def test_a_call_in_a_scope_is_written_when_the_scope_ends(ledger, tmp_path):
    out = _app(tmp_path)
    with build_usage.usage_scope(agent="smith", output_dir=out):
        build_usage.spent(Usage(model="claude-sonnet-5", input_tokens=1200, output_tokens=300))
        assert ledger() == []                                     # written at the end, not before
    (row,) = ledger()
    assert row["project"] == "fxa532bj" and row["agent"] == "smith" and row["phase"] == "change"
    assert row["input_tokens"] == 1200 and row["output_tokens"] == 300 and row["est_cost_usd"] > 0


def test_a_call_a_build_node_records_is_not_written_twice(ledger, tmp_path):
    out = _app(tmp_path)
    used = Usage(model="claude-sonnet-5", input_tokens=500, output_tokens=100)
    with build_usage.usage_scope(agent="smith", output_dir=out):
        build_usage.spent(used)
        RunUsage(project="fxa532bj").record(node="page_code", agent="ui_engineer", usage=used, elapsed_s=1.0)
    assert [r["agent"] for r in ledger()] == ["page_code:ui_engineer"]


def test_a_turn_the_build_starts_is_the_builds_spend(ledger, tmp_path):
    out = _app(tmp_path)
    with build_usage.usage_scope(agent="process_trials", output_dir=out, phase="build", kind="build"):
        build_usage.spent(Usage(model="claude-sonnet-5", input_tokens=10, output_tokens=10))
        with build_usage.usage_scope(agent="smith"):
            build_usage.spent(Usage(model="claude-sonnet-5", input_tokens=20, output_tokens=20))
    rows = {r["agent"]: r for r in ledger()}
    assert set(rows) == {"process_trials", "process_trials:smith"}
    assert rows["process_trials:smith"]["phase"] == "build" and rows["process_trials:smith"]["project"] == "fxa532bj"


def test_a_call_outside_any_scope_is_left_to_its_caller(ledger):
    build_usage.spent(Usage(model="claude-sonnet-5", input_tokens=10, output_tokens=10))
    assert ledger() == []


def test_the_langchain_client_reports_its_calls(ledger, tmp_path):
    from services import llm_client
    ai = SimpleNamespace(content="hi", response_metadata={"stop_reason": "end_turn"},
                         usage_metadata={"input_tokens": 70, "output_tokens": 30,
                                         "input_token_details": {"cache_read": 5}})
    with build_usage.usage_scope(agent="look_at_site", output_dir=_app(tmp_path)):
        llm_client._to_message(ai, "claude-sonnet-5")
    (row,) = ledger()
    # LangChain's 70 includes the 5 read from the cache; the ledger keeps
    # Anthropic's split, so the cached five are priced as cached.
    assert row["input_tokens"] == 65 and row["output_tokens"] == 30 and row["cache_read_tokens"] == 5


def test_a_smith_turn_and_the_builds_checks_open_a_scope(ledger, tmp_path, monkeypatch):
    import importlib
    handle_mod = importlib.import_module("services.smith4.handle")
    from services.smith4.outcome import Outcome

    def turn(**kwargs):
        build_usage.spent(Usage(model="claude-sonnet-5", input_tokens=40, output_tokens=40))
        return Outcome(status="no_op", said="ok")
    monkeypatch.setattr(handle_mod, "_handle", turn)
    handle_mod.handle(project_id="p", output_dir=_app(tmp_path), message="hi")
    assert [r["agent"] for r in ledger()] == ["smith"]

    for module, agent in (("page_repair", "page_repair"), ("process_trials", "process_trials"),
                          ("orchestrator", "page_review")):
        src = (ROOT / "backend/services/blueprint" / f"{module}.py").read_text()
        assert f'usage_scope(agent="{agent}"' in src, module


def test_the_backend_is_told_where_the_ledger_lives():
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    assert "FORGE_USAGE_LOG: ${FORGE_USAGE_LOG:-/output/_usage/build-usage.jsonl}" in compose
