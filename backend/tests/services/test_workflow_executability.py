"""Part B: workflow executability contract.

Distinguishes structurally-valid-but-prose workflows (no-ops at runtime) from
executable ones, and regenerates the prose ones against the contract.
"""
import json

import pytest

from services.workflow_executability import (
    action_node_executable, is_executable_workflow, find_nonexecutable,
    ensure_workflow_executability,
)


def _action(action_type, config_extra):
    return {"id": "a", "type": "action",
            "data": {"label": "x", "config": {"actionType": action_type, **config_extra}}}


def _wf(nodes):
    return {"id": "w", "name": "W", "definition": {
        "trigger": {"type": "manual"},
        "nodes": [{"id": "trigger", "type": "trigger"}, *nodes,
                  {"id": "end", "type": "end"}],
        "edges": [],
    }}


def test_action_node_executable_by_actiontype():
    assert action_node_executable(_action("db_insert", {"table": "t", "values": {"a": "a"}}))
    assert action_node_executable(_action("send_email", {"to": "${email}", "body": "hi"}))
    assert action_node_executable(_action("http_call", {"url": "https://x"}))
    # prose-only — the observed bug
    assert not action_node_executable(_action("send_notification", {"description": "notify office"}))
    assert not action_node_executable(_action("db_query", {"description": "Update Invoice.total"}))
    # custom / unknown actionType is a no-op storyboard
    assert not action_node_executable(_action("ai_classify", {"description": "classify"}))
    # non-action nodes are never the concern
    assert action_node_executable({"id": "c", "type": "condition"})


def test_ai_nodes_are_executable_when_well_formed():
    """Regression: a well-formed AI node must NOT be treated as a no-op, else the
    guard regenerates it into `custom` and silently kills the AI step (e.g. the
    CVParsing ai_extract lost its extraction and became actionType=custom)."""
    # CVParsing shape — prompt + input var present
    assert action_node_executable(_action("ai_extract", {
        "prompt": "Extract fullName, email, phone from the CV.",
        "inputVar": "cvFileUrl", "outputVar": "parsedCv",
    }))
    # canonical ai* field names
    assert action_node_executable(_action("ai_extract", {
        "aiExtractFields": ["fullName", "email"], "aiFileRef": "{{trigger.fileId}}",
    }))
    assert action_node_executable(_action("ai_generate", {"aiPrompt": "Draft an offer letter."}))
    assert action_node_executable(_action("ai_classify", {"aiInput": "{{ticket.body}}"}))
    assert action_node_executable(_action("ai_decide", {"aiPrompt": "Approve if score > 80."}))
    assert action_node_executable(_action("generate_document", {"template": "offer", "data": {"x": 1}}))
    # still a no-op when it carries only prose — SHOULD be regenerated
    assert not action_node_executable(_action("ai_extract", {"description": "extract cv fields"}))
    assert not action_node_executable(_action("generate_document", {"description": "make a pdf"}))


def test_is_executable_workflow():
    crud = _wf([_action("db_insert", {"table": "customers", "values": {"name": "name"}})])
    prose = _wf([_action("send_notification", {"description": "email the manager"})])
    assert is_executable_workflow(crud)
    assert not is_executable_workflow(prose)
    # pure approval/condition flow with no action nodes counts as executable
    assert is_executable_workflow(_wf([{"id": "ap", "type": "approval"}]))


def test_find_nonexecutable(tmp_path):
    wf = tmp_path / "workflows"; wf.mkdir()
    (wf / "CreateCustomer.json").write_text(json.dumps(
        _wf([_action("db_insert", {"table": "customers", "values": {"name": "name"}})])))
    (wf / "WarrantyClaim.json").write_text(json.dumps(
        _wf([_action("send_notification", {"description": "notify"})])))
    bad = find_nonexecutable(tmp_path)
    assert [n for n, _ in bad] == ["WarrantyClaim.json"]  # only the prose one


@pytest.mark.asyncio
async def test_ensure_regenerates_with_injected_fn(tmp_path):
    wf = tmp_path / "workflows"; wf.mkdir()
    (wf / "WarrantyClaim.json").write_text(json.dumps(
        _wf([_action("send_notification", {"description": "notify the office manager"})])))

    async def fake_regen(workflow, plan, domain_context):
        # produce an executable version
        return _wf([_action("send_email", {"to": "${managerEmail}", "subject": "Claim", "body": "done"})])

    report = await ensure_workflow_executability(tmp_path, {}, {}, regenerate=fake_regen)
    assert report["repaired"] == ["WarrantyClaim.json"]
    rebuilt = json.loads((wf / "WarrantyClaim.json").read_text())
    assert is_executable_workflow(rebuilt)
    assert rebuilt["name"] == "W"  # identity preserved


@pytest.mark.asyncio
async def test_ensure_keeps_original_when_regen_still_bad(tmp_path):
    wf = tmp_path / "workflows"; wf.mkdir()
    orig = _wf([_action("send_notification", {"description": "notify"})])
    (wf / "Bad.json").write_text(json.dumps(orig))

    async def bad_regen(workflow, plan, domain_context):
        return _wf([_action("custom", {"description": "still prose"})])  # not executable

    report = await ensure_workflow_executability(tmp_path, {}, {}, regenerate=bad_regen)
    assert report["still_nonexecutable"] == ["Bad.json"]
    assert json.loads((wf / "Bad.json").read_text()) == orig  # untouched


@pytest.mark.asyncio
async def test_ensure_noop_when_all_executable(tmp_path):
    wf = tmp_path / "workflows"; wf.mkdir()
    (wf / "CreateCustomer.json").write_text(json.dumps(
        _wf([_action("db_insert", {"table": "customers", "values": {"name": "name"}})])))

    async def should_not_run(*a):
        raise AssertionError("regenerate should not be called")

    report = await ensure_workflow_executability(tmp_path, {}, {}, regenerate=should_not_run)
    assert report["repaired"] == [] and report["nonexecutable"] == []


# --- FIX B: db_update requires values + mutation SET clause must be resolvable ---

def test_db_update_requires_values():
    """A where-only db_update is a no-op UPDATE — non-executable."""
    assert not action_node_executable(_action("db_update", {"table": "t", "where": {"id": "{{id}}"}}))
    # with a real literal SET clause it passes
    assert action_node_executable(_action(
        "db_update", {"table": "t", "where": {"id": "{{id}}"}, "values": {"status": "Done"}}))


def test_all_null_set_clause_is_nonexecutable():
    """A db_update whose every value is an unbacked {{var}} resolves to all-NULL
    (the destructive wipe) — flagged non-executable at the workflow level."""
    node = _action("db_update", {
        "table": "rentals", "where": {"id": "{{id}}"},
        "values": {"status": "{{status}}", "pickedUpAt": "{{pickedUpAt}}"},
    })
    assert not is_executable_workflow(_wf([node]))


def test_literal_set_clause_passes():
    node = _action("db_update", {
        "table": "rentals", "where": {"id": "{{id}}"},
        "values": {"status": "Picked Up", "pickedUpAt": "CURRENT_TIMESTAMP"},
    })
    assert is_executable_workflow(_wf([node]))


def test_partial_resolvable_set_clause_passes():
    """As long as ONE value resolves (here `{{id}}`), the SET clause is executable —
    the runtime omits the unresolved column, it doesn't NULL-wipe everything."""
    node = _action("db_update", {
        "table": "rentals", "where": {"id": "{{id}}"},
        "values": {"assignedTo": "{{id}}", "note": "{{note}}"},
    })
    assert is_executable_workflow(_wf([node]))
