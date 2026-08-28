"""The planner's job is to be boring: same Blueprint, same pages, every time.

These tests lean on the two properties that make it worth having — that it
fails loudly on anything it cannot resolve, and that it checks its output
against the real component registry rather than against a model's memory of it.
"""
from __future__ import annotations

import json

import pytest

from services.blueprint import page_planner as pp


@pytest.fixture(scope="module")
def catalog():
    return pp.load_catalog()


@pytest.fixture
def entity():
    return {
        "id": "ENTITY-001",
        "name": "JobRole",
        "table": "job_roles",
        "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "title", "type": "text", "required": True},
            {"name": "status", "type": "enum", "values": ["open", "closed"]},
            {"name": "headcount", "type": "int"},
            {"name": "createdAt", "type": "timestamp"},
        ],
    }


@pytest.fixture
def doc(entity):
    return {
        "data": {
            "entities": [
                entity,
                {"id": "ENTITY-002", "name": "Application", "table": "applications",
                 "fields": [{"name": "stage", "type": "text"}]},
            ],
            "relationships": [
                {"from": "ENTITY-002", "to": "ENTITY-001", "fromField": "roleId",
                 "kind": "many-to-one"},
            ],
        },
        "widgets": [
            {"id": "WIDGET-001", "page": "PAGE-001", "kind": "metric",
             "label": "Open Roles",
             "dataSource": {"op": "aggregate", "entity": "ENTITY-001",
                            "aggregation": "count"}},
        ],
        "pages": [],
        "patternTemplates": [],
    }


@pytest.fixture
def page():
    return {
        "id": "PAGE-001", "name": "Roles", "route": "/roles",
        "purpose": "List the open roles.", "pattern": "entity_list",
        "module": "MODULE-001",
        "data": {"primaryEntity": "ENTITY-001"},
        "actions": ["create_role", "filter_by_status", "close_role", "search_roles"],
    }


def list_template():
    return {
        "pattern": "entity_list",
        "requires": {"primaryEntity": True},
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Heading", "props": {"content": "$entity.plural", "level": 1},
             "children": []},
            {"type": "Cluster", "props": {}, "children": [
                {"type": "Button", "repeat": "primaryActions",
                 "props": {"label": "$item.label"}, "children": []}]},
            {"type": "TableSortable",
             "props": {"columns": "$columns", "rows": "{{rows}}"}, "children": []},
        ]},
    }


# --- field-role derivation -------------------------------------------------

def test_title_field_prefers_a_naming_field(entity):
    assert pp.title_field(entity) == "title"


def test_internal_fields_are_not_offered_to_users(entity):
    assert "id" not in [c["key"] for c in pp.columns_for(entity)]
    assert "createdAt" not in [f["name"] for f in pp.form_fields_for(entity)]


def test_columns_are_real_definitions_not_null(entity):
    cols = pp.columns_for(entity)
    assert all(c["key"] and c["label"] for c in cols)
    # Numerics right-align; that is a property of the type, not a design call.
    assert next(c for c in cols if c["key"] == "headcount")["align"] == "right"


def test_enum_becomes_a_select_carrying_its_options(entity):
    field = next(f for f in pp.form_fields_for(entity) if f["name"] == "status")
    assert field["kind"] == "select"
    assert {o["value"] for o in field["options"]} == {"open", "closed"}


def test_enum_without_values_degrades_rather_than_emitting_a_dead_control():
    e = {"fields": [{"name": "status", "type": "enum"}]}
    assert pp.form_fields_for(e)[0]["kind"] == "text"


# --- the closed placeholder vocabulary -------------------------------------

def test_unknown_placeholder_is_an_error_not_a_literal(doc, page, entity):
    ctx = pp.build_context(doc, page, entity)
    with pytest.raises(pp.PlanError, match="unresolved placeholder"):
        pp.resolve("$madeUp", ctx)


def test_engine_bindings_pass_through_untouched(doc, page, entity):
    ctx = pp.build_context(doc, page, entity)
    assert pp.resolve("{{rows}}", ctx) == "{{rows}}"


