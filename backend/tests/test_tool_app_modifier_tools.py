"""Sandboxed tool primitives for _tool_app_modifier — Read / Bash /
Edit / Write / RegistryPatch. Focus of these tests:

  * Sandbox enforcement — refuses paths outside output_dir.
  * Bash allowlist — refuses non-allowlisted commands.
  * Edit — unique-match enforcement, replace_all opt-in.
  * Write — refuses to overwrite.
  * RegistryPatch — updates registry.json + plan.json + contracts
    in sync; add/remove/update op semantics.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.tool_app_modifier_tools import (
    read_tool, bash_tool, edit_tool, write_tool, registry_patch_tool,
    HANDLERS, TOOL_CATALOG,
)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #

def test_read_returns_numbered_content(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.json").write_text('{"hello": 1}\n{"world": 2}\n')
    r = read_tool(str(tmp_path), "src/a.json")
    assert r["ok"] is True
    assert "1  " in r["content"]  # first line numbered
    assert r["lines"] == 3  # 2 content + trailing empty


def test_read_rejects_path_outside_sandbox(tmp_path):
    r = read_tool(str(tmp_path), "../../../etc/passwd")
    assert r["ok"] is False
    assert "outside sandbox" in r["error"]


def test_read_absolute_path_outside_sandbox_rejected(tmp_path):
    r = read_tool(str(tmp_path), "/etc/passwd")
    assert r["ok"] is False


def test_read_missing_file_returns_error(tmp_path):
    r = read_tool(str(tmp_path), "does/not/exist.json")
    assert r["ok"] is False
    assert "not found" in r["error"]


# --------------------------------------------------------------------------- #
# Bash allowlist
# --------------------------------------------------------------------------- #

def test_bash_allows_grep(tmp_path):
    (tmp_path / "a.txt").write_text("hello world\n")
    r = bash_tool(str(tmp_path), "grep hello a.txt")
    assert r["ok"] is True
    assert "hello world" in r["stdout"]
    assert r["exit_code"] == 0


def test_bash_refuses_rm(tmp_path):
    (tmp_path / "victim.txt").write_text("x")
    r = bash_tool(str(tmp_path), "rm victim.txt")
    assert r["ok"] is False
    assert "allowlist" in r["error"]
    assert (tmp_path / "victim.txt").exists()  # untouched


def test_bash_refuses_curl(tmp_path):
    r = bash_tool(str(tmp_path), "curl https://example.com")
    assert r["ok"] is False


def test_bash_git_only_read_subcommands(tmp_path):
    # git status is fine, git commit is not
    r_ok = bash_tool(str(tmp_path), "git status")
    # may return non-zero (not a git repo) but the tool call itself is ok
    assert r_ok["ok"] is True
    r_bad = bash_tool(str(tmp_path), "git commit -am fake")
    assert r_bad["ok"] is False
    assert "not allowed" in r_bad["error"]


def test_bash_python_one_liner_ok(tmp_path):
    (tmp_path / "x.json").write_text('{"a": 1}')
    r = bash_tool(str(tmp_path), 'python3 -c "import json; print(json.load(open(\'x.json\'))[\'a\'])"')
    assert r["ok"] is True
    assert "1" in r["stdout"]


# --------------------------------------------------------------------------- #
# Edit
# --------------------------------------------------------------------------- #

def test_edit_replaces_unique_match(tmp_path):
    (tmp_path / "x.json").write_text('{"kind": "Select"}\n')
    r = edit_tool(str(tmp_path), "x.json", '"Select"', '"FileUpload"')
    assert r["ok"] is True
    assert r["matches_replaced"] == 1
    assert (tmp_path / "x.json").read_text() == '{"kind": "FileUpload"}\n'


def test_edit_refuses_ambiguous_match(tmp_path):
    (tmp_path / "x.json").write_text('{"a": "Select"}\n{"b": "Select"}\n')
    r = edit_tool(str(tmp_path), "x.json", '"Select"', '"FileUpload"')
    assert r["ok"] is False
    assert "ambiguous" in r["error"]
    assert "Select" in (tmp_path / "x.json").read_text()  # untouched


def test_edit_replace_all(tmp_path):
    (tmp_path / "x.json").write_text('{"a": "Select"}\n{"b": "Select"}\n')
    r = edit_tool(str(tmp_path), "x.json", '"Select"', '"FileUpload"',
                  replace_all=True)
    assert r["ok"] is True
    assert r["matches_replaced"] == 2
    assert "Select" not in (tmp_path / "x.json").read_text()


def test_edit_missing_anchor_reports_error(tmp_path):
    (tmp_path / "x.json").write_text('{"kind": "Select"}\n')
    r = edit_tool(str(tmp_path), "x.json", '"Kanban"', '"FileUpload"')
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_edit_rejects_outside_sandbox(tmp_path):
    r = edit_tool(str(tmp_path), "/etc/passwd", "root", "haha")
    assert r["ok"] is False


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #

def test_write_creates_new_file(tmp_path):
    r = write_tool(str(tmp_path), "new/a.json", '{"a": 1}')
    assert r["ok"] is True
    assert (tmp_path / "new" / "a.json").read_text() == '{"a": 1}'


def test_write_refuses_existing_file(tmp_path):
    (tmp_path / "x.json").write_text("old")
    r = write_tool(str(tmp_path), "x.json", "new")
    assert r["ok"] is False
    assert "exists" in r["error"]
    assert (tmp_path / "x.json").read_text() == "old"


def test_write_rejects_outside_sandbox(tmp_path):
    r = write_tool(str(tmp_path), "/tmp/absolutely-not.json", "x")
    assert r["ok"] is False


# --------------------------------------------------------------------------- #
# RegistryPatch — entity add across registry + plan
# --------------------------------------------------------------------------- #

def _seed_project(tmp_path):
    """Seed a minimal project with registry.json, plan.json,
    contracts/resource-registry.json."""
    (tmp_path / "contracts").mkdir()
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"Candidate": {"table": "candidates"}},
        "pages":    [{"route": "/candidates"}],
        "workflows": [],
        "dataSources": [],
    }))
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": [{"name": "Candidate", "table": "candidates"}],
        "pages":    [{"route": "/candidates"}],
        "workflows": [],
    }))
    (tmp_path / "plan.json").write_text(json.dumps({
        "data_models": [{"name": "Candidate", "fields": [{"name": "email"}]}],
        "pages":       [{"route": "/candidates", "type": "list"}],
        "workflows":   [],
    }))
    return tmp_path


def test_registry_patch_add_entity_updates_all(tmp_path):
    _seed_project(tmp_path)
    r = registry_patch_tool(str(tmp_path), "entity", "add", {
        "name": "Recruiter", "table": "recruiters",
        "columns": ["name", "email"],
    })
    assert r["ok"] is True
    assert len(r["files_touched"]) >= 2  # registry.json + resource-registry.json + plan.json

    reg = json.loads((tmp_path / "registry.json").read_text())
    assert "Recruiter" in reg["entities"]

    rr = json.loads((tmp_path / "contracts" / "resource-registry.json").read_text())
    names = {e["name"] for e in rr["entities"]}
    assert "Recruiter" in names

    plan = json.loads((tmp_path / "plan.json").read_text())
    plan_names = {m["name"] for m in plan["data_models"]}
    assert "Recruiter" in plan_names


def test_registry_patch_add_page_updates_registry_and_plan(tmp_path):
    _seed_project(tmp_path)
    r = registry_patch_tool(str(tmp_path), "page", "add", {
        "route": "/recruiters", "type": "list", "entity": "Recruiter",
    })
    assert r["ok"] is True
    reg = json.loads((tmp_path / "registry.json").read_text())
    routes = {p["route"] for p in reg["pages"]}
    assert "/recruiters" in routes
    plan = json.loads((tmp_path / "plan.json").read_text())
    plan_routes = {p["route"] for p in plan["pages"]}
    assert "/recruiters" in plan_routes


def test_registry_patch_remove_entity(tmp_path):
    _seed_project(tmp_path)
    r = registry_patch_tool(str(tmp_path), "entity", "remove", {
        "name": "Candidate",
    })
    assert r["ok"] is True
    reg = json.loads((tmp_path / "registry.json").read_text())
    assert "Candidate" not in reg["entities"]
    rr = json.loads((tmp_path / "contracts" / "resource-registry.json").read_text())
    assert {e["name"] for e in rr["entities"]} == set()
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["data_models"] == []


def test_registry_patch_add_workflow(tmp_path):
    _seed_project(tmp_path)
    r = registry_patch_tool(str(tmp_path), "workflow", "add", {
        "name": "CreateRecruiter", "entity": "Recruiter",
        "trigger": "form_submit",
    })
    assert r["ok"] is True
    plan = json.loads((tmp_path / "plan.json").read_text())
    wf_names = {w["name"] for w in plan["workflows"]}
    assert "CreateRecruiter" in wf_names


def test_registry_patch_add_datasource_no_plan_change(tmp_path):
    """dataSource is a registry-only concept — plan.json unchanged."""
    _seed_project(tmp_path)
    plan_before = (tmp_path / "plan.json").read_text()
    r = registry_patch_tool(str(tmp_path), "dataSource", "add", {
        "name": "recruiters", "entity": "Recruiter", "op": "list",
    })
    assert r["ok"] is True
    assert (tmp_path / "plan.json").read_text() == plan_before


def test_registry_patch_missing_key_rejected(tmp_path):
    _seed_project(tmp_path)
    r = registry_patch_tool(str(tmp_path), "entity", "add", {"table": "x"})
    assert r["ok"] is False
    assert "missing" in r["error"]


def test_registry_patch_unknown_kind_rejected(tmp_path):
    _seed_project(tmp_path)
    r = registry_patch_tool(str(tmp_path), "widget", "add", {"name": "x"})
    assert r["ok"] is False


# --------------------------------------------------------------------------- #
# Handler dispatch — the ReAct loop uses these
# --------------------------------------------------------------------------- #

def test_handlers_cover_every_catalog_tool():
    for t in TOOL_CATALOG:
        assert t["name"] in HANDLERS, f"missing handler for {t['name']}"
    assert set(HANDLERS.keys()) >= {t["name"] for t in TOOL_CATALOG}


def test_handler_dispatches_read(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    out = HANDLERS["Read"](str(tmp_path), {"path": "a.txt"})
    assert out["ok"] is True
    assert "hello" in out["content"]
