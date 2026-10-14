"""A magic link: asked for by address with one answer for every address,
stored only as a digest for fifteen minutes, sent through the connected
email service (and said when it was not), consumed once by the `magic`
provider; the form offers every way in and finishes a link from the
address; the injector ships the routes (2026-10-12)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_route_keeps_a_digest_and_never_answers_with_the_link():
    route = (ROOT / "templates/runtime/api-auth-magic/route.ts").read_text()
    assert "If that address has an account" in route and 'purpose: "magic_link"' in route and "MAGIC_TTL_MS" in route
    assert "magicToken()" in route and "tokenHash: hash" in route
    assert "link }" not in route.replace("notice", "") and "Response.json({ ok: true, message: SAID" in route
    assert 'getActionHandler("send_email")' in route and "no email service is connected" in route
    assert '{ error: { code: "NOT_OFFERED"' in route


def test_auth_ts_consumes_a_link_once_and_builds_every_provider_from_names():
    auth = (ROOT / "templates/app-foundation/src/auth.ts").read_text()
    assert 'id: "magic"' in auth and 'String(row.purpose) !== "magic_link" || row.usedAt' in auth
    assert "set({ usedAt: new Date() })" in auth and "digest(token)" in auth
    assert "BoxyHQSAMLProvider({ id: e.id" in auth and 'checks: ["pkce", "state"]' in auth and "wellKnown: `${issuer}/.well-known/openid-configuration`" in auth
    assert "process.env[e.clientIdKey]" in auth and "if (!connected(e)) return null;" in auth
    assert '"/login?error=DomainNotAllowed"' in auth and '"/login?error=NotInvited"' in auth
    assert "roleFromClaims(claims, e)" in auth and "Object.assign(user, await sessionUserOf(row))" in auth
    assert "sk_" not in auth and "client_secret=" not in auth
    cookies = (ROOT / "templates/app-foundation/src/lib/session-cookie.ts").read_text()
    assert "pkceCodeVerifier" in cookies and "nonce" in cookies and "state:" in cookies


def test_the_form_offers_every_way_in_and_finishes_a_link():
    form = (ROOT / "templates/app-foundation/src/sdk/auth.tsx").read_text()
    assert 'fetch(apiPath("/api/auth/methods"))' in form and 'search?.get("magic")' in form
    assert 'signIn("magic", { token, redirect: false })' in form and "Continue with {p.name}" in form
    assert "is not connected here yet" in form and "Email me a sign-in link" in form
    assert "DomainNotAllowed:" in form and "NotInvited:" in form
    assert "{methods.password && (" in form, "no password fields where nobody holds one"
    barrel = (ROOT / "templates/app-foundation/src/sdk/client.tsx").read_text()
    assert "SignInMethods" in barrel and "useMagicLink" in barrel
    login = (ROOT / "templates/app-foundation/src/app/login/page.tsx").read_text()
    assert "<SignInMethods email={email} />" in login


def test_the_injector_ships_the_routes_and_the_middleware_lets_them_through():
    injector = (ROOT / "services/runtime_injector.py").read_text()
    assert '"api-auth-methods/route.ts", "auth/methods/route.ts"' in injector and '"api-auth-magic/route.ts", "auth/magic/route.ts"' in injector
    assert (ROOT / "templates/runtime/api-auth-methods/route.ts").read_text().count("methods()") == 1
    middleware = (ROOT / "templates/app-foundation/src/middleware.ts").read_text()
    assert "api/auth" in middleware


def test_the_check_lays_its_own_token_on_the_row_and_tries_it_three_times(monkeypatch):
    from services.blueprint import sso_check
    sqls = []
    state = {"sessions": iter([{"user": {"email": "ann@x.com"}}, {}, {}])}

    def rows(app, sql):
        sqls.append(sql)
        if "select email from users" in sql:
            return [["ann@x.com"]]
        if "select purpose" in sql:
            return [["magic_link", "true"]]
        return []

    class Browser:
        def __init__(self): pass
        def json(self, method, url, **kw):
            if url.endswith("/api/auth/magic"):
                return 200, {"ok": True}
            if url.endswith("/api/auth/csrf"):
                return 200, {"csrfToken": "c"}
            if url.endswith("/api/auth/session"):
                return 200, next(state["sessions"])
            return 200, {}
        def go(self, method, url, **kw):
            return 302, "http://app/", ""
    monkeypatch.setattr(sso_check, "_rows", rows)
    monkeypatch.setattr(sso_check, "_Browser", Browser)
    green, red, untried = [], [], []
    sso_check._magic_link(type("App", (), {"base": "http://app"})(), green, red, untried, "A magic link signs in once")
    assert red == [] and green and "signed in once" in green[0]["why"]
    assert any("update forge_invites set token_hash" in s for s in sqls) and any("interval '1 minute'" in s for s in sqls)