def test_primary_actions_drop_affordances_the_component_provides(doc, page, entity):
    every = pp.repeat_items(doc, page, entity, "actions")
    mutating = pp.repeat_items(doc, page, entity, "primaryActions")
    assert len(every) == 4
    assert [i["id"] for i in mutating] == ["create_role", "close_role"]


def test_related_collections_come_from_declared_relationships(doc, entity):
    related = pp.related_collections(doc, "ENTITY-001")
    assert [r["entity"] for r in related] == ["ENTITY-002"]


# --- validation against the real registry ----------------------------------

def test_unregistered_component_is_rejected(catalog):
    errs = pp.validate_template({"root": {"type": "NotAThing"}}, catalog)
    assert "not a registered component" in errs[0]


def test_positional_child_contract_is_enforced(catalog):
    """SplitView renders children[0] as master and children[1] as detail."""
    one_child = {"root": {"type": "SplitView",
                          "children": [{"type": "Card", "children": []}]}}
    assert "needs exactly 2 children" in pp.validate_template(one_child, catalog)[0]

    both = {"root": {"type": "SplitView", "children": [
        {"type": "Card", "children": []}, {"type": "Card", "children": []}]}}
    assert pp.validate_template(both, catalog) == []


def test_tabs_children_must_match_their_labels(catalog):
    mismatched = {"root": {"type": "Tabs",
                           "props": {"tabs": [{"label": "A"}, {"label": "B"}]},
                           "children": [{"type": "Card", "children": []}]}}
    assert "2 entries in props.tabs" in pp.validate_template(mismatched, catalog)[0]


def test_childless_component_cannot_be_given_children(catalog):
    errs = pp.validate_template(
        {"root": {"type": "Badge", "children": [{"type": "Text"}]}}, catalog)
    assert "takes no children" in errs[0]


def test_structural_primitives_are_in_the_catalog(catalog):
    """Stack and friends are dispatched directly, not registered — but a
    pattern cannot be authored without them."""
    for name in ("Stack", "Row", "Grid", "Container", "Text"):
        assert name in catalog


def test_bad_props_fail_the_plan_rather_than_reaching_the_renderer(
        doc, page, catalog):
    template = list_template()
    template["root"]["children"][0]["props"] = {"text": "$entity.plural"}
    with pytest.raises(pp.PlanError, match="Additional properties|unexpected"):
        pp.plan_page(doc, page, template, catalog)


# --- planning --------------------------------------------------------------

def test_plan_produces_a_renderable_page(doc, page, catalog):
    schema = pp.plan_page(doc, page, list_template(), catalog)
    assert schema["id"] == "PAGE-001"
    assert schema["route"] == "/roles"
    assert schema["root"]["type"] == "Stack"

    buttons = schema["root"]["children"][1]["children"]
    assert [b["props"]["label"] for b in buttons] == ["Create Role", "Close Role"]

    table = schema["root"]["children"][2]
    assert isinstance(table["props"]["columns"], list)
    assert table["props"]["columns"][0]["key"] == "title"


def test_data_sources_follow_the_bindings_actually_used(doc, page, catalog):
    """`{name, entity, op}` — the shape the renderer resolves.

    This asserted `source: "/api/job-roles"` for as long as the bug lived:
    `source` is not a field of the DataSource contract, and that path is the
    one the API derivation moved to /api/data/. Pinning it meant every
    generated page shipped `dataSources: []` with the suite green.
    """
    schema = pp.plan_page(doc, page, list_template(), catalog)
    assert schema["dataSources"] == [
        {"name": "rows", "entity": "JobRole", "op": "list"},
    ]


def test_an_authored_binding_names_its_own_source(doc, page, catalog):
    """A2UI binds `{{jobRoles}}`, not `{{rows}}`: the binding name is the
    source name, because that is what the renderer looks up."""
    template = list_template()
    table = template["root"]["children"][2]
    table["props"]["rows"] = "{{jobRoles}}"
    schema = pp.plan_page(doc, page, template, catalog)
    assert schema["dataSources"] == [
        {"name": "jobRoles", "entity": "JobRole", "op": "list"},
    ]


