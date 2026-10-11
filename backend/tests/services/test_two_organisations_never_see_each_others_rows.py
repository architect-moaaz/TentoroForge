"""An organisation's rows are its own: every entity referencing the tenant
entity is scoped to the person's active organisation, derived from the
data model; platform roles see all; the first-row fallback that put a new
row in someone else's workspace is gone (2026-10-12)."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.projection import ownership_rules, project_tenancy, tenancy_columns, tenancy_policy

ROOT = Path(__file__).resolve().parents[2]
DOC = {
    "roles": [{"id": "ROLE-001", "name": "Nurse"}, {"id": "ROLE-002", "name": "Clinic Manager"}, {"id": "ROLE-003", "name": "Platform Admin"}],
    "security": {"tenancy": {"kind": "organisation", "memberRoles": ["ROLE-001", "ROLE-002"], "platformRoles": ["ROLE-003"],
                             "organisationAdminRole": "ROLE-002", "signup": "both"},
                 "ownershipRules": [{"entity": "Note", "column": "authorId", "kind": "scope", "scope": "user"}]},
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Clinic", "table": "clinics", "tenant": True, "labelField": "name", "fields": [{"name": "name", "type": "string"}]},
        {"id": "ENTITY-002", "name": "Patient", "table": "patients", "fields": [{"name": "clinicId", "type": "uuid", "references": "ENTITY-001"}]},
        {"id": "ENTITY-003", "name": "Note", "table": "notes", "fields": [{"name": "authorId", "type": "uuid"}, {"name": "clinicId", "type": "uuid", "references": "ENTITY-001"}]},
        {"id": "ENTITY-004", "name": "Tariff", "table": "tariffs", "fields": [{"name": "code", "type": "string"}]},
    ]},
}


def test_the_policy_names_the_organisation_and_who_belongs():
    pol = tenancy_policy(DOC)
    assert pol["kind"] == "organisation" and pol["entity"] == "Clinic" and pol["table"] == "clinics" and pol["nameColumn"] == "name"
    assert pol["memberRoles"] == ["Clinic Manager", "Nurse"] and pol["platformRoles"] == ["Platform Admin"] and pol["adminRole"] == "Clinic Manager"
    assert tenancy_columns(DOC)["Patient"] == "clinicId" and tenancy_columns(DOC)["notes"] == "clinicId" and "Tariff" not in tenancy_columns(DOC)
    assert tenancy_policy({})["kind"] == "none"
    assert tenancy_policy({**DOC, "data": {"entities": []}})["kind"] == "none", "no tenant entity, no organisations"


def test_every_record_of_an_organisation_is_scoped_to_it_without_an_authored_rule():
    rules = ownership_rules(DOC)
    patient = rules["patient"]
    assert patient == [{"column": "clinicId", "kind": "scope", "scope": "workspace", "unscopedRoles": ["Platform Admin"], "derived": "tenancy"}]
    note_cols = {r["column"] for r in rules["note"]}
    assert note_cols == {"authorId", "clinicId"}, "the author's own rule stands beside the organisation's"
    assert "tariff" not in rules, "a record type with no organisation is not scoped"


def test_the_runtime_reads_the_active_organisation_and_never_guesses(tmp_path):
    project_tenancy(DOC, tmp_path)
    src = (tmp_path / "src/lib/tenancy-policy.ts").read_text()
    assert '"kind": "organisation"' in src and '"patients": "clinicId"' in src
    engine = (ROOT / "templates/runtime/data-engine.ts").read_text()
    assert 'for (const wsName of ["workspaces"' not in engine, "the first-row fallback is gone"
    assert "belongs to an organisation and you are acting in none" in engine
    assert "user?.activeOrgId ?? user?.workspaceId" in engine
    auth = (ROOT / "templates/app-foundation/src/auth.ts").read_text()
    assert 'trigger === "update"' in auth and "tenancy.resolve(" in auth
    assert 'activeOrgId: text("active_org_id")' in (ROOT / "templates/app-foundation/src/db/schema/user.ts").read_text()
