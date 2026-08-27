# backend/tests/test_workflow_step_translator.py
from services.workflow_step_translator import is_rich_step_list, _normalize_expression
from services.workflow_step_translator import _translate_config
from services.workflow_step_translator import _translate_node, _humanize_id


def test_is_rich_step_list_detects_planner_shape():
    rich = [{"id": "trigger", "type": "trigger", "next": "a"},
            {"id": "a", "type": "action", "config": {"actionType": "db_insert", "table": "x"}}]
    assert is_rich_step_list(rich) is True


def test_is_rich_step_list_rejects_prose_and_empty():
    assert is_rich_step_list(["Create record", "Send email"]) is False
    assert is_rich_step_list([{"name": "Create record", "node_type": "action"}]) is False
    assert is_rich_step_list([]) is False
    assert is_rich_step_list(None) is False


def test_is_rich_step_list_detects_branches_only():
    assert is_rich_step_list([{"id": "g", "type": "exclusive_gateway",
                               "branches": {"true": "a", "false": "b"}}]) is True


def test_is_rich_step_list_tolerates_stray_non_dict():
    """A stray non-dict element must NOT abort detection — keep scanning and still
    recognize the genuinely-rich dict steps (even when the stray comes FIRST, before
    any rich signal is seen)."""
    assert is_rich_step_list(
        [{"id": "trigger", "type": "trigger", "next": "a"}, "stray-string",
         {"id": "a", "type": "action", "config": {"actionType": "db_insert", "table": "x"}}]
    ) is True
    # stray FIRST — the old early-return would abort here and route to legacy
    assert is_rich_step_list(
        ["stray-string",
         {"id": "a", "type": "action", "config": {"actionType": "db_insert", "table": "x"}}]
    ) is True


def test_is_rich_step_list_prose_dicts_still_false():
    """A pure prose dict list (no config/branches/typed-graph signal) stays legacy."""
    assert is_rich_step_list([{"name": "do a", "node_type": "action"},
                              {"name": "do b", "node_type": "action"}]) is False


def test_translate_workflow_ignores_stray_non_dict_step():
    """A rich workflow carrying one stray non-dict step must translate without
    crashing; the non-dict is simply ignored."""
    wf = {"name": "Stray", "steps": [
        {"id": "trigger", "type": "trigger", "next": "a"},
        "stray-string",
        {"id": "a", "type": "action", "next": "end",
         "config": {"actionType": "db_insert", "table": "records", "fields": ["email"]}},
        {"id": "end", "type": "end"},
    ]}
    out = translate_workflow(wf)
    assert out is not None
    node_ids = {n["id"] for n in out["definition"]["nodes"]}
    assert node_ids == {"trigger", "a", "end"}  # stray dropped, no crash


def test_normalize_expression_feel_lite():
    assert _normalize_expression("recommendation == 'Hire'") == "recommendation = 'Hire'"
    assert _normalize_expression("a === b") == "a = b"
    assert _normalize_expression("a !== b") == "a != b"
    assert _normalize_expression("a && b || c") == "a and b or c"
    assert _normalize_expression("score >= 80") == "score >= 80"  # untouched
    assert _normalize_expression("") == ""


def test_db_insert_fields_become_values():
    cfg = _translate_config({"actionType": "db_insert", "table": "applicants",
                             "fields": ["firstName", "email"]})
    assert cfg["actionType"] == "db_insert"
    assert cfg["table"] == "applicants"
    assert cfg["values"] == {"firstName": "{{firstName}}", "email": "{{email}}"}


def test_db_update_gets_where_id_and_values():
    cfg = _translate_config({"actionType": "db_update", "table": "applications",
                             "fields": ["stage", "status"]})
    assert cfg["table"] == "applications"
    assert cfg["where"] == {"id": "{{id}}"}
    assert cfg["values"] == {"stage": "{{stage}}", "status": "{{status}}"}