def test_a_page_with_no_bindings_declares_no_sources(doc, page, catalog):
    template = list_template()
    template["root"]["children"] = []
    schema = pp.plan_page(doc, page, template, catalog)
    assert schema["dataSources"] == []


def test_a_page_missing_what_its_pattern_requires_fails_loudly(doc, catalog):
    orphan = {"id": "PAGE-009", "name": "Nowhere", "route": "/x",
              "pattern": "entity_list", "data": {}, "actions": []}
    with pytest.raises(pp.PlanError, match="requires a primary entity"):
        pp.plan_page(doc, orphan, list_template(), catalog)


def test_planning_is_deterministic(doc, page, catalog):
    first = pp.plan_page(doc, page, list_template(), catalog)
    second = pp.plan_page(doc, page, list_template(), catalog)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_pages_without_a_template_are_reported_not_silently_dropped(
        doc, page, catalog):
    doc["pages"] = [page]
    doc["patternTemplates"] = []
    result = pp.plan_pages(doc, catalog)
    assert result["planned"] == {}
    assert result["skipped"][0]["page"] == "PAGE-001"


def test_plan_pages_covers_every_page_with_a_template(doc, page, catalog):
    doc["pages"] = [page]
    doc["patternTemplates"] = [list_template()]
    result = pp.plan_pages(doc, catalog)
    assert list(result["planned"]) == ["PAGE-001"]
    assert result["failed"] == [] and result["skipped"] == []


# --- the catalog is generated, so it can go stale ---------------------------

def test_component_catalog_is_current():
    """Regenerate the catalog and confirm it matches what is committed.

    The registry is authoritative. If a component is added, renamed or given a
    child contract and nobody re-emits, A2UI is told about a library that no
    longer exists — and the planner validates against the same stale picture,
    so nothing catches it.
    """
    import subprocess

    repo_root = pp.CATALOG_PATH.parents[2]
    pkg = repo_root / "packages" / "library"
    if not (repo_root / "node_modules").exists():
        pytest.skip("workspace dependencies not installed")

    committed = pp.CATALOG_PATH.read_bytes()
    try:
        out = subprocess.run(
            ["npm", "run", "--silent", "emit:catalog"],
            cwd=pkg, capture_output=True, text=True, timeout=600,
        )
        assert out.returncode == 0, out.stderr
        regenerated = pp.CATALOG_PATH.read_bytes()
    finally:
        pp.CATALOG_PATH.write_bytes(committed)

    assert regenerated == committed, (
        "component-catalog.json is stale — re-run "
        "`npm run emit:catalog --workspace=packages/library`"
    )


# --- what a template genuinely requires ------------------------------------

def test_a_repeat_does_not_make_its_source_mandatory():
    """A metrics strip over an empty widget list is zero nodes, not a failure.

    This cost a perfectly good kanban page: the board rendered fine, but the
    template happened to carry an optional widget strip and the page was
    rejected outright for having no widgets.
    """
    template = {"root": {"type": "Stack", "props": {}, "children": [
        {"type": "MetricTile", "repeat": "widgets",
         "props": {"label": "$item.label"}, "children": []}]}}
    assert pp.derived_requires(template)["widgets"] is False


def test_a_scalar_entity_placeholder_does_make_an_entity_mandatory():
    """Substitution has no sensible fallback — unlike a repeat, it cannot
    degrade to nothing."""
    template = {"root": {"type": "Heading",
                         "props": {"content": "$entity.plural"}, "children": []}}
    assert pp.derived_requires(template)["primaryEntity"] is True


def test_a_page_without_widgets_still_plans(doc, page, catalog):
    template = list_template()
    template["root"]["children"].append(
        {"type": "MetricTile", "repeat": "widgets",
         "props": {"label": "$item.label", "value": "$item.value",
                   "format": "number"}, "children": []})
    doc["widgets"] = []
    schema = pp.plan_page(doc, page, template, catalog)
    assert not any(n["type"] == "MetricTile"
                   for n in schema["root"].get("children") or [])


