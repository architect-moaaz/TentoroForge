"""A projection is a translation, not a decision.

The generated app is a scaffold plus vendored engines that read Blueprint-derived
files at run time, so producing those files is deterministic. These tests pin
the translation against the shape `app-foundation` already ships — an emitted
module that does not match what the data engine expects is worse than no module,
because it compiles and then behaves wrongly.
"""
import inspect
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


def test_a_page_with_no_template_is_reported_and_gets_a_fallback(tmp_path):
    """A page nothing composed is REPORTED in `skipped` and also gets a written
    fallback schema, so the route is never blank (no "No schema" in the editor,
    no 404 in the preview). Reported, never omitted."""
    from services.blueprint.projection import project_frontend

    doc = _frontend_doc()
    doc["pages"].append({
        "id": "PAGE-002", "name": "Board", "route": "/board",
        "purpose": "Pipeline board.", "pattern": "kanban",
        "data": {"primaryEntity": "ENTITY-001"}, "actions": [],
    })
    result = project_frontend(doc, tmp_path / "app")
    assert result["pages"] == 2                              # both routes have a schema
    assert result["skipped"][0]["page"] == "PAGE-002"        # still reported
    assert result["skipped"][0]["pattern"] == "kanban"
    assert (tmp_path / "app" / "src" / "schemas" / "board.json").exists()


def test_frontend_projection_records_every_file_in_code_map(tmp_path):
    from services.blueprint.projection import apply_frontend_projection

    svc = BlueprintService.create(output_dir=tmp_path / "bp", app_id="a",
                                  name="n", domain="d")
    svc.doc.update(_frontend_doc())
    result = apply_frontend_projection(svc, tmp_path / "app")

    entry = next(e for e in svc.doc["codeMap"] if e["artifact"] == "PAGE-001")
    # §21 files a page's implementation under `frontend`; a page schema is
    # what the UI engine renders, so it is the page's frontend here.
    assert entry["frontend"] == ["src/schemas/candidates.json"]
    assert "service" not in entry
    assert (tmp_path / "app" / entry["frontend"][0]).exists(), (
        "codeMap must point at a file that exists — the whole point of §21")
    assert result["pages"] == 1


def test_a_pages_implementation_is_reachable_as_its_frontend(tmp_path):
    """The reason the facet matters, not just which key it is. `code_intel.where`
    answers §21's "where does this page live" off typed facets — filed under
    `service` a page reported no frontend at all, while claiming a service
    layer it does not have."""
    from services.blueprint.projection import apply_frontend_projection
    from services.smith.code_intel import where

    svc = BlueprintService.create(output_dir=tmp_path / "bp", app_id="a",
                                  name="n", domain="d")
    svc.doc.update(_frontend_doc())
    apply_frontend_projection(svc, tmp_path / "app")

    located = where(svc.doc, "PAGE-001")
    assert located.frontend == ("src/schemas/candidates.json",)
    assert located.service == ()
    assert located.mapped


def test_a_declared_page_keeps_its_last_good_schema_when_its_layout_is_withdrawn(tmp_path):
    """A still-declared page whose composed tree is withdrawn keeps its last
    good schema rather than being deleted. The old policy deleted it (serve
    nothing over serve stale), which 404'd a route the app still declares — the
    exact blank-page defect. Now a declared route is never left without a
    schema: the real one is preserved (not overwritten by the placeholder, not
    removed). A page that is genuinely removed from the Blueprint is still
    cleaned up (that file is no longer declared)."""
    from services.blueprint.projection import project_frontend
    import json as _json

    doc = _frontend_doc()
    project_frontend(doc, tmp_path / "app")
    cand = tmp_path / "app" / "src" / "schemas" / "candidates.json"
    assert cand.exists()

    # The composed tree is withdrawn but the page is STILL declared.
    doc["pageLayouts"] = []
    result = project_frontend(doc, tmp_path / "app")
    assert cand.exists(), "a declared route must not be left without a schema"
    assert "candidates.json" not in result["removed"]
    # The real layout is kept, not degraded to a placeholder.
    assert not _json.loads(cand.read_text())["meta"].get("fallback")


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
    # `accountType` joined the scaffold's users table — the account type the
    # user picked at signup, which auth folds into the session role so the menu
    # can gate on it. Parsing is what makes this a one-line acknowledgement
    # instead of a fourth hand-copy drifting off the original.
    assert set(declared) == {"id", "email", "password", "name",
                             "accountType", "isActive", "createdAt"}
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


