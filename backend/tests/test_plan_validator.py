"""Deterministic plan-validator rules. Same false-negative bias as
patch_coherence: a rule reports violations when the plan clearly
breaks its contract; ambiguous shapes pass through so we don't
reject legitimate plans."""
from __future__ import annotations

import pytest

from services.plan_validator import (
    format_violations_for_retry,
    validate_plan,
)


# =========================================================================
# Baseline — a clean, minimal plan that should validate with 0 issues
# =========================================================================

def _minimal_clean_plan() -> dict:
    return {
        "moduleName": "Todos",
        "dataModels": [
            {"name": "User", "table": "users", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "varchar(320)"},
            ]},
            {"name": "Todo", "table": "todos", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "title", "type": "varchar(255)"},
                {"name": "status", "type": "varchar(50)"},
                {"name": "assigneeId", "type": "uuid"},
                {"name": "createdAt", "type": "timestamp"},
            ]},
        ],
        "relations": [
            {"from": "Todo", "to": "User", "type": "many-to-one",
             "foreignKey": "assigneeId"},
        ],
        "pages": [
            {"route": "/todos", "name": "TodoListPage",
             "entity": "Todo", "archetype": "list"},
            {"route": "/todos/new", "name": "TodoCreatePage",
             "entity": "Todo", "archetype": "form"},
            {"route": "/", "name": "HomePage",
             "entity": None, "archetype": "dashboard"},
        ],
        "workflows": [{
            "name": "MarkTodoDone",
            "steps": [
                {"id": "trigger", "type": "trigger", "next": "update"},
                {"id": "update", "type": "action", "next": "end"},
                {"id": "end", "type": "end"},
            ],
        }],
    }


def test_clean_plan_passes():
    """A clean minimal plan has no ERRORS. It can still produce
    completeness warnings — those are advisory, telling the planner which
    fields to enrich next, not a signal to reject the plan."""
    violations = validate_plan(_minimal_clean_plan())
    errors = [v for v in violations if v.get("severity") == "error"]
    assert errors == [], f"expected no errors, got: {errors}"


def test_non_dict_input_returns_shape_error():
    v = validate_plan("not a plan")
    assert v and v[0]["rule"] == "shape"


def test_format_violations_returns_empty_string_when_no_violations():
    assert format_violations_for_retry([]) == ""


# =========================================================================
# Rule 1 — duplicate field names
# =========================================================================

def test_duplicate_field_is_flagged():
    plan = _minimal_clean_plan()
    plan["dataModels"][1]["fields"].append({"name": "title", "type": "text"})
    v = validate_plan(plan)
    assert any(x["rule"] == "duplicate_field" and "title" in x["message"] for x in v)


# =========================================================================
# Rule 2 — relation endpoints exist
# =========================================================================

def test_relation_from_missing_entity_is_flagged():
    plan = _minimal_clean_plan()
    plan["relations"].append({"from": "Ghost", "to": "User", "foreignKey": "userId"})
    v = validate_plan(plan)
    assert any(x["rule"] == "relation_endpoint_missing" and "Ghost" in x["message"] for x in v)


def test_relation_to_missing_entity_is_flagged():
    plan = _minimal_clean_plan()
    plan["relations"].append({"from": "Todo", "to": "Nowhere", "foreignKey": "assigneeId"})
    v = validate_plan(plan)
    assert any(x["rule"] == "relation_endpoint_missing" and "Nowhere" in x["message"] for x in v)


# =========================================================================
# Rule 3 — relation FK field exists on source
# =========================================================================

def test_relation_fk_not_on_source_is_flagged():
    plan = _minimal_clean_plan()
    plan["relations"].append({
        "from": "Todo", "to": "User", "foreignKey": "notARealField",
    })
    v = validate_plan(plan)
    assert any(x["rule"] == "relation_fk_not_on_source" for x in v)


def test_relation_missing_fk_is_flagged():
    plan = _minimal_clean_plan()
    plan["relations"].append({"from": "Todo", "to": "User"})
    v = validate_plan(plan)
    assert any(x["rule"] == "relation_fk_missing" for x in v)


# =========================================================================
# Rule 4 — actor FK must relate to User
# =========================================================================

