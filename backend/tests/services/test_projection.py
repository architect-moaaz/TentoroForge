"""A projection is a translation, not a decision.

The generated app is a scaffold plus vendored engines that read Blueprint-derived
files at run time, so producing those files is deterministic. These tests pin
the translation against the shape `app-foundation` already ships — an emitted
module that does not match what the data engine expects is worse than no module,
because it compiles and then behaves wrongly.
"""
import json
import pathlib
from pathlib import Path

import pytest

from services.blueprint.projection import (
    REMAINING,
    apply_data_projection,
    drizzle_column,
    emit_entity_module,
    project_data_layer,
    to_snake,
)
from services.blueprint.service import BlueprintService

SCAFFOLD = (Path(__file__).resolve().parents[2]
            / "templates/app-foundation/src/db/schema/user.ts")


def doc(**over):
    base = {
        "schemaVersion": "1", "version": 1,
        "application": {"id": "a", "name": "R", "domain": "ATS"},
        "data": {"entities": [{
            "id": "ENTITY-001", "name": "Candidate", "table": "candidates",
            "labelField": "fullName",
            "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "fullName", "type": "string", "required": True,
                 "sensitive": True},
                {"name": "email", "type": "string", "required": True,
                 "unique": True},
                {"name": "score", "type": "integer"},
                {"name": "isActive", "type": "boolean"},
                {"name": "appliedAt", "type": "datetime"},
                {"name": "meta", "type": "json"},
            ]}]},
    }
    base.update(over)
    return base


# --- the translation --------------------------------------------------------

def test_column_names_use_the_scaffold_convention():
    assert to_snake("fullName") == "full_name"
    assert to_snake("changedByUserId") == "changed_by_user_id"
    assert to_snake("id") == "id"


def test_types_map_to_real_drizzle_builders():
    for ftype, builder in (("string", "text"), ("integer", "integer"),
                           ("boolean", "boolean"), ("datetime", "timestamp"),
                           ("json", "jsonb"), ("uuid", "uuid"),
                           ("decimal", "numeric"), ("date", "date")):
        _, got = drizzle_column({"name": "x", "type": ftype})
        assert got == builder, ftype


def test_an_unknown_type_falls_back_to_text_rather_than_breaking():
    _, builder = drizzle_column({"name": "x", "type": "wat"})
    assert builder == "text"


def test_modifiers_are_emitted():
    line, _ = drizzle_column({"name": "email", "type": "string",
                              "required": True, "unique": True})
    assert ".notNull()" in line and ".unique()" in line
    pk, _ = drizzle_column({"name": "id", "type": "uuid", "primaryKey": True})
    assert ".primaryKey().defaultRandom()" in pk
    assert ".notNull()" not in pk, "a primary key is implicitly not-null"


def test_emitted_module_matches_the_scaffolds_shape():
    """The scaffold's own user.ts is the reference; ours must look like it."""
    src = emit_entity_module(doc()["data"]["entities"][0], doc())
    assert 'from "drizzle-orm/pg-core"' in src
    assert 'export const candidates = pgTable("candidates", {' in src
    assert 'fullName: text("full_name").notNull(),' in src
    assert 'id: uuid("id").primaryKey().defaultRandom(),' in src
    if SCAFFOLD.exists():
        ref = SCAFFOLD.read_text()
        assert "pgTable(" in ref and "drizzle-orm/pg-core" in ref


def test_an_entity_with_no_primary_key_gets_a_uuid_one():
    d = doc()
    d["data"]["entities"][0]["fields"] = [{"name": "name", "type": "string"}]
    src = emit_entity_module(d["data"]["entities"][0], d)
    assert 'id: uuid("id").primaryKey().defaultRandom(),' in src


# --- relationships become real foreign keys ---------------------------------

def test_a_declared_relationship_becomes_a_reference():
    d = doc()
    d["data"]["entities"].append({
        "id": "ENTITY-002", "name": "Application", "table": "applications",
        "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]})
    d["data"]["relationships"] = [{
        "from": "ENTITY-002", "to": "ENTITY-001", "kind": "one_to_many",
        "fromField": "candidateId"}]
    src = emit_entity_module(d["data"]["entities"][1], d)
    assert 'candidateId: uuid("candidate_id").references(() => candidates.id),' in src
    assert 'import { candidates } from "./candidate";' in src


def test_a_relationship_whose_column_already_exists_is_not_duplicated():
    d = doc()
    d["data"]["entities"].append({
        "id": "ENTITY-002", "name": "Application", "table": "applications",
        "fields": [{"name": "candidateId", "type": "uuid"}]})
    d["data"]["relationships"] = [{
        "from": "ENTITY-002", "to": "ENTITY-001", "kind": "one_to_many",
        "fromField": "candidateId"}]
    src = emit_entity_module(d["data"]["entities"][1], d)
    assert src.count("candidateId:") == 1


# --- the projection as a whole ---------------------------------------------

def test_projection_writes_a_module_per_entity_plus_a_barrel(tmp_path):
    r = project_data_layer(doc(), tmp_path)
    assert r["entities"] == 1
    assert (tmp_path / "src/db/schema/candidate.ts").exists()
    barrel = (tmp_path / "src/db/schema/index.ts").read_text()
    assert 'export * from "./candidate";' in barrel


def test_projection_is_byte_identical_on_a_re_run(tmp_path):
    """A projection that churns diffs cannot be trusted to be a translation."""
    project_data_layer(doc(), tmp_path)
    first = (tmp_path / "src/db/schema/candidate.ts").read_bytes()
    project_data_layer(doc(), tmp_path)
    assert (tmp_path / "src/db/schema/candidate.ts").read_bytes() == first


def test_deprecated_entities_are_not_projected(tmp_path):
    d = doc()
    d["data"]["entities"][0]["status"] = "DEPRECATED"
    r = project_data_layer(d, tmp_path)
    assert r["entities"] == 0


# --- codeMap: what makes Blueprint<->Implementation checkable ---------------

def test_projection_records_real_paths_in_codemap(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path / "bp", app_id="a",
                                  name="n", domain="d")
    svc.doc["data"] = doc()["data"]
    r = apply_data_projection(svc, tmp_path / "app")

    entry = svc.doc["codeMap"][0]
    assert entry["artifact"] == "ENTITY-001"
    assert entry["service"] == ["src/db/schema/candidate.ts"]
    assert (tmp_path / "app" / entry["service"][0]).exists(), (
        "codeMap must point at a file that exists — the whole point of §21")
    svc.validate()


def test_remaining_work_is_declared_so_green_is_not_mistaken_for_done():
    """REMAINING is the honesty check: what a green run still does not give you."""
    # Every projection now lands on disk; what a green run still does not give
    # you is an app that has been assembled, installed, migrated and served.
    assert any("assembly" in r for r in REMAINING)
    # And it must not keep advertising work that is done, or it stops being read.
    for done in ("frontend", "workflows:", "navigation:", "design:", "seed:"):
        assert not any(r.startswith(done) for r in REMAINING), done


# ---------------------------------------------------------------------------
# frontend — page contracts instantiated from their pattern templates
# ---------------------------------------------------------------------------

def _frontend_doc():
    return {
        "data": {
            "entities": [{
                "id": "ENTITY-001", "name": "Candidate", "table": "candidates",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "fullName", "type": "text", "required": True},
                    {"name": "stage", "type": "text"},
                ],
            }],
            "relationships": [],
        },
        "pages": [{
            "id": "PAGE-001", "name": "Candidates", "route": "/candidates",
            "purpose": "Every candidate in the pipeline.",
            "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-001"},
            "actions": ["create_candidate", "search_candidates"],
        }],
        "widgets": [],
        "pageLayouts": [{
            "page": "PAGE-001",
            "pattern": "entity_list", "requires": {"primaryEntity": True},
            "root": {"type": "Stack", "props": {}, "children": [
                {"type": "Heading", "props": {"content": "$entity.plural"},
                 "children": []},
                {"type": "TableSortable",
                 "props": {"columns": "$columns", "rows": "{{rows}}"},
                 "children": []},
            ]},
        }],
    }


def test_frontend_projection_writes_a_renderable_schema_per_page(tmp_path):
    from services.blueprint.projection import project_frontend

    result = project_frontend(_frontend_doc(), tmp_path / "app")
    assert result["pages"] == 1
    assert result["failed"] == [] and result["skipped"] == []

    written = tmp_path / "app" / "src" / "schemas" / "candidates.json"
    schema = json.loads(written.read_text())
    assert schema["route"] == "/candidates"
    assert schema["root"]["type"] == "Stack"
    # The columns are real definitions, derived from the entity's own fields.
    table = schema["root"]["children"][1]
    assert [c["key"] for c in table["props"]["columns"]] == ["fullName", "stage"]
    # {name, entity, op} — what the renderer resolves. `source` was never a
    # field of the DataSource contract, and /api/candidates is the path the
    # API derivation moved to /api/data/.
    assert schema["dataSources"] == [
        {"name": "rows", "entity": "Candidate", "op": "list"}]


def test_frontend_projection_is_idempotent(tmp_path):
    from services.blueprint.projection import project_frontend

    doc = _frontend_doc()
    project_frontend(doc, tmp_path / "app")
    first = (tmp_path / "app" / "src" / "schemas" / "candidates.json").read_text()
    project_frontend(doc, tmp_path / "app")
    second = (tmp_path / "app" / "src" / "schemas" / "candidates.json").read_text()
    assert first == second


def test_a_page_with_no_template_is_reported_not_silently_omitted(tmp_path):
    """Eleven of eighteen pages emitted must not look like success."""
    from services.blueprint.projection import project_frontend

    doc = _frontend_doc()
    doc["pages"].append({
        "id": "PAGE-002", "name": "Board", "route": "/board",
        "purpose": "Pipeline board.", "pattern": "kanban",
        "data": {"primaryEntity": "ENTITY-001"}, "actions": [],
    })
    result = project_frontend(doc, tmp_path / "app")
    assert result["pages"] == 1
    assert result["skipped"][0]["page"] == "PAGE-002"
    assert result["skipped"][0]["pattern"] == "kanban"


def test_frontend_projection_records_every_file_in_code_map(tmp_path):
    from services.blueprint.projection import apply_frontend_projection

    svc = BlueprintService.create(output_dir=tmp_path / "bp", app_id="a",
                                  name="n", domain="d")
    svc.doc.update(_frontend_doc())
    result = apply_frontend_projection(svc, tmp_path / "app")

    entry = next(e for e in svc.doc["codeMap"] if e["artifact"] == "PAGE-001")
    assert entry["service"] == ["src/schemas/candidates.json"]
    assert (tmp_path / "app" / entry["service"][0]).exists(), (
        "codeMap must point at a file that exists — the whole point of §21")
    assert result["pages"] == 1


def test_a_page_that_stops_planning_does_not_leave_its_schema_behind(tmp_path):
    """Otherwise the directory still looks complete while one file is stale."""
    from services.blueprint.projection import project_frontend

    doc = _frontend_doc()
    project_frontend(doc, tmp_path / "app")
    assert (tmp_path / "app" / "src" / "schemas" / "candidates.json").exists()

    # The composed tree is withdrawn; the page can no longer be planned.
    doc["pageLayouts"] = []
    result = project_frontend(doc, tmp_path / "app")
    assert result["pages"] == 0
    assert result["removed"] == ["candidates.json"]
    assert not (tmp_path / "app" / "src" / "schemas" / "candidates.json").exists()


# ---------------------------------------------------------------------------
# platform tables — the Blueprint may extend them, never redefine them
# ---------------------------------------------------------------------------

def _platform_source() -> str:
    from services.blueprint.projection import PLATFORM_TABLE_SOURCES
    root = pathlib.Path(__file__).resolve().parents[2]
    return (root / PLATFORM_TABLE_SOURCES["users"]).read_text("utf-8")


def test_the_platform_declaration_is_parsed_not_transcribed():
    """Three separate login-breaking bugs came from a hand-copy of this table
    drifting off the original: wrong column names, then a lost
    `.default(true)` on `isActive`, then `createdAt` omitted entirely. Parsing
    the scaffold's own declaration is what makes a fourth impossible."""
    from services.blueprint.projection import parse_platform_table, platform_table

    declared = {f["name"]: f for f in platform_table("users")}
    assert set(declared) == {"id", "email", "password", "name",
                             "isActive", "createdAt"}
    assert declared["email"] == {"name": "email", "type": "text",
                                 "required": True, "unique": True}
    # The default `authorize()` depends on — a falsy isActive rejects the login.
    assert declared["isActive"]["default"] is True
    assert declared["createdAt"]["defaultNow"] is True
    assert declared["id"]["primaryKey"] is True

    # And it is genuinely read from the file, not a constant behind a function.
    assert parse_platform_table(_platform_source()) == platform_table("users")


