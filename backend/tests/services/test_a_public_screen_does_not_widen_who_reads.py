"""A public screen opens to visitors only the record types access lets them
read. 60v142ju's public intake form and confirmation screen made every
submission readable signed out, while access granted reading to three staff
roles only (2026-10-12)."""
from __future__ import annotations

from services.blueprint.projection import anonymous_may_read, entity_access, public_apis

ROLES = [{"id": "ROLE-001", "name": "Officer", "permissions": ["PERM-2"]}]
SUB = {"id": "ENTITY-001", "name": "Submission", "table": "submissions"}
DOC = {"roles": ROLES, "permissions": [{"id": "PERM-2", "action": "read", "subject": "ENTITY-001"}],
       "data": {"entities": [SUB]},
       "workflows": [{"id": "FLOW-001", "launchedFrom": ["PAGE-001"]}],
       "pages": [{"id": "PAGE-001", "route": "/", "access": "public", "pattern": "form", "data": {"primaryEntity": "ENTITY-001"}}]}


def test_declared_staff_readers_keep_visitors_out():
    assert not anonymous_may_read(DOC, SUB)
    assert public_apis(DOC) == ["api/workflows/FLOW-001"], "the form's process stays open; its records do not"
    assert "*" not in entity_access(DOC)["submissions"]["read"]


def test_what_access_opens_to_visitors_stays_open():
    for rule in ({"entity": "Submission", "kind": "scope", "column": "x", "reads": "everyone"},
                 {"entity": "Submission", "kind": "scope", "column": "x", "guestColumn": "guestToken"}):
        doc = {**DOC, "security": {"ownershipRules": [rule]}}
        assert anonymous_may_read(doc, SUB) and "api/data/submissions" in public_apis(doc)
    undeclared = {**DOC, "permissions": []}
    assert anonymous_may_read(undeclared, SUB), "no read permission declared: as before"
