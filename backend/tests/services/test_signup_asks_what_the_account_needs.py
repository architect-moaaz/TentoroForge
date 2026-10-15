"""Registration works for every application out of the box: the scaffold
signup form asks the account entity's own fields, the name typed at signup
is the person's name on their record, a value the application starts with
counts as supplied, and a required field a process owns starts with a
value of its kind. Personal Finance's tester could not create an account
at all — "Display name is required" with the Name box filled (2026-10-15)."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import account_model as am

FOUNDATION = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src"


def test_the_scaffold_signup_form_asks_the_accounts_fields_and_sends_them():
    page = (FOUNDATION / "app" / "signup" / "page.tsx").read_text()
    assert 'import { ACCOUNT, type AccountField } from "@/lib/account";' in page
    assert "ACCOUNT_FIELDS.map((f) => (" in page and "<AccountFieldInput" in page
    # Sent as `account`, in both shapes of the body; an email field is the login's.
    assert "{ name, email, password, accountType, account }" in page and "{ name, email, password, account }" in page
    assert 'f.kind !== "email" && !nameLike(f.name)' in page
    # The route's reason reaches the person, not "[object Object]".
    assert "j?.error?.message" in page


def test_the_route_takes_the_typed_name_as_the_display_name_and_honours_initial_values():
    route = (FOUNDATION / "app" / "api" / "auth" / "signup" / "route.ts").read_text()
    assert "accountValues(data.account ?? {}, data.email, data.name)" in route
    assert "ACCOUNT.labelField === f.name || NAME_LIKE.test(f.name)" in route
    assert 'Object.prototype.hasOwnProperty.call(ACCOUNT_INITIAL, f.name)) continue;' in route


def _doc(fields: list[dict], writes: list[dict] | None = None) -> dict:
    return {
        "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Consumer"}],
        "security": {"authentication": "email_password"},
        "data": {"entities": [{"id": "ENTITY-001", "name": "User", "table": "users", "account": True, "fields": [
            {"name": "id", "type": "uuid", "required": True, "primaryKey": True},
            {"name": "email", "type": "string", "required": True}, *fields]}]},
        "workflows": writes or [],
    }


def test_a_required_field_a_process_owns_starts_with_a_value_of_its_kind():
    fields = [{"name": "displayName", "type": "string", "required": True},
              {"name": "currency", "type": "string", "required": True},
              {"name": "budgetStartDate", "type": "integer", "required": True},
              {"name": "onboardingCompleted", "type": "boolean", "required": True},
              {"name": "kycStatus", "type": "enum", "enumValues": ["pending", "verified"], "required": True}]
    # Onboarding sets currency, the start date and the flag; a review sets the status.
    writes = [{"id": "FLOW-001", "name": "Complete Onboarding Setup", "steps": [
                  {"key": "save", "type": "action", "entity": "ENTITY-001",
                   "config": {"actionType": "db_update",
                              "values": {"currency": "INR", "budgetStartDate": 1, "onboardingCompleted": True}}}]},
              {"id": "FLOW-002", "name": "Verify", "steps": [
                  {"key": "ok", "type": "action", "entity": "ENTITY-001",
                   "config": {"actionType": "db_update", "values": {"kycStatus": "verified"}}}]}]
    doc = _doc(fields, writes)
    initial = am.account_initial(doc)
    typed = {f["name"] for f in am.account_fields(doc)}
    # What the person types is asked, not seeded; what a process owns is seeded by kind.
    assert "displayName" in typed
    for name in ("currency", "budgetStartDate", "onboardingCompleted", "kycStatus"):
        assert name not in typed, name
    assert initial["currency"] == "" and initial["budgetStartDate"] == 0 and initial["onboardingCompleted"] is False
    assert initial["kycStatus"] == "pending"
    assert "displayName" not in initial
