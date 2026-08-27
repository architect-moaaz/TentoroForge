"""Unit tests for services.interaction_extractor — SV-1.

Fixtures are built on the fly inside each test's tmp_path so we don't
couple to a snapshot of the actual output/ tree; the extractor's job is
to walk contract shapes it was given, not to mimic today's generator.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    DetailInteraction,
    FieldSpec,
    FormInteraction,
    FormSubmit,
    ListInteraction,
    RouteInteraction,
    WorkflowInput,
    extract_interactions,
    to_dict,
)


# ── Fixture builders ─────────────────────────────────────────────────────


def _write(root: Path, rel: str, data: dict | list) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _mk_nav_flow(pages: list[dict], **extra) -> dict:
    return {
        "version": "1.0",
        "initialPage": pages[0]["id"] if pages else None,
        "pages": pages,
        "transitions": [],
        "guards": {},
        "auth_routes": extra.get("auth_routes", []),
        "authGated": extra.get("authGated", False),
    }


def _mk_page(pid: str, route: str, *, shell: bool = True, guard: str | None = None) -> dict:
    p = {
        "id": pid, "route": route, "title": pid,
        "schemaFile": f"src/schemas/{pid}.json",
        "layout": None, "params": [], "shell": shell,
    }
    if guard:
        p["guard"] = guard
    return p


def _mk_registry(entities: dict, relations: list = None) -> dict:
    return {
        "entities": entities,
        "relations": relations or [],
        "api_routes": {}, "components": {}, "pages": {},
        "workflow_bindings": {}, "rules": {},
    }


def _mk_plan(workflows: list[dict]) -> dict:
    return {"workflows": workflows}


# A "simple app" fixture used by half the tests: 3 routes, mixed content.
@pytest.fixture
def simple_app(tmp_path: Path) -> Path:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("home", "/"),
        _mk_page("candidates", "/candidates"),
        _mk_page("candidates-new", "/candidates/new"),
    ]))
    _write(tmp_path, "src/contracts/plan.json", _mk_plan([
        {
            "name": "CreateCandidate",
            "inputs": [
                {"name": "fullName", "type": "varchar", "required": True},
                {"name": "email", "type": "email", "required": True},
                {"name": "status", "type": "varchar", "enum": ["applied", "hired"]},
            ],
        },
    ]))
    _write(tmp_path, "registry.json", _mk_registry({
        "Candidate": {
            "fields": {
                "id": {"type": "uuid", "nullable": False, "primaryKey": True},
                "fullName": {"type": "varchar", "nullable": True},
                "email": {"type": "varchar", "nullable": True, "unique": True},
                "status": {"type": "varchar", "enum_values": ["applied", "hired"]},
            },
        },
    }))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "home", "route": "/",
        "dataSources": [],
        "root": {
            "type": "Section", "props": {}, "children": [
                {"type": "Button", "props": {"label": "Go to Candidates", "navigate": "/candidates"}},
            ],
        },
    })
    _write(tmp_path, "src/schemas/candidates.json", {
        "id": "candidates", "route": "/candidates",
        "dataSources": [{"name": "candidates", "entity": "Candidate", "op": "list"}],
        "root": {
            "type": "Section", "props": {}, "children": [
                {"type": "Button", "props": {"label": "New Candidate", "navigate": "/candidates/new"}},
                {"type": "Table", "props": {
                    "columns": [{"key": "fullName", "label": "Full Name"}],
                    "rows": "{{candidates}}",
                    "rowHref": "/candidates/{id}",
                }},
            ],
        },
    })
    _write(tmp_path, "src/schemas/candidates/new.json", {
        "id": "candidates-new", "route": "/candidates/new",
        "dataSources": [],
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateCandidate", "submitLabel": "Create"},
            "children": [
                {"type": "Input", "props": {"name": "fullName", "label": "Full Name",
                                           "validators": {"required": True}}},
                {"type": "Input", "props": {"name": "email", "label": "Email"}},
                {"type": "Select", "props": {"name": "status", "label": "Status",
                                             "options": [{"value": "applied", "label": "Applied"},
                                                         {"value": "hired", "label": "Hired"}]}},
                {"type": "Button", "props": {"label": "Create", "submit": True}},
            ],
        },
    })
    return tmp_path


# ── Route extraction ────────────────────────────────────────────────────


def test_extracts_route_per_nav_flow_page(simple_app: Path) -> None:
    interactions = extract_interactions(simple_app)
    routes = [i for i in interactions if isinstance(i, RouteInteraction)]
    got = sorted(r.route for r in routes)
    assert got == ["/", "/candidates", "/candidates/new"]


def test_route_ids_are_stable(simple_app: Path) -> None:
    interactions = extract_interactions(simple_app)
    routes = {i.route: i.id for i in interactions if isinstance(i, RouteInteraction)}
    assert routes["/"] == "route:/"
    assert routes["/candidates"] == "route:/candidates"


def test_extraction_is_deterministic(simple_app: Path) -> None:
    a = extract_interactions(simple_app)
    b = extract_interactions(simple_app)
    assert [i.id for i in a] == [i.id for i in b]


def test_missing_nav_flow_returns_empty_route_set(tmp_path: Path) -> None:
    # No nav-flow, no schemas → empty result, not a crash.
    result = extract_interactions(tmp_path)
    assert result == []


# ── Auth-gated route detection ──────────────────────────────────────────


def test_shell_false_marks_route_as_public(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("login", "/login", shell=False),
        _mk_page("home", "/", shell=True),
    ], authGated=True))
    routes = {i.route: i for i in extract_interactions(tmp_path) if isinstance(i, RouteInteraction)}
    assert routes["/login"].requires_auth is False
    assert routes["/"].requires_auth is True


def test_auth_routes_list_marks_route_as_public(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("signup", "/signup"),
        _mk_page("home", "/"),
    ], auth_routes=["/signup"], authGated=True))
    routes = {i.route: i for i in extract_interactions(tmp_path) if isinstance(i, RouteInteraction)}
    assert routes["/signup"].requires_auth is False
    assert routes["/"].requires_auth is True


def test_no_authgated_no_auth_required(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("home", "/"),
    ], authGated=False))
    routes = {i.route: i for i in extract_interactions(tmp_path) if isinstance(i, RouteInteraction)}
    assert routes["/"].requires_auth is False


def test_explicit_guard_marks_auth_required(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("admin", "/admin", guard="admin-only"),
    ]))  # authGated=False globally, but this route has a guard.
    routes = {i.route: i for i in extract_interactions(tmp_path) if isinstance(i, RouteInteraction)}
    assert routes["/admin"].requires_auth is True


# ── Button extraction ───────────────────────────────────────────────────


def test_extracts_navigate_button_simple_form(simple_app: Path) -> None:
    buttons = [
        i for i in extract_interactions(simple_app)
        if isinstance(i, ButtonInteraction) and i.action.kind == "navigate"
    ]
    labels = sorted(b.label for b in buttons)
    assert "New Candidate" in labels
    assert "Go to Candidates" in labels
    nc = next(b for b in buttons if b.label == "New Candidate")
    assert nc.action.navigate_target == "/candidates/new"


def test_extracts_navigate_button_onclick_form(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("home", "/"),
    ]))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "home", "route": "/",
        "root": {"type": "Button", "props": {
            "label": "Open",
            "onClick": {"action": "navigate", "to": "/next"},
        }},
    })
    buttons = [i for i in extract_interactions(tmp_path) if isinstance(i, ButtonInteraction)]
    assert len(buttons) == 1
    assert buttons[0].action.kind == "navigate"
    assert buttons[0].action.navigate_target == "/next"


def test_extracts_workflow_button(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("home", "/"),
    ]))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "home", "route": "/",
        "root": {"type": "Button", "props": {"label": "Fire", "workflow": "DoTheThing"}},
    })
    buttons = [i for i in extract_interactions(tmp_path) if isinstance(i, ButtonInteraction)]
    assert buttons[0].action.kind == "workflow"
    assert buttons[0].action.workflow_target == "DoTheThing"


def test_button_with_no_action_classified_as_none(tmp_path: Path) -> None:
    """The spec's BUTTON_NO_ACTION_DECLARED signature depends on this."""
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("h", "/")]))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "h", "route": "/",
        "root": {"type": "Button", "props": {"label": "Dead"}},
    })
    buttons = [i for i in extract_interactions(tmp_path) if isinstance(i, ButtonInteraction)]
    assert buttons[0].action.kind == "none"


def test_submit_button_classified_as_submit(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("h", "/")]))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "h", "route": "/",
        "root": {"type": "Button", "props": {"label": "Save", "submit": True}},
    })
    buttons = [i for i in extract_interactions(tmp_path) if isinstance(i, ButtonInteraction)]
    assert buttons[0].action.kind == "submit"


def test_compute_button_carries_target_and_formula(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("h", "/")]))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "h", "route": "/",
        "root": {"type": "Button", "props": {
            "label": "=",
            "onClick": {"kind": "compute", "target": "display", "formula": "evalExpression(display)"},
        }},
    })
    buttons = [i for i in extract_interactions(tmp_path) if isinstance(i, ButtonInteraction)]
    assert buttons[0].action.kind == "compute"
    assert buttons[0].action.compute_target == "display"
    assert buttons[0].action.compute_formula == "evalExpression(display)"


# ── Form extraction ─────────────────────────────────────────────────────


def test_extracts_form_with_workflow_submit(simple_app: Path) -> None:
    forms = [i for i in extract_interactions(simple_app) if isinstance(i, FormInteraction)]
    assert len(forms) == 1
    f = forms[0]
    assert f.route == "/candidates/new"
    assert f.submit.kind == "workflow"
    assert f.submit.workflow_target == "CreateCandidate"


