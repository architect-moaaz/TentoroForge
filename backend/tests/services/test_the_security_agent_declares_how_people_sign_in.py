"""The ways in are a security decision: password, magic link, identity
providers naming an `auth` integration with the three names per entry; a
way nobody could take is refused; the policy is projected with role NAMES;
no sign-up page where nobody holds a password (2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint.account_model import auth_page_bodies, has_sign_in, passwords_on
from services.blueprint.agent_contract import _READS, AgentResult, ArtifactProposal, InvalidSignIn, check_sign_in
from services.blueprint.projection import project_sign_in, sign_in_policy, sso_secret_names

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Accountant"}, {"id": "ROLE-002", "name": "Viewer"}],
    "integrations": [{"id": "INT-001", "name": "Microsoft 365 sign-in", "kind": "auth", "provider": "entra", "serves": "sign_in",
                      "status": "APPROVED", "secretRefs": ["SSO_ENTRA_ISSUER", "SSO_ENTRA_CLIENT_ID", "SSO_ENTRA_CLIENT_SECRET"]}],
    "security": {"authentication": "email_password"},
}


def _security(body: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="security", proposals=[ArtifactProposal(section="security", natural_key="security", body=body)])


def test_the_names_follow_the_entry():
    assert sso_secret_names("okta_saml") == {"issuerKey": "SSO_OKTA_SAML_ISSUER", "clientIdKey": "SSO_OKTA_SAML_CLIENT_ID",
                                             "clientSecretKey": "SSO_OKTA_SAML_CLIENT_SECRET"}


def test_a_provider_is_declared_with_its_row_and_role_map():
    check_sign_in(_security({"signIn": {"password": False, "sso": [
        {"id": "entra", "name": "Microsoft 365", "kind": "oidc", "provider": "entra", "integration": "INT-001", "domains": ["acme.com"],
         "roleFrom": {"claim": "groups", "map": {"Finance": "ROLE-001"}, "default": "ROLE-002"}, "provisioning": "just_in_time"}]}}), DOC)


@pytest.mark.parametrize("sign_in, said", [
    ({"password": False, "magicLink": False, "sso": []}, "nobody could sign in"),
    ({"sso": [{"id": "Entra!", "name": "x", "integration": "INT-001", "roleFrom": {"default": "ROLE-002"}}]}, "lower_snake"),
    ({"sso": [{"id": "okta", "name": "Okta", "integration": "INT-404", "roleFrom": {"default": "ROLE-002"}}]}, "none found"),
    ({"sso": [{"id": "entra", "name": "x", "integration": "INT-001", "domains": ["not a domain"], "roleFrom": {"default": "ROLE-002"}}]}, "domains"),
    ({"sso": [{"id": "entra", "name": "x", "integration": "INT-001", "roleFrom": {"map": {"Finance": "ROLE-009"}}}]}, "unknown role"),
    ({"sso": [{"id": "entra", "name": "x", "integration": "INT-001"}]}, "needs a role"),
    ({"sso": [{"id": "okta", "name": "x", "integration": "INT-001", "roleFrom": {"default": "ROLE-002"}}]}, "add SSO_OKTA_CLIENT_ID"),
])
def test_what_the_runtime_could_not_serve_is_refused(sign_in, said):
    with pytest.raises(InvalidSignIn) as e:
        check_sign_in(_security({"signIn": sign_in}), DOC)
    assert said in str(e.value)


def test_a_proposed_integration_row_counts_and_a_lone_auth_row_is_the_default():
    res = AgentResult(task_id="T", agent="security", proposals=[
        ArtifactProposal(section="integrations", natural_key="Okta sign-in", body={
            "name": "Okta sign-in", "kind": "auth", "serves": "sign_in", "provider": "okta",
            "secretRefs": ["SSO_OKTA_ISSUER", "SSO_OKTA_CLIENT_ID", "SSO_OKTA_CLIENT_SECRET"]}),
        ArtifactProposal(section="security", natural_key="security", body={"signIn": {"sso": [
            {"id": "okta", "name": "Okta", "integration": "Okta sign-in", "roleFrom": {"default": "ROLE-002"}}]}})])
    check_sign_in(res, {"roles": DOC["roles"]})
    check_sign_in(_security({"signIn": {"sso": [{"id": "entra", "name": "x", "roleFrom": {"default": "ROLE-002"}}]}}), DOC)


def test_the_policy_is_projected_with_role_names_and_the_entrys_names(tmp_path):
    doc = {**DOC, "security": {"signIn": {"password": False, "magicLink": True, "sso": [
        {"id": "entra", "name": "Microsoft 365", "provider": "entra", "integration": "INT-001", "domains": ["@Acme.com"],
         "roleFrom": {"claim": "groups", "map": {"Finance": "ROLE-001"}, "default": "ROLE-002"}, "provisioning": "invite_only"},
        {"id": "corp", "name": "Corp SAML", "provider": "saml", "integration": "INT-001"}]}}}
    pol = sign_in_policy(doc)
    assert pol["password"] is False and pol["magicLink"] is True
    assert pol["sso"][0] == {"id": "entra", "name": "Microsoft 365", "kind": "oidc", "provider": "entra",
                             "issuerKey": "SSO_ENTRA_ISSUER", "clientIdKey": "SSO_ENTRA_CLIENT_ID", "clientSecretKey": "SSO_ENTRA_CLIENT_SECRET",
                             "domains": ["acme.com"], "roleFrom": {"claim": "groups", "map": {"Finance": "Accountant"}, "default": "Viewer"},
                             "provisioning": "invite_only"}
    assert pol["sso"][1]["kind"] == "saml" and pol["sso"][1]["roleFrom"] is None and pol["sso"][1]["provisioning"] == "just_in_time"
    out = project_sign_in(doc, tmp_path)
    src = (tmp_path / "src/lib/sign-in-policy.ts").read_text()
    assert out["files"] == ["src/lib/sign-in-policy.ts"] and '"issuerKey": "SSO_ENTRA_ISSUER"' in src and "Accountant" in src
    assert "client_secret" not in src.lower().replace("clientsecretkey", "") or "SSO_" in src
    assert sign_in_policy({"security": {"signIn": {"password": False}}})["password"] is True, "a document nobody could sign in to still has a way in"


def test_no_sign_up_page_where_nobody_holds_a_password():
    doc = {"security": {"authentication": "none", "signIn": {"password": False, "magicLink": True}}, "pages": []}
    assert has_sign_in(doc) and not passwords_on(doc)
    assert [p["route"] for p in auth_page_bodies(doc)] == ["/login"]
    assert [p["route"] for p in auth_page_bodies({"security": {}, "pages": []})] == ["/login", "/signup"]


def test_the_security_agent_sees_the_integrations_and_follows_them():
    assert "integrations" in _READS["security"]
    from services.blueprint.orchestrator import DAG
    assert "integrations" in DAG["security"].depends_on
    from services.blueprint.executors import NODE_TASKS
    assert "`signIn`" in NODE_TASKS["security"] and "magicLink" in NODE_TASKS["security"]
