"""Create/edit forms must have an input for every editable column — including
optional ones and FK dropdowns — not just the required columns."""
import json

from services.form_scaffold import (
    scaffold_forms, repair_fk_dropdowns, ensure_required_markers, _fk_target, _plural,
    _infer_required,
)


def _setup(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "seed-plan.json").write_text(json.dumps({
        "field_generators": {"rentals": {
            "status": "faker:helpers:arrayElement[Reserved, Picked Up, Returned, Cancelled]",
        }},
    }), encoding="utf-8")
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Rental": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "customerId": {"type": "uuid", "nullable": False},
                "equipmentId": {"type": "uuid", "nullable": False},
                "startDate": {"type": "timestamp", "nullable": False},
                "totalCost": {"type": "numeric", "nullable": True},
                "status": {"type": "varchar", "nullable": False},
                "notes": {"type": "text", "nullable": True},
                "createdAt": {"type": "timestamp"},
            }},
            "Customer": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
            "Equipment": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
        "relations": [
            {"from_entity": "Rental", "to_entity": "Customer", "type": "many-to-one"},
            {"from_entity": "Rental", "to_entity": "Equipment", "type": "many-to-one"},
        ],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    return sdir


def _form(*inputs):
    return {"root": {"type": "Form", "props": {"workflow": "CreateRental"}, "children": [
        {"type": "Stack", "children": list(inputs)},
    ]}}


def test_fk_target_resolves_via_relations():
    rels = [{"from_entity": "Rental", "to_entity": "Customer", "type": "many-to-one"}]
    ents = {"Customer": {}, "Equipment": {}}
    assert _fk_target("rental", "customerid", rels, ents) == "Customer"


def test_fk_target_person_role_resolves_to_user():
    # requesterId / assigneeId are User-in-a-role FKs: the role word shares no letters
    # with "User" and Ticket has TWO relations (User, Asset) so neither the lexical
    # match nor the single-relation heuristic fires — the person-role alias must.
    rels = [{"from_entity": "Ticket", "to_entity": "User", "type": "many-to-one"},
            {"from_entity": "Ticket", "to_entity": "Asset", "type": "many-to-one"}]
    ents = {"User": {"fields": {"id": {}, "fullName": {}}}, "Asset": {}, "Ticket": {}}
    assert _fk_target("ticket", "requesterid", rels, ents) == "User"
    assert _fk_target("ticket", "assigneeid", rels, ents) == "User"
    # a real FK stem still resolves normally (not hijacked by the role path)
    assert _fk_target("ticket", "assetid", rels, ents) == "Asset"


def test_fk_target_person_role_no_user_entity_is_unresolved():
    # No user-like entity to point at → stays None so the caller flags/prunes it,
    # never inventing a phantom source. (Two relations so the single-relation
    # fallback doesn't fire.)
    rels = [{"from_entity": "Ticket", "to_entity": "Asset", "type": "many-to-one"},
            {"from_entity": "Ticket", "to_entity": "Category", "type": "many-to-one"}]
    ents = {"Asset": {}, "Category": {}, "Ticket": {}}
    assert _fk_target("ticket", "requesterid", rels, ents) is None


def test_plural():
    assert _plural("Customer") == "customers"
    assert _plural("Category") == "categories"
    assert _plural("Class") == "classes"


def test_plural_y_after_vowel_keeps_the_y():
    """English rule: `y → ies` ONLY when preceded by a consonant. `day`
    becomes `days` (not `daies`). Without this guard `AssessmentDay`
    pluralizes to `assessmentDaies` and every downstream binding to it
    404s at runtime — the Assessment Days table renders empty."""
    assert _plural("AssessmentDay") == "assessmentDays"
    assert _plural("Day") == "days"
    assert _plural("Boy") == "boys"
    assert _plural("Key") == "keys"
    assert _plural("Survey") == "surveys"
    # Consonant-y still applies the rule.
    assert _plural("Story") == "stories"
    assert _plural("Company") == "companies"
    assert _plural("Policy") == "policies"