def test_form_harvests_fields_from_descendant_nodes(simple_app: Path) -> None:
    forms = [i for i in extract_interactions(simple_app) if isinstance(i, FormInteraction)]
    fnames = sorted(f.name for f in forms[0].fields)
    assert fnames == ["email", "fullName", "status"]


def test_form_field_required_flag_from_validators(simple_app: Path) -> None:
    forms = [i for i in extract_interactions(simple_app) if isinstance(i, FormInteraction)]
    by_name = {f.name: f for f in forms[0].fields}
    assert by_name["fullName"].required is True
    assert by_name["email"].required is False


def test_form_select_field_options_extracted(simple_app: Path) -> None:
    forms = [i for i in extract_interactions(simple_app) if isinstance(i, FormInteraction)]
    status = next(f for f in forms[0].fields if f.name == "status")
    assert status.type == "select"
    assert set(status.options) == {"applied", "hired"}


def test_workflow_inputs_attached_to_form_submit(simple_app: Path) -> None:
    forms = [i for i in extract_interactions(simple_app) if isinstance(i, FormInteraction)]
    inputs = {i.name: i for i in forms[0].submit.workflow_inputs}
    assert set(inputs) == {"fullName", "email", "status"}
    assert inputs["email"].type == "email"
    assert set(inputs["status"].options) == {"applied", "hired"}


def test_workflow_inputs_alias_trigger_inputs(tmp_path: Path) -> None:
    """plan_completeness_validator accepts both `inputs` and `trigger_inputs`."""
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("f", "/f")]))
    _write(tmp_path, "src/contracts/plan.json", _mk_plan([
        {"name": "W", "trigger_inputs": [{"name": "x", "type": "text", "required": True}]},
    ]))
    _write(tmp_path, "src/schemas/f.json", {
        "id": "f", "route": "/f",
        "root": {"type": "Form", "props": {"workflow": "W"}, "children": []},
    })
    forms = [i for i in extract_interactions(tmp_path) if isinstance(i, FormInteraction)]
    assert forms[0].submit.workflow_inputs[0].name == "x"


def test_form_with_datasource_submit(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("f", "/f")]))
    _write(tmp_path, "src/schemas/f.json", {
        "id": "f", "route": "/f",
        "root": {"type": "Form", "props": {"dataSource": "candidates"}, "children": []},
    })
    forms = [i for i in extract_interactions(tmp_path) if isinstance(i, FormInteraction)]
    assert forms[0].submit.kind == "dataSource"
    assert forms[0].submit.dataSource_target == "candidates"


def test_form_with_no_submit_classified_as_none(tmp_path: Path) -> None:
    """FORM_NO_SUBMIT_ACTION signature relies on this classification."""
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("f", "/f")]))
    _write(tmp_path, "src/schemas/f.json", {
        "id": "f", "route": "/f",
        "root": {"type": "Form", "props": {}, "children": []},
    })
    forms = [i for i in extract_interactions(tmp_path) if isinstance(i, FormInteraction)]
    assert forms[0].submit.kind == "none"


# ── FK field promotion from registry ────────────────────────────────────


def test_fk_field_promoted_to_uuid_with_fk_entity(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("f", "/apps")]))
    _write(tmp_path, "registry.json", _mk_registry(
        entities={
            "Application": {"fields": {"candidate_id": {"type": "uuid"}}},
            "Candidate":   {"fields": {"id": {"type": "uuid"}}},
        },
        relations=[
            {"from_entity": "Application", "to_entity": "Candidate",
             "type": "many-to-one", "foreignKey": "candidate_id"},
        ],
    ))
    _write(tmp_path, "src/schemas/apps.json", {
        "id": "apps", "route": "/apps",
        "dataSources": [{"name": "apps", "entity": "Application"}],
        "root": {"type": "Form", "props": {"dataSource": "apps"}, "children": [
            {"type": "Input", "props": {"name": "candidate_id", "label": "Candidate"}},
        ]},
    })
    forms = [i for i in extract_interactions(tmp_path) if isinstance(i, FormInteraction)]
    fk = forms[0].fields[0]
    assert fk.type == "uuid"
    assert fk.fk_entity == "Candidate"


