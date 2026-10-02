"""The app SDK a coded page compiles against — generated from the Blueprint, so
the compiler can refuse what the application does not have."""

from services.blueprint.app_sdk import (
    CODE_PAGE_MARKER, code_page_dir, code_page_files, page_keys, project_app_sdk,
    project_code_pages, sdk_files, workflow_keys,
)


def _doc():
    return {
        "application": {"id": "t", "name": "Desk"},
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Case", "table": "cases", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "title", "type": "string", "required": True},
                {"name": "status", "type": "enum", "required": True, "enumValues": ["OPEN", "CLOSED"]},
                {"name": "amount", "type": "decimal"},
                {"name": "tags", "type": "string[]"},
                {"name": "openedAt", "type": "timestamp", "required": True}]},
            {"id": "ENTITY-002", "name": "User", "table": "users", "fields": [
                {"name": "email", "type": "string", "required": True},
                {"name": "jobTitle", "type": "string"}]},
        ], "relationships": [
            {"from": "ENTITY-001", "to": "ENTITY-002", "kind": "many_to_one", "fromField": "ownerId"}]},
        "workflows": [
            {"id": "FLOW-001", "name": "Close Case", "steps": [{"entity": "ENTITY-001"}],
             "inputs": [{"name": "case", "kind": "record", "entity": "ENTITY-001", "required": True},
                        {"name": "status", "kind": "field", "required": True},
                        {"name": "note", "kind": "field", "type": "text", "required": False}]},
            {"id": "FLOW-002", "name": "delete", "inputs": []},
        ],
        "pages": [
            {"id": "PAGE-001", "name": "All Cases", "route": "/cases"},
            {"id": "PAGE-002", "name": "Case Record", "route": "/cases/[id]"},
            {"id": "PAGE-003", "name": "Home", "route": "/"},
            {"id": "PAGE-004", "name": "Gone", "route": "/gone", "status": "DEPRECATED"},
        ],
    }


def test_each_entity_is_typed_as_its_table_is():
    schema = sdk_files(_doc())["src/sdk/schema.ts"]
    assert "export interface Case {" in schema
    assert "  status: \"OPEN\" | \"CLOSED\";" in schema          # an enum keeps its values
    assert "  amount: number | null;" in schema                   # numeric, optional
    assert "  tags: string[] | null;" in schema
    assert "  openedAt: string;" in schema                        # dates cross as ISO strings
    assert "  ownerId: string | null;" in schema                  # the relationship's FK column
    assert '"Case": ["amount"]' in schema                         # coerced from numeric text


def test_a_credential_is_never_typed_or_returned():
    """The platform's users table has a password hash; no page may read it,
    and the SDK returns only the typed columns."""
    schema = sdk_files(_doc())["src/sdk/schema.ts"]
    user = schema[schema.index("export interface User {"):]
    user = user[:user.index("}")]
    assert "password" not in user and "email: string;" in user
    readable = schema[schema.index("READABLE_FIELDS"):]
    assert "password" not in readable[:readable.index("};")]


def test_an_entity_named_like_a_global_type_does_not_shadow_it():
    """An entity `Record` must not become `interface Record` — schema.ts itself
    types its constants as `Record<string, …>`, which would stop being generic."""
    doc = _doc()
    doc["data"]["entities"].append(
        {"id": "ENTITY-003", "name": "Record", "table": "records", "fields": [
            {"name": "title", "type": "string", "required": True}]})
    schema = sdk_files(doc)["src/sdk/schema.ts"]
    assert "export interface Record " not in schema
    assert "export interface RecordRow {" in schema
    assert '  "Record": RecordRow;' in schema                    # the SDK still reads it by name
    assert "READABLE_FIELDS: Record<string, readonly string[]>" in schema
    assert "LABEL_FIELD: Record<string, string>" in schema