def test_scaffolds_all_missing_editable_columns(tmp_path):
    sdir = _setup(tmp_path)
    # Form starts with only ONE field (startDate); everything else is missing.
    (sdir / "rentals-new.json").write_text(json.dumps(
        _form({"type": "DatePicker", "props": {"name": "startDate", "label": "Start date"}})), encoding="utf-8")

    res = scaffold_forms(str(tmp_path))
    assert res["added"] >= 5

    schema = json.loads((sdir / "rentals-new.json").read_text(encoding="utf-8"))
    by_name = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                by_name[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(schema)

    # FK dropdowns added with optionsFrom, and matching dataSources created.
    assert by_name["customerId"]["type"] == "Select"
    assert by_name["customerId"]["props"]["optionsFrom"]["source"] == "customers"
    assert by_name["equipmentId"]["props"]["optionsFrom"]["source"] == "equipments"
    ds_names = {d["name"] for d in schema.get("dataSources", [])}
    assert {"customers", "equipments"} <= ds_names

    # Enum/numeric/text columns typed correctly.
    assert by_name["status"]["type"] == "Select"
    assert {o["value"] for o in by_name["status"]["props"]["options"]} >= {"Reserved", "Cancelled"}
    assert by_name["totalCost"]["type"] == "NumberInput"
    assert by_name["notes"]["type"] == "Textarea"

    # Existing field preserved, system columns skipped.
    assert by_name["startDate"]["type"] == "DatePicker"
    assert "createdAt" not in by_name
    assert "id" not in by_name


def test_ignores_non_form_pages(tmp_path):
    sdir = _setup(tmp_path)
    # A list page (no create/edit signal) must not be scaffolded.
    (sdir / "rentals.json").write_text(json.dumps(
        {"root": {"type": "Stack", "children": [{"type": "Table", "props": {}}]}}), encoding="utf-8")
    res = scaffold_forms(str(tmp_path))
    assert res["added"] == 0


def test_fk_target_bridges_stem_to_longer_entity_name():
    rels = [{"from_entity": "Member", "to_entity": "MembershipPlan", "type": "many-to-one"}]
    ents = {"Member": {}, "MembershipPlan": {}}
    # planId's stem "plan" is a substring of "MembershipPlan" — must resolve.
    assert _fk_target("member", "planid", rels, ents) == "MembershipPlan"


def test_repair_fixes_wrong_fk_entity(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Member": {"fields": {"id": {"type": "uuid"}, "planId": {"type": "uuid"}}},
            "MembershipPlan": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
        "relations": [{"from_entity": "Member", "to_entity": "MembershipPlan", "type": "many-to-one"}],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "members"
    sdir.mkdir(parents=True)
    # The bug: dataSource entity "Plan" (doesn't exist) → empty dropdown.
    (sdir / "new.json").write_text(json.dumps({
        "route": "/members/new",
        "dataSources": [{"name": "plans", "entity": "Plan", "op": "list"}],
        "root": {"type": "Form", "props": {"workflow": "CreateMember"}, "children": [
            {"type": "Select", "props": {"name": "planId", "label": "Plan",
                                         "optionsFrom": {"source": "plans", "value": "id", "label": "name"}}},
        ]},
    }), encoding="utf-8")

    res = repair_fk_dropdowns(str(tmp_path))
    assert res["repaired"] == 1

    d = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    ds = d["dataSources"][0]
    assert ds["entity"] == "MembershipPlan"           # real entity
    assert ds["name"] == "membershipPlans"            # resolvable /api/data/ path
    sel = d["root"]["children"][0]["props"]
    assert sel["optionsFrom"]["source"] == "membershipPlans"
    assert sel["optionsFrom"]["label"] == "name"


def test_repair_leaves_correct_dropdown_untouched(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Member": {"fields": {"id": {"type": "uuid"}, "trainerId": {"type": "uuid"}}},
            "Trainer": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
        "relations": [{"from_entity": "Member", "to_entity": "Trainer", "type": "many-to-one"}],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "members"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/members/new",
        "dataSources": [{"name": "trainers", "entity": "Trainer", "op": "list"}],
        "root": {"type": "Form", "children": [
            {"type": "Select", "props": {"name": "trainerId", "label": "Trainer",
                                         "optionsFrom": {"source": "trainers", "value": "id", "label": "name"}}},
        ]},
    }), encoding="utf-8")
    res = repair_fk_dropdowns(str(tmp_path))
    assert res["repaired"] == 0   # already correct


def test_missing_dir_safe(tmp_path):
    assert scaffold_forms(str(tmp_path)) == {"added": 0, "files": 0}
    assert repair_fk_dropdowns(str(tmp_path)) == {"repaired": 0, "files": 0}


# --- nested create forms (foo/new.json) + workflow-based entity resolution ---
from services.form_scaffold import _entity_from_form_workflow


def test_entity_from_form_workflow_resolves_via_create_workflow():
    entities = {"ClassBooking": {}, "Member": {}}
    schema = {"root": {"type": "Form", "props": {"workflow": "CreateClassBooking"},
                       "children": []}}
    assert _entity_from_form_workflow(schema, entities) == "classbooking"
    # Unknown workflow entity → None (don't guess).
    assert _entity_from_form_workflow(
        {"root": {"type": "Form", "props": {"workflow": "CreateWidget"}}}, entities) is None


def test_scaffold_populates_nested_new_form(tmp_path):
    # A synthesized-style nested create form with an EMPTY field container, resolved
    # to its entity purely by the Create<Entity> workflow (basename "new" is generic).
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "ClassBooking": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "memberId": {"type": "uuid", "nullable": False},
                "classId": {"type": "uuid", "nullable": False},
                "status": {"type": "varchar", "nullable": False},
                "bookedAt": {"type": "timestamp", "nullable": False},
            }},
            "Member": {"fields": {"id": {"type": "uuid"}, "fullName": {"type": "varchar"}}},
            "Class": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
        "relations": [
            {"from_entity": "ClassBooking", "to_entity": "Member", "type": "many-to-one"},
            {"from_entity": "ClassBooking", "to_entity": "Class", "type": "many-to-one"},
        ],
    }), encoding="utf-8")
    nested = tmp_path / "src" / "schemas" / "bookings"
    nested.mkdir(parents=True)
    (nested / "new.json").write_text(json.dumps({
        "route": "/bookings/new",
        "root": {"type": "Form", "props": {"workflow": "CreateClassBooking"}, "children": [
            {"type": "Stack", "children": []},
        ]},
    }), encoding="utf-8")

    res = scaffold_forms(str(tmp_path))
    assert res["added"] >= 3
    doc = json.loads((nested / "new.json").read_text(encoding="utf-8"))
    fields = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                fields[n["props"]["name"]] = n["type"]
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(doc)
    # FK columns become Selects with a list dataSource; scalar columns are added too.
    assert fields.get("memberId") == "Select"
    assert fields.get("classId") == "Select"
    assert "status" in fields and "bookedAt" in fields


# --- FK-typed Input → Select upgrade (the uuid:"M" crash) -----------------------

