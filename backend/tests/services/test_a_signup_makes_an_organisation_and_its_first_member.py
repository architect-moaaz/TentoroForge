"""Signing up may start an organisation; an invite joins one in its role;
switching is only into one's own; the seed makes two organisations so the
scope can be proven; Smith adds organisations and moves logins
(2026-10-12)."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import tenancy_trials as tt
from services.blueprint.service import BlueprintService
from services.smith import accounts, tenancy_change

ROOT = Path(__file__).resolve().parents[2]
DOC = {
    "roles": [{"id": "ROLE-001", "name": "Nurse"}, {"id": "ROLE-002", "name": "Clinic Manager"}],
    "security": {"tenancy": {"kind": "organisation", "memberRoles": ["ROLE-001", "ROLE-002"], "organisationAdminRole": "ROLE-002", "signup": "both"}},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Clinic", "table": "clinics", "tenant": True, "labelField": "name", "fields": [{"name": "name", "type": "string"}]}]},
}


def test_the_runtime_ships_signup_invites_switching_and_two_seeded_organisations():
    signup = (ROOT / "templates/app-foundation/src/app/api/auth/signup/route.ts").read_text()
    assert "tenancy.createOrganisation(orgName)" in signup and "tenancy.setActive(" in signup
    setpw = (ROOT / "templates/runtime/api-auth-set-password/route.ts").read_text()
    assert "tenancy.join(" in setpw
    invites = (ROOT / "templates/runtime/db/forge-invites.schema.ts").read_text()
    assert 'orgId: text("org_id")' in invites and 'role: text("role")' in invites
    org = (ROOT / "templates/runtime/api-org/route.ts").read_text()
    assert "You do not belong to that organisation." in org
    members = (ROOT / "templates/runtime/api-org/members/route.ts").read_text()
    assert "Only the organisation's administrator invites people." in members and "forge_invites" in members
    seed = (ROOT / "templates/runtime/seed.ts").read_text()
    assert '"Demo organisation", "Second organisation"' in seed and "entry.organisation" in seed
    injector = (ROOT / "services/runtime_injector.py").read_text()
    assert "_forge_memberships.ts" in injector and "org/members/route.ts" in injector and "tenancy-policy.ts" in injector
    layout = (ROOT / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert "<OrgSwitcher />" in layout


def test_the_check_drives_signup_invite_and_switch(monkeypatch):
    state = {"orgs": [["org-1"], ["org-2"]], "active": ""}

    def rows(app, sql):
        if "where \"name\" = 'Check Org" in sql:
            return [["org-new"]]
        if "select m.role from forge_memberships" in sql:
            return [["Nurse"]]
        if "select coalesce(active_org_id, '') from users where email" in sql:
            return [["org-new"]]
        if "from forge_invites where email" in sql:
            return [["org-1", "Clinic Manager"]]
        if "order by 1 limit 2" in sql:
            return state["orgs"]
        if "select u.id::text, u.email from users u join forge_memberships" in sql:
            return [["u-1", "nurse@example.com"]]
        if "select coalesce(active_org_id, '') from users where id::text" in sql:
            return [[state["active"]]]
        return []
    monkeypatch.setattr(tt, "_rows", rows)
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, role, guest=None: (role, [{"role": role}]))
    monkeypatch.setattr("services.preview_session.cookies", lambda s, base_url: [{"sub": s.sub}])

    def call(app, method, path, body, cookies):
        if path == "/api/auth/signup":
            return 201, {"id": "u-new"}
        if path == "/api/org/members":
            return 201, {"ok": True, "invited": True}
        if path == "/api/org":
            if body["orgId"] == "org-2":
                state["active"] = "org-2"
                return 200, {"ok": True}
            return 403, {"error": "You do not belong to that organisation."}
        return 404, {}
    monkeypatch.setattr(tt, "_call", call)
    from types import SimpleNamespace
    out = tt.check_tenancy(SimpleNamespace(base="http://app.test"), DOC)
    assert [g["id"] for g in out["green"]] == ["tenancy::signup", "tenancy::invite", "tenancy::switch", "tenancy::stranger"]
    assert out["red"] == [] and out["untried"] == []
    assert tt.check_tenancy(object(), {"security": {"tenancy": {"kind": "none"}}}) == {"total": 0, "green": [], "red": [], "untried": []}


def test_smith_adds_organisations_and_moves_logins(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Clinics", domain="health")
    svc.doc.update({"roles": DOC["roles"], "security": DOC["security"], "data": DOC["data"]})
    svc.save()
    out = tenancy_change.add_organisation(svc, str(tmp_path), change="add an organisation called Northside Clinic")
    assert out["applied"] and "Northside Clinic" in out["diff_summary"]
    assert accounts.load(tmp_path)["organisations"] == [{"name": "Northside Clinic"}]
    accounts.add(tmp_path, email="dave@clinic.com", role="Nurse")
    out = tenancy_change.move_login(svc, str(tmp_path), change="move dave@clinic.com to Northside Clinic as Nurse")
    assert out["applied"]
    entry = accounts._entry(accounts.load(tmp_path), "dave@clinic.com")
    assert entry["organisation"] == "Northside Clinic" and entry["role"] == "Nurse"
    out = tenancy_change.move_login(svc, str(tmp_path), change="move dave@clinic.com to Northside Clinic as Janitor")
    assert not out["applied"] and "not a member role" in out["reason"]
    single = BlueprintService.create(output_dir=tmp_path / "one", app_id="b", name="One", domain="x")
    out = tenancy_change.add_organisation(single, str(tmp_path / "one"), change="add an organisation called X")
    assert not out["applied"] and out["options"]


def test_the_verbs_are_smiths():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    for v in ("add_organisation", "move_login"):
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM
