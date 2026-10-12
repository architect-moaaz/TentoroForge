"""The Workbench: the one door to a running app, and what it proves first.

Everything that runs an app to prove something — the statements of what
must happen, Smith's trials, the page review, the Preview tab — met the app
at its own door, and each door checked a different thing or nothing: the
review pushed a schema when it created a database and never again; the
preview asked whether a database answered; the statements signed in and
found out. TStyle (forge-v3, 2026-10-09) went through six builds that way:
an install cut off by a killed worker left a lockfile npm could not read,
the database got its tables while the app was not installed and so never
its rows, the handover named a login that did not exist, and 18 statements
were refused at the sign-in form and reported as the app's failures. Across
the fleet 126 of 169 statements were never tried, and the database check
was skipped in 23 of 24 apps because the platform's container has no Docker.

So there is one door now. Before anything runs the app, the Workbench proves
five things, re-establishing any that is missing:

1. installed — `node_modules` carries its completion marker and the lockfile
   is one npm can read;
2. schema — the database has the tables the definition declares;
3. seeded — the seed has run: the users table holds a login;
4. the server answers;
5. sign-in works — the seeded administrator signs in through the form.

The first three need no server and are proven by `prepare`; the last two
are proven by `RunningApp` as it serves (`served`). A precondition that
cannot be established is a `PlatformFault`: ours to fix, named by what it is,
and never a result reported for the app.
"""
from __future__ import annotations

import http.cookiejar
import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

#: What the Workbench proves, in order.
PRECONDITIONS = ("installed", "schema", "seeded", "server", "login")


class PlatformFault(RuntimeError):
    """A precondition the platform could not establish — the platform's
    fault, never a result for the app. `precondition` names which."""

    def __init__(self, precondition: str, why: str):
        self.precondition = precondition
        self.why = why
        super().__init__(f"the platform could not get the app {_said(precondition)}: {why}")


def _said(precondition: str) -> str:
    return {"installed": "installed", "schema": "its database tables", "seeded": "its seeded rows and logins",
            "server": "served", "login": "signed in to"}.get(precondition, precondition)


def prepare(app_root: str | Path) -> dict[str, dict]:
    """Prove preconditions 1–3 for the app at `app_root`, re-establishing
    any that is missing. Returns what was found and done, per precondition:
    `{"ok": True, "did": what was re-established or ""}`. Raises
    `PlatformFault` for the first one that cannot be established."""
    root = Path(app_root)
    return {"installed": _installed(root), **_database(root)}


def _installed(root: Path) -> dict:
    """Installed: the completion marker present and the lockfile readable.
    A tree without the marker is an install that was cut off and is thrown
    away with the lockfile it was writing; then npm installs again."""
    from services.blueprint import assembly

    if not (root / "package.json").is_file():
        return {"ok": True, "did": "", "note": "no package.json — nothing to install"}
    cleared = assembly._clear_unfinished_install(root)
    relocked = assembly._drop_unreadable_lockfile(root)
    if (root / "node_modules" / assembly.INSTALLED_MARK).exists() and not relocked:
        return {"ok": True, "did": ""}
    try:
        assembly.install_dependencies(root)
    except Exception as exc:  # noqa: BLE001 — the reason, in npm's words
        raise PlatformFault("installed", str(exc)[:600]) from exc
    return {"ok": True, "did": "installed" + (" after a cut-off install was thrown away" if cleared else "")
                                           + (" with a new lockfile" if relocked else "")}


def _database(root: Path) -> dict[str, dict]:
    """Schema and seed. On the apps server (forge-v3): the app's own database
    there, pushed and seeded whenever it lacks tables or a login. With Docker:
    the app's own `start.sh --seed-only`, which boots, pushes and seeds."""
    from services import app_databases

    if app_databases.server():
        try:
            out = app_databases.ensure(root) or {}
        except Exception as exc:  # noqa: BLE001 — the database's own words
            raise PlatformFault("schema", f"the app's database could not be prepared: {exc}"[:600]) from exc
        name = app_databases.name_for(root)
        if not app_databases._has_tables(name):
            raise PlatformFault("schema", str(out.get("reason") or "the schema was not pushed")[:600])
        if not app_databases._has_a_login(name):
            raise PlatformFault("seeded", str(out.get("reason") or "the seed wrote no login")[:600])
        did = "pushed and seeded" if out.get("pushed") else ""
        return {"schema": {"ok": True, "did": did}, "seeded": {"ok": True, "did": did}}
    from services.blueprint import page_review
    try:
        started = page_review.ensure_docker_database(root)
    except page_review.ReviewUnavailable as exc:
        raise PlatformFault("schema", str(exc)[:600]) from exc
    did = "started, pushed and seeded" if started else ""
    return {"schema": {"ok": True, "did": did}, "seeded": {"ok": True, "did": did, "started": started}}


def signs_in(base: str, email: str, password: str, *, timeout: int = 60) -> bool:
    """Whether `email` signs in through the app's own form at `base` — the
    CSRF token, the credentials callback, then a session that names them."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        csrf = json.loads(opener.open(base + "/api/auth/csrf", timeout=timeout).read() or b"{}").get("csrfToken", "")
        form = urllib.parse.urlencode({"csrfToken": csrf, "email": email, "password": password,
                                       "json": "true"}).encode()
        opener.open(base + "/api/auth/callback/credentials", data=form, timeout=timeout).read(100)
        session = json.loads(opener.open(base + "/api/auth/session", timeout=timeout).read() or b"{}")
    except Exception as exc:  # noqa: BLE001 — not signed in, whatever the reason
        logger.info("[workbench] %s could not sign in at %s: %s", email, base, exc)
        return False
    user = session.get("user") if isinstance(session, dict) else None
    return bool(user and str(user.get("email") or "").lower() == email.lower())


def served(base: str, email: str, password: str) -> dict[str, dict]:
    """Preconditions 4 and 5 for a server that answers at `base`: the seeded
    administrator signs in through the form. Raises `PlatformFault("login")`
    when they cannot — an app nobody can sign in to is not one to try."""
    if not signs_in(base, email, password):
        raise PlatformFault("login", f"{email} could not sign in through the form at {base}/login")
    return {"server": {"ok": True, "did": ""}, "login": {"ok": True, "did": "", "as": email}}


def fault_of(exc: BaseException | None) -> PlatformFault | None:
    """The `PlatformFault` behind an exception, if one is — raised as itself
    or wrapped (`raise ReviewUnavailable(...) from fault`)."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, PlatformFault):
            return exc
        exc = exc.__cause__ or exc.__context__
    return None


__all__ = ["PRECONDITIONS", "PlatformFault", "prepare", "served", "signs_in", "fault_of"]