def _ats_registry(tmp_path):
    """Recruitment-ATS-shaped registry: Application has uuid FKs candidateId,
    recruitmentDriveId, shortlistedById (the last is a person-role FK to User)."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Application": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "candidateId": {"type": "uuid", "nullable": True},
                "recruitmentDriveId": {"type": "uuid", "nullable": True},
                "shortlistedById": {"type": "uuid", "nullable": True},
                "status": {"type": "varchar", "nullable": True},
            }},
            "Candidate": {"fields": {"id": {"type": "uuid"}, "email": {"type": "varchar"}}},
            "RecruitmentDrive": {"fields": {"id": {"type": "uuid"}, "title": {"type": "varchar"}}},
            "User": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
        "relations": [
            {"from_entity": "Application", "to_entity": "Candidate", "type": "many-to-one"},
            {"from_entity": "Application", "to_entity": "RecruitmentDrive", "type": "many-to-one"},
            {"from_entity": "Application", "to_entity": "User", "type": "many-to-one"},
        ],
    }), encoding="utf-8")


def test_fk_target_shortlistedby_resolves_to_user():
    # shortlistedById / interviewedById are person-role FKs → the User entity, even
    # though Application has three relations (so the single-relation heuristic can't fire).
    rels = [{"from_entity": "Application", "to_entity": "Candidate", "type": "many-to-one"},
            {"from_entity": "Application", "to_entity": "RecruitmentDrive", "type": "many-to-one"},
            {"from_entity": "Application", "to_entity": "User", "type": "many-to-one"}]
    ents = {"Candidate": {}, "RecruitmentDrive": {}, "User": {"fields": {"id": {}, "name": {}}}}
    assert _fk_target("application", "shortlistedbyid", rels, ents) == "User"


def test_repair_upgrades_fk_input_to_select(tmp_path):
    # The bug: the LLM rendered the uuid FK shortlistedById as a plain text Input,
    # so a user could type "M" → PostgresError invalid uuid. repair must upgrade it
    # to a Select bound to the users list.
    _ats_registry(tmp_path)
    sdir = tmp_path / "src" / "schemas" / "applications"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/applications/new",
        "root": {"type": "Form", "props": {"workflow": "CreateApplication"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Select", "props": {"name": "candidateId", "label": "Candidate",
                    "optionsFrom": {"source": "candidates", "value": "id", "label": "email"}}},
                {"type": "Input", "props": {"name": "shortlistedById", "label": "Shortlisted By"}},
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
            ]},
        ]},
    }), encoding="utf-8")

    res = repair_fk_dropdowns(str(tmp_path))
    assert res["repaired"] >= 1

    doc = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    nodes = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                nodes[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(doc)
    # shortlistedById upgraded to a Select bound to the User list.
    sb = nodes["shortlistedById"]
    assert sb["type"] == "Select"
    assert sb["props"]["optionsFrom"]["source"] == "users"
    assert sb["props"]["optionsFrom"]["value"] == "id"
    # a list dataSource for users was added
    assert any(d.get("entity") == "User" and d.get("name") == "users"
               for d in doc.get("dataSources", []))
    # non-FK Input (status) is left alone; the existing FK Select is untouched.
    assert nodes["status"]["type"] == "Input"
    assert nodes["candidateId"]["type"] == "Select"


def test_repair_skips_hidden_preset_fk_input(tmp_path):
    # A hidden FK carrying a bound id (defaultValue) must NOT become a visible Select.
    _ats_registry(tmp_path)
    sdir = tmp_path / "src" / "schemas" / "applications"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/applications/new",
        "root": {"type": "Form", "props": {"workflow": "CreateApplication"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "candidateId", "type": "hidden",
                                            "defaultValue": "{{candidate.id}}"}},
            ]},
        ]},
    }), encoding="utf-8")
    res = repair_fk_dropdowns(str(tmp_path))
    doc = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    node = doc["root"]["children"][0]["children"][0]
    assert node["type"] == "Input"     # untouched
    assert res["repaired"] == 0


def test_ensure_required_markers_stamps_notnull_fields(tmp_path):
    # An LLM create form of plain Inputs with no required markers. Fields backing a
    # NOT-NULL column (title) must gain validators.required (the `*`); a nullable
    # column (notes) and a NOT-NULL-with-default column (must be left alone) do not.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Widget": {"fields": {
                "id": {"type": "uuid", "primaryKey": True, "nullable": False},
                "title": {"type": "varchar", "nullable": False},
                "quantity": {"type": "integer", "nullable": False, "hasDefault": True},
                "notes": {"type": "text", "nullable": True},
                "createdAt": {"type": "timestamp", "nullable": False, "hasDefault": True},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "widgets"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/widgets/new",
        "root": {"type": "Form", "props": {"workflow": "CreateWidget"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "title", "label": "Title"}},
                {"type": "NumberInput", "props": {"name": "quantity", "label": "Quantity"}},
                {"type": "Textarea", "props": {"name": "notes", "label": "Notes"}},
            ]},
        ]},
    }), encoding="utf-8")

    res = ensure_required_markers(str(tmp_path))
    assert res["marked"] == 1

    doc = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    nodes = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                nodes[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(doc)
    assert nodes["title"]["props"]["validators"]["required"] is True
    # nullable + defaulted NOT-NULL fields untouched.
    assert "validators" not in nodes["quantity"]["props"]
    assert "validators" not in nodes["notes"]["props"]

    # Idempotent: a second pass marks nothing more.
    assert ensure_required_markers(str(tmp_path))["marked"] == 0


def test_ensure_required_markers_skips_system_and_hidden(tmp_path):
    # System/owner/PK and hidden preset fields must never gain a required marker.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Widget": {"fields": {
                "id": {"type": "uuid", "primaryKey": True, "nullable": False},
                "ownerId": {"type": "uuid", "nullable": False},
                "candidateId": {"type": "uuid", "nullable": False},
                "createdAt": {"type": "timestamp", "nullable": False},
                "name": {"type": "varchar", "nullable": False},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "widgets"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/widgets/new",
        "root": {"type": "Form", "props": {"workflow": "CreateWidget"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "ownerId", "type": "hidden",
                                            "defaultValue": "{{user.id}}"}},
                {"type": "Input", "props": {"name": "candidateId", "type": "hidden"}},
                {"type": "Input", "props": {"name": "name", "label": "Name"}},
            ]},
        ]},
    }), encoding="utf-8")
    res = ensure_required_markers(str(tmp_path))
    assert res["marked"] == 1  # only `name`
    doc = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    nodes = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                nodes[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(doc)
    assert nodes["name"]["props"]["validators"]["required"] is True
    assert "validators" not in nodes["ownerId"]["props"]      # owner FK skipped
    assert "validators" not in nodes["candidateId"]["props"]  # hidden preset skipped


def test_ensure_required_markers_ignores_non_form_pages(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"Widget": {"fields": {"name": {"type": "varchar", "nullable": False}}}},
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    (sdir / "widgets.json").write_text(json.dumps({
        "route": "/widgets",
        "root": {"type": "Stack", "children": [
            {"type": "Input", "props": {"name": "name", "label": "Search"}},
        ]},
    }), encoding="utf-8")
    assert ensure_required_markers(str(tmp_path))["marked"] == 0


def test_ensure_required_markers_missing_dir_safe(tmp_path):
    assert ensure_required_markers(str(tmp_path)) == {"marked": 0, "files": 0}


def test_ensure_required_markers_deterministic_fallback_all_nullable(tmp_path):
    # The 98tuyun7 case: the planner marked NOTHING required, so every registry
    # column is nullable:true. The notNull path marks 0 fields; the deterministic
    # structural fallback must still mark the FK (customerId), the scheduling date
    # (startDate) and the status column — but NOT the optional `notes` free text.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Booking": {"fields": {
                "id": {"type": "uuid", "primaryKey": True, "nullable": True},
                "customerId": {"type": "uuid", "nullable": True},
                "startDate": {"type": "date", "nullable": True},
                "status": {"type": "varchar", "nullable": True},
                "notes": {"type": "text", "nullable": True},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "bookings"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/bookings/new",
        "root": {"type": "Form", "props": {"workflow": "CreateBooking"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Select", "props": {"name": "customerId", "label": "Customer"}},
                {"type": "DatePicker", "props": {"name": "startDate", "label": "Start Date"}},
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
                {"type": "Textarea", "props": {"name": "notes", "label": "Notes"}},
            ]},
        ]},
    }), encoding="utf-8")

    res = ensure_required_markers(str(tmp_path))
    # customerId, startDate, status marked; notes left alone.
    assert res["marked"] == 3

    doc = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    nodes = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                nodes[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(doc)
    assert nodes["customerId"]["props"]["validators"]["required"] is True
    assert nodes["startDate"]["props"]["validators"]["required"] is True
    assert nodes["status"]["props"]["validators"]["required"] is True
    assert "validators" not in nodes["notes"]["props"]        # optional free text

    # Idempotent: a second pass marks nothing more.
    assert ensure_required_markers(str(tmp_path))["marked"] == 0


def test_ensure_required_markers_fallback_never_overrides_explicit_false(tmp_path):
    # An explicit validators.required=False on an otherwise-core field must survive —
    # the fallback only *adds* markers, never flips an author's opt-out.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Booking": {"fields": {
                "id": {"type": "uuid", "primaryKey": True, "nullable": True},
                "status": {"type": "varchar", "nullable": True},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "bookings"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/bookings/new",
        "root": {"type": "Form", "props": {"workflow": "CreateBooking"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "status", "label": "Status",
                                            "validators": {"required": False}}},
            ]},
        ]},
    }), encoding="utf-8")
    # required is already present (False) — the pass leaves it untouched.
    res = ensure_required_markers(str(tmp_path))
    doc = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    node = doc["root"]["children"][0]["children"][0]
    assert node["props"]["validators"]["required"] is False
    assert res["marked"] == 0  # explicit opt-out preserved, nothing marked


def test_infer_required_unit_matrix():
    # Direct unit checks of the deterministic heuristic (all columns nullable-silent).
    assert _infer_required("customerId", {"type": "uuid", "nullable": True}) is True   # FK
    assert _infer_required("startDate", {"type": "date", "nullable": True}) is True    # date
    assert _infer_required("status", {"type": "varchar", "nullable": True}) is True    # status name
    assert _infer_required("name", {"type": "varchar", "nullable": True}) is True      # identity
    assert _infer_required("notes", {"type": "text", "nullable": True}) is False       # optional text
    assert _infer_required("description", {"type": "text", "nullable": True}) is False # optional text
    assert _infer_required("address", {"type": "varchar", "nullable": True}) is False  # generic free text
    assert _infer_required("isActive", {"type": "boolean", "nullable": True}) is False # bool flag
    assert _infer_required("id", {"type": "uuid", "primaryKey": True}) is False        # PK
    assert _infer_required("ownerId", {"type": "uuid", "nullable": True}) is False     # owner FK
    assert _infer_required("createdAt", {"type": "timestamp", "nullable": True}) is False  # lifecycle
    # DB-defaulted column is never user-required, even if core-named.
    assert _infer_required("status", {"type": "varchar", "hasDefault": True}) is False


def test_repair_leaves_fk_input_on_nonform_page(tmp_path):
    # A list/filter page's text field named like a FK must not be converted.
    _ats_registry(tmp_path)
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    (sdir / "applications.json").write_text(json.dumps({
        "route": "/applications",
        "root": {"type": "Stack", "children": [
            {"type": "Input", "props": {"name": "candidateId", "label": "Filter by candidate"}},
        ]},
    }), encoding="utf-8")
    res = repair_fk_dropdowns(str(tmp_path))
    doc = json.loads((sdir / "applications.json").read_text(encoding="utf-8"))
    assert doc["root"]["children"][0]["type"] == "Input"
    assert res["repaired"] == 0


# --- enum-select upgrade (status/stage free-text Input → Select) ------------------
from services.form_scaffold import ensure_enum_selects


def _nodes_by_name(doc):
    nodes = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                nodes[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(doc)
    return nodes


def test_ensure_enum_selects_upgrades_status_input(tmp_path):
    # An LLM create form of plain Inputs. A `status` box (no enum_values, no workflow
    # literals) is upgraded to a curated Select; open-ended fields (nationality, notes)
    # and the FK column (candidateId) are left alone.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Application": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "status": {"type": "varchar", "nullable": False},
                "nationality": {"type": "varchar", "nullable": True},
                "notes": {"type": "text", "nullable": True},
                "candidateId": {"type": "uuid", "nullable": True},
            }},
            "Candidate": {"fields": {"id": {"type": "uuid"}, "email": {"type": "varchar"}}},
        },
        "relations": [{"from_entity": "Application", "to_entity": "Candidate", "type": "many-to-one"}],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "applications"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/applications/new",
        "root": {"type": "Form", "props": {"workflow": "CreateApplication"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
                {"type": "Input", "props": {"name": "nationality", "label": "Nationality"}},
                {"type": "Input", "props": {"name": "notes", "label": "Notes"}},
                {"type": "Input", "props": {"name": "candidateId", "label": "Candidate"}},
            ]},
        ]},
    }), encoding="utf-8")

    res = ensure_enum_selects(str(tmp_path))
    assert res["converted"] == 1

    nodes = _nodes_by_name(json.loads((sdir / "new.json").read_text(encoding="utf-8")))
    assert nodes["status"]["type"] == "Select"
    assert {o["value"] for o in nodes["status"]["props"]["options"]} >= {"Active", "Pending"}
    assert nodes["nationality"]["type"] == "Input"   # open-ended → untouched
    assert nodes["notes"]["type"] == "Input"          # open-ended → untouched
    assert nodes["candidateId"]["type"] == "Input"    # FK → left for repair_fk_dropdowns

    # idempotent — a second pass finds the Select already in place.
    assert ensure_enum_selects(str(tmp_path))["converted"] == 0


def test_ensure_enum_selects_prefers_registry_enum(tmp_path):
    # Declared enum_values win over the curated fallback.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Ticket": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "status": {"type": "varchar", "enum_values": ["Open", "Resolved", "Closed"]},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "tickets"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/tickets/new",
        "root": {"type": "Form", "props": {"workflow": "CreateTicket"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
            ]},
        ]},
    }), encoding="utf-8")

    assert ensure_enum_selects(str(tmp_path))["converted"] == 1
    nodes = _nodes_by_name(json.loads((sdir / "new.json").read_text(encoding="utf-8")))
    assert nodes["status"]["type"] == "Select"
    assert {o["value"] for o in nodes["status"]["props"]["options"]} == {"Open", "Resolved", "Closed"}


def test_ensure_enum_selects_missing_dir_safe(tmp_path):
    assert ensure_enum_selects(str(tmp_path)) == {"converted": 0, "files": 0}


def test_ensure_enum_selects_labels_use_title_case_for_flat_keys(tmp_path):
    """Spec B1: when the plan emits flat `[str]` enum keys, each label is
    Title-Cased (`in_progress` → `In Progress`). Users never see raw keys."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Ticket": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "status": {"type": "varchar", "enum_values": ["open", "in_progress", "closed"]},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "tickets"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/tickets/new",
        "root": {"type": "Form", "props": {"workflow": "CreateTicket"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
            ]},
        ]},
    }), encoding="utf-8")

    assert ensure_enum_selects(str(tmp_path))["converted"] == 1
    nodes = _nodes_by_name(json.loads((sdir / "new.json").read_text(encoding="utf-8")))
    opts = nodes["status"]["props"]["options"]
    assert opts == [
        {"value": "open", "label": "Open"},
        {"value": "in_progress", "label": "In Progress"},
        {"value": "closed", "label": "Closed"},
    ]