def test_a_workflow_is_typed_by_its_inputs():
    wf = sdk_files(_doc())["src/sdk/workflows.ts"]
    assert "closeCase: wf<{" in wf
    assert "    case: string;" in wf                                 # a record input is its id
    assert '    status: "OPEN" | "CLOSED";' in wf                    # typed by the column it writes
    assert "    note?: string;" in wf                                # optional input
    assert 'delete_: wf<Record<string, never>>("FLOW-002", "delete")' in wf   # a reserved word
    assert workflow_keys(_doc()) == {"FLOW-001": "closeCase", "FLOW-002": "delete_"}


def test_a_page_is_typed_by_its_route():
    pages = sdk_files(_doc())["src/sdk/pages.ts"]
    assert 'caseRecord: { id: "PAGE-002", name: "Case Record", route: "/cases/[id]" } as PageRef<"/cases/[id]">' in pages
    assert "gone" not in pages                                         # deprecated pages are not linkable
    assert page_keys(_doc())["PAGE-001"] == "allCases"


def test_the_sdk_is_idempotent(tmp_path):
    first = project_app_sdk(_doc(), tmp_path)
    before = {p: (tmp_path / p).read_text() for p in first}
    project_app_sdk(_doc(), tmp_path)
    assert {p: (tmp_path / p).read_text() for p in first} == before


def test_a_coded_page_lives_in_the_dashboard_group():
    doc = _doc()
    assert code_page_dir(doc["pages"][1]) == "src/app/(dashboard)/cases/[id]"
    assert code_page_dir(doc["pages"][2]) == "src/app/_root"      # `/`: the catch-all renders it
    files = code_page_files(doc, {"page": "PAGE-002", "load": "L", "view": "V"})
    page = files["src/app/(dashboard)/cases/[id]/page.tsx"]
    assert page.startswith(CODE_PAGE_MARKER)
    assert "<View {...data} />" in page and "notFound()" in page
    assert files["src/app/(dashboard)/cases/[id]/load.ts"] == "L"
    assert code_page_files(doc, {"page": "PAGE-004", "load": "L", "view": "V"}) == {}


def test_a_page_the_blueprint_dropped_is_removed_and_nothing_else_is(tmp_path):
    doc = _doc()
    doc["pageCode"] = [{"page": "PAGE-001", "load": "L", "view": "V"},
                       {"page": "PAGE-002", "load": "L2", "view": "V2"}]
    project_code_pages(doc, tmp_path)
    hand = tmp_path / "src/app/(dashboard)/tasks/page.tsx"
    hand.parent.mkdir(parents=True)
    hand.write_text("export default function Tasks() { return null }")
    doc["pageCode"] = doc["pageCode"][:1]
    project_code_pages(doc, tmp_path)
    assert (tmp_path / "src/app/(dashboard)/cases/page.tsx").exists()
    assert not (tmp_path / "src/app/(dashboard)/cases/[id]/page.tsx").exists()
    assert hand.exists(), "a route the projection did not write is never touched"


def test_a_public_coded_page_takes_the_public_route_and_is_the_only_file_there(tmp_path):
    """A public page's route file sits outside `(dashboard)`; its code must go
    there too, and the public-route writer must then leave it alone — two
    files resolving to /guest is a build Next refuses (22lzrc2p, 2026-09-18)."""
    from services.blueprint.projection import project_public_routes

    doc = _doc()
    doc["pages"].append({"id": "PAGE-009", "name": "Guest", "route": "/guest", "access": "public"})
    doc["pageCode"] = [{"page": "PAGE-009", "load": "L", "view": "V"}]
    assert code_page_dir(doc["pages"][-1]) == "src/app/guest"
    project_code_pages(doc, tmp_path)
    project_public_routes(doc, tmp_path)
    pages = sorted(str(p.relative_to(tmp_path)) for p in (tmp_path / "src/app").rglob("page.tsx"))
    assert pages == ["src/app/guest/page.tsx"]
    body = (tmp_path / "src/app/guest/page.tsx").read_text()
    assert body.startswith(CODE_PAGE_MARKER) and "<PublicPageFrame>" in body
    # dropping the code hands the route back to the public schema file
    doc["pageCode"] = []
    project_code_pages(doc, tmp_path)
    project_public_routes(doc, tmp_path)
    assert "forge:public-route" in (tmp_path / "src/app/guest/page.tsx").read_text()