def test_db_update_explicit_literal_values_written_verbatim():
    # A2: the author (planner/business-logic) supplies the CONCRETE target state.
    # The translator must write it verbatim — highest priority, NOT self-refs, NOT
    # label-derived — so the button sets the right value by construction.
    cfg = _translate_config(
        {"actionType": "db_update", "table": "equipment",
         "fields": ["availabilityStatus", "restoredAt"],
         "values": {"availabilityStatus": "Available", "restoredAt": "CURRENT_TIMESTAMP"}},
        label="Restore Equipment Availability",
    )
    assert cfg["values"] == {"availabilityStatus": "Available", "restoredAt": "CURRENT_TIMESTAMP"}


def test_db_update_no_explicit_values_still_label_derives():
    # #6 fallback intact: no authored `values`, a status field + a "Set X" label →
    # the status literal is recovered from the label.
    cfg = _translate_config(
        {"actionType": "db_update", "table": "rentals", "fields": ["status"]},
        label="Set Returned",
    )
    assert cfg["values"] == {"status": "Returned"}


def test_db_update_genuine_form_field_left_as_template():
    # A genuine user-supplied input keeps its {{field}} — not invented, not literalized.
    cfg = _translate_config(
        {"actionType": "db_update", "table": "tickets",
         "values": {"reviewerNotes": "{{reviewerNotes}}"}},
        label="Add Reviewer Notes",
    )
    assert cfg["values"] == {"reviewerNotes": "{{reviewerNotes}}"}


def test_db_update_mixed_literal_and_form_field_kept_verbatim():
    # An explicit literal present → the whole map (literal + form field) is verbatim.
    cfg = _translate_config(
        {"actionType": "db_update", "table": "orders",
         "values": {"status": "Approved", "reviewerNotes": "{{reviewerNotes}}"}},
        label="Approve Order",
    )
    assert cfg["values"] == {"status": "Approved", "reviewerNotes": "{{reviewerNotes}}"}


def test_db_update_pure_selfref_values_demoted_to_label_derivation():
    # An authored pure self-ref {{status}} (no literal) must NOT beat label-derivation.
    cfg = _translate_config(
        {"actionType": "db_update", "table": "rentals",
         "fields": ["status"], "values": {"status": "{{status}}"}},
        label="Mark as Cancelled",
    )
    assert cfg["values"] == {"status": "Cancelled"}


def test_db_insert_explicit_literal_values_written_verbatim():
    cfg = _translate_config(
        {"actionType": "db_insert", "table": "audit_log",
         "fields": ["action"], "values": {"action": "created"}},
        label="Log Creation",
    )
    assert cfg["values"] == {"action": "created"}


def test_ai_extract_prompt_and_fields_map():
    cfg = _translate_config({"actionType": "ai_extract",
                             "prompt": "Extract name and email", "fields": ["name", "email"]})
    assert cfg["aiPrompt"] == "Extract name and email"
    assert cfg["aiExtractFields"] == ["name", "email"]
    assert cfg["aiInput"] == "{{input}}"  # exec-contract group 2 satisfied


def test_ai_decide_prompt_maps_to_aiprompt():
    cfg = _translate_config({"actionType": "ai_decide", "prompt": "Score 0-100"})
    assert cfg["aiPrompt"] == "Score 0-100"


def test_send_notification_template_becomes_message_with_recipient():
    # planner gives no recipient — translator must still make it executable
    cfg = _translate_config({"actionType": "send_notification",
                             "template": "Applicant {{firstName}} scored {{aiScore}}"})
    assert cfg["actionType"] == "send_notification"
    assert cfg["message"] == "Applicant {{firstName}} scored {{aiScore}}"
    assert cfg["channel"] == "in_app"        # satisfies executability contract
    assert cfg["toRole"] == "admin"


def test_send_email_gets_recipient_role_and_body():
    cfg = _translate_config({"actionType": "send_email", "template": "Hello {{name}}"})
    assert cfg["body"] == "Hello {{name}}"
    assert cfg["recipientRole"] == "admin"