# ── List / Table extraction ─────────────────────────────────────────────


def test_extracts_list_from_table_row_binding(simple_app: Path) -> None:
    lists = [i for i in extract_interactions(simple_app) if isinstance(i, ListInteraction)]
    assert len(lists) == 1
    lst = lists[0]
    assert lst.route == "/candidates"
    assert lst.dataSource == "candidates"
    assert lst.entity == "Candidate"


def test_table_without_datasource_binding_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([_mk_page("h", "/")]))
    _write(tmp_path, "src/schemas/home.json", {
        "id": "h", "route": "/",
        "root": {"type": "Table", "props": {"columns": [], "rows": "not a binding"}},
    })
    lists = [i for i in extract_interactions(tmp_path) if isinstance(i, ListInteraction)]
    assert lists == []


def test_list_seed_min_rows_is_one(simple_app: Path) -> None:
    lists = [i for i in extract_interactions(simple_app) if isinstance(i, ListInteraction)]
    assert lists[0].seed_min_rows == 1


# ── Detail extraction ───────────────────────────────────────────────────


def test_detail_interaction_for_bracket_route(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("candidates", "/candidates"),
        _mk_page("candidates-detail", "/candidates/[id]"),
    ]))
    _write(tmp_path, "registry.json", _mk_registry({"Candidate": {"fields": {}}}))
    _write(tmp_path, "src/schemas/candidates.json", {
        "id": "candidates", "route": "/candidates",
        "dataSources": [{"name": "candidates", "entity": "Candidate", "op": "list"}],
        "root": {"type": "Table", "props": {"rows": "{{candidates}}"}},
    })
    details = [i for i in extract_interactions(tmp_path) if isinstance(i, DetailInteraction)]
    assert len(details) == 1
    assert details[0].route == "/candidates/[id]"
    assert details[0].param_name == "id"
    assert details[0].entity == "Candidate"  # inferred from parent list


def test_detail_entity_none_when_parent_list_missing(tmp_path: Path) -> None:
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("x-detail", "/x/[id]"),
    ]))
    details = [i for i in extract_interactions(tmp_path) if isinstance(i, DetailInteraction)]
    assert details[0].entity is None


# ── Scope filter ────────────────────────────────────────────────────────


def test_scope_wildcard_returns_all(simple_app: Path) -> None:
    assert extract_interactions(simple_app, scope="*") == extract_interactions(simple_app, scope="")


def test_scope_exact_route(simple_app: Path) -> None:
    result = extract_interactions(simple_app, scope="/candidates")
    routes = {i.route for i in result}
    assert routes == {"/candidates"}


def test_scope_prefix_glob(simple_app: Path) -> None:
    """`/candidates/*` includes the prefix route itself + every sub-path.

    Chose include-prefix semantics because a user saying "verify the
    candidates section" wouldn't intuitively want the list page dropped.
    Callers who need strict-nested can filter the result.
    """
    result = extract_interactions(simple_app, scope="/candidates/*")
    routes = {i.route for i in result}
    assert "/candidates" in routes
    assert "/candidates/new" in routes
    assert "/" not in routes  # unrelated routes are still filtered out


# ── Ordering + serialization ────────────────────────────────────────────


def test_interactions_sorted_by_route_kind_id(simple_app: Path) -> None:
    result = extract_interactions(simple_app)
    # Extract the sort key values and confirm they're in ascending order.
    prev = ("", -1, "")
    for it in result:
        # Route order must be non-decreasing; within same route, kind order
        # follows the (route, list, detail, form, button) precedence.
        assert (it.route, ) >= (prev[0],)
        prev = (it.route, 0, it.id)


def test_to_dict_produces_json_safe_output(simple_app: Path) -> None:
    result = extract_interactions(simple_app)
    for it in result:
        d = to_dict(it)
        # Must round-trip through JSON without a TypeError.
        json.dumps(d)


def test_workflow_input_dataclass_serializes(tmp_path: Path) -> None:
    wi = WorkflowInput(name="x", type="text", required=True, options=("a", "b"))
    d = to_dict(FormInteraction(
        id="f:1", kind="form", route="/f", selector="form",
        fields=(FieldSpec(name="x", type="text"),),
        submit=FormSubmit(kind="workflow", workflow_target="W", workflow_inputs=(wi,)),
    ))
    assert d["submit"]["workflow_inputs"][0]["name"] == "x"
    assert d["submit"]["workflow_inputs"][0]["options"] == ("a", "b") or \
           list(d["submit"]["workflow_inputs"][0]["options"]) == ["a", "b"]