def test_a_trigger_step_is_the_start_not_a_second_node(tmp_path):
    """A Blueprint step of type `trigger` keyed `trigger` projected as a second
    Start with the edge trigger -> trigger; the engine looped on it until its
    cycle guard fired, and Delete never deleted (22lzrc2p, 2026-09-19)."""
    import json as _json
    from services.blueprint.projection import project_workflows

    doc = _doc()
    doc["workflows"] = [{"id": "FLOW-003", "name": "Delete Record", "trigger": {"kind": "manual"},
                         "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001"}],
                         "steps": [
                             {"key": "trigger", "type": "trigger", "next": ["delete_record"]},
                             {"key": "delete_record", "type": "action", "entity": "ENTITY-001",
                              "config": {"actionType": "db_delete", "table": "cases",
                                         "where": {"id": "{{record.id}}"}}, "next": ["end"]},
                             {"key": "end", "type": "end"}]}]
    project_workflows(doc, tmp_path)
    (defn,) = list((tmp_path / "src/lib/workflows/definitions").glob("*.json"))
    graph = _json.loads(defn.read_text())["definition"]
    ids = [n["id"] for n in graph["nodes"]]
    edges = [(e["source"], e["target"]) for e in graph["edges"]]
    assert ids == ["trigger", "delete_record", "end"]
    assert edges == [("trigger", "delete_record"), ("delete_record", "end")]
    assert all(a != b for a, b in edges)


def test_a_branch_must_name_both_of_its_targets():
    """A condition with no `next` was chained into the list order and its two
    ends into each other; the author is now told so."""
    from services.catalog import workflow_nodes

    steps = [{"key": "check", "type": "condition", "config": {"expression": "age >= 1"}},
             {"key": "save", "type": "action", "config": {"actionType": "db_insert", "table": "t"}},
             {"key": "ok", "type": "end", "config": {"refused": False}},
             {"key": "bad", "type": "end", "config": {"refused": True, "message": "Age is required."}}]
    errs = workflow_nodes().flow_errors({"steps": steps})
    assert len(errs) == 1 and "check" in errs[0] and "else-step" in errs[0]
    steps[0]["next"] = ["save", "bad"]
    steps[1]["next"] = ["ok"]
    assert workflow_nodes().flow_errors({"steps": steps}) == []
    steps[1]["next"] = ["nowhere"]
    assert "not a step of this workflow" in workflow_nodes().flow_errors({"steps": steps})[0]


def test_every_end_of_a_branching_workflow_says_whether_it_was_refused():
    """h7gmi93x: an empty Add Data form took the validation branch, saved
    nothing, and was told "Record added successfully." — both ends completed
    alike. With two ends each says which it is; a refused one says why."""
    from services.catalog import workflow_nodes

    steps = [{"key": "check", "type": "condition", "config": {"expression": "age >= 1"},
              "next": ["save", "bad"]},
             {"key": "save", "type": "action", "config": {"actionType": "db_insert", "table": "t"},
              "next": ["ok"]},
             {"key": "ok", "type": "end"}, {"key": "bad", "type": "end"}]
    errs = workflow_nodes().flow_errors({"steps": steps})
    assert len(errs) == 2 and all("config.refused" in e for e in errs)
    steps[2]["config"] = {"refused": False}
    steps[3]["config"] = {"refused": True}
    (err,) = workflow_nodes().flow_errors({"steps": steps})
    assert err.startswith("bad:") and "config.message" in err
    steps[3]["config"]["message"] = "Age must be between 1 and 120."
    assert workflow_nodes().flow_errors({"steps": steps}) == []
    steps[3]["config"]["refused"] = "yes"
    assert "true or false" in workflow_nodes().flow_errors({"steps": steps})[0]


