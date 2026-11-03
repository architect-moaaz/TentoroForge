"""DITANS QA, 2026-11-02 (D-59, D-60, D-65, D-67, D-70, D-71): a brand-new
employer's Home listed seven tasks, offers awaiting approval and a teammate of
another organisation; a new agency saw seven clients and six job orders.

DITANS keeps membership as a record of its own — OrganisationMember
(organisationId, email) — and the users row carries no organisation, so no
rule could say "my organisation's rows". Its 30 rules were all per person, and
a page that found no membership for the person fell back to every row.

`scope: "member"` says it: the row's `column` must be an organisation the
actor has a `members` row in, matched on their email (or id). The engine half
is proven by run-ownership-tests.sh; this covers the contract, the manifest
and the seal.
"""
from services.blueprint.agent_contract import ownership_findings
from services.blueprint.projection import _sealed_fields, ownership_rules

DOC = {"data": {"entities": [
    {"id": "ENTITY-001", "name": "OrganisationMember", "table": "organisation_members",
     "fields": [{"name": "id"}, {"name": "organisationId"}, {"name": "email"}, {"name": "fullName"}]},
    {"id": "ENTITY-002", "name": "Job", "table": "jobs",
     "fields": [{"name": "id"}, {"name": "organisationId"}, {"name": "title"}]},
]}}

RULE = {"entity": "Job", "column": "organisationId", "kind": "scope", "scope": "member",
        "members": "OrganisationMember", "memberColumn": "organisationId", "memberEmailColumn": "email",
        "unscopedRoles": ["Candidate"]}


def test_the_manifest_names_the_membership_table_and_its_columns():
    rules = ownership_rules({**DOC, "security": {"ownershipRules": [RULE]}})
    rule = rules["job"][0]
    assert rule["scope"] == "member"
    assert rule["members"] == "organisation_members", "written as the table, like `through`"
    assert (rule["memberColumn"], rule["memberEmailColumn"]) == ("organisationId", "email")
    assert "memberUserColumn" not in rule


def test_a_member_rule_says_where_membership_is_kept():
    assert ownership_findings({"ownershipRules": [RULE]}, DOC) == []
    found = ownership_findings({"ownershipRules": [{**RULE, "members": "Membership"}]}, DOC)
    assert len(found) == 1 and "'Membership' is not one the data model has" in found[0]
    found = ownership_findings({"ownershipRules": [{**RULE, "memberColumn": "orgId"}]}, DOC)
    assert len(found) == 1 and "`memberColumn`" in found[0]
    found = ownership_findings({"ownershipRules": [{**RULE, "memberEmailColumn": None}]}, DOC)
    assert len(found) == 1 and "`memberEmailColumn`" in found[0]


def test_the_email_members_are_found_by_is_never_sealed():
    """Sealed with a fresh nonce, the email would match no one and every
    member would reach nothing."""
    member = {**DOC["data"]["entities"][0], "fields": [
        {"name": "id"}, {"name": "organisationId"},
        {"name": "email", "mask": "partial"}, {"name": "phone", "mask": "partial"}]}
    doc = {"data": {"entities": [member, DOC["data"]["entities"][1]]}}
    assert {"email", "phone"} <= _sealed_fields(member, doc), "without the rule both are sealed"
    doc["security"] = {"ownershipRules": [RULE]}
    sealed = _sealed_fields(member, doc)
    assert "email" not in sealed and "phone" in sealed


def test_a_public_board_reaches_visitors_and_scopes_members():
    """DITANS's job board is browsed signed out; scoped to members alone it
    listed no job (2026-11-03). `reads: "visitors"` is carried to the engine."""
    rules = ownership_rules({**DOC, "security": {"ownershipRules": [{**RULE, "reads": "visitors"}]}})
    assert rules["job"][0]["reads"] == "visitors"
    rules = ownership_rules({**DOC, "security": {"ownershipRules": [{**RULE, "reads": "scoped"}]}})
    assert "reads" not in rules["job"][0]