def test_a_role_restricted_page_names_who_may_open_it(tmp_path):
    """Reception opened the Income Auditor's queue and the Users admin page:
    the middleware gated a role-restricted route on a session alone. The page
    declares its users; the session carries the role's name; the middleware
    compares the two and sends everyone else to /403."""
    from services.blueprint.projection import project_middleware, role_routes

    doc = {
        "roles": [{"id": "ROLE-005", "name": "Income Auditor"}, {"id": "ROLE-008", "name": "Admin"}],
        "pages": [
            {"id": "PAGE-001", "route": "/income-auditor-queue", "access": "role_restricted", "users": ["ROLE-005"]},
            {"id": "PAGE-002", "route": "/users/[id]", "access": "role_restricted", "users": ["ROLE-008"]},
            {"id": "PAGE-003", "route": "/refund-cases", "access": "authenticated", "users": ["ROLE-005"]},
            {"id": "PAGE-004", "route": "/reports", "access": "role_restricted"},
        ],
    }
    assert role_routes(doc) == [
        {"route": "/income-auditor-queue", "roles": ["Income Auditor"]},
        {"route": "/users/[id]", "roles": ["Admin"]},
    ]
    result = project_middleware(doc, tmp_path / "app")
    text = (tmp_path / "app" / "src" / "middleware.ts").read_text()
    assert result["byRole"] == role_routes(doc)
    assert '{ route: new RegExp("^/income-auditor-queue$"), roles: ["Income Auditor"] }' in text
    assert '{ route: new RegExp("^/users/[^/]+$"), roles: ["Admin"] }' in text
    assert "/refund-cases" not in text.split("ROLE_ROUTES")[1].split("];")[0]
    assert 'NextResponse.redirect(new URL("/403", req.url))' in text
    assert "req.nextauth.token" in text


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


def test_the_root_route_is_owned_inside_the_shell(tmp_path):
    """`[...slug]` is a required catch-all and never matches "/", so the root
    needs a page of its own — and it has to be the one INSIDE `(dashboard)`,
    because that group carries the layout with the sidebar.

    This used to write `src/app/page.tsx`, on the grounds that the scaffold's
    root redirected to a hardcoded `/home`. The scaffold stopped doing that and
    now ships `(dashboard)/page.tsx`, which renders the `/` schema exactly as
    the catch-all would — so this was writing a SECOND handler for a route that
    already had one, outside the group. Both resolved to `/`, route groups not
    affecting the URL, and the one outside rendered without the shell.

    Every page in the application had a sidebar except the one everybody lands
    on, with identical content either way, which reads as a styling bug rather
    than a routing one.
    """
    from services.blueprint.projection import project_root_route

    def _scaffolded(root):
        (root / "src" / "app" / "(dashboard)").mkdir(parents=True)
        (root / "src" / "app" / "(dashboard)" / "page.tsx").write_text(
            "// scaffold: renders / from the registry\n")
        return root

    a = _scaffolded(tmp_path / "a")
    claimed = {"pages": [{"id": "PAGE-001", "route": "/", "name": "Entry"},
                         {"id": "PAGE-002", "route": "/overview"}]}
    r = project_root_route(claimed, a)
    assert r["claimedBy"] == "PAGE-001"
    assert r["files"] == [], "the scaffold's page already renders /"
    assert not (a / "src" / "app" / "page.tsx").exists(), (
        "a root page outside (dashboard) resolves to / without the shell")

    b = _scaffolded(tmp_path / "b")
    (b / "src" / "app" / "page.tsx").write_text("// stale from an older build\n")
    unclaimed = {"pages": [{"id": "PAGE-002", "route": "/sign-in"},
                           {"id": "PAGE-003", "route": "/overview"}]}
    r = project_root_route(unclaimed, b)
    assert r["redirectsTo"] == "/overview"
    assert r["removedStaleRoot"] is True
    assert not (b / "src" / "app" / "page.tsx").exists()
    body = (b / "src" / "app" / "(dashboard)" / "page.tsx").read_text()
    assert 'redirect("/overview")' in body
    # Only the *statement* matters — the comment explains the old bug and
    # legitimately names the route it used to hardcode.
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))
    assert "/home" not in code

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
    # A role the CONTRACT does not claim passes through under its own name and
    # keeps its hex (the scaffold reads it raw). `focusRing` is no longer such a
    # role — the contract consumes it into `--ring` (see the sibling test) — so
    # this uses a genuinely app-specific colour.
    assert "--status-paid: #1B6B3A;" in css


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


# --- who may launch a workflow, who may read an entity --------------------------


def test_launch_roles_come_from_the_pages_a_workflow_launches_from(tmp_path):
    """Reception posted a refund through the API: the posting queue page was
    Finance's, but nothing compared the caller to it.

    And the other way round: `users` is "roles for whom this page is
    meaningful", which only `role_restricted` turns into a gate. Reading it
    on an `authenticated` page made the API stricter than the application —
    0l133sp2's admin was shown "List a Tool", filled it in, uploaded a photo
    and got 403 from the page that had just offered it."""
    from services.blueprint.projection import launch_roles, project_launch_roles

    doc = {
        "roles": [{"id": "ROLE-001", "name": "Reception"}, {"id": "ROLE-006", "name": "Finance"}, {"id": "ROLE-009", "name": "Guest"}],
        "pages": [
            {"id": "PAGE-004", "route": "/posting-queue", "access": "role_restricted", "users": ["ROLE-006"]},
            {"id": "PAGE-008", "route": "/guest/refund-request", "access": "public", "users": ["ROLE-009"]},
            {"id": "PAGE-007", "route": "/refund-cases/new", "access": "authenticated", "users": ["ROLE-001"]},
        ],
        "workflows": [
            {"id": "FLOW-008", "name": "Post Refund", "launchedFrom": ["PAGE-004"], "steps": []},
            {"id": "FLOW-002", "name": "Guest Refund Request Submission", "launchedFrom": ["PAGE-008"], "steps": []},
            {"id": "FLOW-001", "name": "Refund Case Intake", "launchedFrom": ["PAGE-007"], "steps": []},
            {"id": "FLOW-099", "name": "Nightly sweep", "steps": []},
        ],
    }
    assert launch_roles(doc) == {"FLOW-008": ["Finance"], "FLOW-002": ["*"],
                                 "FLOW-001": ["@signed-in"], "FLOW-099": None}
    project_launch_roles(doc, tmp_path / "app")
    text = (tmp_path / "app" / "src" / "lib" / "workflows" / "launch-roles.ts").read_text()
    assert '"FLOW-008": ["Finance"]' in text and '"post-refund": ["Finance"]' in text
    assert '"FLOW-002": ["*"]' in text and '"FLOW-099": null' in text
    assert '"FLOW-001": ["@signed-in"]' in text, "a page anyone signed in may open admits them all"

    from services import runtime_injector
    gate = inspect.getsource(runtime_injector)
    assert 'allowed.includes("@signed-in") && Boolean(user?.id)' in gate, (
        "the route has to read the same word the projection writes")


def test_entity_access_comes_from_the_pages_that_use_an_entity(tmp_path):
    """Reception read every user account: the Users page was Admin's, but
    nothing carried that to the data endpoint."""
    from services.blueprint.projection import entity_access, project_entity_access

    doc = {
        "roles": [{"id": "ROLE-001", "name": "Reception"}, {"id": "ROLE-006", "name": "Finance"},
                  {"id": "ROLE-008", "name": "Admin"}, {"id": "ROLE-009", "name": "Guest"}],
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Property", "table": "properties"},
            {"id": "ENTITY-002", "name": "User", "table": "users"},
            {"id": "ENTITY-003", "name": "RefundCase", "table": "refund_cases"},
        ]},
        "pages": [
            {"id": "P-USERS", "route": "/users", "access": "role_restricted", "users": ["ROLE-008"], "data": {"primaryEntity": "ENTITY-002"}},
            {"id": "P-CASES", "route": "/refund-cases", "access": "authenticated", "users": ["ROLE-001", "ROLE-006"], "data": {"primaryEntity": "ENTITY-003"}},
            {"id": "P-GUEST", "route": "/guest/refund-request", "access": "public", "users": ["ROLE-009"], "data": {"primaryEntity": "ENTITY-003"}},
        ],
        "pageLayouts": [{"page": "P-GUEST", "root": {}, "dataSources": [{"name": "properties", "entity": "Property", "op": "list"}]}],
        "security": {"ownershipRules": [{"entity": "RefundCase", "column": "propertyId", "kind": "scope", "scope": "workspace", "unscopedRoles": ["Finance", "CEO"]}]},
    }
    access = entity_access(doc)
    assert access["users"] == {"read": ["Admin"], "write": ["Admin"]}
    assert access["properties"]["read"] == ["*"]
    assert set(access["refund_cases"]["read"]) == {"*", "CEO", "Finance", "Reception"}
    assert set(access["refund_cases"]["write"]) == {"*", "Finance", "Reception"}
    project_entity_access(doc, tmp_path / "app")
    assert '"users"' in (tmp_path / "app" / "src" / "lib" / "entity-access.ts").read_text()