def test_every_platform_column_survives_projection():
    """The regression net for the whole class.

    A generated app's `users` table is written by the Blueprint but read by
    auth. Any platform column the projection drops, renames or strips a
    constraint from breaks signup or login — and the failure surfaces as a
    baffling runtime error, never as a projection error.
    """
    from services.blueprint.projection import emit_entity_module, platform_table

    # A User entity that disagrees with the platform on every point it can.
    entity = {
        "id": "ENTITY-001", "name": "User", "table": "users",
        "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "text", "required": True},
            {"name": "email", "type": "text", "required": True},
            {"name": "passwordHash", "type": "text", "required": True},
            {"name": "userRole", "type": "enum", "required": True},
        ],
    }
    emitted = emit_entity_module(entity, {"data": {"entities": [entity]}})

    for field in platform_table("users"):
        name = field["name"]
        assert f"{name}: " in emitted, f"platform column {name} was dropped"
        if field.get("required"):
            assert f"{name}: " in emitted and ".notNull()" in \
                emitted.split(f"{name}: ")[1].split("\n")[0], name
        if field.get("unique"):
            assert ".unique()" in emitted.split(f"{name}: ")[1].split("\n")[0], name
        if field.get("default") is True:
            assert ".default(true)" in emitted.split(f"{name}: ")[1].split("\n")[0], name
        if field.get("defaultNow"):
            assert ".defaultNow()" in emitted.split(f"{name}: ")[1].split("\n")[0], name

    # The Blueprint's own additions survive too — but nullable, because
    # platform code inserts rows without knowing they exist.
    row = emitted.split("userRole: ")[1].split("\n")[0]
    assert "user_role" in row and ".notNull()" not in row


def test_a_blueprint_field_never_shadows_a_platform_column():
    """`passwordHash` and `fullName` mean what `password` and `name` mean, so
    they must fold into the platform column rather than sit beside it."""
    from services.blueprint.projection import reconcile_platform_table

    entity = {"name": "User", "table": "users", "fields": [
        {"name": "passwordHash", "type": "text", "required": True},
        {"name": "fullName", "type": "text", "required": True},
        {"name": "userRole", "type": "text"},
    ]}
    fields, folded = reconcile_platform_table(entity)
    names = [f["name"] for f in fields]
    assert "passwordHash" not in names and "fullName" not in names
    assert sorted(folded) == ["fullName", "passwordHash"]
    assert "userRole" in names


# ---------------------------------------------------------------------------
# §100 access — auth is a property of a page, not of an application
# ---------------------------------------------------------------------------

def _matcher(app) -> str:
    import re as _re
    text = (app / "src" / "middleware.ts").read_text()
    return _re.search(r'matcher: \["(.+?)"\]', text).group(1)


def _pages(*specs):
    return {"pages": [{"id": f"PAGE-{i:03d}", "route": r, "access": a}
                      for i, (r, a) in enumerate(specs, 1)]}


def test_a_page_is_gated_unless_it_says_it_is_public(tmp_path):
    """Fail closed. An accidentally public page leaks data; an accidentally
    gated one is a visible annoyance somebody reports."""
    from services.blueprint.projection import access_map

    doc = {"pages": [{"id": "PAGE-001", "route": "/roles"}]}   # no access stated
    assert access_map(doc)["authenticated"] == ["/roles"]
    assert access_map(doc)["public"] == []


def test_a_fully_open_app_gates_nothing_but_the_auth_flow(tmp_path):
    from services.blueprint.projection import project_middleware

    doc = _pages(("/", "public"), ("/pricing", "public"))
    result = project_middleware(doc, tmp_path / "app")
    assert result["gated"] == 0
    assert set(result["public"]) == {"/", "/pricing"}
    assert "pricing" in _matcher(tmp_path / "app")


def test_a_partly_public_app_is_expressible(tmp_path):
    """The case the hardcoded matcher made impossible: browse publicly,
    check out behind a login."""
    from services.blueprint.projection import project_middleware

    doc = _pages(("/", "public"), ("/catalog", "public"),
                 ("/checkout", "authenticated"), ("/orders", "role_restricted"))
    result = project_middleware(doc, tmp_path / "app")
    assert result["gated"] == 2
    matcher = _matcher(tmp_path / "app")
    assert "catalog" in matcher
    assert "checkout" not in matcher and "orders" not in matcher


