"""The ways in, proven on a running copy.

Each identity provider the Blueprint declares is driven end to end against
the platform's mock issuer (`routers/mock_idp.py`): the application's own
sign-in starts the flow, the issuer sends the person back, the application
exchanges the code, and the session that results holds the role the claims
named — then the person opens their role's page. A domain the entry does not
admit is refused in words; a person not invited to an `invite_only` entry is
refused in words. A magic link signs in once and not twice. Where passwords
are off, there is no sign-up page. The bench's environment names the mock
issuer under the entry's own names (`bench_env`), so no real value is read.
"""
from __future__ import annotations

import http.cookiejar
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)

CRITERION = "routes"


def entries(doc: dict) -> list[dict]:
    from services.blueprint.projection import sign_in_policy
    return list(sign_in_policy(doc)["sso"])


def policy(doc: dict) -> dict:
    from services.blueprint.projection import sign_in_policy
    return sign_in_policy(doc)


def bench_env(doc: dict) -> dict[str, str]:
    """The names each declared provider is reached with, pointing at the
    platform's mock issuer: set on the bench copy only."""
    from routers.mock_idp import issuer
    env: dict[str, str] = {}
    for e in entries(doc):
        env[e["issuerKey"]] = issuer()
        env[e["clientIdKey"]] = f"check-{e['id']}"
        env[e["clientSecretKey"]] = "check"
    return env


class _Browser:
    """One person's browser: cookies kept, redirects reported not followed."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()

        class _Stay(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a: Any, **k: Any) -> None:  # noqa: D401
                return None
        self.opener = urllib.request.build_opener(_Stay, urllib.request.HTTPCookieProcessor(self.jar))

    def go(self, method: str, url: str, *, form: dict | None = None, body: dict | None = None,
           headers: dict | None = None) -> tuple[int, str, str]:
        data = None
        h = dict(headers or {})
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            h["content-type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            h["content-type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=240) as r:
                return r.status, r.headers.get("location") or "", r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("location") or "", e.read().decode("utf-8", "replace")

    def json(self, method: str, url: str, **kw: Any) -> tuple[int, dict]:
        status, _loc, text = self.go(method, url, **kw)
        try:
            parsed = json.loads(text) if text else {}
        except ValueError:
            parsed = {}
        return status, parsed if isinstance(parsed, dict) else {}


def _q(s: Any) -> str:
    return str(s).replace("'", "''")


def _rows(app: Any, sql: str) -> list[list[str]]:
    from services.blueprint.page_review import _query
    return _query(app, sql)


def _csrf(b: _Browser, base: str) -> str:
    _s, body = b.json("GET", f"{base}/api/auth/csrf")
    return str(body.get("csrfToken") or "")


def _register(client_id: str, claims: dict[str, Any]) -> None:
    """The next sign-in's claims, on the platform's mock issuer — in process
    when this is the platform, over HTTP otherwise."""
    try:
        from routers.mock_idp import register_next
        register_next(client_id, claims)
    except Exception:  # noqa: BLE001
        pass
    try:
        from services.app_reporting import internal_url
        urllib.request.urlopen(urllib.request.Request(
            internal_url() + "/dev/mock-idp/next", data=json.dumps({"client_id": client_id, "claims": claims}).encode(),
            headers={"content-type": "application/json"}, method="POST"), timeout=20).read()
    except Exception:  # noqa: BLE001 — in process was enough
        pass


def sign_in_through(app: Any, entry: dict, claims: dict[str, Any]) -> tuple[dict | None, str]:
    """Drive the application's sign-in through the mock issuer as the person
    `claims` describe. `(session user, where it ended)`: the user when a
    session resulted, else None and the address the app sent the person to."""
    b = _Browser()
    base = app.base
    _register(f"check-{entry['id']}", claims)
    csrf = _csrf(b, base)
    status, body = b.json("POST", f"{base}/api/auth/signin/{entry['id']}",
                          form={"csrfToken": csrf, "callbackUrl": f"{base}/login", "json": "true"})
    url = str(body.get("url") or "")
    if status != 200 or not url:
        return None, f"the sign-in could not be started ({status}: {str(body)[:160]})"
    if "/login?error=" in url or url.rstrip("/").endswith("/login"):
        return None, url
    # Out to the issuer and back: the issuer answers with a redirect to the
    # application's callback, which exchanges the code and sets the session.
    status, location, text = b.go("GET", url)
    if status not in (302, 303, 307) or not location:
        return None, f"the issuer did not send the person back ({status}: {text[:160]})"
    status, location, text = b.go("GET", location)
    if status not in (302, 303, 307):
        return None, f"the callback did not finish ({status}: {text[:200]})"
    where = location
    _s, session = b.json("GET", f"{base}/api/auth/session")
    user = session.get("user") if isinstance(session.get("user"), dict) else None
    return user, where


def _landing(app: Any, doc: dict, role: str, b: _Browser | None = None) -> str:
    from services.blueprint.account_model import landing_by_role
    return landing_by_role(doc).get(role) or "/"


def check_sso(app: Any, doc: dict, *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}` for the ways in."""
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    pol = policy(doc)
    role_names = [str(r.get("name") or "") for r in doc.get("roles") or [] if isinstance(r, dict)]

    for e in entries(doc):
        if cancelled():
            break
        eid, name = e["id"], e["name"]
        label = f"Signs in through {name}"
        # The role the claims should land in: the first mapped group, else
        # the default, else the signup role; a person made on first sign-in.
        rf = e.get("roleFrom") or {}
        group, role = next(iter((rf.get("map") or {}).items()), (None, rf.get("default")))
        if not role:
            from services.blueprint.account_model import signup_role
            role = signup_role(doc) or (role_names[0] if role_names else "")
        domain = (e.get("domains") or ["example.com"])[0]
        email = f"check.{eid}.{secrets.token_hex(3)}@{domain}"
        if e.get("provisioning") == "invite_only":
            rows = _rows(app, "select email, coalesce(role, '') from users where email not like 'check.%' order by created_at limit 1")
            if not rows or not rows[0] or not rows[0][0]:
                untried.append(item(CRITERION, label, "no invited login on the copy to sign in as", f"sso:{eid}"))
                continue
            email, role = rows[0][0], rows[0][1] or role
        claims = {"sub": f"sub-{secrets.token_hex(4)}", "email": email, "name": f"Check {name}",
                  **({"groups": [group], "roles": [group]} if group else {}), "hd": domain}
        try:
            user, where = sign_in_through(app, e, claims)
        except Exception as exc:  # noqa: BLE001
            red.append(item(CRITERION, label, f"the sign-in crashed: {str(exc)[:200]}", f"sso:{eid}"))
            continue
        if user is None:
            red.append(item(CRITERION, label, f"no session resulted; the application sent the person to {where[:200]}", f"sso:{eid}"))
            continue
        got = str(user.get("role") or "")
        if role and got != role:
            red.append(item(CRITERION, label, f"the session holds the role {got!r}; the claims named {role!r}", f"sso:{eid}"))
            continue
        if str(user.get("email") or "").lower() != email.lower():
            red.append(item(CRITERION, label, f"the session is {user.get('email')!r}, not the person who signed in ({email})", f"sso:{eid}"))
            continue
        if e.get("provisioning") != "invite_only":
            rows = _rows(app, f"select count(*) from users where lower(email) = '{_q(email.lower())}'")
            if not rows or rows[0][0] != "1":
                red.append(item(CRITERION, label, "the person was signed in but no account row was made for them", f"sso:{eid}"))
                continue
        green.append(item(CRITERION, label, f"signed in as {got or 'a member'}, landed on {_landing(app, doc, got)}", f"sso:{eid}"))

        if e.get("domains"):
            label2 = f"{name} refuses another organisation's address"
            try:
                user2, where2 = sign_in_through(app, e, {**claims, "sub": f"sub-{secrets.token_hex(4)}",
                                                          "email": f"stranger.{secrets.token_hex(3)}@not-{domain}"})
            except Exception as exc:  # noqa: BLE001
                red.append(item(CRITERION, label2, f"the sign-in crashed: {str(exc)[:200]}", f"sso:{eid}"))
                continue
            if user2 is not None:
                red.append(item(CRITERION, label2, "an address outside the allowed domains was signed in", f"sso:{eid}"))
            elif "error=DomainNotAllowed" not in where2:
                red.append(item(CRITERION, label2, f"refused, but without saying why (sent to {where2[:120]})", f"sso:{eid}"))
            else:
                green.append(item(CRITERION, label2, "refused in words", f"sso:{eid}"))
        if e.get("provisioning") == "invite_only":
            label3 = f"{name} refuses a person who was not invited"
            try:
                user3, where3 = sign_in_through(app, e, {**claims, "sub": f"sub-{secrets.token_hex(4)}",
                                                          "email": f"uninvited.{secrets.token_hex(3)}@{domain}"})
            except Exception as exc:  # noqa: BLE001
                red.append(item(CRITERION, label3, f"the sign-in crashed: {str(exc)[:200]}", f"sso:{eid}"))
                continue
            if user3 is not None:
                red.append(item(CRITERION, label3, "a person nobody invited was signed in", f"sso:{eid}"))
            elif "error=NotInvited" not in where3:
                red.append(item(CRITERION, label3, f"refused, but without saying why (sent to {where3[:120]})", f"sso:{eid}"))
            else:
                green.append(item(CRITERION, label3, "refused in words", f"sso:{eid}"))

    if pol.get("magicLink") and not cancelled():
        label = "A magic link signs in once"
        try:
            _magic_link(app, green, red, untried, label)
        except Exception as exc:  # noqa: BLE001
            red.append(item(CRITERION, label, f"the check crashed: {str(exc)[:200]}", "magic_link"))

    if not pol.get("password") and not cancelled():
        label = "No sign-up page where nobody holds a password"
        b = _Browser()
        status, _loc, _t = b.go("GET", f"{app.base}/signup")
        if status == 404:
            green.append(item(CRITERION, label, "/signup answers 404", "sign_up"))
        else:
            red.append(item(CRITERION, label, f"/signup answers {status}; a person arrives by link or through their organisation", "sign_up"))

    return {"total": len(green) + len(red) + len(untried), "green": green, "red": red, "untried": untried}