def test_actor_fk_without_relation_is_flagged():
    """The classic bug: entity has `reviewerId` but no relation → User."""
    plan = _minimal_clean_plan()
    plan["dataModels"][1]["fields"].append({"name": "reviewerId", "type": "uuid"})
    v = validate_plan(plan)
    assert any(x["rule"] == "actor_fk_without_relation" and "reviewerId" in x["message"] for x in v)


def test_actor_fk_wrong_target_is_flagged():
    plan = _minimal_clean_plan()
    plan["dataModels"][1]["fields"].append({"name": "reviewerId", "type": "uuid"})
    plan["relations"].append({
        "from": "Todo", "to": "Todo",  # wrong target!
        "foreignKey": "reviewerId",
    })
    v = validate_plan(plan)
    assert any(x["rule"] == "actor_fk_wrong_target" for x in v)


def test_actor_fk_with_correct_relation_passes():
    plan = _minimal_clean_plan()
    plan["dataModels"][1]["fields"].append({"name": "reviewerId", "type": "uuid"})
    plan["relations"].append({
        "from": "Todo", "to": "User",
        "foreignKey": "reviewerId",
    })
    v = validate_plan(plan)
    assert all(x["rule"] not in ("actor_fk_without_relation", "actor_fk_wrong_target") for x in v)


def test_actor_fk_check_skipped_when_no_user_entity():
    """Plans that genuinely don't need a User (public utility apps)
    shouldn't be flagged for missing User relations."""
    plan = _minimal_clean_plan()
    plan["dataModels"] = [e for e in plan["dataModels"] if e["name"] != "User"]
    plan["relations"] = []
    plan["dataModels"][0]["fields"].append({"name": "assigneeId", "type": "uuid"})
    v = validate_plan(plan)
    assert all(x["rule"] != "actor_fk_without_relation" for x in v)


# =========================================================================
# Rule 5 — pages reference real entities
# =========================================================================

def test_page_entity_missing_is_flagged():
    plan = _minimal_clean_plan()
    plan["pages"].append({
        "route": "/orphans", "name": "OrphansListPage",
        "entity": "Orphan", "archetype": "list",
    })
    v = validate_plan(plan)
    assert any(x["rule"] == "page_entity_missing" and "Orphan" in x["message"] for x in v)


def test_entity_free_page_passes():
    """Dashboards / chat pages with entity=null are legitimate."""
    plan = _minimal_clean_plan()
    plan["pages"].append({
        "route": "/analytics", "name": "AnalyticsPage",
        "entity": None, "archetype": "dashboard",
    })
    v = validate_plan(plan)
    assert all(x["rule"] != "page_entity_missing" for x in v)


# =========================================================================
# Rule 6 — archetype in the closed set
# =========================================================================

def test_unsupported_archetype_is_flagged():
    """The drift I found in the current planner — 'report' and 'inbox'
    are emitted but the builder handles neither."""
    plan = _minimal_clean_plan()
    plan["pages"].append({
        "route": "/reports", "name": "ReportsPage",
        "entity": "Todo", "archetype": "report",
    })
    v = validate_plan(plan)
    assert any(x["rule"] == "unsupported_archetype" and "report" in x["message"] for x in v)


def test_all_supported_archetypes_pass():
    plan = _minimal_clean_plan()
    for i, arch in enumerate(("list", "form", "create", "edit", "detail",
                              "kanban", "calendar", "dashboard")):
        plan["pages"].append({
            "route": f"/t{i}", "name": f"P{i}",
            "entity": "Todo" if arch != "dashboard" else None,
            "archetype": arch,
        })
    v = validate_plan(plan)
    assert all(x["rule"] != "unsupported_archetype" for x in v)


def test_missing_archetype_is_not_flagged():
    """Some plan shapes leave archetype implicit (router derives it
    from the route shape). Don't false-flag those."""
    plan = _minimal_clean_plan()
    plan["pages"].append({
        "route": "/notes", "name": "NotesPage", "entity": "Todo",
        # no archetype key at all
    })
    v = validate_plan(plan)
    assert all(x["rule"] != "unsupported_archetype" for x in v)


# =========================================================================
# Rule 7 — workflow connectivity
# =========================================================================

def test_gateway_using_next_instead_of_branches_is_flagged():
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "BadGateway",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "gate"},
            {"id": "gate", "type": "exclusive_gateway", "next": "end"},  # WRONG
            {"id": "end", "type": "end"},
        ],
    }]
    v = validate_plan(plan)
    assert any(x["rule"] == "gateway_uses_next" for x in v)