def test_pattern_page_facts_names_the_weakest_page_in_each_group(doc, page):
    """A template fits every page of its pattern or none, so the group's
    entity-less members have to be visible when it is authored."""
    doc["pages"] = [page, {"id": "PAGE-002", "name": "Entry", "route": "/",
                           "pattern": "entity_list", "data": {}, "actions": []}]
    facts = pp.pattern_page_facts(doc)
    assert "NO PRIMARY ENTITY" in facts
    assert "Entry (/)" in facts
    assert "entity JobRole" in facts


# --- absent data degrades; broken templates do not -------------------------

def test_a_node_whose_required_list_is_empty_is_dropped(catalog):
    """A FilterBar needs at least one chip. A page whose entity yields none
    cannot give it one — so the bar is omitted, exactly as an empty repeat
    emits nothing, rather than failing the whole page."""
    node = {"type": "Stack", "children": [
        {"type": "FilterBar", "props": {"chips": []}},
        {"type": "Heading", "props": {"content": "Roles"}},
    ]}
    pruned = pp.prune_unsatisfiable(node, catalog)
    assert [c["type"] for c in pruned["children"]] == ["Heading"]


def test_pruning_does_not_hide_a_genuinely_wrong_prop(doc, page, catalog):
    """Only absent data degrades. A template asking for something the
    component cannot do is still a hard failure."""
    template = list_template()
    template["root"]["children"][0]["props"] = {"content": "x", "level": 99}
    with pytest.raises(pp.PlanError):
        pp.plan_page(doc, page, template, catalog)


def test_the_digest_states_array_item_shapes(catalog):
    """`array<object>` gets filled in from imagination; a Kanban's cardFields
    arrived as {label, value} when the component wanted {field}."""
    digest = pp.catalog_digest(catalog)
    assert "cardFields: array<{field*, label}>" in digest


def test_the_digest_marks_required_props_and_bounds(catalog):
    digest = pp.catalog_digest(catalog)
    assert "chips*:" in digest
    assert "masterWidth: integer (>=160, <=600" in digest


# --- per-page authoring ----------------------------------------------------

def test_an_authored_page_overrides_its_pattern(doc, page, catalog):
    """Switching one page to bespoke must not strand the rest on nothing."""
    doc["pages"] = [page]
    doc["patternTemplates"] = [list_template()]
    doc["pageLayouts"] = [{
        "page": "PAGE-001",
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Heading", "props": {"content": "Bespoke"}, "children": []}]},
    }]
    result = pp.plan_pages(doc, catalog)
    root = result["planned"]["PAGE-001"]["root"]
    assert root["children"][0]["props"]["content"] == "Bespoke"


def test_pages_nobody_authored_still_fall_back_to_the_pattern(doc, page, catalog):
    second = dict(page, id="PAGE-002", route="/other", name="Other")
    doc["pages"] = [page, second]
    doc["patternTemplates"] = [list_template()]
    doc["pageLayouts"] = [{
        "page": "PAGE-001",
        "root": {"type": "Stack", "props": {}, "children": []},
    }]
    result = pp.plan_pages(doc, catalog)
    assert set(result["planned"]) == {"PAGE-001", "PAGE-002"}
    assert result["skipped"] == [] and result["failed"] == []


def test_an_authored_page_is_held_to_the_same_catalog(doc, page, catalog):
    """The gate is what makes per-page safe — its absence is what made
    per-page composition fail in the old platform."""
    doc["pages"] = [page]
    doc["pageLayouts"] = [{
        "page": "PAGE-001",
        "root": {"type": "NotAComponent", "props": {}, "children": []},
    }]
    errs = pp.validate_template(doc["pageLayouts"][0], catalog)
    assert "not a registered component" in errs[0]


