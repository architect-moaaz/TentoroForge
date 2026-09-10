import json

from services.fk_semantics import classify_entity_fks, FkRole


def _reg(cols, slug="pets", name="Pet", table="pets"):
    return {"entities": {name: {"name": name, "slug": slug, "table": table,
            "camel": name[0].lower()+name[1:], "columns": cols}}}


def _users_entity(reg):
    reg["entities"]["User"] = {"name": "User", "slug": "users", "table": "users",
                               "camel": "user", "columns": [{"name": "id", "type": "uuid", "fk": None}]}
    reg["entities"]["Owner"] = {"name": "Owner", "slug": "owners", "table": "owners",
                                "camel": "owner", "columns": [{"name": "id", "type": "uuid", "fk": None}]}
    return reg


def test_domain_fk_beats_name():
    # pets.ownerId references the OWNERS entity, not users -> domain, despite the name
    reg = _users_entity(_reg([
        {"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["ownerId"].role == "domain"
    assert roles["ownerId"].target_slug == "owners"


def test_actor_fk_when_target_is_users():
    reg = _users_entity(_reg([
        {"name": "createdById", "type": "uuid", "fk": "user", "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["createdById"].role == "actor"


def test_actor_name_fallback_when_no_fk():
    # constraint-less createdById (no .references) still auto-fills -> actor
    reg = _users_entity(_reg([
        {"name": "createdById", "type": "uuid", "fk": None, "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["createdById"].role == "actor"


def test_tenancy_by_name_when_no_fk():
    reg = _users_entity(_reg([
        {"name": "workspaceId", "type": "uuid", "fk": None, "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["workspaceId"].role == "tenancy"


def test_plain_non_fk_column():
    reg = _users_entity(_reg([{"name": "name", "type": "varchar", "fk": None, "notNull": False}]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["name"].role == "plain"


def test_required_flag_from_notnull():
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": True}]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["ownerId"].required is True


def test_classify_registry_returns_all_entities():
    from services.fk_semantics import classify_registry
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False}]))
    allroles = classify_registry(reg)
    assert "Pet" in allroles and allroles["Pet"]["ownerId"].role == "domain"


def test_schema_reference_fallback(tmp_path):
    # registry column.fk missing, but schema .references() knows the target
    from services.fk_semantics import classify_registry
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": None, "notNull": False}]))
    sdir = tmp_path / "src" / "db" / "schema"; sdir.mkdir(parents=True)
    (sdir / "pets.ts").write_text(
        'import { owners } from "./owners";\n'
        'export const pets = pgTable("pets", { ownerId: uuid("owner_id").references(() => owners.id) });\n', encoding="utf-8")
    allroles = classify_registry(reg, output_dir=str(tmp_path))
    assert allroles["Pet"]["ownerId"].role == "domain"


def _write_registry(tmp_path, reg):
    cdir = tmp_path / "contracts"; cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "resource-registry.json").write_text(json.dumps(reg), encoding="utf-8")


def test_emit_fk_semantics_json(tmp_path):
    from services.fk_semantics import emit_fk_semantics
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False}]))
    _write_registry(tmp_path, reg)
    emit_fk_semantics(str(tmp_path))
    data = json.loads((tmp_path / "contracts" / "fk-semantics.json").read_text(encoding="utf-8"))
    assert data["Pet"]["ownerId"]["role"] == "domain"
    assert data["Pet"]["ownerId"]["targetSlug"] == "owners"


def test_emit_fk_roles_module(tmp_path):
    from services.fk_semantics import emit_fk_roles_module
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False}]))
    _write_registry(tmp_path, reg)
    emit_fk_roles_module(str(tmp_path))
    ts = (tmp_path / "src" / "lib" / "fk-roles.ts").read_text(encoding="utf-8")
    assert "export const FK_ROLES" in ts
    assert "export function fkRole(table" in ts
    assert '"pets"' in ts and '"ownerId"' in ts and '"domain"' in ts


# ── hidden_fk_columns — the shared consumer helper (Task 5) ──────────────────

def test_hidden_fk_columns_excludes_domain_includes_actor_tenancy():
    from services.fk_semantics import hidden_fk_columns
    reg = _users_entity(_reg([
        {"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": True},       # domain
        {"name": "createdById", "type": "uuid", "fk": "user", "notNull": True},    # actor
        {"name": "workspaceId", "type": "uuid", "fk": None, "notNull": True},      # tenancy (name)
    ]))
    hidden = hidden_fk_columns("Pet", reg)
    assert "ownerid" not in hidden        # domain FK is NOT hidden — the bug fix
    assert "createdbyid" in hidden        # actor FK stays hidden (server-filled)
    assert "workspaceid" in hidden        # tenancy FK stays hidden


def test_hidden_fk_columns_fields_shape_with_relations():
    # The Contract-Registry shape: entities carry `fields` (no per-column `fk`); FK
    # targets live in top-level `relations`. A domain FK (leaveTypeId -> LeaveType) must
    # NOT be hidden; a users FK (userId -> User) is an actor and stays hidden.
    from services.fk_semantics import hidden_fk_columns
    reg = {"entities": {
        "LeaveRequest": {"name": "LeaveRequest", "slug": "leave-requests",
                         "table": "leave_requests", "camel": "leaveRequest", "fields": {
                             "id": {"type": "uuid", "primaryKey": True},
                             "userId": {"type": "uuid", "nullable": False},
                             "leaveTypeId": {"type": "uuid", "nullable": False},
                         }},
        "User": {"name": "User", "slug": "users", "table": "users", "camel": "user",
                 "fields": {"id": {"type": "uuid"}}},
        "LeaveType": {"name": "LeaveType", "slug": "leave-types", "table": "leave_types",
                      "camel": "leaveType", "fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
    }, "relations": [
        {"from_entity": "LeaveRequest", "to_entity": "User", "foreignKey": "userId"},
        {"from_entity": "LeaveRequest", "to_entity": "LeaveType", "foreignKey": "leaveTypeId"},
    ]}
    hidden = hidden_fk_columns("LeaveRequest", reg)
    assert "userid" in hidden             # -> users => actor => hidden
    assert "leavetypeid" not in hidden     # -> LeaveType (domain) => NOT hidden


def test_hidden_fk_columns_fallback_when_registry_absent():
    from services.fk_semantics import hidden_fk_columns, default_hidden_fk_norms
    # Unknown entity / empty registry -> conservative name-based default (no regression).
    assert hidden_fk_columns("Ghost", {}) == default_hidden_fk_norms()
    assert "ownerid" in hidden_fk_columns("Ghost", {"entities": {}})


def test_build_form_includes_domain_fk_as_select():
    # The critical Task 5 behavior change: a create form now INCLUDES a domain FK as a
    # Select (previously excluded by the name-based _OWNER_FK set); an actor FK stays out.
    from services.deterministic_pages import build_form_page
    reg = {"entities": {
        "Pet": {"name": "Pet", "slug": "pets", "table": "pets", "camel": "pet", "columns": [
            {"name": "id", "type": "uuid", "primaryKey": True, "notNull": True, "fk": None},
            {"name": "name", "type": "varchar", "notNull": True, "fk": None},
            {"name": "ownerId", "type": "uuid", "notNull": True, "fk": "owner"},
            {"name": "createdById", "type": "uuid", "notNull": True, "fk": "user"},
        ]},
        "Owner": {"name": "Owner", "slug": "owners", "table": "owners", "camel": "owner", "columns": [
            {"name": "id", "type": "uuid", "primaryKey": True, "fk": None},
            {"name": "name", "type": "varchar", "fk": None}]},
        "User": {"name": "User", "slug": "users", "table": "users", "camel": "user",
                 "columns": [{"name": "id", "type": "uuid", "fk": None}]},
    }}
    cols = {"id": {"type": "uuid", "primaryKey": True}, "name": {"type": "varchar", "nullable": False},
            "ownerId": {"type": "uuid", "nullable": False}, "createdById": {"type": "uuid", "nullable": False}}
    page = build_form_page("Pet", cols, "/pets/new", None, op="create",
                           entities=reg["entities"], registry=reg)

    by_name: dict = {}

    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                by_name[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(page["root"])

    assert "ownerId" in by_name                          # domain FK now included
    assert by_name["ownerId"]["type"] == "Select"        # ... as a relational Select
    assert by_name["ownerId"]["props"]["optionsFrom"]["source"] == "owners"
    assert "createdById" not in by_name                  # actor FK still excluded


def test_hidden_prefers_canonical_registry_from_output_dir(tmp_path):
    """The trap: a caller passes a THIN registry (fields shape, no resolvable FK
    target) but an output_dir with a CANONICAL registry present. The authority must
    prefer the canonical one so a domain FK (ownerId->owners) is NOT hidden — else the
    create-page path re-drops it via the actor-name fallback."""
    import json
    from services.fk_semantics import hidden_fk_columns
    (tmp_path / "contracts").mkdir(parents=True)
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": {
            "Pet": {"name": "Pet", "slug": "pets", "table": "pets", "camel": "pet",
                    "columns": [{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False}]},
            "Owner": {"name": "Owner", "slug": "owners", "table": "owners", "camel": "owner",
                      "columns": [{"name": "id", "type": "uuid", "fk": None}]},
        }
    }), encoding="utf-8")
    # thin registry the caller happens to hold: ownerId with NO resolvable target
    thin = {"entities": {"Pet": {"fields": {"ownerId": {"type": "uuid"}}}}}
    # without output_dir the thin registry misclassifies ownerId as actor (name fallback)
    assert "ownerid" in hidden_fk_columns("Pet", thin)
    # with output_dir the canonical registry wins → ownerId is domain → NOT hidden
    assert hidden_fk_columns("Pet", thin, str(tmp_path)) == set()


def test_assignment_fk_to_users_is_people_picker_not_actor():
    """assignee/reviewer/manager -> users is a Select of users (assignment), NOT
    auto-filled; created_by/owner -> users stays actor (auto-fill from ctx.user)."""
    from services.fk_semantics import classify_entity_fks, hidden_fk_columns
    reg = _users_entity(_reg([
        {"name": "assigneeId",  "type": "uuid", "fk": "user", "notNull": True},
        {"name": "reviewerId",  "type": "uuid", "fk": "user", "notNull": False},
        {"name": "createdById", "type": "uuid", "fk": "user", "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["assigneeId"].role == "assignment"
    assert roles["reviewerId"].role == "assignment"
    assert roles["createdById"].role == "actor"
    hidden = hidden_fk_columns("Pet", reg)
    # assignment columns are a picker -> NOT hidden; actor stays hidden
    assert "assigneeid" not in hidden and "reviewerid" not in hidden
    assert "createdbyid" in hidden


def test_assessor_fk_to_users_is_assignment_people_picker():
    """C-4: an FK to the users table whose column names an ASSESSOR/EVALUATOR/…
    is a people-picker Select of users (role `assignment`), NOT auto-filled
    (`actor`) and NOT `plain`. Also catches the `assigned*` prefix
    (`assignedAssessorId`) so the assessment isn't auto-assigned to its creator."""
    reg = _users_entity(_reg([
        {"name": "assessorId",         "type": "uuid", "fk": "user", "notNull": True},
        {"name": "assignedAssessorId", "type": "uuid", "fk": "user", "notNull": False},
        {"name": "evaluatorId",        "type": "uuid", "fk": "user", "notNull": False},
        {"name": "interviewerId",      "type": "uuid", "fk": "user", "notNull": False},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["assessorId"].role == "assignment"
    assert roles["assignedAssessorId"].role == "assignment"
    assert roles["evaluatorId"].role == "assignment"
    assert roles["interviewerId"].role == "assignment"
    # target resolves to the users table
    assert roles["assessorId"].target_table == "users"