def test_generate_document_keeps_template_id():
    cfg = _translate_config({"actionType": "generate_document",
                             "template": "assessment_summary_report", "fields": ["a", "b"]})
    assert cfg["template"] == "assessment_summary_report"
    assert cfg["actionType"] == "generate_document"


def test_unknown_actiontype_passthrough_stays_present():
    # transform carries an expression → executable, must not be dropped
    cfg = _translate_config({"actionType": "transform", "expression": "a + b"})
    assert cfg["actionType"] == "transform"
    assert cfg["expression"] == "a + b"


def test_translate_action_node():
    n = _translate_node({"id": "extract_cv", "type": "action",
                         "config": {"actionType": "ai_extract", "prompt": "Extract"}}, idx=1)
    assert n["type"] == "action"
    assert n["data"]["nodeType"] == "action"
    assert n["data"]["config"]["actionType"] == "ai_extract"
    assert n["data"]["config"]["aiPrompt"] == "Extract"
    assert n["data"]["label"] == "Extract Cv"
    assert n["id"] == "extract_cv"


def test_top_level_ai_generate_resolves_to_ai_node_type():
    # A1: a planner step typed `ai_generate` must translate to a TOP-LEVEL node
    # (type == "ai_generate"), NOT type=="action"+actionType=="ai_generate".
    n = _translate_node({"id": "gen_summary", "type": "ai_generate",
                         "config": {"prompt": "x"}}, idx=1)
    assert n["type"] == "ai_generate"
    assert n["data"]["nodeType"] == "ai_generate"
    cfg = n["data"]["config"]
    # the AI config must STILL be built for the top-level node path
    assert cfg.get("aiPrompt") == "x"
    assert cfg.get("aiInput") == "{{input}}"


def test_top_level_ai_classify_extract_decide_resolve_to_ai_node_types():
    # ai_classify / ai_extract / ai_decide must also resolve top-level.
    n_cls = _translate_node({"id": "c", "type": "ai_classify",
                             "config": {"prompt": "cls"}}, idx=1)
    assert n_cls["type"] == "ai_classify"
    assert n_cls["data"]["config"].get("aiPrompt") == "cls"

    n_ext = _translate_node({"id": "e", "type": "ai_extract",
                             "config": {"prompt": "ext", "fields": ["a"]}}, idx=2)
    assert n_ext["type"] == "ai_extract"
    assert n_ext["data"]["config"].get("aiPrompt") == "ext"
    assert n_ext["data"]["config"].get("aiExtractFields") == ["a"]

    n_dec = _translate_node({"id": "d", "type": "ai_decide",
                             "config": {"prompt": "dec"}}, idx=3)
    assert n_dec["type"] == "ai_decide"
    assert n_dec["data"]["config"].get("aiPrompt") == "dec"


def test_bare_db_update_step_still_resolves_to_action():
    # A1 regression: a non-AI action typed bare (`type:"db_update"`) is UNCHANGED —
    # still a top-level `action` node with actionType db_update.
    n = _translate_node({"id": "advance", "type": "db_update",
                         "config": {"table": "apps", "fields": ["stage"]}}, idx=1)
    assert n["type"] == "action"
    assert n["data"]["nodeType"] == "action"
    assert n["data"]["config"]["actionType"] == "db_update"


def test_legacy_action_ai_generate_still_builds_ai_config():
    # A1 back-compat: the OLD shape (type:"action" + config.actionType:"ai_generate")
    # must still yield a working AI node with prompt config.
    n = _translate_node({"id": "gen", "type": "action",
                         "config": {"actionType": "ai_generate", "prompt": "y"}}, idx=1)
    assert n["type"] == "action"
    assert n["data"]["config"]["actionType"] == "ai_generate"
    assert n["data"]["config"].get("aiPrompt") == "y"
    assert n["data"]["config"].get("aiInput") == "{{input}}"