def test_the_brief_carries_the_requirements_the_page_serves(doc, page, entity):
    """The pattern author never saw these — it designed structure without ever
    knowing what the user asked for."""
    doc["pages"] = [dict(page, requirements=["REQ-001"])]
    doc["requirements"] = [{"id": "REQ-001", "description": "Scan open roles"},
                           {"id": "REQ-002", "description": "Unrelated"}]
    brief = pp.page_brief(doc, "PAGE-001")
    assert [r["id"] for r in brief["requirements"]] == ["REQ-001"]
    assert brief["entity"]["id"] == "ENTITY-001"
    assert [c["key"] for c in brief["derived"]["columns"]][0] == "title"


def test_the_brief_is_one_page_not_the_whole_app(doc, page):
    doc["pages"] = [page, dict(page, id="PAGE-002", name="Other", route="/o")]
    brief = pp.page_brief(doc, "PAGE-001")
    assert brief["page"]["id"] == "PAGE-001"
    assert "PAGE-002" not in json.dumps(brief)


def test_the_gate_does_not_reject_the_vocabulary_it_offers(catalog):
    """A placeholder is a deferred value, not a type error.

    The apply-time gate validates an *un-instantiated* tree, where
    `$summaryFields` is still the string it currently is rather than the array
    it becomes. Checking it literally rejected a page for using the
    placeholders exactly as designed — and the retry, correctly told what was
    wrong, could only comply by abandoning them.
    """
    schema = {"root": {"type": "DescriptionList",
                       "props": {"items": "$summaryFields"}}}
    assert pp.validate_props(schema, catalog) == []

    bound = {"root": {"type": "Table",
                      "props": {"columns": "$columns", "rows": "{{records}}"}}}
    assert pp.validate_props(bound, catalog) == []


def test_the_gate_still_rejects_a_value_the_component_refuses(catalog):
    """Deferring placeholders must not defer everything — an enum the
    component does not accept is wrong now and wrong later."""
    schema = {"root": {"type": "Table", "props": {
        "columns": "$columns",
        "rowActions": [{"label": "Open", "variant": "ghost"}],
    }}}
    errors = pp.validate_props(schema, catalog)
    assert len(errors) == 1 and "ghost" in errors[0]


def test_the_digest_states_nested_array_item_shapes(catalog):
    """A list inside a list item needs its own shape stated.

    `FilterBar.chips[].options` is a list of {value, label}. Rendered as a bare
    name, an author wrote a list of plain strings — correct-looking, and
    rejected by the gate. That one page failed twice and, before fan-out
    failures were made survivable, took six downstream nodes with it.
    """
    digest = pp.catalog_digest(catalog)
    assert "options*: [{value*, label*}]" in digest


def test_the_digest_states_scalar_array_types_too(catalog):
    """`columnOrder: array<string>` should not read as an array of objects."""
    digest = pp.catalog_digest(catalog)
    assert "columnOrder: [string]" in digest or "columnOrder: array<string>" in digest


# --- views: a filtered variant is not a page -------------------------------

def _viewed_page(page):
    return dict(page, views=[
        {"key": "mine", "label": "Assigned to me",
         "filter": {"assignee": "$currentUser"}},
        {"key": "overdue", "label": "Overdue", "filter": {"overdue": "true"},
         "isDefault": False},
    ])


def test_saved_views_reach_the_component_that_renders_them(doc, page, entity, catalog):
    """The library could always do this — FilterBar.savedViews and
    SavedViewsPicker exist — and the contract had no way to ask for it. So a
    workshop tracker produced /jobs, /jobs/mine, /jobs/unassigned,
    /jobs/overdue and /jobs/ready-for-collection: six routes over one list.
    """
    ctx = pp.build_context(doc, _viewed_page(page), entity)
    assert ctx["$savedViews"] == [
        {"id": "mine", "label": "Assigned to me",
         "filters": {"assignee": "$currentUser"}},
        {"id": "overdue", "label": "Overdue", "filters": {"overdue": "true"}},
    ]


def test_a_template_can_repeat_over_views(doc, page, entity):
    items = pp.repeat_items(doc, _viewed_page(page), entity, "views")
    assert [i["id"] for i in items] == ["mine", "overdue"]
    assert items[0]["label"] == "Assigned to me"