def test_one_end_needs_no_outcome_and_a_free_outcome_label_is_left_alone():
    """A single end is the run finishing. `outcome` is the agents' own label
    (`not_found`, an approval's `rejected`) and is not what decides."""
    from services.catalog import workflow_nodes

    steps = [{"key": "save", "type": "action", "config": {"actionType": "db_insert", "table": "t"}},
             {"key": "done", "type": "end", "config": {"outcome": "created"}}]
    assert workflow_nodes().flow_errors({"steps": steps}) == []


def test_a_straight_line_never_flows_out_of_an_end(tmp_path):
    import json as _json
    from services.blueprint.projection import project_workflows

    doc = _doc()
    doc["workflows"] = [{"id": "FLOW-001", "name": "Log", "trigger": {"kind": "manual"}, "steps": [
        {"key": "save", "type": "action", "entity": "ENTITY-001",
         "config": {"actionType": "db_insert", "table": "cases", "values": {"title": "x"}}},
        {"key": "done", "type": "end"}, {"key": "other", "type": "end"}]}]
    project_workflows(doc, tmp_path)
    (defn,) = list((tmp_path / "src/lib/workflows/definitions").glob("*.json"))
    edges = [(e["source"], e["target"]) for e in _json.loads(defn.read_text())["definition"]["edges"]]
    assert ("done", "other") not in edges and ("save", "done") in edges


def test_two_pages_at_one_url_are_refused_before_the_build(tmp_path):
    from services.blueprint.assembly import RouteCollision, check_route_tree, route_collisions

    app = tmp_path / "src/app"
    for rel in ("(dashboard)/cases/page.tsx", "(dashboard)/[entity]/page.tsx",
                "[...slug]/page.tsx", "cases/[id]/page.tsx", "(dashboard)/cases/[caseId]/page.tsx"):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text("export default function P() { return null }")
    clashes = dict(route_collisions(tmp_path))
    assert set(clashes) == {"/cases/[*]"}, clashes           # [entity] vs [...slug] may coexist
    (app / "cases/page.tsx").write_text("x")
    import pytest
    with pytest.raises(RouteCollision) as e:
        check_route_tree(tmp_path)
    assert "src/app/(dashboard)/cases/page.tsx" in str(e.value) and "src/app/cases/page.tsx" in str(e.value)


def test_a_graph_that_would_loop_is_never_projected():
    import pytest
    from services.blueprint.projection import WorkflowGraphInvalid, _check_graph
    from services.catalog import workflow_nodes

    nodes = [{"id": "trigger", "type": "trigger"}, {"id": "end", "type": "end"}]
    with pytest.raises(WorkflowGraphInvalid, match="flows into itself"):
        _check_graph("W", nodes, [{"source": "trigger", "target": "trigger"}], workflow_nodes())
    with pytest.raises(WorkflowGraphInvalid, match="is an end but flows on"):
        _check_graph("W", nodes + [{"id": "x", "type": "end"}], [{"source": "end", "target": "x"}], workflow_nodes())
    with pytest.raises(WorkflowGraphInvalid, match="used twice"):
        _check_graph("W", nodes + [{"id": "end", "type": "end"}], [], workflow_nodes())


def test_the_root_page_is_rendered_by_the_catch_all_and_its_stub_comes_back(tmp_path):
    """`/` cannot have its own route file beside `[[...slug]]`; a coded root sat
    in `(dashboard)/page.tsx`, which assembly retires, and was lost
    (2g13o6yz, 2026-09-19). It lives in the private `_root` module now."""
    doc = _doc()
    doc["pageCode"] = [{"page": "PAGE-003", "load": "L", "view": "V"}]
    project_code_pages(doc, tmp_path)
    root = tmp_path / "src/app/_root/page.tsx"
    assert "export const hasCodeRoot = true;" in root.read_text()
    doc["pageCode"] = []
    project_code_pages(doc, tmp_path)
    assert "export const hasCodeRoot = false;" in root.read_text(), "the catch-all imports it"
    assert not (tmp_path / "src/app/_root/load.ts").exists()
    from services.blueprint.assembly import route_collisions
    assert route_collisions(tmp_path) == []                  # a private folder is not a route


# --- widgets: the analytics a page carries -----------------------------------