def test_a_list_column_is_jsonb():
    """`string[]` fell through to the text default, so the column held whatever
    reached it — the fixture's JSON text, the create form's comma string."""
    line, builder = drizzle_column({"name": "specialities", "type": "string[]", "required": True})
    assert builder == "jsonb" and line.startswith('specialities: jsonb("specialities")')


def test_a_retired_workflows_definition_is_removed(tmp_path):
    """The engine registers every file in definitions/; a stale file kept a
    DEPRECATED workflow runnable after Smith retired it."""
    from services.blueprint.projection import project_workflows
    def wf(wid, name, status=None):
        row = {"id": wid, "name": name, "purpose": "", "trigger": {"kind": "manual"}, "launchedFrom": [],
               "inputs": [{"name": "record", "kind": "record", "entity": "E-1", "required": True}],
               "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["do"]},
                         {"key": "do", "name": name, "type": "action", "entity": "E-1",
                          "config": {"actionType": "db_delete", "table": "things", "where": {"id": "{{record.id}}"}}, "next": ["done"]},
                         {"key": "done", "name": "End", "type": "end", "next": []}]}
        if status:
            row["status"] = status
        return row
    doc = {"data": {"entities": [{"id": "E-1", "name": "Thing", "table": "things", "fields": [{"name": "id", "type": "uuid"}]}]},
           "workflows": [wf("FLOW-001", "Delete Thing"), wf("FLOW-002", "Notify Admin")]}
    project_workflows(doc, tmp_path)
    defs = tmp_path / "src" / "lib" / "workflows" / "definitions"
    assert sorted(p.name for p in defs.glob("*.json")) == ["delete-thing.json", "notify-admin.json"]
    doc["workflows"][1]["status"] = "DEPRECATED"
    project_workflows(doc, tmp_path)
    assert sorted(p.name for p in defs.glob("*.json")) == ["delete-thing.json"]


# ---------------------------------------------------------------------------
# reading a projected module back — what a spreadsheet of the records needs
# ---------------------------------------------------------------------------

def test_a_projected_module_reads_back_as_field_and_column_pairs():
    """`services.smith.records_out` has to SELECT what the database has and
    head the column with what the owner calls it. Both are in the declaration
    this emits, so neither is re-derived anywhere."""
    from services.blueprint.projection import emit_entity_module, parse_table_columns

    entity = {"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
              "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                         {"name": "fullName", "type": "string", "required": True},
                         {"name": "yearsOfExperience", "type": "int"}]}
    doc = {"data": {"entities": [entity], "relationships": []}}

    table, columns = parse_table_columns(emit_entity_module(entity, doc))
    assert table == "nurses"
    assert columns == (("id", "id"), ("fullName", "full_name"),
                       ("yearsOfExperience", "years_of_experience"))


def test_a_foreign_key_column_is_read_back_too():
    """A relationship adds a column no entity field declares. It is data, and
    an export that dropped it would lose which job a part was used on."""
    from services.blueprint.projection import emit_entity_module, parse_table_columns

    part = {"id": "ENTITY-002", "name": "PartUsage", "table": "part_usages",
            "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}
    job = {"id": "ENTITY-003", "name": "Job", "table": "jobs",
           "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}
    doc = {"data": {"entities": [part, job],
                    "relationships": [{"from": "ENTITY-002", "to": "ENTITY-003",
                                       "kind": "one_to_many", "fromField": "jobId"}]}}

    _table, columns = parse_table_columns(emit_entity_module(part, doc))
    assert ("jobId", "job_id") in columns


def test_a_module_with_no_table_declares_nothing():
    """The barrel re-exports and declares no columns; a reader must not
    invent a table for it."""
    from services.blueprint.projection import parse_table_columns

    assert parse_table_columns('export * from "./nurse";\n') == ("", ())