def test_a_public_landing_route_is_actually_reachable(tmp_path):
    """A negative lookahead cannot exclude the empty path, so `/` stayed gated
    however it was declared — requiring one character after the slash is what
    actually opens it."""
    from services.blueprint.projection import project_middleware

    project_middleware(_pages(("/", "public")), tmp_path / "open")
    assert _matcher(tmp_path / "open").endswith(".+)")

    project_middleware(_pages(("/", "authenticated")), tmp_path / "shut")
    assert _matcher(tmp_path / "shut").endswith(".*)")


def test_dynamic_segments_become_a_wildcard(tmp_path):
    from services.blueprint.projection import project_middleware

    project_middleware(_pages(("/docs/[slug]", "public")), tmp_path / "app")
    assert "docs/[^/]+" in _matcher(tmp_path / "app")


def test_the_auth_flow_is_never_caught_by_its_own_gate(tmp_path):
    """A gate that catches the login page locks everyone out permanently."""
    from services.blueprint.projection import project_middleware

    project_middleware(_pages(("/anything", "authenticated")), tmp_path / "app")
    assert "api/auth" in _matcher(tmp_path / "app")


def test_the_root_route_is_projected_not_guessed(tmp_path):
    """`[...slug]` is a required catch-all and never matches "/", so the root
    always needs its own file. The scaffold's hardcoded `redirect("/home")` sent
    it to a route the app did not have — the root 404d, and the 404 redirected
    into the login gate."""
    from services.blueprint.projection import project_root_route

    claimed = {"pages": [{"id": "PAGE-001", "route": "/", "name": "Entry"},
                         {"id": "PAGE-002", "route": "/overview"}]}
    r = project_root_route(claimed, tmp_path / "a")
    assert r["claimedBy"] == "PAGE-001"
    body = (tmp_path / "a" / "src" / "app" / "page.tsx").read_text()
    assert "renderSchemaPage" in body and "redirect(" not in body

    unclaimed = {"pages": [{"id": "PAGE-002", "route": "/sign-in"},
                           {"id": "PAGE-003", "route": "/overview"}]}
    r = project_root_route(unclaimed, tmp_path / "b")
    body = (tmp_path / "b" / "src" / "app" / "page.tsx").read_text()
    assert r["redirectsTo"] == "/overview"
    assert 'redirect("/overview")' in body
    # Only the *statement* matters — the comment explains the old bug and
    # legitimately names the route it used to hardcode.
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))
    assert '"/home"' not in code, "never a route the Blueprint did not declare"


def test_the_root_never_forwards_to_a_login_screen(tmp_path):
    from services.blueprint.projection import landing_route

    doc = {"pages": [{"route": "/login"}, {"route": "/sign-up"},
                     {"route": "/dashboard"}]}
    assert landing_route(doc) == "/dashboard"


# ---------------------------------------------------------------------------
# Design tokens — the whole system, in the format the scaffold consumes
# ---------------------------------------------------------------------------

_DESIGN = {
    "designSystem": {
        "colors": {"primary": "#125E8A", "background": "#F7F8F9",
                   "foreground": "#16202A", "danger": "#A8261F",
                   "focusRing": "#0B72C4", "statusPaid": "#1B6B3A"},
        "radius": {"md": "6px", "card": "8px", "pill": "999px"},
        "typography": {"baseSize": "15px", "fontFamilyBase": "'Inter', sans-serif"},
        "spacing": {"md": "16px"},
    }
}


def test_the_whole_design_system_reaches_the_stylesheet(tmp_path):
    """Four of thirteen sections used to survive, so apps looked unstyled."""
    from services.blueprint.projection import project_design_tokens

    project_design_tokens(_DESIGN, tmp_path)
    css = (tmp_path / "src" / "app" / "tokens.css").read_text()
    assert "--status-paid: #1B6B3A;" in css       # a role shadcn never names
    assert "--radius-card: 8px;" in css           # radius is an object
    assert "--font-size-base: 15px;" in css       # typography was never read
    assert "--space-md: 16px;" in css


def test_names_the_scaffold_wraps_are_emitted_as_hsl_triplets(tmp_path):
    """`hsl(var(--primary))` with a hex is invalid and silently drops."""
    from services.blueprint.projection import project_design_tokens

    project_design_tokens(_DESIGN, tmp_path)
    css = (tmp_path / "src" / "app" / "tokens.css").read_text()
    assert "--primary: 202 77% 31%;" in css
    assert "--primary: #125E8A;" not in css
    # Roles the scaffold does not wrap keep their hex.
    assert "--focus-ring: #0B72C4;" in css


