"""Past the password (2026-11-12): two-step sign-in by an emailed code, a pause
after five wrong passwords, forgot password by code, and the devices a person
is signed in on. The behaviour is checked under node against the shipped
`lib/sign-in-guard.ts` (templates/runtime/__tests__/a-password-is-not-the-whole-way-in.test.mts);
this checks that every app gets the pieces and that the wiring stops a session,
not a screen."""
from __future__ import annotations

import tempfile
from pathlib import Path

from services.blueprint.platform_routes import PUBLIC
from services.blueprint.projection import project_middleware

ROOT = Path(__file__).resolve().parents[2]
ROUTES = (("api-auth-two-step/route.ts", "auth/two-step/route.ts"),
          ("api-auth-password-reset/route.ts", "auth/password-reset/route.ts"),
          ("api-auth-devices/route.ts", "auth/devices/route.ts"))


def test_every_app_gets_the_routes_and_an_existing_one_is_brought_up():
    injector = (ROOT / "services/runtime_injector.py").read_text()
    from services.smith import sync_app
    for tmpl, dst in ROUTES:
        assert (ROOT / "templates/runtime" / tmpl).is_file(), tmpl
        assert f'("{tmpl}", "{dst}")' in injector, tmpl
        assert (tmpl, f"src/app/api/{dst}") in sync_app.AUTH_ROUTES, tmpl
    assert "src/lib/sign-in-guard.ts" in sync_app.AUTH_FOUNDATION_FILES, "auth.ts imports it: an old app is given it, not only refreshed"
    assert "src/lib/session-cookie.ts" in sync_app.ENGINE_FOUNDATION_FILES


def test_the_forgot_password_page_is_open_to_a_signed_out_visitor():
    assert any(r.route == "/reset-password" and not r.subtree for r in PUBLIC)
    out = Path(tempfile.mkdtemp())
    project_middleware({"pages": [], "roles": [], "security": {}}, out)
    assert 'new RegExp("^/reset-password$")' in (out / "src/middleware.ts").read_text()
    assert (ROOT / "templates/app-foundation/src/app/reset-password/page.tsx").is_file()


def test_no_session_exists_before_the_code_and_a_signed_out_session_is_refused():
    auth = (ROOT / "templates/app-foundation/src/auth.ts").read_text()
    # The refusal is thrown from authorize: next-auth then mints no token at all.
    assert 'throw new guard.SignInRefused({ code: "TWO_STEP_REQUIRED"' in auth
    assert auth.index('user.twoStep === true && !guard.trusted(') < auth.index('return (await startSession(user, "password"')
    assert 'throw new guard.SignInRefused({ code: "SIGN_IN_PAUSED"' in auth
    assert '(error as Error)?.name === "SignInRefused") throw error' in auth, "the catch-all must not swallow the refusal"
    # A session whose id is gone is refused on its next read.
    assert 'else if (token.id && !(await stillHeld(token as any)))' in auth
    assert "async signOut({ token })" in auth and "guard.dropDevice" in auth


def test_the_sign_in_columns_live_on_the_users_table_and_never_leave_it():
    user = (ROOT / "templates/app-foundation/src/db/schema/user.ts").read_text()
    for col in ('"two_step"', '"sign_in_code_hash"', '"sign_in_code_for"', '"sign_in_code_expires_at"', '"sign_in_code_sent_at"',
                '"sign_in_code_attempts"', '"failed_sign_ins"', '"sign_in_paused_until"', '"signed_in_devices"', '"session_version"'):
        assert col in user, col
    engine = (ROOT / "templates/runtime/data-engine.ts").read_text()
    assert 'if ((t ? getTableName(t as any) : entityName) === "users") for (const c of SIGN_IN_COLUMNS) delete' in engine
    assert engine.count("withoutSignInColumns(entityName, cleanData);") == 2, "neither create nor update sets them"
    guard = (ROOT / "templates/app-foundation/src/lib/sign-in-guard.ts").read_text()
    engine_list = engine.split("const SIGN_IN_COLUMNS = [", 1)[1].split("];", 1)[0]
    guard_list = guard.split("export const SIGN_IN_COLUMNS = [", 1)[1].split("]", 1)[0]
    norm = lambda s: sorted(x.strip().strip('"') for x in s.replace("\n", " ").split(",") if x.strip())  # noqa: E731
    assert norm(engine_list) == norm(guard_list), "the engine and the guard name the same columns"


def test_the_reset_answers_the_same_for_anyone():
    route = (ROOT / "templates/runtime/api-auth-password-reset/route.ts").read_text()
    post = route.split("export async function POST", 1)[1].split("export async function PUT", 1)[0]
    assert post.count("return Response.json({ ok: true") == 1 and "notice" not in post.split("return Response.json({ ok: true", 1)[1]
    put = route.split("export async function PUT", 1)[1]
    assert put.count('said(400, "WRONG_CODE", NOT_RIGHT)') == 2, "an unknown address and a wrong code read the same"
    assert "guard.afterReset(" in put


def test_microsoft_for_any_organisation_and_linkedin_are_entries_like_any_other():
    """Social sign-in is `signIn.sso` entries (no new Blueprint field): Google by its fixed
    issuer, Microsoft for every tenant (`entra` at .../common/v2.0), LinkedIn as plain OIDC."""
    auth = (ROOT / "templates/app-foundation/src/auth.ts").read_text()
    assert 'e.provider === "entra" && /\\/(common|organizations|consumers)(\\/|$)/.test(issuer)' in auth
    assert 'idToken: !anyTenant' in auth and 'userinfo: "https://graph.microsoft.com/oidc/userinfo"' in auth
    assert 'token_endpoint_auth_method: "client_secret_post"' in auth
    from services.blueprint.projection import sign_in_policy
    pol = sign_in_policy({"roles": [], "security": {"signIn": {"sso": [
        {"id": "google", "name": "Google", "kind": "oidc", "provider": "google", "provisioning": "invite_only"},
        {"id": "microsoft", "name": "Microsoft", "kind": "oidc", "provider": "entra", "provisioning": "invite_only"},
        {"id": "linkedin", "name": "LinkedIn", "kind": "oidc", "provider": "oidc", "provisioning": "invite_only"}]}}})
    assert [(e["id"], e["clientIdKey"], e["issuerKey"]) for e in pol["sso"]] == [
        ("google", "SSO_GOOGLE_CLIENT_ID", "SSO_GOOGLE_ISSUER"),
        ("microsoft", "SSO_MICROSOFT_CLIENT_ID", "SSO_MICROSOFT_ISSUER"),
        ("linkedin", "SSO_LINKEDIN_CLIENT_ID", "SSO_LINKEDIN_ISSUER")]
