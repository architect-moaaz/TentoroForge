"""A signed-in browser, for reviewing the pages a signed-out one cannot see.

`access` defaults to ``authenticated`` in the page contract — §100's "an
accidentally public page leaks data, an accidentally gated one merely annoys" —
so most pages of a generated application are gated, and
:mod:`services.rendered_pages` was visiting them signed out. Every one
redirected to ``/login`` and was discarded, correctly and uselessly: the visual
review ran over whatever had opted into ``public`` and reported honestly that it
had reviewed a landing page.

The gate is NextAuth. ``project_middleware`` writes ``withAuth`` with a matcher
built from what the pages declare, so what stands between the browser and a
gated page is one cookie holding an encrypted JWT.

Minting it rather than typing it in
-----------------------------------
The obvious route is to drive the login form. It needs a user that already
exists with credentials somebody knows, and it couples the sweep to the shape
of the login page — the field names, the button, whether there is a
two-step. That page is generated, so it changes, and a capture that breaks when
the login form is restyled is a capture nobody trusts.

The cookie is the contract instead. NextAuth v4 derives its encryption key from
``NEXTAUTH_SECRET`` by HKDF and encrypts the session as a JWE (``dir`` +
``A256GCM``); the preview is booted with a secret we choose, so the same
derivation produces a token the app accepts. No form, no credentials, nothing
to drift.

This is not a way past anybody's authentication. It applies to a preview the
platform just built, booted on localhost with a throwaway secret and a seeded
database, for the purpose of photographing it. It has no bearing on a deployed
application, whose secret is its own and unknown here.

Roles
-----
A ``role_restricted`` page is not opened by any session, only by one carrying
the right role — and §100 makes that a real distinction rather than a
formality. The claims carry a role, so the sweep can mint one session per role
the pages actually ask for — as the role's *name*, because the scaffold reads
`user.role` out of its own users table and the Blueprint's `ROLE-001` is not a
string any generated check compares against. That also makes a question the structural matrix
cannot ask answerable: a role-restricted page that renders identically for two
roles is a page whose restriction does nothing.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: NextAuth v4's own derivation, from `jwt.ts`: HKDF-SHA256 over the secret
#: with an empty salt and this exact info string. Reproduced rather than
#: guessed — a different info string derives a different key and the app
#: rejects the cookie with nothing in the log to say why.
_INFO = b"NextAuth.js Generated Encryption Key"

#: The cookie NextAuth reads over http. The `__Secure-` prefix is the https
#: spelling; a preview on localhost is http, and sending the secure name over
#: http would be a cookie the browser refuses to store.
COOKIE_NAME = "next-auth.session-token"

#: The secret the preview is booted with. Fixed and public on purpose: it
#: exists so this module and the app under review agree, and a preview whose
#: secret varied per run could not be reproduced. Anything real supplies its
#: own through the environment.
PREVIEW_SECRET = "forge-preview-secret-not-for-deployment"

DEFAULT_TTL_S = 60 * 60


@dataclass(frozen=True)
class Session:
    """Who the browser is signed in as."""

    sub: str = "preview-user"
    name: str = "Preview User"
    email: str = "preview@example.com"
    #: What the app will see as `session.user.role`. A *name*, not a ROLE id:
    #: the scaffold's `authorize` returns `user.role || "user"` from the users
    #: table, so the application's role vocabulary is its own strings and the
    #: Blueprint's `ROLE-001` is not what any in-page check compares against.
    role: str = ""

    def claims(self, *, now: int, ttl_s: int = DEFAULT_TTL_S) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name, "email": self.email, "sub": self.sub,
            # `id`, not just `sub`. The scaffold's jwt callback sets
            # `token.id` and its session callback reads it back as
            # `session.user.id`; a token with only `sub` signs in fine and then
            # every page keyed to the current user's id sees undefined.
            "id": self.sub,
            "iat": now, "exp": now + ttl_s,
            # NextAuth sets a jti. Derived from the subject so the *session*
            # is the same session across runs — the ciphertext is not
            # reproducible and does not need to be, since A256GCM draws a
            # fresh IV every time. What a screenshot needs is stable claims
            # and a stable seed, and both of those this has.
            "jti": str(uuid.uuid5(uuid.NAMESPACE_URL, f"forge-preview/{self.sub}")),
        }
        if self.role:
            out["role"] = self.role
        return out


def derive_key(secret: str) -> bytes:
    """NextAuth's encryption key for this secret."""
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"", info=_INFO,
    ).derive(secret.encode("utf-8"))


def session_token(
    session: Session, *, secret: str = PREVIEW_SECRET,
    now: int | None = None, ttl_s: int = DEFAULT_TTL_S,
) -> str:
    """The encrypted JWT NextAuth expects in its session cookie."""
    from jose import jwe

    payload = json.dumps(
        session.claims(now=int(now if now is not None else time.time()),
                       ttl_s=ttl_s),
        separators=(",", ":"), sort_keys=True,
    )
    token = jwe.encrypt(payload, derive_key(secret),
                        algorithm="dir", encryption="A256GCM")
    return token.decode("ascii") if isinstance(token, bytes) else token


def cookie(
    session: Session, *, base_url: str, secret: str = PREVIEW_SECRET,
    now: int | None = None,
) -> dict[str, Any]:
    """The cookie in Playwright's ``add_cookies`` shape."""
    from urllib.parse import urlsplit

    host = urlsplit(base_url).hostname or "localhost"
    return {
        "name": COOKIE_NAME,
        "value": session_token(session, secret=secret, now=now),
        "domain": host,
        "path": "/",
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }


def boot_env(base_url: str, secret: str = PREVIEW_SECRET) -> dict[str, str]:
    """What the preview must be booted with for the cookie to be accepted.

    ``NEXTAUTH_URL`` as well as the secret, because NextAuth resolves callback
    and redirect URLs from it and a mismatch sends a signed-in browser back to
    ``/login`` — which the sweep would report as a sign-in gate on every page
    it exists to review.

    The scaffold falls back to ``"dev-secret"`` when ``NEXTAUTH_SECRET`` is
    unset, so an app booted by someone else is still reviewable by passing that
    as the secret rather than this one.
    """
    return {
        "NEXTAUTH_SECRET": secret,
        "AUTH_SECRET": secret,
        "NEXTAUTH_URL": base_url,
    }


def sessions_for(doc: dict, roles_needed: set[str]) -> dict[str, Session]:
    """One session per role the pages actually ask for, plus a plain one.

    Keyed by role id, with ``""`` for pages that only need somebody signed in.
    Names come from the Blueprint so a screenshot of a page showing "Signed in
    as …" shows the role it was reviewed as, which is the whole point of
    reviewing it twice.
    """
    by_id = {r.get("id"): r for r in (doc.get("roles") or [])
             if isinstance(r, dict)}
    out: dict[str, Session] = {"": Session()}
    for role_id in sorted(roles_needed):
        role = by_id.get(role_id) or {}
        label = (role.get("name") or role_id or "").strip()
        out[role_id] = Session(
            sub=f"preview-{role_id.lower()}" if role_id else "preview-user",
            name=f"{label} (preview)" if label else "Preview User",
            email=f"{(label or 'preview').lower().replace(' ', '.')}@example.com",
            # The name, not the id — see `Session.role`.
            role=label,
        )
    return out