def test_a_shadcn_name_the_blueprint_omits_falls_back_to_a_declared_role(tmp_path):
    """The Blueprint says `danger`; components ask for `--destructive`."""
    from services.blueprint.projection import project_design_tokens

    project_design_tokens(_DESIGN, tmp_path)
    css = (tmp_path / "src" / "app" / "tokens.css").read_text()
    # Aliases are triplets too: the scaffold wraps these in hsl() as well.
    assert "--destructive: 3 69% 39%;" in css
    assert "--ring: 207 89% 41%;" in css


def test_the_scaffold_imports_the_tokens_and_defines_none_of_them_itself():
    """Nothing imported tokens.css for the life of the file, and globals.css
    held __CSS_*__ placeholders nothing substituted — which won by source
    order, because Tailwind flattens @layer base instead of emitting a layer."""
    from pathlib import Path

    globals_css = Path(__file__).resolve().parents[2] / (
        "templates/app-foundation/src/app/globals.css")
    text = globals_css.read_text()
    assert '@import "./tokens.css";' in text
    assert "__CSS_" not in text


# ---------------------------------------------------------------------------
# A public page is only public if what it fetches is reachable.
#
# /plants was public and rendered for anyone; /api/data/plants and
# /api/workflows/FLOW-002/execute were not. The table came up empty and adding
# a plant did nothing, with no error anywhere — a 307 to /login is a perfectly
# successful HTTP exchange.
# ---------------------------------------------------------------------------

def _access_doc(access="public"):
    return {
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Plant", "table": "plants"},
            {"id": "ENTITY-002", "name": "WateringEvent", "table": "waterings"},
        ]},
        "pages": [
            {"id": "PAGE-001", "name": "Plants", "route": "/plants",
             "access": access, "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-009", "name": "Admin", "route": "/admin",
             "access": "authenticated", "data": {"primaryEntity": "ENTITY-002"}},
        ],
        "pageLayouts": [
            {"page": "PAGE-001",
             "dataSources": [{"name": "waterings", "entity": "WateringEvent",
                              "op": "list"}],
             "root": {"type": "Stack", "props": {}, "children": []}},
        ],
        "workflows": [
            {"id": "FLOW-001", "name": "Record Watering",
             "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"]},
            {"id": "FLOW-009", "name": "Purge", "trigger": {"kind": "manual"},
             "launchedFrom": ["PAGE-009"]},
        ],
    }


def test_a_public_page_opens_the_data_and_workflows_it_uses():
    from services.blueprint.projection import public_apis

    apis = public_apis(_access_doc())
    # Its own entity, and the entity its tree binds through a carried source.
    assert "api/data/plants" in apis
    assert "api/data/waterings" in apis
    assert "api/workflows/FLOW-001" in apis


def test_a_gated_pages_data_and_workflows_stay_gated():
    """Opening `/api/data` wholesale because one page is public would expose
    every entity in the application."""
    from services.blueprint.projection import public_apis

    apis = public_apis(_access_doc())
    assert "api/workflows/FLOW-009" not in apis


def test_an_app_with_no_public_page_opens_nothing():
    from services.blueprint.projection import public_apis

    assert public_apis(_access_doc(access="authenticated")) == []


def test_the_matcher_excludes_the_apis_a_public_page_needs(tmp_path):
    from services.blueprint.projection import project_middleware

    result = project_middleware(_access_doc(), tmp_path / "app")
    written = (tmp_path / "app" / "src" / "middleware.ts").read_text("utf-8")
    assert "api/data/plants" in written
    assert "api/workflows/FLOW-001" in written
    assert "api/workflows/FLOW-009" not in written
    assert result["publicApis"]


# ---------------------------------------------------------------------------
# nav-flow is a graph, not an index.
# ---------------------------------------------------------------------------