def test_ensure_enum_selects_labels_from_plan_authored_object_shape(tmp_path):
    """Spec B1: when the plan emits `[{key,label}]` object shape, planner-
    authored labels win verbatim (e.g. `ACH Transfer`, not `Ach`)."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Payment": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "method": {"type": "varchar"},
            }},
        },
    }), encoding="utf-8")
    # Plan authoring — this is where the LLM emits labels.
    plan_dir = tmp_path / "src" / "contracts"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps({
        "entities": {"Payment": {"fields": [
            {"name": "method", "enum_values": [
                {"key": "ach", "label": "ACH Transfer"},
                {"key": "cash", "label": "Cash"},
                {"key": "credit_card", "label": "Credit Card"},
            ]},
        ]}},
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "payments"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/payments/new",
        "root": {"type": "Form", "props": {"workflow": "CreatePayment"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "method", "label": "Method"}},
            ]},
        ]},
    }), encoding="utf-8")

    assert ensure_enum_selects(str(tmp_path))["converted"] == 1
    nodes = _nodes_by_name(json.loads((sdir / "new.json").read_text(encoding="utf-8")))
    assert nodes["method"]["props"]["options"] == [
        {"value": "ach", "label": "ACH Transfer"},
        {"value": "cash", "label": "Cash"},
        {"value": "credit_card", "label": "Credit Card"},
    ]


def test_ensure_enum_selects_plan_wins_over_workflow_harvest(tmp_path):
    """Bug 2 cure — the CAUSE of the polluted Status dropdown.

    When the plan declares `entities[].fields[].enum_values`, the enum
    harvester's other sources (workflow strings, entity-name inference,
    curated dictionary) are BYPASSED entirely for that column. Only the
    plan's list ships. Every other spelling of the same statuses in the
    surrounding workflows or humanized aliases in memory MUST NOT leak."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Application": {"fields": {
                "id":     {"type": "uuid", "primaryKey": True},
                "status": {"type": "varchar"},   # no registry enum on purpose
            }},
        },
    }), encoding="utf-8")
    # Plan says these are the ONLY 3 valid statuses.
    contracts = tmp_path / "src" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "plan.json").write_text(json.dumps({
        "entities": {
            "Application": {"fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "status", "type": "varchar",
                 "enum_values": ["open", "shortlisted", "rejected"]},
            ]},
        },
    }), encoding="utf-8")
    # Workflow set-nodes reference OTHER strings — which the harvester would
    # merge in without the plan authority. They MUST NOT leak into the form.
    wdir = tmp_path / "workflows"
    wdir.mkdir()
    (wdir / "shortlist.json").write_text(json.dumps({
        "id": "shortlist",
        "nodes": [
            {"id": "set", "type": "action", "config": {
                "actionType": "db_update", "table": "applications",
                "fields": ["status"],
                "values": {"status": "interview_scheduled"},
            }},
        ],
    }), encoding="utf-8")
    # Create form with a plain Status input.
    sdir = tmp_path / "src" / "schemas" / "applications"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/applications/new",
        "root": {"type": "Form", "props": {"workflow": "CreateApplication"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
            ]},
        ]},
    }), encoding="utf-8")

    # Invalidate any lookup cache from prior tests so this run picks up the
    # freshly-written plan.json under `tmp_path` (the module-level cache is
    # keyed by mtime but the path is unique per pytest tmp_path so this is
    # already correct; kept explicit for readability).
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    ensure_enum_selects(str(tmp_path))

    nodes = _nodes_by_name(json.loads((sdir / "new.json").read_text(encoding="utf-8")))
    assert nodes["status"]["type"] == "Select"
    got = [o["value"] for o in nodes["status"]["props"]["options"]]
    # Exactly the plan's list, in the plan's order. No workflow strings.
    assert got == ["open", "shortlisted", "rejected"]
    # Explicitly: the workflow's other status must NOT have leaked in.
    assert "interview_scheduled" not in got