def _analytics_doc():
    d = _doc()
    d["widgets"] = [
        {"id": "WIDGET-001", "page": "PAGE-003", "kind": "metric", "label": "Open cases",
         "unit": "number", "order": 1,
         "dataSource": {"op": "aggregate", "entity": "ENTITY-001", "aggregation": "count",
                        "filter": {"status": "OPEN"}}},
        {"id": "WIDGET-002", "page": "PAGE-003", "kind": "chart", "label": "Cases by status",
         "unit": "number", "order": 3, "chart": {"mark": "donut"},
         "dataSource": {"op": "series", "entity": "ENTITY-001", "aggregation": "count",
                        "groupBy": "status"}},
        {"id": "WIDGET-003", "page": "PAGE-003", "kind": "chart", "label": "Amount by month",
         "unit": "currency", "order": 2, "size": "lg", "chart": {"mark": "area", "stacked": True},
         "description": "What was opened, by value.",
         "dataSource": {"op": "query", "entity": "ENTITY-001",
                        "measures": [{"key": "amount", "label": "Amount", "aggregation": "sum",
                                      "field": "amount"}],
                        "dimensions": [{"field": "openedAt", "bucket": "month"}, {"field": "status"}],
                        "timeField": "openedAt"}},
        {"id": "WIDGET-004", "page": "PAGE-001", "kind": "chart", "label": "Gone",
         "unit": "number", "status": "DEPRECATED",
         "dataSource": {"op": "series", "entity": "ENTITY-001", "aggregation": "count",
                        "groupBy": "status"}},
    ]
    return d


def test_every_widget_is_one_query_shape():
    """aggregate and series are a query with one measure; the app runs one path."""
    from services.blueprint.app_sdk import widget_query

    d = _analytics_doc()
    kpi, pie, area = (widget_query(d, w) for w in d["widgets"][:3])
    assert kpi == {"op": "query", "entity": "Case", "filter": {"status": "OPEN"}, "dimensions": [],
                   "measures": [{"key": "value", "label": "Open cases", "aggregation": "count"}]}
    assert pie["dimensions"] == [{"field": "status"}]
    assert area["measures"][0] == {"key": "amount", "label": "Amount", "aggregation": "sum", "field": "amount"}
    assert area["timeField"] == "openedAt"


def test_widgets_are_typed_handles_in_the_sdk():
    files = sdk_files(_analytics_doc())
    widgets = files["src/sdk/widgets.ts"]
    assert 'export * from "./widgets";' in files["src/sdk/index.ts"]
    assert "openCases: {" in widgets and "casesByStatus: {" in widgets
    assert "amountByMonth: {" in widgets and '"mark": "area"' in widgets
    assert "as const satisfies WidgetRef" in widgets
    assert "gone:" not in widgets                                   # a retired widget is not emitted


def test_a_page_brief_lists_its_widgets_in_order():
    from services.blueprint.ui_engineer import _page_brief

    d = _analytics_doc()
    brief = _page_brief(d, d["pages"][2])
    assert [w["sdkKey"] for w in brief["widgets"]] == ["openCases", "amountByMonth", "casesByStatus"]
    area = brief["widgets"][1]
    assert area["reads"] == {"entity": "Case", "measures": ["amount"], "by": ["openedAt per month", "status"]}
    assert area["size"] == "lg" and area["chart"] == {"mark": "area", "stacked": True}
    assert _page_brief(d, d["pages"][0])["widgets"] == []            # the retired one is gone


# --- a widget's key is decided once, at the write, and stays put ---------------

def _clinic_doc():
    """An application from before keys were stored: two widgets with the same
    label, keyed by the old derivation as `activePatients`, `activePatients2`."""
    d = _doc()
    d["pages"].append({"id": "PAGE-004", "name": "Clinic", "route": "/clinic", "pattern": "dashboard",
                       "access": "authenticated", "data": {"primaryEntity": "ENTITY-001"}})
    src = {"op": "query", "entity": "ENTITY-001", "filter": {},
           "measures": [{"key": "n", "aggregation": "count"}], "dimensions": []}
    d["widgets"] = [
        {"id": "WIDGET-001", "page": "PAGE-003", "kind": "metric", "label": "Active Patients", "dataSource": src},
        {"id": "WIDGET-002", "page": "PAGE-004", "kind": "metric", "label": "Active Patients", "dataSource": src},
        {"id": "WIDGET-003", "page": "PAGE-004", "kind": "metric", "label": "Vaccination History", "dataSource": src},
    ]
    return d