def test_a_page_with_no_views_renders_nothing_extra(doc, page, entity):
    """Absent views must degrade to nothing, like every other repeat."""
    assert pp.build_context(doc, page, entity)["$savedViews"] == []
    assert pp.repeat_items(doc, page, entity, "views") == []


def test_the_bound_shape_is_the_one_the_component_accepts(doc, page, entity, catalog):
    """$savedViews is only useful if FilterBar actually takes it."""
    schema = {"root": {"type": "FilterBar", "props": {
        "chips": [{"key": "status", "label": "Status",
                   "options": [{"value": "open", "label": "Open"}]}],
        "savedViews": pp.build_context(doc, _viewed_page(page), entity)["$savedViews"],
    }}}
    assert pp.validate_props(schema, catalog) == []


def test_repeat_over_states_reads_the_array_the_contract_declares():
    """PageContract.states is z.array(z.enum([...])), not a mapping.

    Reading it as a dict crashed the entire frontend projection the first time
    a pattern template repeated over it — five nodes lost to `'list' object has
    no attribute 'items'`.
    """
    from services.blueprint.page_planner import repeat_items

    page = {"states": ["loading", "empty", "populated", "error"]}
    items = repeat_items({}, page, {}, "states")
    assert [i["id"] for i in items] == ["loading", "empty", "populated", "error"]
    assert items[0]["value"] == "loading"
    assert items[1]["label"]


def test_repeat_over_states_is_empty_when_none_are_declared():
    from services.blueprint.page_planner import repeat_items

    assert repeat_items({}, {"states": []}, {}, "states") == []
    assert repeat_items({}, {}, {}, "states") == []


# --- §33: the page declares the process it starts ---------------------------


def _wf_doc():
    return {
        "workflows": [
            {"id": "FLOW-001", "name": "Bike Drop-off Intake",
             "status": "active", "trigger": {"kind": "manual"},
             # Opens by registering a Customer, though /jobs/new starts it:
             # this is exactly what an inference over step order gets wrong.
             "steps": [{"type": "action", "entity": "ENTITY-001"},
                       {"type": "action", "entity": "ENTITY-002"}]},
            {"id": "FLOW-006", "name": "Flag a Job Awaiting Parts",
             "status": "active", "trigger": {"kind": "manual"},
             "steps": [{"type": "action", "entity": "ENTITY-002"}]},
        ],
    }


def test_a_page_dispatches_the_workflow_it_declares():
    page = {"id": "PAGE-010", "route": "/jobs/new", "dispatches": "FLOW-001"}
    assert pp.workflow_for_page(_wf_doc(), page, {"id": "ENTITY-002"}) == "FLOW-001"


def test_a_page_that_declares_nothing_dispatches_nothing():
    """Silence is not a licence to guess."""
    page = {"id": "PAGE-010", "route": "/jobs/new"}
    assert pp.workflow_for_page(_wf_doc(), page, {"id": "ENTITY-002"}) is None


def test_a_declared_workflow_that_does_not_exist_is_refused():
    page = {"id": "PAGE-010", "route": "/jobs/new", "dispatches": "FLOW-999"}
    assert pp.workflow_for_page(_wf_doc(), page, {"id": "ENTITY-002"}) is None


def test_the_form_carries_the_workflow_and_the_button_does_not():
    """A twelve-step intake dispatched from a button has nowhere to type."""
    root = {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "New drop-off",
                                     "navigate": "/jobs/new"}},
        {"type": "Form", "props": {"fields": [{"name": "x"}]}},
    ]}
    out = pp.bind_workflows(root, "FLOW-001")
    assert out["children"][1]["props"]["workflow"] == "FLOW-001"
    assert "workflow" not in out["children"][0]["props"]


def test_an_authored_workflow_is_not_overwritten():
    root = {"type": "Form", "props": {"fields": [{"name": "x"}],
                                      "workflow": "invoice.update"}}
    assert pp.bind_workflows(root, "FLOW-001")["props"]["workflow"] == "invoice.update"
