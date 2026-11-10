"""DITANS QA, 2026-11-05 (DIT-005, DIT-016): sign-up made and signed in every
account at once — no code was ever sent, and an unverified example.com
address was let straight in.

`security.signIn.verifyEmail`: a new account is "pending" until it enters a
six-digit code sent to its own address (also from the test version, which
otherwise emails only the organisation's people); until then the middleware
lets it reach only the sign-in machinery and the code step. Accounts made
before the application asked are never shut out."""
from __future__ import annotations

import tempfile
from pathlib import Path

from services.blueprint.projection import project_middleware, sign_in_policy

ROOT = Path(__file__).resolve().parents[2]


def test_the_policy_carries_the_requirement_and_where_the_code_is_asked():
    assert sign_in_policy({"security": {}})["verifyEmail"] is False
    on = sign_in_policy({"security": {"signIn": {"verifyEmail": True}}})
    assert on["verifyEmail"] is True and on["verifyPath"] == "/verify-email"
    own = sign_in_policy({"security": {"signIn": {"verifyEmail": True, "verifyPath": "/signup?step=verify"}}})
    assert own["verifyPath"] == "/signup?step=verify"


def test_a_new_account_starts_pending_and_only_a_digest_is_kept():
    user = (ROOT / "templates/app-foundation/src/db/schema/user.ts").read_text()
    for col in ('"email_verification"', '"email_code_hash"', '"email_code_expires_at"', '"email_code_attempts"'):
        assert col in user
    signup = (ROOT / "templates/app-foundation/src/app/api/auth/signup/route.ts").read_text()
    assert 'signInPolicy().verifyEmail ? { emailVerification: "pending" }' in signup
    auth = (ROOT / "templates/app-foundation/src/auth.ts").read_text()
    assert '"emailCodeHash", "emailCodeExpiresAt"' in auth, "the code's digest never rides in the session"


def test_the_route_sends_to_the_own_address_and_checks_with_limits():
    route = (ROOT / "templates/runtime/api-auth-email-code/route.ts").read_text()
    assert "randomInt(0, 1_000_000)" in route and "emailCodeHash: digest(code)" in route
    assert "toTheirOwnAddress: true" in route and "to: row.email" in route
    assert "TTL_MS = 10 * 60_000" in route and "ATTEMPTS = 5" in route and "RESEND_MS = 30_000" in route
    assert 'emailVerification: "verified"' in route and "no email service is connected" in route
    engine = (ROOT / "templates/runtime/workflows/index.ts").read_text()
    assert '!(config as any).toTheirOwnAddress' in engine, "the test version lets a code to the own address through"
    injector = (ROOT / "services/runtime_injector.py").read_text()
    assert '"api-auth-email-code/route.ts", "auth/email-code/route.ts"' in injector


def test_the_middleware_holds_a_pending_account_at_the_code_step():
    out = Path(tempfile.mkdtemp())
    project_middleware({"pages": [], "roles": [], "security": {}}, out)
    mw = (out / "src/middleware.ts").read_text()
    assert 'import { SIGN_IN } from "@/lib/sign-in-policy";' in mw
    assert 'emailVerification === "pending"' in mw and 'refuse(403, "EMAIL_NOT_VERIFIED"' in mw
    assert mw.index("pendingProof(req.nextauth.token)") < mw.index("if (isPublic(path)) return NextResponse.next();"), \
        "public pages are held too: an employer's onboarding is public"
    assert 'to.searchParams.set("next", path + req.nextUrl.search)' in mw


def test_the_sdk_and_a_default_page_ask_for_the_code_and_refresh_the_session():
    sdk = (ROOT / "templates/app-foundation/src/sdk/auth.tsx").read_text()
    assert "export function useEmailCode()" in sdk and "await update();" in sdk
    page = (ROOT / "templates/app-foundation/src/app/verify-email/page.tsx").read_text()
    assert "useEmailCode()" in page and 'autoComplete="one-time-code"' in page
    from services.smith import sync_app
    assert ("api-auth-email-code/route.ts", "src/app/api/auth/email-code/route.ts") in sync_app.AUTH_ROUTES
    assert "src/auth.ts" in sync_app.ENGINE_FOUNDATION_FILES and "src/sdk/auth.tsx" in sync_app.ENGINE_FOUNDATION_FILES