def test_translate_gateway_node_uses_expression():
    n = _translate_node({"id": "check_recommendation", "type": "exclusive_gateway",
                         "config": {"condition": "recommendation == 'Hire'"}}, idx=2)
    assert n["type"] == "exclusive_gateway"
    assert n["data"]["config"]["expression"] == "recommendation = 'Hire'"


def test_translate_end_node():
    n = _translate_node({"id": "end", "type": "end"}, idx=9)
    assert n["type"] == "end"
    assert n["data"]["label"] == "Complete"


def test_humanize_id():
    assert _humanize_id("extract_cv") == "Extract Cv"
    assert _humanize_id("notify_recruiter_hire") == "Notify Recruiter Hire"


from services.workflow_step_translator import _translate_edges


def test_linear_next_edges():
    steps = [{"id": "trigger", "type": "trigger", "next": "a"},
             {"id": "a", "type": "action", "next": "end"},
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    pairs = {(e["source"], e["target"]) for e in edges}
    assert ("trigger", "a") in pairs and ("a", "end") in pairs
    assert all(e["data"]["edgeType"] == "default" for e in edges)


def test_gateway_branches_become_then_else():
    steps = [{"id": "g", "type": "exclusive_gateway",
              "branches": {"true": "hire", "false": "review"}},
             {"id": "hire", "type": "action", "next": "end"},
             {"id": "review", "type": "action", "next": "end"},
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    then = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "then"]
    els = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "else"]
    assert then and then[0]["target"] == "hire"
    assert els and els[0]["target"] == "review"
    assert els[0]["sourceHandle"] == "else"


def test_terminal_step_without_next_connects_to_end():
    steps = [{"id": "trigger", "type": "trigger", "next": "a"},
             {"id": "a", "type": "action"},              # no next, no branches
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    assert ("a", "end") in {(e["source"], e["target"]) for e in edges}


def test_gateway_missing_branch_target_routes_to_end():
    steps = [{"id": "g", "type": "exclusive_gateway",
              "branches": {"true": "hire", "false": "missing_id"}},
             {"id": "hire", "type": "action", "next": "end"},
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    then = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "then"]
    els = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "else"]
    assert then and then[0]["target"] == "hire"
    # missing_id doesn't exist -> else edge falls back to the end node
    assert els and els[0]["target"] == "end"
    assert els[0]["sourceHandle"] == "else"


import json
import os
from services.workflow_step_translator import translate_workflow, is_rich_step_list
from services.workflow_executability import is_executable_workflow

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ewn5ue3r_plan_workflows.json")


def _load(name):
    return json.load(open(_FIX))[name]


def test_translate_returns_none_for_prose():
    assert translate_workflow({"name": "X", "steps": ["do a", "do b"]}) is None


def test_cv_parsing_is_executable_with_ai_nodes():
    wf = translate_workflow(_load("CVParsingWorkflow"))
    assert wf is not None
    assert is_executable_workflow(wf)
    nodes = wf["definition"]["nodes"]
    ats = [((n.get("data") or {}).get("config") or {}).get("actionType")
           for n in nodes if n["type"] == "action"]
    assert "ai_extract" in ats and "ai_decide" in ats and "db_insert" in ats
    # the ai_extract prompt survived
    ext = next(n for n in nodes if ((n["data"]["config"]).get("actionType")) == "ai_extract")
    assert ext["data"]["config"]["aiPrompt"].startswith("Extract applicant")


def test_feedback_has_gateway_with_then_else():
    wf = translate_workflow(_load("FeedbackSubmissionWorkflow"))
    assert wf is not None
    assert is_executable_workflow(wf)
    nodes, edges = wf["definition"]["nodes"], wf["definition"]["edges"]
    gw = next(n for n in nodes if n["type"] == "exclusive_gateway")
    assert gw["data"]["config"]["expression"] == "recommendation = 'Hire'"
    outs = {e["data"]["edgeType"] for e in edges if e["source"] == gw["id"]}
    assert "then" in outs and "else" in outs


