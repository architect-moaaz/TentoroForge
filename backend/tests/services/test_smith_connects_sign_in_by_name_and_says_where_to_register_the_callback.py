"""Smith connects sign-in to Microsoft 365 / Google / Okta / SAML by NAME:
an `auth` row with the three names, a `signIn.sso` entry, the redirect
address to register; changes the ways in; maps a provider's groups to
roles; limits domains — and refuses a change that leaves nobody a way in
(2026-10-12)."""
from __future__ import annotations

from services.blueprint.service import BlueprintService
from services.smith import connect_service, sign_in_change, sign_in_connect


def _svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Ledger", domain="finance")
    s.doc["roles"] = [{"id": "ROLE-001", "name": "Accountant", "status": "APPROVED"}, {"id": "ROLE-002", "name": "Viewer", "status": "APPROVED"}]
    s.save()
    return s


def test_only_a_sentence_about_signing_in_is_the_adapters():
    assert sign_in_connect.service_for("connect it to our Microsoft 365") is None, "mail, not sign-in"
    assert sign_in_connect.service_for("let people sign in with their Microsoft 365 account").provider == "entra"
    assert sign_in_connect.service_for("connect sign-in to Okta over SAML").provider == "saml"
    assert sign_in_connect.service_for("single sign-on through Google").provider == "google"
    assert sign_in_connect.service_for("login with Keycloak (OIDC)").provider == "oidc"
    assert connect_service.ADAPTERS[0] is sign_in_connect and "sign_in" in connect_service.actions()


def test_connect_declares_the_row_the_entry_and_the_names_only(tmp_path):
    svc = _svc(tmp_path)
    out = sign_in_connect.connect(svc, service="let people sign in with Microsoft 365", output_dir=str(tmp_path))
    doc = BlueprintService.load(output_dir=tmp_path).doc
    row = doc["integrations"][0]
    assert row["kind"] == "auth" and row["serves"] == "sign_in" and row["provider"] == "entra"
    assert row["secretRefs"] == ["SSO_ENTRA_ISSUER", "SSO_ENTRA_CLIENT_ID", "SSO_ENTRA_CLIENT_SECRET"]
    entry = doc["security"]["signIn"]["sso"][0]
    assert entry["id"] == "entra" and entry["integration"] == row["id"] and entry["kind"] == "oidc"
    said = sign_in_connect.summarise(out)
    assert "/api/auth/callback/entra" in said and "SSO_ENTRA_CLIENT_ID" in said and "Settings" in said
    # a second Microsoft tenant is its own entry with its own names
    sign_in_connect.connect(svc, service="sign in with Microsoft 365", output_dir=str(tmp_path))
    doc = BlueprintService.load(output_dir=tmp_path).doc
    assert [e["id"] for e in doc["security"]["signIn"]["sso"]] == ["entra", "entra_2"]
    assert "SSO_ENTRA_2_CLIENT_ID" in doc["integrations"][1]["secretRefs"]
    why, options = sign_in_connect.refusal("Facebook", svc.doc)
    assert "Microsoft 365" in why and options


def test_the_contract_check_accepts_a_triple_under_the_entrys_own_id():
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, check_integrations
    check_integrations(AgentResult(task_id="T", agent="integration", proposals=[ArtifactProposal(
        section="integrations", natural_key="Okta sign-in (okta_2)", body={
            "name": "Okta sign-in (okta_2)", "kind": "auth", "provider": "okta", "serves": "sign_in",
            "secretRefs": ["SSO_OKTA_2_ISSUER", "SSO_OKTA_2_CLIENT_ID", "SSO_OKTA_2_CLIENT_SECRET"]})]), {})
    assert sign_in_connect.complete_triples(["SSO_OKTA_2_ISSUER", "SSO_OKTA_2_CLIENT_ID"]) == []


def test_the_ways_in_change_but_never_to_none(tmp_path):
    svc = _svc(tmp_path)
    out = sign_in_change.set_sign_in_method(svc, str(tmp_path), change="turn passwords off")
    assert not out["applied"] and "nobody could sign in" in out["reason"]
    out = sign_in_change.set_sign_in_method(svc, str(tmp_path), change="sign in by magic link only")
    si = BlueprintService.load(output_dir=tmp_path).doc["security"]["signIn"]
    assert out["applied"] and si["password"] is False and si["magicLink"] is True and "no sign-up page" in out["diff_summary"]
    out = sign_in_change.set_sign_in_method(svc, str(tmp_path), change="passwords only")
    si = BlueprintService.load(output_dir=tmp_path).doc["security"]["signIn"]
    assert out["applied"] and si["password"] is True and si["magicLink"] is False
    assert not sign_in_change.set_sign_in_method(svc, str(tmp_path), change="make it nicer")["applied"]


def test_groups_become_roles_and_domains_limit_who_may_sign_in(tmp_path):
    svc = _svc(tmp_path)
    out = sign_in_change.map_sso_roles(svc, str(tmp_path), change="people in the Finance group are Accountants")
    assert not out["applied"] and "connect sign-in" in out["reason"].lower()
    sign_in_connect.connect(svc, service="sign in with Okta", output_dir=str(tmp_path))
    out = sign_in_change.map_sso_roles(svc, str(tmp_path), change="people in the Finance group are Accountants, everyone else is a Viewer")
    entry = BlueprintService.load(output_dir=tmp_path).doc["security"]["signIn"]["sso"][0]
    assert out["applied"] and entry["roleFrom"] == {"claim": "groups", "map": {"Finance": "ROLE-001"}, "default": "ROLE-002"}
    out = sign_in_change.map_sso_roles(svc, str(tmp_path), change="the Admins group signs in as Wizard")
    assert not out["applied"] and "Wizard" in out["reason"]
    out = sign_in_change.restrict_sign_in_domains(svc, str(tmp_path), change="only @acme.com and acme.co.uk may sign in")
    entry = BlueprintService.load(output_dir=tmp_path).doc["security"]["signIn"]["sso"][0]
    assert out["applied"] and entry["domains"] == ["acme.co.uk", "acme.com"]
    out = sign_in_change.restrict_sign_in_domains(svc, str(tmp_path), change="anyone may sign in")
    assert out["applied"] and BlueprintService.load(output_dir=tmp_path).doc["security"]["signIn"]["sso"][0]["domains"] == []


def test_the_verbs_are_smiths():
    from services.smith.capabilities import GROUPS
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    for v in ("set_sign_in_method", "map_sso_roles", "restrict_sign_in_domains"):
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM
        assert any(v in g[2] for g in GROUPS)
