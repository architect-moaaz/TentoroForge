"""Signing up through Google, Microsoft or LinkedIn makes the account the
signup form would have made (DITANS, 2026-11-16).

A recruiter who chose "Employer" and pressed "Continue with Google" came back
a Candidate: the provider's return knew nothing of the choice, and no record
of the person was made behind the login. The choice now rides in a cookie of
the app's own (POST /api/auth/methods), checked against the roles signup
offers on the way out and again on the way back; the person's record is made
by the same helper the password signup uses. An invite-only provider (an
enterprise's own) still admits nobody new, whatever the form said.

Proven end to end on 2026-11-16 against the platform's mock issuer: Employer +
Google → Organisation Admin on the organisation-type step; Professional +
Google → Candidate with a Candidate record on build-your-profile."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "templates/app-foundation/src"


def _read(rel: str) -> str:
    return (FOUNDATION / rel).read_text()


def test_the_choice_is_kept_only_when_signup_offers_it():
    route = (ROOT / "templates/runtime/api-auth-methods/route.ts").read_text()
    sign_in = _read("lib/sign-in.ts")
    assert "export async function POST" in route
    assert "offeredSignupRole(body.as)" in route and "status: 400" in route
    assert "httpOnly: true" in route and "maxAge: 900" in route
    # Read back, the cookie is checked again: a hand-made one cannot name a role signup does not offer.
    assert "return { as: offeredSignupRole(parsed.as), account };" in sign_in


def test_a_new_person_gets_the_chosen_role_and_their_record():
    auth = _read("auth.ts")
    jit = auth[auth.index("async function admitSso"):auth.index("IS THIS SESSION STILL HELD")]
    assert "readSignupIntent(jar.get(signupIntentCookie())?.value)" in jit
    assert "const role = claimed || intent.as || SIGNUP_ROLE || undefined;" in jit
    assert "writeAccountRow(tx, created.id, account.values)" in jit
    assert 'emailVerification: "verified"' in jit, "the provider proved the address"


def test_an_invite_only_provider_admits_nobody_new_whatever_the_form_said():
    auth = _read("auth.ts")
    jit = auth[auth.index("async function admitSso"):auth.index("IS THIS SESSION STILL HELD")]
    assert 'if (e.provisioning !== "just_in_time") { await _signIn(null, email, false, `sso:${e.id}`); return "/login?error=NotInvited"; }' in jit


def test_both_ways_in_share_one_account_helper():
    signup = (FOUNDATION / "app/api/auth/signup/route.ts").read_text()
    assert 'from "@/lib/account-row"' in signup and "writeAccountRow(tx, created.id, account.values)" in signup
    assert "function accountValues" not in signup


def test_the_form_offers_only_providers_that_make_accounts():
    sdk = _read("sdk/auth.tsx")
    assert "export async function signUpWith(" in sdk
    assert "p.connected && p.signUp" in sdk
    assert 'signUp: e.provisioning === "just_in_time"' in _read("lib/sign-in.ts")


def test_microsoft_needs_no_issuer_for_every_organisation():
    assert 'entra: "https://login.microsoftonline.com/common/v2.0"' in _read("lib/sign-in.ts")


def test_an_app_already_built_gets_the_new_files_on_its_next_sync():
    from services.smith.sync_app import AUTH_FOUNDATION_FILES, AUTH_ROUTES
    assert "src/lib/account-row.ts" in AUTH_FOUNDATION_FILES and "src/lib/sign-in.ts" in AUTH_FOUNDATION_FILES
    assert ("api-auth-methods/route.ts", "src/app/api/auth/methods/route.ts") in AUTH_ROUTES