def test_translated_id_name_preserved():
    wf = translate_workflow(_load("CVParsingWorkflow"))
    assert wf["name"] == "CVParsingWorkflow"
    assert wf["id"]  # non-empty slug
    assert wf["definition"]["trigger"]["type"]  # a runtime trigger type


def test_translated_definition_preserves_raw_steps():
    """The translated definition must carry the raw planner steps (for the editor/
    preview), matching what _sync_workflows_from_plan writes."""
    src = _load("CVParsingWorkflow")
    wf = translate_workflow(src)
    assert wf["definition"]["steps"] == src["steps"]


# ---------------------------------------------------------------------------
# Array-order (no next/branches) fallback: sequential chaining + heuristic branch
# ---------------------------------------------------------------------------
from services.workflow_step_translator import (
    _has_connectivity, _translate_edges_sequential,
)

_FIX_SEQ = os.path.join(os.path.dirname(__file__), "fixtures", "ioup5l3v_plan_workflows.json")


def _load_seq(name):
    return json.load(open(_FIX_SEQ))[name]


def test_has_connectivity():
    # a step with an explicit `next` → connectivity present
    assert _has_connectivity([{"id": "a", "type": "action", "next": "b"}]) is True
    # a step with a dict `branches` → connectivity present
    assert _has_connectivity(
        [{"id": "g", "type": "exclusive_gateway", "branches": {"true": "a", "false": "b"}}]
    ) is True
    # pure array-order steps → NO connectivity
    assert _has_connectivity(
        [{"id": "a", "type": "action", "config": {"actionType": "db_insert"}}]
    ) is False


def test_sequential_chains_in_order():
    steps = [
        {"id": "trigger", "type": "trigger"},
        {"id": "s0", "type": "action", "config": {"actionType": "db_insert"}},
        {"id": "s1", "type": "action", "config": {"actionType": "db_update"}},
        {"id": "s2", "type": "action", "config": {"actionType": "send_email"}},
        {"id": "end", "type": "end"},
    ]
    edges = _translate_edges_sequential(steps)
    pairs = {(e["source"], e["target"]) for e in edges}
    assert ("trigger", "s0") in pairs
    assert ("s0", "s1") in pairs
    assert ("s1", "s2") in pairs
    assert ("s2", "end") in pairs
    assert all(e["data"]["edgeType"] == "default" for e in edges)
    # NOT the broken all→end fan-out
    assert not all(e["target"] == "end" for e in edges)


def test_sequential_gateway_gets_then_else():
    steps = [
        {"id": "trigger", "type": "trigger"},
        {"id": "g", "type": "exclusive_gateway", "config": {"condition": "x == 1"}},
        {"id": "a", "type": "action", "config": {"actionType": "db_update"}},
        {"id": "b", "type": "action", "config": {"actionType": "send_email"}},
        {"id": "end", "type": "end"},
    ]
    edges = _translate_edges_sequential(steps)
    then = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "then"]
    els = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "else"]
    assert then and then[0]["target"] == "a"          # then → step after gateway
    assert els and els[0]["target"] == "end"           # else → end (heuristic)
    assert els[0]["sourceHandle"] == "else"


def test_ioup5l3v_shortlist_is_connected_and_branches():
    wf = translate_workflow(_load_seq("ApplicantShortlistWorkflow"))
    assert wf is not None
    nodes, edges = wf["definition"]["nodes"], wf["definition"]["edges"]
    node_ids = {n["id"] for n in nodes}
    end_ids = {n["id"] for n in nodes if n["type"] in ("end", "end_event")}
    # (a) NOT all edges point to end
    assert not all(e["target"] in end_ids for e in edges)
    # (b) at least one then and one else edge
    etypes = {e["data"]["edgeType"] for e in edges}
    assert "then" in etypes and "else" in etypes
    # (c) connected: every non-end node has >=1 outgoing edge; no edge targets a missing node
    sources = {e["source"] for e in edges}
    for n in nodes:
        if n["id"] not in end_ids:
            assert n["id"] in sources, f"{n['id']} has no outgoing edge"
    for e in edges:
        assert e["target"] in node_ids, f"edge targets missing node {e['target']}"
    # trigger reaches end (graph is walkable)
    trig = next(n for n in nodes if n["type"] == "trigger")
    seen, frontier = set(), [trig["id"]]
    adj = {}
    for e in edges:
        adj.setdefault(e["source"], []).append(e["target"])
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        frontier.extend(adj.get(cur, []))
    assert end_ids & seen, "end not reachable from trigger"


