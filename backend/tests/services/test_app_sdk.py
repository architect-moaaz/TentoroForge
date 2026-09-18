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
    assert code_page_dir(doc["pages"][2]) == "src/app/(dashboard)"
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
             {"key": "ok", "type": "end"}, {"key": "bad", "type": "end"}]
    errs = workflow_nodes().flow_errors({"steps": steps})
    assert len(errs) == 1 and "check" in errs[0] and "else-step" in errs[0]
    steps[0]["next"] = ["save", "bad"]
    steps[1]["next"] = ["ok"]
    assert workflow_nodes().flow_errors({"steps": steps}) == []
    steps[1]["next"] = ["nowhere"]
    assert "not a step of this workflow" in workflow_nodes().flow_errors({"steps": steps})[0]


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