def _magic_link(app: Any, green: list, red: list, untried: list, label: str) -> None:
    """A link requested for a login lands a row holding only a digest; a
    token whose digest is on the row signs in once; the same token again,
    and an expired one, do not."""
    import hashlib
    rows = _rows(app, "select email from users where email not like 'check.%' order by created_at limit 1")
    if not rows or not rows[0] or not rows[0][0]:
        untried.append(item(CRITERION, label, "no login on the copy to send a link to", "magic_link"))
        return
    email = rows[0][0]
    b = _Browser()
    base = app.base
    status, body = b.json("POST", f"{base}/api/auth/magic", body={"email": email})
    if status != 200:
        red.append(item(CRITERION, label, f"asking for a link answered {status}: {str(body)[:160]}", "magic_link"))
        return
    rows = _rows(app, f"select purpose, (expires_at > now())::text from forge_invites where email = '{_q(email)}'")
    if not rows or rows[0][0] != "magic_link" or rows[0][1] != "true":
        red.append(item(CRITERION, label, "no live magic-link row was written for the address", "magic_link"))
        return
    # The check's own token, on the row: the route keeps only a digest, so
    # the link it sent cannot be read back — one with a known digest is laid
    # in its place and used as the person would.
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    _rows(app, f"update forge_invites set token_hash = '{digest}', used_at = null, expires_at = now() + interval '15 minutes' "
               f"where email = '{_q(email)}'")
    csrf = _csrf(b, base)
    status, location, _t = b.go("POST", f"{base}/api/auth/callback/magic",
                                form={"csrfToken": csrf, "token": token, "callbackUrl": f"{base}/login"})
    _s, session = b.json("GET", f"{base}/api/auth/session")
    user = session.get("user") if isinstance(session.get("user"), dict) else None
    if not user or str(user.get("email") or "").lower() != email.lower():
        red.append(item(CRITERION, label, f"the link did not sign the person in ({status}, sent to {location[:120]})", "magic_link"))
        return
    b2 = _Browser()
    csrf2 = _csrf(b2, base)
    b2.go("POST", f"{base}/api/auth/callback/magic", form={"csrfToken": csrf2, "token": token, "callbackUrl": f"{base}/login"})
    _s, again = b2.json("GET", f"{base}/api/auth/session")
    if isinstance(again.get("user"), dict):
        red.append(item(CRITERION, label, "the same link signed in a second time", "magic_link"))
        return
    _rows(app, f"update forge_invites set used_at = null, expires_at = now() - interval '1 minute' where email = '{_q(email)}'")
    b3 = _Browser()
    csrf3 = _csrf(b3, base)
    b3.go("POST", f"{base}/api/auth/callback/magic", form={"csrfToken": csrf3, "token": token, "callbackUrl": f"{base}/login"})
    _s, expired = b3.json("GET", f"{base}/api/auth/session")
    if isinstance(expired.get("user"), dict):
        red.append(item(CRITERION, label, "an expired link signed the person in", "magic_link"))
        return
    green.append(item(CRITERION, label, f"a link for {email} signed in once; a second use and an expired one did not", "magic_link"))


__all__ = ["CRITERION", "bench_env", "check_sso", "entries", "policy", "sign_in_through"]