def test_ensure_enum_selects_falls_through_when_plan_silent(tmp_path):
    """When the plan doesn't declare enum_values, existing behavior stands.

    Backward compat: legacy generations that predate the complete-plan-schema
    still get their Status selects populated from registry / workflow / curated
    sources. The plan authority is opt-in per field."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Ticket": {"fields": {
                "id":     {"type": "uuid", "primaryKey": True},
                "status": {"type": "varchar",
                           "enum_values": ["Open", "Resolved"]},
            }},
        },
    }), encoding="utf-8")
    # plan.json exists but has NO enum_values for status — silent for this field.
    contracts = tmp_path / "src" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "plan.json").write_text(json.dumps({
        "entities": {
            "Ticket": {"fields": [
                {"name": "id",     "type": "uuid", "primaryKey": True},
                {"name": "status", "type": "varchar"},   # no enum_values
            ]},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "tickets"
    sdir.mkdir(parents=True)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/tickets/new",
        "root": {"type": "Form", "props": {"workflow": "CreateTicket"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "status", "label": "Status"}},
            ]},
        ]},
    }), encoding="utf-8")
    from services.plan_field_lookup import _CACHE
    _CACHE.clear()

    ensure_enum_selects(str(tmp_path))

    nodes = _nodes_by_name(json.loads((sdir / "new.json").read_text(encoding="utf-8")))
    assert nodes["status"]["type"] == "Select"
    got = {o["value"] for o in nodes["status"]["props"]["options"]}
    # Registry enum_values (the pre-existing #1 priority) still wins.
    assert got == {"Open", "Resolved"}
