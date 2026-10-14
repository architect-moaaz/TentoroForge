"""A workspace scope is refused unless it says where the actor's workspace
comes from or the application declares organisations; a tenancy is refused
without a tenant entity, with a role on both sides, or with an admin who is
not a member (2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (AgentResult, ArtifactProposal, InvalidOwnershipRule, InvalidTenancy,
                                               check_security, check_tenancy)

ROLES = [{"id": "ROLE-001", "name": "Nurse"}, {"id": "ROLE-002", "name": "Platform Admin"}]
ENTS = [{"id": "ENTITY-001", "name": "Clinic", "table": "clinics", "tenant": True, "fields": [{"name": "name", "type": "string"}]},
        {"id": "ENTITY-002", "name": "Patient", "table": "patients", "fields": [{"name": "clinicId", "type": "uuid", "references": "ENTITY-001"}]},
        {"id": "ENTITY-003", "name": "Staff", "table": "users", "account": True, "fields": [{"name": "homeClinicId", "type": "uuid"}]}]


def _security(body: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="security", proposals=[ArtifactProposal(section="security", natural_key="security", body=body)])


def test_a_workspace_scope_needs_an_actor_column_or_organisations():
    doc = {"roles": ROLES, "data": {"entities": ENTS}, "security": {}}
    with pytest.raises(InvalidOwnershipRule, match="where the actor's"):
        check_security(_security({"ownershipRules": [{"entity": "Patient", "column": "clinicId", "kind": "scope", "scope": "workspace"}]}), doc)
    check_security(_security({"ownershipRules": [{"entity": "Patient", "column": "clinicId", "kind": "scope", "scope": "workspace", "actorColumn": "homeClinicId"}]}), doc)
    with pytest.raises(InvalidOwnershipRule, match="not a field of the login entity"):
        check_security(_security({"ownershipRules": [{"entity": "Patient", "column": "clinicId", "kind": "scope", "scope": "workspace", "actorColumn": "nowhere"}]}), doc)
    with_orgs = {**doc, "security": {"tenancy": {"kind": "organisation"}}}
    check_security(_security({"ownershipRules": [{"entity": "Patient", "column": "clinicId", "kind": "scope", "scope": "workspace"}]}), with_orgs)


def test_a_tenancy_names_a_tenant_and_splits_the_roles():
    doc = {"roles": ROLES, "data": {"entities": ENTS}}
    check_tenancy(_security({"tenancy": {"kind": "organisation", "memberRoles": ["ROLE-001"], "platformRoles": ["ROLE-002"], "organisationAdminRole": "ROLE-001"}}), doc)
    with pytest.raises(InvalidTenancy, match="needs an entity marked"):
        check_tenancy(_security({"tenancy": {"kind": "organisation", "memberRoles": ["ROLE-001"]}}), {"roles": ROLES, "data": {"entities": []}})
    with pytest.raises(InvalidTenancy, match="never both"):
        check_tenancy(_security({"tenancy": {"kind": "organisation", "memberRoles": ["ROLE-001"], "platformRoles": ["ROLE-001"]}}), doc)
    with pytest.raises(InvalidTenancy, match="not one of the member roles"):
        check_tenancy(_security({"tenancy": {"kind": "organisation", "memberRoles": ["ROLE-001"], "organisationAdminRole": "ROLE-002"}}), doc)
    with pytest.raises(InvalidTenancy, match="only ONE entity"):
        check_tenancy(AgentResult(task_id="T", agent="data_model", proposals=[
            ArtifactProposal(section="data.entities", natural_key="Company", body={"name": "Company", "tenant": True})]), doc)
