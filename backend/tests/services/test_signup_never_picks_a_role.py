"""A person signing up never picks their own role: the account record's copy of it is the login's (kkb5mzo3, 2026-11-23)."""
from services.blueprint.account_model import account_fields, account_initial, role_field


def _doc(signup=True):
    roles = [{"id": "ROLE-1", "name": "Requester"}, {"id": "ROLE-2", "name": "Manager"}, {"id": "ROLE-3", "name": "Administrator"}]
    return {
        "roles": roles,
        "security": {"signupRole": "ROLE-1"} if signup else {},
        "data": {"entities": [{"id": "ENTITY-1", "name": "Staff", "account": True, "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True, "required": True},
            {"name": "fullName", "type": "text", "required": True},
            {"name": "role", "type": "enum", "required": True, "enumValues": ["Requester", "Manager", "Administrator"]},
            {"name": "shift", "type": "enum", "required": False, "enumValues": ["early", "late"]},
        ]}]},
        "workflows": [],
    }


def test_the_role_is_not_asked_and_starts_as_the_signup_role():
    doc = _doc()
    assert role_field(doc) == "role"
    names = [f["name"] for f in account_fields(doc)]
    assert "role" not in names and "shift" in names
    assert account_initial(doc)["role"] == "Requester"


def test_without_a_signup_role_the_role_is_still_asked():
    doc = _doc(signup=False)
    assert "role" in [f["name"] for f in account_fields(doc)]