def test_adding_a_widget_with_a_colliding_label_does_not_move_the_keys_pages_were_written_against(tmp_path):
    """nlwtcyz5: 57 widgets, keys derived from labels at every projection and
    numbered in document order — one widget added on another page and
    `widgets.vaccinationHistory3` became `vaccinationHistory2`, so six pages
    stopped type-checking. The write seam now stores each widget's key once."""
    from services.blueprint.app_sdk import widget_keys
    from services.blueprint.service import BlueprintService

    from services.blueprint.ids import IdAllocator

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Clinic", domain="health")
    svc.doc.update(_clinic_doc())
    with IdAllocator.session(output_dir=tmp_path) as alloc:          # ids the document already uses
        for w in svc.doc["widgets"]:
            alloc.bind(f"WIDGET:{w['page']}:{w['id']}", w["id"])
    assert widget_keys(svc.doc) == {"WIDGET-001": "activePatients", "WIDGET-002": "activePatients2",
                                    "WIDGET-003": "vaccinationHistory"}
    assert not any(w.get("key") for w in svc.doc["widgets"]), "an old application carries no keys"

    src = svc.doc["widgets"][0]["dataSource"]
    new = svc.upsert("widgets", {"page": "PAGE-003", "kind": "metric", "label": "Active Patients", "dataSource": src},
                     natural_key="WIDGET:/clinic:active-patients-3")
    # the rows that were there are stamped with the keys they read by, and the
    # newcomer takes the next free suffix rather than renumbering them
    assert [w["key"] for w in svc.doc["widgets"]] == ["activePatients", "activePatients2", "vaccinationHistory", "activePatients3"]
    assert new["key"] == "activePatients3"

    # retiring the first and adding a fifth still leaves every survivor where it was
    svc.doc["widgets"][0]["status"] = "DEPRECATED"
    svc.upsert("widgets", {"page": "PAGE-004", "kind": "metric", "label": "Active Patients", "dataSource": src},
               natural_key="WIDGET:/clinic:active-patients-5")
    keys = widget_keys(svc.doc)
    assert keys["WIDGET-002"] == "activePatients2" and keys[new["id"]] == "activePatients3"
    assert keys["WIDGET-003"] == "vaccinationHistory"
    # the retired handle is free again, so the newcomer is not `activePatients4`
    assert keys[svc.doc["widgets"][-1]["id"]] == "activePatients"

    # an update through the seam keeps the row's key even when its label changes:
    # the handle in the page code is the row's identity, not its title
    svc.upsert("widgets", {"id": "WIDGET-003", "page": "PAGE-004", "kind": "metric",
                           "label": "Immunisation History", "dataSource": src},
               natural_key="WIDGET:PAGE-004:WIDGET-003")
    assert widget_keys(svc.doc)["WIDGET-003"] == "vaccinationHistory"
    # `key` is in the contract: whatever else this sketch of a document lacks,
    # nothing about a widget is refused
    from services.blueprint.service import BlueprintInvalid
    try:
        svc.validate()
    except BlueprintInvalid as exc:
        assert not [e for e in exc.errors if e.startswith("widgets/")], exc.errors