def test_dangling_workflow_target_is_flagged():
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "Dangler",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "phantom"},
            {"id": "end", "type": "end"},
        ],
    }]
    v = validate_plan(plan)
    assert any(x["rule"] == "workflow_dangling_target" and "phantom" in x["message"] for x in v)


def test_multiple_triggers_is_flagged():
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "TwoStarts",
        "steps": [
            {"id": "t1", "type": "trigger", "next": "end"},
            {"id": "t2", "type": "trigger", "next": "end"},
            {"id": "end", "type": "end"},
        ],
    }]
    v = validate_plan(plan)
    assert any(x["rule"] == "workflow_trigger_count" for x in v)


def test_missing_end_node_is_flagged():
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "Endless",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "act"},
            {"id": "act", "type": "action", "next": "act"},  # loops
        ],
    }]
    v = validate_plan(plan)
    assert any(x["rule"] == "workflow_end_count" for x in v)


def test_gateway_without_branches_is_flagged():
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "GatewayNoBranches",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "gate"},
            {"id": "gate", "type": "exclusive_gateway"},
            {"id": "end", "type": "end"},
        ],
    }]
    v = validate_plan(plan)
    assert any(x["rule"] == "gateway_no_branches" for x in v)


# =========================================================================
# Rule 8 — page actions reference declared workflows
# =========================================================================

def test_action_referencing_unknown_workflow_is_flagged():
    plan = _minimal_clean_plan()
    plan["pages"][0]["actions"] = [
        {"label": "Publish", "workflow": "PublishNotDeclared"},
    ]
    v = validate_plan(plan)
    assert any(x["rule"] == "action_workflow_missing" and "PublishNotDeclared" in x["message"] for x in v)


def test_action_referencing_declared_workflow_passes():
    plan = _minimal_clean_plan()
    plan["pages"][0]["actions"] = [
        {"label": "Mark Done", "workflow": "MarkTodoDone"},
    ]
    v = validate_plan(plan)
    assert all(x["rule"] != "action_workflow_missing" for x in v)


def test_action_check_skipped_when_no_workflows_declared():
    """A plan with zero workflows shouldn't flag every action —
    it's a signal the plan is nav-only, not that references are broken."""
    plan = _minimal_clean_plan()
    plan["workflows"] = []
    plan["pages"][0]["actions"] = [{"label": "Any", "workflow": "Anything"}]
    v = validate_plan(plan)
    assert all(x["rule"] != "action_workflow_missing" for x in v)


# =========================================================================
# Alternate plan shape — the oneshot planner emits entities as a dict
# =========================================================================

def test_oneshot_dict_entities_shape_is_accepted():
    """`_ONESHOT_SYSTEM_PROMPT` emits entities as {Name: {…}} instead of
    a list — the validator normalizes both without false-flagging."""
    plan = {
        "entities": {
            "User": {"table": "users", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
            ]},
            "Note": {"table": "notes", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "authorId", "type": "uuid"},
            ]},
        },
        "relations": [
            {"from": "Note", "to": "User", "foreignKey": "authorId"},
        ],
        "pages": [{"route": "/notes", "entity": "Note", "archetype": "list"}],
    }
    v = validate_plan(plan)
    # The classic actor-FK ('authorId') has a proper relation, so no
    # errors for it. Completeness warnings (missing not_null / fk on
    # authorId) are advisory and don't reject the plan.
    errors = [x for x in v if x.get("severity") == "error"]
    assert errors == [], f"expected no errors, got: {errors}"


# =========================================================================
# Retry-prompt renderer
# =========================================================================

# =========================================================================
# Rule 9 — workflow input coverage (added to catch the July-17 crash)
# =========================================================================

def _wf_input_uncovered_plan() -> dict:
    """A workflow that references `{{input.id}}` but the trigger declares
    no `id` input. This is the exact class of the runtime crash we saw."""
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "UpdateAppointment",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "upd",
             "config": {"inputs": []}},  # ← empty inputs
            {"id": "upd", "type": "db_update", "next": "end",
             "config": {
                 "table": "appointments",
                 "where": {"id": "{{input.id}}"},  # ← id not declared
                 "values": {"status": "{{input.status}}"},
             }},
            {"id": "end", "type": "end"},
        ],
    }]
    plan["pages"][0]["actions"] = [{
        "label": "Update", "workflow": "UpdateAppointment",
    }]
    return plan


def test_uncovered_workflow_input_binding_is_flagged():
    v = validate_plan(_wf_input_uncovered_plan())
    rules = [x["rule"] for x in v]
    assert "workflow_input_uncovered" in rules
    # both `input.id` and `input.status` fire
    msgs = " ".join(x["message"] for x in v if x["rule"] == "workflow_input_uncovered")
    assert "'id'" in msgs and "'status'" in msgs


def test_covered_by_trigger_inputs_passes():
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"][0]["config"]["inputs"] = [
        {"name": "id"}, {"name": "status"},
    ]
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_covered_by_form_fields_passes():
    """Trigger declaring inputs under config.form.fields also counts."""
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"][0]["config"] = {
        "form": {"fields": [{"name": "id"}, {"name": "status"}]},
    }
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_covered_by_page_action_input_map_passes():
    """A page.action.input_map that supplies `id` counts, even when the
    trigger doesn't declare it — the dispatcher passes it through."""
    plan = _wf_input_uncovered_plan()
    plan["pages"][0]["actions"] = [{
        "label": "Update", "workflow": "UpdateAppointment",
        "input_map": {"id": "{{item.id}}", "status": "'closed'"},
    }]
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_system_prefix_bindings_pass():
    """`{{page.id}}`, `{{context.userId}}`, `{{now}}`, `{{uuid()}}` are
    supplied by the dispatcher — never a plan-level gap."""
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"][1]["config"] = {
        "table": "appointments",
        "where": {"id": "{{page.id}}"},
        "values": {
            "closedAt": "{{now}}",
            "userId": "{{context.userId}}",
            "session": "{{uuid()}}",
        },
    }
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_step_ref_to_earlier_step_passes():
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"] = [
        {"id": "trigger", "type": "trigger", "next": "load",
         "config": {"inputs": [{"name": "code"}]}},
        {"id": "load", "type": "db_query", "next": "upd",
         "config": {"table": "appointments",
                    "where": {"code": "{{input.code}}"}}},
        {"id": "upd", "type": "db_update", "next": "end",
         "config": {"table": "appointments",
                    "where": {"id": "{{steps.load.id}}"},
                    "values": {"status": "'done'"}}},
        {"id": "end", "type": "end"},
    ]
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)
    assert not any(x["rule"] == "workflow_step_ref_not_reachable" for x in v)


def test_step_ref_to_later_step_is_flagged():
    """A step referencing `steps.LATER.field` breaks — the value isn't
    computed yet when this step runs."""
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"] = [
        {"id": "trigger", "type": "trigger", "next": "upd",
         "config": {"inputs": []}},
        # upd references `later`, which appears AFTER it — unreachable.
        {"id": "upd", "type": "db_update", "next": "later",
         "config": {"table": "appointments",
                    "where": {"id": "{{steps.later.rowId}}"},
                    "values": {"status": "'x'"}}},
        {"id": "later", "type": "db_query", "next": "end",
         "config": {"table": "appointments"}},
        {"id": "end", "type": "end"},
    ]
    v = validate_plan(plan)
    assert any(x["rule"] == "workflow_step_ref_not_reachable" for x in v)


def test_bare_binding_treated_as_input_ref():
    """`{{id}}` (no scope prefix) is caught the same way as `{{input.id}}`
    — the runtime resolver falls back to the variables map either way."""
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"][1]["config"]["where"] = {"id": "{{id}}"}
    v = validate_plan(plan)
    assert any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_literal_string_values_do_not_trigger():
    """A step's config with no `{{ … }}` bindings at all is fine — the
    literal `"'done'"` value is a FEEL literal, not a binding."""
    plan = _wf_input_uncovered_plan()
    plan["workflows"][0]["steps"][1]["config"] = {
        "table": "appointments",
        "where": {"status": "'active'"},
        "values": {"status": "'done'"},
    }
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_retry_prompt_lists_violations_numbered():
    plan = _minimal_clean_plan()
    plan["dataModels"][1]["fields"].append({"name": "reviewerId", "type": "uuid"})
    plan["pages"].append({"route": "/reports", "entity": "Todo", "archetype": "report"})
    text = format_violations_for_retry(validate_plan(plan))
    assert "1." in text and "2." in text
    assert "reviewerId" in text
    assert "report" in text
    assert "corrected plan" in text.lower()