# ---------------------------------------------------------------------------
# Executability backfill: an action node the planner under-specified must still
# pass action_node_executable (deterministic, faithful, idempotent).
# ---------------------------------------------------------------------------
from services.workflow_executability import action_node_executable


def _rich_wf(action_step):
    """Wrap a single action step in a minimal rich (explicit-connectivity) workflow."""
    return {"name": "Backfill", "steps": [
        {"id": "trigger", "type": "trigger", "next": action_step["id"]},
        {**action_step, "next": "end"},
        {"id": "end", "type": "end"},
    ]}


def _action_node(wf_out, node_id):
    return next(n for n in wf_out["definition"]["nodes"] if n["id"] == node_id)


def test_set_variable_without_name_is_executable():
    wf = translate_workflow(_rich_wf(
        {"id": "mark_reviewed", "type": "action", "config": {"actionType": "set_variable"}}))
    node = _action_node(wf, "mark_reviewed")
    assert action_node_executable(node)
    cfg = node["data"]["config"]
    assert cfg["variableName"] == "mark_reviewed"   # derived from the step id
    assert is_executable_workflow(wf)


def test_bare_custom_becomes_executable_marker():
    wf = translate_workflow(_rich_wf(
        {"id": "compute_score", "type": "action", "config": {"actionType": "custom"}}))
    node = _action_node(wf, "compute_score")
    cfg = node["data"]["config"]
    # dead custom → executable set_variable progress marker.
    # Value key: `variableValue` (canonical). The old `value` key was a
    # naming-drift bug — the runtime reads `variableValue`/`expression`
    # only, so a marker written with `value` sets the variable to
    # undefined. See workflow-audit P1-10.
    assert cfg["actionType"] == "set_variable"
    assert cfg["variableName"] == "compute_score_done"
    assert cfg["variableValue"] is True
    assert "value" not in cfg  # legacy key must not leak
    assert action_node_executable(node)
    assert is_executable_workflow(wf)


def test_bare_transform_becomes_executable_marker():
    wf = translate_workflow(_rich_wf(
        {"id": "map_fields", "type": "action", "config": {"actionType": "transform"}}))
    cfg = _action_node(wf, "map_fields")["data"]["config"]
    assert cfg["actionType"] == "set_variable"
    assert cfg["variableName"] == "map_fields_done"
    assert is_executable_workflow(wf)


def test_ai_decide_without_prompt_is_executable():
    wf = translate_workflow(_rich_wf(
        {"id": "decide_hire", "type": "action", "config": {"actionType": "ai_decide"}}))
    node = _action_node(wf, "decide_hire")
    cfg = node["data"]["config"]
    assert cfg["aiPrompt"] == "Decide the outcome for: Decide Hire."
    assert action_node_executable(node)
    assert is_executable_workflow(wf)


def test_present_keys_not_overwritten():
    # set_variable WITH a planner-provided variableName — keep it
    wf1 = translate_workflow(_rich_wf(
        {"id": "s", "type": "action",
         "config": {"actionType": "set_variable", "variableName": "myVar", "value": 7}}))
    cfg1 = _action_node(wf1, "s")["data"]["config"]
    assert cfg1["variableName"] == "myVar"
    assert cfg1["value"] == 7
    # ai_decide WITH a planner-provided prompt — keep it, no aiPrompt injection
    wf2 = translate_workflow(_rich_wf(
        {"id": "d", "type": "action", "config": {"actionType": "ai_decide", "prompt": "X"}}))
    cfg2 = _action_node(wf2, "d")["data"]["config"]
    assert cfg2["prompt"] == "X"
    assert cfg2.get("aiPrompt") != "Decide the outcome for: D."
    # custom WITH an expression — stays custom, not converted
    wf3 = translate_workflow(_rich_wf(
        {"id": "c", "type": "action",
         "config": {"actionType": "custom", "expression": "a + b"}}))
    cfg3 = _action_node(wf3, "c")["data"]["config"]
    assert cfg3["actionType"] == "custom"
    assert cfg3["expression"] == "a + b"