def test_the_generated_sdk_reads_the_stored_keys_and_derives_only_for_rows_without_one():
    from services.blueprint.app_sdk import stamp_widget_keys, widget_keys
    from services.blueprint.ui_engineer import page_widget_brief

    d = _clinic_doc()
    # a stored key wins whatever the label says and wherever the row sits;
    # the unstamped rows read as before, numbered around it
    d["widgets"][2]["key"] = "activePatients"
    d["widgets"][1]["key"] = "activePatientsOnClinic"
    widgets = sdk_files(d)["src/sdk/widgets.ts"]
    assert "activePatients: {" in widgets and '"id": "WIDGET-003"' in widgets.split("activePatients: {")[1].split("\n")[0]
    assert "activePatientsOnClinic: {" in widgets
    assert "activePatients2: {" in widgets                              # WIDGET-001, derived around the stored ones
    assert "vaccinationHistory" not in widgets
    assert [w["sdkKey"] for w in page_widget_brief(d, d["pages"][3])] == ["activePatientsOnClinic", "activePatients"]

    # stamping writes exactly those keys onto the rows that lack one, once
    assert stamp_widget_keys(d) == 1
    assert d["widgets"][0]["key"] == "activePatients2"
    assert stamp_widget_keys(d) == 0
    assert widget_keys(d) == {"WIDGET-001": "activePatients2", "WIDGET-002": "activePatientsOnClinic", "WIDGET-003": "activePatients"}


# --- the root and the sign-in pages get the frame every other page has -------

def test_a_coded_root_is_rendered_inside_the_shell_unless_it_is_public(tmp_path):
    """Kids Vaccination (2026-09-23): the parent dashboard at `/` rendered with
    no menu, no sign-out and no padding, because the catch-all that serves
    `/` sits outside `(dashboard)` and rendered the coded root bare."""
    from pathlib import Path

    from services.blueprint.app_sdk import page_module

    catch_all = (Path(__file__).resolve().parents[2]
                 / "templates/standalone-app/src/app/[[...slug]]/page.tsx").read_text()
    assert 'import DashboardLayout from "../(dashboard)/layout";' in catch_all
    assert "rootIsPublic ? page : <DashboardLayout>{page}</DashboardLayout>" in catch_all
    stub = (Path(__file__).resolve().parents[2] / "templates/standalone-app/src/app/_root/page.tsx").read_text()
    assert "export const rootIsPublic = false;" in stub

    doc = {"pages": [{"id": "PAGE-001", "name": "Home", "route": "/", "pattern": "dashboard",
                      "access": "authenticated"}], "data": {"entities": []}}
    signed_in = page_module(doc, doc["pages"][0], {"page": "PAGE-001", "load": "", "view": ""})
    assert "export const hasCodeRoot = true;" in signed_in and "export const rootIsPublic = false;" in signed_in
    doc["pages"][0]["access"] = "public"
    public = page_module(doc, doc["pages"][0], {"page": "PAGE-001", "load": "", "view": ""})
    assert "export const rootIsPublic = true;" in public and "PublicPageFrame" in public


def test_a_sign_in_page_is_given_a_full_height_frame_to_centre_in():
    """Its view was dropped straight into <body>, as tall as its content, so a
    view written to centre itself sat at the top of an empty screen."""
    from services.blueprint.app_sdk import page_module

    doc = {"pages": [{"id": "PAGE-026", "name": "Sign in", "route": "/login", "pattern": "auth",
                      "access": "public"}], "data": {"entities": []}}
    module = page_module(doc, doc["pages"][0], {"page": "PAGE-026", "load": "", "view": ""})
    assert '<div className="min-h-dvh grid">' in module and "</div>" in module
    assert "PageFrame" not in module and "hasCodeRoot" not in module


def test_a_load_that_takes_no_context_still_compiles_against_the_page_module():
    """`load()` for a page that needs nothing is a natural spelling; the module
    called `load(ctx)` and TS2554 cost three compile rounds and the page
    (Contacts Mini PAGE-004 on UAT; Kids Vaccination's sign-in, 2026-09-23)."""
    from services.blueprint.app_sdk import page_module

    doc = {"pages": [{"id": "PAGE-026", "name": "Sign in", "route": "/login", "pattern": "auth",
                      "access": "public"}], "data": {"entities": []}}
    module = page_module(doc, doc["pages"][0], {"page": "PAGE-026", "load": "export async function load() { return {}; }", "view": ""})
    assert "(load as (ctx: PageContext) => ReturnType<typeof load>)(ctx)" in module
    assert "await load(ctx)" not in module