def _nav_doc():
    return {"pages": [
        {"id": "PAGE-001", "name": "Dashboard", "route": "/",
         "access": "authenticated", "entry": True, "navigatesTo": ["PAGE-002"]},
        {"id": "PAGE-002", "name": "Surveys", "route": "/surveys",
         "access": "authenticated", "navigatesTo": ["PAGE-003"]},
        {"id": "PAGE-003", "name": "Survey", "route": "/surveys/[id]",
         "access": "authenticated", "presentation": "drawer"},
        {"id": "PAGE-004", "name": "Fill", "route": "/survey/[slug]",
         "access": "public", "entry": True},
    ]}


def _nav(tmp_path):
    import json
    from services.blueprint.projection import project_nav_flow

    project_nav_flow(_nav_doc(), tmp_path / "app")
    return json.loads(
        (tmp_path / "app" / "src" / "contracts" / "nav-flow.json").read_text())


def test_each_audience_gets_its_own_entry(tmp_path):
    """An application has as many front doors as it has audiences. A survey
    author signs in and lands on a dashboard; a respondent opens a link."""
    nav = _nav(tmp_path)
    assert nav["entries"] == {"authenticated": "/", "public": "/survey/[slug]"}


def test_the_gated_entry_is_named_for_what_it_is(tmp_path):
    """Calling it `initialPage` claimed a neutrality it does not have: it is
    the gated entry, chosen because a login redirect and a "back to the
    application" link both need one and both need a concrete URL."""
    assert _nav(tmp_path)["gatedEntry"] == "/"


def test_initial_page_stays_a_page_id_for_the_editor(tmp_path):
    """VisualEditorWorkspace reads `initialPage` and falls back to
    `pages[0].id`, so it wants an id. A route there is something it cannot
    look up — and the field was carrying one."""
    nav = _nav(tmp_path)
    assert nav["initialPage"] in {p["id"] for p in nav["pages"]}


def test_public_and_gated_routes_are_disjoint(tmp_path):
    """Both keys were written from the same list, so one route was at once
    reachable without a session and requiring one — and the middleware read
    that contradiction."""
    nav = _nav(tmp_path)
    assert nav["public_routes"] == ["/survey/[slug]"]
    assert "/survey/[slug]" not in nav["auth_routes"]
    assert set(nav["auth_routes"]) == {"/", "/surveys", "/surveys/[id]"}


def test_the_arrows_come_from_the_pages(tmp_path):
    """`transitions` shipped as [] on every application ever generated: it read
    a `navigation` section nobody authors. Pages are authored."""
    edges = {(t["from"], t["to"]) for t in _nav(tmp_path)["transitions"]}
    assert edges == {("/", "/surveys"), ("/surveys", "/surveys/[id]")}


def test_a_public_page_renders_without_the_app_shell(tmp_path):
    """Navigation into a product the visitor cannot reach is worse than none."""
    pages = {p["route"]: p for p in _nav(tmp_path)["pages"]}
    assert pages["/survey/[slug]"]["shell"] is False
    assert pages["/"]["shell"] is True


def test_presentation_survives_into_the_contract(tmp_path):
    """A detail opened beside its list is a different application from one that
    navigates away, and only the second could be expressed."""
    pages = {p["route"]: p for p in _nav(tmp_path)["pages"]}
    assert pages["/surveys/[id]"]["presentation"] == "drawer"
    assert pages["/"]["presentation"] == "page"


def test_a_status_field_is_seeded_with_its_own_states():
    """The contract's name is `enumValues` and the field object is
    `additionalProperties: false`, so the `values`/`enum` this used to look for
    could not appear on a valid Blueprint. A status field seeded as "Status 1"
    is a value the app's own enum does not allow — and it is what stopped a
    page that only means something once something is submitted from ever having
    a record to show."""
    from services.blueprint.projection import _seed_value

    field = {"name": "status", "type": "text",
             "enumValues": ["draft", "submitted", "approved"]}
    seeded = [_seed_value(field, "Application", row) for row in (1, 2, 3)]
    assert seeded == ["draft", "submitted", "approved"]


def test_a_select_offers_the_values_the_entity_declares():
    """The same wrong key degraded every enum field in every generated form to
    a free-text box, because a select with no options cannot be filled."""
    from services.blueprint.page_planner import form_fields_for

    fields = form_fields_for({
        "name": "Application",
        "fields": [{"name": "status", "type": "enum",
                    "enumValues": ["draft", "submitted"]}],
    }, creating=True)
    status = next((f for f in fields if f.get("name") == "status"), None)
    assert status is not None
    assert [o["value"] for o in status.get("options") or []] == [
        "draft", "submitted"]
