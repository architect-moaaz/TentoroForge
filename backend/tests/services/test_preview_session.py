"""A signed-in browser, so the pages a signed-out one cannot see get reviewed.

`access` defaults to `authenticated`, so most pages of a generated application
are gated and the sweep was visiting them signed out. Every one redirected to
`/login` and was discarded — correctly, and uselessly.
"""
import json

import pytest
from jose import jwe

from services.preview_session import (
    COOKIE_NAME,
    PREVIEW_SECRET,
    Session,
    boot_env,
    cookie,
    derive_key,
    session_token,
    sessions_for,
)


def claims_of(token: str, secret: str = PREVIEW_SECRET) -> dict:
    return json.loads(jwe.decrypt(token, derive_key(secret)))


# --- the token the scaffold actually reads ---------------------------------

def test_the_token_is_the_jwe_nextauth_expects():
    """v4 encrypts the session with `dir` + A256GCM. A signed-but-not-encrypted
    JWT is rejected with nothing in the log to say why."""
    import base64

    header = session_token(Session()).split(".")[0]
    decoded = json.loads(base64.urlsafe_b64decode(header + "=="))
    assert decoded == {"alg": "dir", "enc": "A256GCM"}


def test_the_key_is_derived_the_way_next_auth_derives_it():
    """HKDF-SHA256, empty salt, that exact info string. A different one derives
    a different key and the cookie is silently ignored."""
    assert len(derive_key("anything")) == 32
    assert derive_key("a") != derive_key("b")


def test_the_claims_carry_id_not_only_sub():
    """The scaffold's jwt callback sets `token.id` and its session callback
    reads it back as `session.user.id`. A token with only `sub` signs in fine
    and then every page keyed to the current user sees undefined."""
    claims = claims_of(session_token(Session(sub="preview-user")))
    assert claims["id"] == "preview-user"
    assert claims["sub"] == "preview-user"


def test_a_role_reaches_the_session_when_there_is_one():
    assert claims_of(session_token(Session(role="Recruiter")))["role"] == "Recruiter"


def test_no_role_means_no_role_claim():
    """A plain authenticated user is not a user with an empty role."""
    assert "role" not in claims_of(session_token(Session()))


def test_the_session_is_the_same_session_across_runs():
    """The ciphertext is not reproducible — A256GCM draws a fresh IV — and does
    not need to be. What a screenshot needs is stable claims."""
    a = claims_of(session_token(Session(), now=1000))
    b = claims_of(session_token(Session(), now=1000))
    assert a == b
    assert a["jti"] == b["jti"]


def test_the_token_expires():
    claims = claims_of(session_token(Session(), now=1000, ttl_s=60))
    assert claims["iat"] == 1000 and claims["exp"] == 1060


def test_a_token_minted_against_one_secret_does_not_open_another():
    """Which is the whole reason this is safe: it opens a preview booted with a
    secret we chose, and nothing else."""
    token = session_token(Session(), secret="ours")
    with pytest.raises(Exception):
        claims_of(token, secret="theirs")


# --- the cookie -------------------------------------------------------------

def test_the_cookie_is_the_name_next_auth_reads_over_http():
    """The `__Secure-` prefix is the https spelling, and a browser refuses to
    store it over http — which a localhost preview is."""
    c = cookie(Session(), base_url="http://localhost:3000")
    assert c["name"] == COOKIE_NAME
    assert c["secure"] is False
    assert c["httpOnly"] is True
    assert c["domain"] == "localhost"
    assert c["path"] == "/"


# --- booting so the cookie is accepted --------------------------------------

def test_the_app_is_booted_with_the_secret_the_token_was_minted_against():
    env = boot_env("http://localhost:3000", "s")
    assert env["NEXTAUTH_SECRET"] == "s"


def test_the_boot_env_sets_the_url_next_auth_resolves_redirects_from():
    """A mismatch sends a signed-in browser back to /login, which the sweep
    would report as a sign-in gate on every page it exists to review."""
    assert boot_env("http://localhost:4000")["NEXTAUTH_URL"] == "http://localhost:4000"


# --- one session per role the pages ask for ---------------------------------

def test_a_role_session_carries_the_role_name_not_the_blueprint_id():
    """The scaffold's `authorize` returns `user.role` from its own users table,
    so `ROLE-001` is not a string any generated check compares against."""
    out = sessions_for({"roles": [{"id": "ROLE-001", "name": "Recruiter"}]},
                       {"ROLE-001"})
    assert out["ROLE-001"].role == "Recruiter"


def test_there_is_always_a_plain_session_for_pages_that_just_need_signing_in():
    assert sessions_for({}, set())[""].role == ""


def test_a_role_with_no_definition_still_gets_a_session():
    """A page addressed to a role the roles section never defined is a defect,
    and not one to fix by refusing to photograph the page."""
    out = sessions_for({"roles": []}, {"ROLE-009"})
    assert "ROLE-009" in out


def test_each_role_is_a_distinguishable_user():
    """A screenshot showing "Signed in as …" should show the role it was
    reviewed as — that is the point of reviewing it twice."""
    out = sessions_for(
        {"roles": [{"id": "ROLE-001", "name": "Recruiter"},
                   {"id": "ROLE-002", "name": "Hiring Manager"}]},
        {"ROLE-001", "ROLE-002"})
    subs = {s.sub for s in out.values()}
    assert len(subs) == 3
    assert out["ROLE-002"].email == "hiring.manager@example.com"


# --- the app's own cookie name ----------------------------------------------

def test_the_cookie_is_also_named_the_way_the_app_names_it():
    """session-cookie.ts: `forge-<FNV-1a of the secret>.session-token`. The
    fingerprints are the template's own function run in node on these
    secrets, so a drift in the Python port is caught here, not by a review
    landing on /login."""
    from services.preview_session import cookie_names, cookies
    assert cookie_names(PREVIEW_SECRET) == ["forge-dfdcd746.session-token", "next-auth.session-token"]
    assert cookie_names("dev-secret")[0] == "forge-9543efe3.session-token"
    both = cookies(Session(), base_url="http://localhost:3000")
    assert [c["name"] for c in both] == cookie_names(PREVIEW_SECRET)
    assert len({c["value"] for c in both}) == 1 and all(c["domain"] == "localhost" for c in both)


def test_the_token_is_a_jwe_the_apps_next_auth_can_open():
    """`jose` (what next-auth decodes with) requires a 12-byte IV for GCM and
    python-jose wrote 16, so no minted token ever opened a real app. Pinned
    here: the IV length, and a decrypt over `cryptography` alone — proven
    once against nlwtcyz5's next-auth 4.24.15 `decode` (2026-09-25)."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    token = session_token(Session(sub="a45fb2de", role="Parent"), secret=PREVIEW_SECRET)
    header, key, iv, body, tag = token.split(".")
    assert key == "" and json.loads(unb64(header)) == {"alg": "dir", "enc": "A256GCM"}
    assert len(unb64(iv)) == 12
    claims = json.loads(AESGCM(derive_key(PREVIEW_SECRET)).decrypt(
        unb64(iv), unb64(body) + unb64(tag), header.encode("ascii")))
    assert claims["sub"] == claims["id"] == "a45fb2de" and claims["role"] == "Parent"