# =========================================================================
# Completeness contract — the plan must be authoritative for downstream
# =========================================================================


def test_completeness_flags_missing_enum_values():
    """A `status`-shaped field with no `enum_values` triggers a warning."""
    plan = {
        "entities": {"Application": {"table": "applications", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True, "not_null": True},
            {"name": "status", "type": "varchar", "not_null": True},
        ]}},
    }
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "field_enum_missing"]
    assert len(hits) == 1
    assert "status" in hits[0]["message"]


def test_completeness_flags_uuid_without_fk():
    """A uuid field that isn't a PK must declare its FK target."""
    plan = {
        "entities": {"Application": {"table": "applications", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True, "not_null": True},
            {"name": "candidateId", "type": "uuid", "not_null": True},
        ]}},
    }
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "field_fk_missing"]
    assert len(hits) == 1
    assert "candidateId" in hits[0]["message"]


def test_completeness_workflow_needs_inputs():
    """A user-triggered workflow with no declared inputs warns."""
    plan = {
        "entities": {"Interview": {"table": "interviews", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True, "not_null": True},
        ]}},
        "workflows": [{
            "name": "ScheduleInterview",
            "trigger": "manual on Interview",
            "steps": [
                {"id": "trigger", "type": "trigger", "config": {
                    "triggerType": "manual", "entity": "Interview"}, "next": "end"},
                {"id": "end", "type": "end"},
            ],
        }],
    }
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "workflow_inputs_missing"]
    assert len(hits) == 1
    assert "ScheduleInterview" in hits[0]["message"]


def test_completeness_workflow_scheduled_needs_no_inputs():
    """A cron/scheduled workflow shouldn't be flagged for missing inputs."""
    plan = {
        "workflows": [{
            "name": "DailyReminder",
            "trigger": "schedule daily",
            "steps": [
                {"id": "trigger", "type": "trigger", "config": {
                    "triggerType": "schedule"}, "next": "end"},
                {"id": "end", "type": "end"},
            ],
        }],
    }
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "workflow_inputs_missing"]
    assert hits == []


def test_completeness_nav_missing_initial_for_role():
    """Every actor role must have a nav.initialFor entry."""
    plan = {
        "actors": [
            {"name": "Admin",     "role": "admin",     "onboarding": {"source": "platform_org"}},
            {"name": "Candidate", "role": "candidate", "onboarding": {"source": "self_signup"}},
        ],
        "pages": [
            {"route": "/dashboard", "archetype": "dashboard"},
            {"route": "/profile",   "archetype": "detail"},
        ],
        "nav": {
            "initialFor": {"admin": "/dashboard"},  # candidate missing
            "sidebar": [{"role": "admin", "items": ["/dashboard"]}],
        },
    }
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "nav_initial_missing"]
    assert len(hits) == 1
    assert "candidate" in hits[0]["message"]


def test_completeness_nav_sidebar_route_not_in_pages():
    """A sidebar entry linking to a route not in pages[] is a dead link."""
    plan = {
        "actors": [{"name": "Admin", "role": "admin",
                    "onboarding": {"source": "platform_org"}}],
        "pages": [{"route": "/dashboard", "archetype": "dashboard"}],
        "nav": {
            "initialFor": {"admin": "/dashboard"},
            "sidebar": [{"role": "admin", "items": ["/dashboard", "/nowhere"]}],
        },
    }
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "nav_sidebar_orphan"]
    assert len(hits) == 1
    assert "/nowhere" in hits[0]["message"]


# --------------------------------------------------------------------------- #
# processVariables coverage — reads of declared / earlier-written vars are OK
# --------------------------------------------------------------------------- #

def _wf_process_var_plan(pv_names: list[str] | None = None, steps: list[dict] | None = None) -> dict:
    """Base plan for the processVariables coverage tests. Trigger has no
    inputs so any bare-name read is only coverable by a processVariable
    (declared or step-written)."""
    plan = _minimal_clean_plan()
    plan["workflows"] = [{
        "name": "SetAndUse",
        "processVariables": [{"name": n, "type": "string"} for n in (pv_names or [])],
        "steps": steps or [],
    }]
    plan["pages"][0]["actions"] = [{"label": "Run", "workflow": "SetAndUse"}]
    return plan


def test_declared_process_variable_covers_bare_read():
    """A `{{approvalDecision}}` read is fine when the workflow declares it."""
    plan = _wf_process_var_plan(
        pv_names=["approvalDecision"],
        steps=[
            {"id": "trigger", "type": "trigger", "next": "notify",
             "config": {"inputs": []}},
            {"id": "notify", "type": "action", "next": "end",
             "config": {"actionType": "send_notification",
                        "recipient": "admin@example.com",
                        "message": "Decision: {{approvalDecision}}"}},
            {"id": "end", "type": "end"},
        ],
    )
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_set_variable_step_covers_later_read():
    """An earlier `set_variable` step declares the name for downstream steps."""
    plan = _wf_process_var_plan(
        pv_names=[],  # planner forgot processVariables — set_variable backfills
        steps=[
            {"id": "trigger", "type": "trigger", "next": "init",
             "config": {"inputs": []}},
            {"id": "init", "type": "action", "next": "use",
             "config": {"actionType": "set_variable",
                        "variableName": "retryCount", "variableValue": 0}},
            {"id": "use", "type": "action", "next": "end",
             "config": {"actionType": "send_notification",
                        "recipient": "admin@example.com",
                        "message": "Retries so far: {{retryCount}}"}},
            {"id": "end", "type": "end"},
        ],
    )
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_undeclared_bare_read_still_flagged():
    """A bare read that ISN'T in processVariables and ISN'T written earlier
    still fails — the diagnostic mentions processVariable as one of the fix
    seams so authors know how to resolve it."""
    plan = _wf_process_var_plan(
        pv_names=[],
        steps=[
            {"id": "trigger", "type": "trigger", "next": "use",
             "config": {"inputs": []}},
            {"id": "use", "type": "action", "next": "end",
             "config": {"actionType": "send_notification",
                        "recipient": "admin@example.com",
                        "message": "Value: {{unknownVar}}"}},
            {"id": "end", "type": "end"},
        ],
    )
    v = validate_plan(plan)
    hits = [x for x in v if x["rule"] == "workflow_input_uncovered"]
    assert hits, "expected undeclared read to be flagged"
    assert "unknownVar" in hits[0]["message"]
    # Diagnostic teaches the author how to fix it.
    assert "processVariable" in hits[0]["message"]


def test_set_variable_after_read_does_not_cover_it():
    """A step is only helped by set_variable writes that appear BEFORE it."""
    plan = _wf_process_var_plan(
        pv_names=[],
        steps=[
            {"id": "trigger", "type": "trigger", "next": "use",
             "config": {"inputs": []}},
            {"id": "use", "type": "action", "next": "init",
             "config": {"actionType": "send_notification",
                        "recipient": "admin@example.com",
                        "message": "Value: {{later}}"}},
            # Writes `later` AFTER the read — doesn't cover it.
            {"id": "init", "type": "action", "next": "end",
             "config": {"actionType": "set_variable",
                        "variableName": "later", "variableValue": 1}},
            {"id": "end", "type": "end"},
        ],
    )
    v = validate_plan(plan)
    assert any(x["rule"] == "workflow_input_uncovered" for x in v)


def test_promoted_output_covers_later_read():
    """An outputMappings entry that promotes to a processVar declares it for downstream."""
    plan = _wf_process_var_plan(
        pv_names=[],
        steps=[
            {"id": "trigger", "type": "trigger", "next": "create",
             "config": {"inputs": []}},
            {"id": "create", "type": "action", "next": "use",
             "config": {"actionType": "db_insert", "table": "orders",
                        "values": {"status": "'new'"},
                        "outputMappings": [{"output": "inserted.id",
                                            "processVar": "newOrderId"}]}},
            {"id": "use", "type": "action", "next": "end",
             "config": {"actionType": "send_notification",
                        "recipient": "admin@example.com",
                        "message": "Created: {{newOrderId}}"}},
            {"id": "end", "type": "end"},
        ],
    )
    v = validate_plan(plan)
    assert not any(x["rule"] == "workflow_input_uncovered" for x in v)
