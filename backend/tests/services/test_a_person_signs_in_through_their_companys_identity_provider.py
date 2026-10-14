"""An application's sign-in through an identity provider is proven on a
bench against the platform's mock issuer: discovery, a code, PKCE, an
RS256 id token its JWKS verifies, userinfo — and BoxyHQ Jackson's paths,
so a SAML sign-in (OIDC to the bridge) is proven the same way. The check
drives the app's own sign-in and reads the role off the session; the
bench's environment names the mock under the entry's own names
(2026-10-12)."""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import mock_idp
from services.blueprint import sso_check

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Accountant"}, {"id": "ROLE-002", "name": "Viewer"}],
    "security": {"signIn": {"password": True, "magicLink": False, "sso": [
        {"id": "entra", "name": "Microsoft 365", "provider": "entra", "integration": "INT-001", "domains": ["acme.com"],
         "roleFrom": {"claim": "groups", "map": {"Finance": "ROLE-001"}, "default": "ROLE-002"}},
        {"id": "corp", "name": "Corp SAML", "provider": "saml", "integration": "INT-002", "provisioning": "invite_only"}]}},
}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mock_idp.router)
    return TestClient(app)


def test_the_mock_issuer_speaks_oidc_with_pkce_and_a_verifiable_id_token(monkeypatch):
    monkeypatch.setenv("FORGE_URL", "http://platform.test")
    c = _client()
    disc = c.get("/dev/mock-idp/.well-known/openid-configuration").json()
    assert disc["issuer"] == "http://platform.test/dev/mock-idp" and disc["jwks_uri"].endswith("/jwks")
    mock_idp.register_next("check-entra", {"sub": "s1", "email": "ann@acme.com", "groups": ["Finance"]})
    verifier = "v" * 48
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = c.get("/dev/mock-idp/authorize", params={"client_id": "check-entra", "redirect_uri": "http://app/api/auth/callback/entra",
                                                 "state": "st", "nonce": "n1", "code_challenge": challenge, "code_challenge_method": "S256"},
              follow_redirects=False)
    assert r.status_code == 302
    back = urlparse(r.headers["location"])
    q = parse_qs(back.query)
    assert back.path == "/api/auth/callback/entra" and q["state"] == ["st"] and q["code"]
    bad = c.post("/dev/mock-idp/token", data={"grant_type": "authorization_code", "code": q["code"][0], "client_id": "check-entra",
                                             "code_verifier": "wrong"})
    assert bad.status_code == 400, "a wrong PKCE verifier is refused and the code is spent"
    mock_idp.register_next("check-entra", {"sub": "s1", "email": "ann@acme.com", "groups": ["Finance"]})
    r = c.get("/dev/mock-idp/authorize", params={"client_id": "check-entra", "redirect_uri": "http://app/cb", "code_challenge": challenge,
                                                 "code_challenge_method": "S256", "nonce": "n1"}, follow_redirects=False)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    basic = base64.b64encode(b"check-entra:check").decode()
    tok = c.post("/dev/mock-idp/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
                 headers={"Authorization": f"Basic {basic}"}).json()
    assert tok["token_type"] == "Bearer" and tok["id_token"]
    from jose import jwt
    jwks = c.get("/dev/mock-idp/jwks").json()
    claims = jwt.decode(tok["id_token"], jwks, algorithms=["RS256"], audience="check-entra", issuer="http://platform.test/dev/mock-idp")
    assert claims["email"] == "ann@acme.com" and claims["groups"] == ["Finance"] and claims["nonce"] == "n1"
    info = c.get("/dev/mock-idp/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    assert info["email"] == "ann@acme.com"
    assert c.get("/dev/mock-idp/userinfo").status_code == 401


def test_saml_is_oidc_to_the_app_the_bridges_paths_answer_too(monkeypatch):
    monkeypatch.setenv("FORGE_URL", "http://platform.test")
    c = _client()
    mock_idp.register_next("check-corp", {"sub": "s2", "email": "bob@corp.com", "name": "Bob Builder", "groups": ["Admins"]})
    r = c.get("/dev/mock-idp/api/oauth/authorize", params={"client_id": "check-corp", "redirect_uri": "http://app/api/auth/callback/corp",
                                                           "state": "x"}, follow_redirects=False)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    tok = c.post("/dev/mock-idp/api/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": "check-corp",
                                                        "client_secret": "check"}).json()
    info = c.get("/dev/mock-idp/api/oauth/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    assert info == {"id": "s2", "email": "bob@corp.com", "firstName": "Bob", "lastName": "Builder", "groups": ["Admins"], "roles": ["Admins"]}


def test_the_bench_names_the_mock_under_each_entrys_names(monkeypatch):
    monkeypatch.setenv("FORGE_URL", "http://platform.test")
    env = sso_check.bench_env(DOC)
    assert env == {"SSO_ENTRA_ISSUER": "http://platform.test/dev/mock-idp", "SSO_ENTRA_CLIENT_ID": "check-entra", "SSO_ENTRA_CLIENT_SECRET": "check",
                   "SSO_CORP_ISSUER": "http://platform.test/dev/mock-idp", "SSO_CORP_CLIENT_ID": "check-corp", "SSO_CORP_CLIENT_SECRET": "check"}
    src = (sso_check.__file__.rsplit("/services/", 1)[0] + "/services/blueprint/fix_to_green.py")
    text = open(src).read()
    assert "bench_env(svc.doc)" in text and "check_sso(app, svc.doc" in text


def test_the_check_reads_the_role_off_the_session_and_refuses_in_words(monkeypatch):
    seen = []

    def drive(app, entry, claims):
        seen.append((entry["id"], claims["email"]))
        if entry["id"] == "entra":
            if claims["email"].endswith("@acme.com"):
                return {"email": claims["email"], "role": "Accountant"}, "http://app/"
            return None, "http://app/login?error=DomainNotAllowed"
        if claims["email"] == "bob@corp.com":
            return {"email": "bob@corp.com", "role": "Viewer"}, "http://app/"
        return None, "http://app/login?error=NotInvited"

    def rows(app, sql):
        if "count(*)" in sql:
            return [["1"]]
        if "select email, coalesce(role, '')" in sql:
            return [["bob@corp.com", "Viewer"]]
        return []
    monkeypatch.setattr(sso_check, "sign_in_through", drive)
    monkeypatch.setattr(sso_check, "_rows", rows)
    app = type("App", (), {"base": "http://app"})()
    out = sso_check.check_sso(app, DOC)
    assert out["red"] == [] and out["untried"] == []
    assert [g["label"] for g in out["green"]] == ["Signs in through Microsoft 365", "Microsoft 365 refuses another organisation's address",
                                                   "Signs in through Corp SAML", "Corp SAML refuses a person who was not invited"]
    assert seen[0][0] == "entra" and seen[0][1].endswith("@acme.com") and "not-acme.com" in seen[1][1]
    assert out["green"][0]["cause"] == "sso:entra" and out["total"] == 4

    def wrong_role(app, entry, claims):
        return {"email": claims["email"], "role": "Viewer"}, "http://app/"
    monkeypatch.setattr(sso_check, "sign_in_through", wrong_role)
    out = sso_check.check_sso(app, {**DOC, "security": {"signIn": {"sso": DOC["security"]["signIn"]["sso"][:1]}}})
    assert out["red"] and "the claims named 'Accountant'" in out["red"][0]["why"]


def test_a_way_in_is_its_own_repair_cause():
    from services.blueprint.fix_to_green import by_cause
    groups = by_cause([{"cause": "sso:entra", "label": "x", "why": "y"}, {"cause": "magic_link", "label": "m", "why": "y"},
                       {"cause": "PAGE-001", "label": "p", "why": "y"}])
    assert [g["kind"] for g in groups] == ["page", "sign_in", "sign_in"]


def test_the_platform_registers_the_mock_issuer():
    text = open(mock_idp.__file__.rsplit("/routers/", 1)[0] + "/main.py").read()
    assert "mock_idp_router" in text
