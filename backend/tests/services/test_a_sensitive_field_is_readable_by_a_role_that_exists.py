"""A sensitive field's readers count only where they name declared roles;
otherwise the record's readers (the access step's read permissions) govern.
The records step runs before roles exist: 60v142ju's personal details named
`AdminUser`, a record type, and no admin could ever see a submitter's name
(2026-10-12)."""
from __future__ import annotations

from services.blueprint.projection import sensitive_columns

ROLES = [{"id": "ROLE-001", "name": "Officer", "permissions": ["PERM-1"]},
         {"id": "ROLE-002", "name": "Supervisor", "permissions": ["PERM-1"]}]
PERMS = [{"id": "PERM-1", "action": "read", "subject": "ENTITY-001"}]


def _doc(readers):
    return {"roles": ROLES, "permissions": PERMS, "data": {"entities": [{"id": "ENTITY-001", "name": "Submission", "table": "submissions",
            "fields": [{"name": "phoneNumber", "sensitive": True, "mask": "phone", **({"readers": readers} if readers is not None else {})}]}]}}


def test_readers_that_name_no_role_fall_back_to_the_records_readers():
    assert sensitive_columns(_doc(["AdminUser"]))["Submission"]["phoneNumber"]["readers"] == ["Officer", "Supervisor"]
    assert sensitive_columns(_doc(None))["Submission"]["phoneNumber"]["readers"] == ["Officer", "Supervisor"]


def test_readers_by_id_or_name_are_honoured_as_names():
    assert sensitive_columns(_doc(["ROLE-002"]))["Submission"]["phoneNumber"]["readers"] == ["Supervisor"]
    assert sensitive_columns(_doc(["Supervisor", "Nobody"]))["Submission"]["phoneNumber"]["readers"] == ["Supervisor"]