def test_all_ewn5ue3r_workflows_still_executable():
    """Regression: every workflow in the ewn5ue3r fixture still translates and stays
    executable after the backfill (backfill must not break already-valid nodes)."""
    data = json.load(open(_FIX))
    for name in data:
        wf = translate_workflow(data[name])
        assert wf is not None, name
        assert is_executable_workflow(wf), name


def test_ewn5ue3r_explicit_connectivity_unchanged():
    """Regression: the explicit-connectivity fixture must still use the faithful
    path — its gateway keeps then/else built from `branches`, not the fallback."""
    wf = translate_workflow(_load("FeedbackSubmissionWorkflow"))
    assert wf is not None
    nodes, edges = wf["definition"]["nodes"], wf["definition"]["edges"]
    gw = next(n for n in nodes if n["type"] == "exclusive_gateway")
    then = [e for e in edges if e["source"] == gw["id"] and e["data"]["edgeType"] == "then"]
    els = [e for e in edges if e["source"] == gw["id"] and e["data"]["edgeType"] == "else"]
    # faithful branch targets from the planner's `branches`
    assert then and then[0]["target"] == "generate_offer_summary"
    assert els and els[0]["target"] == "notify_recruiter_review"


# ── workflow-audit slice 3 regressions ─────────────────────────────────

def test_decision_node_preserves_decisionTable_config():
    """Decision-table nodes used to be reduced to {nodeType,expression}
    by the gateway path — dropping the decisionTable config so the
    runtime treated every decision node as {skipped:true,reason:'no
    decision table'}. See workflow-audit P1-10."""
    from services.workflow_step_translator import translate_workflow

    table = {
        "inputs": [{"name": "amount", "type": "number"}],
        "outputs": [{"name": "tier", "type": "string"}],
        "rules": [
            {"when": {"amount": ">= 100"}, "then": {"tier": "gold"}},
            {"when": {"amount": "< 100"}, "then": {"tier": "silver"}},
        ],
        "hitPolicy": "first",
    }
    wf = translate_workflow({
        "id": "score",
        "name": "score",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "d"},
            {"id": "d", "type": "decision", "config": {
                "decisionTable": table,
                "outputMapping": {"tier": "$.tier"},
            }, "next": "end"},
            {"id": "end", "type": "end"},
        ],
    })
    dec = next(n for n in wf["definition"]["nodes"] if n["id"] == "d")
    assert dec["data"]["config"]["decisionTable"] == table
    assert dec["data"]["config"]["outputMapping"] == {"tier": "$.tier"}


def test_escalation_node_preserves_sla_config():
    """`escalation` used to be aliased to `action` in _NODE_ALIASES,
    which stripped every field the engine's escalation case reads
    (slaHours, escalateTo). See workflow-audit P1-10."""
    from services.workflow_step_translator import translate_workflow

    wf = translate_workflow({
        "id": "sla",
        "name": "sla",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "esc"},
            {"id": "esc", "type": "escalation", "config": {
                "slaHours": 24,
                "escalateTo": "manager",
                "reminderIntervalHours": 4,
            }, "next": "end"},
            {"id": "end", "type": "end"},
        ],
    })
    esc = next(n for n in wf["definition"]["nodes"] if n["id"] == "esc")
    cfg = esc["data"]["config"]
    assert cfg["nodeType"] == "escalation"
    assert cfg["slaHours"] == 24
    assert cfg["escalateTo"] == "manager"
    assert cfg["reminderIntervalHours"] == 4
