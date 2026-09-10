"""_tool_app_modifier — the ReAct loop.

Tests inject a canned query_fn (list of steps) so we exercise the
loop's dispatch, duplicate-call short-circuit, terminal handling,
result envelope, and post-terminal guard invocation without hitting
Anthropic.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agents.tool_app_modifier import run_tool_app_modifier


def _seed_project(tmp_path):
    (tmp_path / "src" / "schemas" / "candidates").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "candidates" / "new.json").write_text(
        '{"root": {"type": "Select", "props": {"name": "cvUploadId"}}}'
    )
    (tmp_path / "contracts").mkdir(exist_ok=True)
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"Candidate": {"table": "candidates"}},
        "pages":    [{"route": "/candidates/new"}],
        "workflows": [], "dataSources": [],
    }), encoding="utf-8")
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": [{"name": "Candidate", "table": "candidates"}],
        "pages":    [{"route": "/candidates/new"}], "workflows": [],
    }), encoding="utf-8")
    (tmp_path / "plan.json").write_text(json.dumps({
        "data_models": [{"name": "Candidate", "fields": []}],
        "pages":       [{"route": "/candidates/new", "type": "form"}],
        "workflows":   [],
    }), encoding="utf-8")
    return tmp_path


def _canned(steps):
    """Return an async query_fn that ignores prompt/messages and
    returns ``steps`` verbatim."""
    async def _fn(system_prompt, messages, catalog):
        return steps
    return _fn


# --------------------------------------------------------------------------- #
# Terminal shapes
# --------------------------------------------------------------------------- #

def test_no_query_fn_returns_not_enabled(tmp_path):
    _seed_project(tmp_path)
    result = asyncio.run(run_tool_app_modifier(
        ask="do something", output_dir=str(tmp_path),
    ))
    assert result["status"] == "not_enabled"
    assert "query_fn" in result["summary"] or "boundary" in result["summary"]


def test_terminal_answer_no_mutation_is_no_change_needed(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    result = asyncio.run(run_tool_app_modifier(
        ask="explain what CV field does",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "Read", "args": {"path": "src/schemas/candidates/new.json"}},
            {"tool": "answer", "args": {"text": "The CV field is currently a Select."}},
        ]),
    ))
    assert result["status"] == "no_change_needed"
    assert "Select" in result["summary"]


def test_terminal_ask_is_blocked(tmp_path):
    _seed_project(tmp_path)
    result = asyncio.run(run_tool_app_modifier(
        ask="which candidate page",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "ask", "args": {"question": "Which candidate page? new or apply?"}},
        ]),
    ))
    assert result["status"] == "blocked"
    assert "candidate page" in result["question_for_user"].lower()


# --------------------------------------------------------------------------- #
# Real tool dispatch — Edit + terminal
# --------------------------------------------------------------------------- #

def test_edit_then_answer_marks_applied(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    # No guard failures
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    result = asyncio.run(run_tool_app_modifier(
        ask="swap the CV Select to FileUpload",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "Read", "args": {"path": "src/schemas/candidates/new.json"}},
            {"tool": "Edit", "args": {
                "path": "src/schemas/candidates/new.json",
                "old_string": '"Select"', "new_string": '"FileUpload"',
            }},
            {"tool": "answer", "args": {"text": "Swapped CV Select to FileUpload."}},
        ]),
    ))
    assert result["status"] == "applied"
    assert any(f["path"].endswith("new.json") and f["action"] == "modified"
               for f in result["files_touched"])
    # Trace contains all three steps
    tools_called = [s["tool"] for s in result["trace"]]
    assert tools_called == ["Read", "Edit", "answer"]
    # File was actually edited
    content = (tmp_path / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8")
    assert "FileUpload" in content
    assert "Select" not in content


# --------------------------------------------------------------------------- #
# RegistryPatch — plan/registry sync
# --------------------------------------------------------------------------- #

def test_registry_patch_add_entity_updates_both(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    result = asyncio.run(run_tool_app_modifier(
        ask="add Recruiter entity",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "Write", "args": {
                "path": "src/db/schema/recruiter.ts",
                "content": "export const recruiter = pgTable('recruiter', {});\n",
            }},
            {"tool": "RegistryPatch", "args": {
                "kind": "entity", "op": "add",
                "entry": {"name": "Recruiter", "table": "recruiter",
                          "columns": ["name", "email"]},
            }},
            {"tool": "answer", "args": {"text": "Added Recruiter entity."}},
        ]),
    ))
    assert result["status"] == "applied"
    # Files touched includes the write + registry files
    paths = {f["path"] for f in result["files_touched"]}
    assert "src/db/schema/recruiter.ts" in paths
    assert any("registry.json" in p for p in paths)
    assert any("plan.json" in p for p in paths)
    # Actual disk state
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert any(m["name"] == "Recruiter" for m in plan["data_models"])
    reg = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert "Recruiter" in reg["entities"]


# --------------------------------------------------------------------------- #
# Loop discipline
# --------------------------------------------------------------------------- #

def test_duplicate_calls_short_circuit(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    result = asyncio.run(run_tool_app_modifier(
        ask="ping",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "Read", "args": {"path": "registry.json"}},
            {"tool": "Read", "args": {"path": "registry.json"}},  # dup
            {"tool": "answer", "args": {"text": "done"}},
        ]),
    ))
    assert result["status"] == "no_change_needed"
    dup_step = result["trace"][1]
    assert "SKIPPED" in dup_step["result_summary"]


def test_unknown_tool_recorded_but_loop_continues(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    result = asyncio.run(run_tool_app_modifier(
        ask="ping",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "MadeUpTool", "args": {}},
            {"tool": "answer", "args": {"text": "recovered"}},
        ]),
    ))
    assert result["status"] == "no_change_needed"
    # Bad-tool step logged
    assert "ERROR" in result["trace"][0]["result_summary"]


def test_no_terminal_hits_iteration_cap(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    # 3 Read calls, no terminal → max_iters=2 stops us
    result = asyncio.run(run_tool_app_modifier(
        ask="loop",
        output_dir=str(tmp_path),
        max_iters=2,
        query_fn=_canned([
            {"tool": "Read", "args": {"path": "registry.json"}},
            {"tool": "Read", "args": {"path": "plan.json"}},
            {"tool": "Read", "args": {"path": "contracts/resource-registry.json"}},
        ]),
    ))
    assert result["status"] == "failed"
    assert "cap" in result["summary"].lower() or "iteration" in result["summary"].lower()


# --------------------------------------------------------------------------- #
# emit_fn streaming
# --------------------------------------------------------------------------- #

def test_emit_fn_receives_step_events(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: type("R", (), {"failures": []})(),
    )
    events: list[tuple] = []
    def _emit(stage, payload): events.append((stage, payload))

    asyncio.run(run_tool_app_modifier(
        ask="ping",
        output_dir=str(tmp_path),
        emit_fn=_emit,
        query_fn=_canned([
            {"tool": "Read", "args": {"path": "registry.json"}},
            {"tool": "answer", "args": {"text": "done"}},
        ]),
    ))
    stages = [s for s, _ in events]
    assert "modifier_step" in stages
    # The Read + answer both emit a modifier_step
    assert stages.count("modifier_step") == 2


# --------------------------------------------------------------------------- #
# Guard suite integration
# --------------------------------------------------------------------------- #

def test_guard_failures_carried_in_validation(tmp_path, monkeypatch):
    _seed_project(tmp_path)
    class _F:
        def __init__(self, g, m): self.guard = g; self.message = m
    class _R:
        def __init__(self): self.failures = [_F("test_guard", "sample failure")]
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes_with_result",
        lambda _: _R(),
    )
    result = asyncio.run(run_tool_app_modifier(
        ask="do the thing",
        output_dir=str(tmp_path),
        query_fn=_canned([
            {"tool": "Edit", "args": {
                "path": "src/schemas/candidates/new.json",
                "old_string": '"Select"', "new_string": '"FileUpload"',
            }},
            {"tool": "answer", "args": {"text": "swapped"}},
        ]),
    ))
    assert result["status"] == "applied"
    assert result["validation"]["guard_count"] == 1
    assert result["validation"]["guard_failures"][0]["guard"] == "test_guard"
