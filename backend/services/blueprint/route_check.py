"""Every route answers as its declaration says, for every kind of person.

The page contract declares who may open a page (`access`: public,
authenticated, role_restricted with `users`), and the projection writes a
middleware from it: a visitor who is not signed in is sent to `/login`, a
signed-in person of the wrong role to `/403`. Nothing measured that the
built application does so — a 307 to /login is a perfectly successful HTTP
exchange — until the person found "Go to Vendor Dashboard" landing on 403
(Ecom L1, 2026-10-11).

This is plain HTTP, no browser and no model: one request per page per
person (every role and signed out), with the redirect reported rather than
followed (`trials._http`). What the request could not reach — the app
refused the connection, a record page has no record to open — is `untried`,
the check's own shortfall, never the application's.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)

SIGNED_OUT = "signed out"
_SIGN_IN = re.compile(r"/(login|signin|sign-in)(\?|$|/)")
_FORBIDDEN = re.compile(r"/403(\?|$|/)")


def expected_outcomes(doc: dict) -> list[dict]:
    """`{page, name, route, as, expect}` for every live page and every kind
    of person; `expect` is "200", "sign-in" (a visitor is sent to sign in)
    or "403" (a signed-in person of another role is refused)."""
    from services.blueprint.account_model import has_sign_in
    from services.blueprint.projection import restricted_roles
    from services.blueprint.scope import built_view

    view = built_view(doc)
    roles = [str(r.get("name")) for r in view.get("roles") or []
             if isinstance(r, dict) and r.get("name") and r.get("status") != "DEPRECATED"]
    sign_in = has_sign_in(view)
    out: list[dict] = []
    for p in view.get("pages") or []:
        if not isinstance(p, dict) or not p.get("route") \
                or str(p.get("status") or "").upper() in ("DEPRECATED", "REMOVED"):
            continue
        base = {"page": str(p.get("id")), "name": str(p.get("name") or p["route"]), "route": str(p["route"]),
                "entity": str((p.get("data") or {}).get("primaryEntity") or "")}
        if p.get("pattern") == "auth":
            out.append({**base, "as": SIGNED_OUT, "expect": "200"})
            continue
        access = str(p.get("access") or "authenticated")
        if access == "public":
            out.append({**base, "as": SIGNED_OUT, "expect": "200"})
            out += [{**base, "as": r, "expect": "200"} for r in roles]
            continue
        if sign_in:
            out.append({**base, "as": SIGNED_OUT, "expect": "sign-in"})
        if access == "role_restricted":
            allowed = set(restricted_roles(view, p))
            out += [{**base, "as": r, "expect": "200" if r in allowed else "403"} for r in roles]
        else:
            out += [{**base, "as": r, "expect": "200"} for r in roles]
    return out


def outcome_findings(status: int, location: str, visit: dict) -> list[str]:
    """What is wrong with one answer to one person, or nothing."""
    expect, who, route = visit["expect"], visit["as"], visit["route"]
    to_sign_in = bool(_SIGN_IN.search(location or ""))
    forbidden = status == 403 or bool(_FORBIDDEN.search(location or ""))
    if expect == "200":
        if to_sign_in:
            return [f"it sends {'a visitor' if who == SIGNED_OUT else 'a signed-in ' + who} to sign in"]
        if forbidden:
            return [f"it refuses {who}, who it is for"]
        if status >= 400:
            return [f"it answers HTTP {status} to {who}"]
        return []
    if expect == "sign-in":
        if to_sign_in:
            return []
        if status < 400 and not location:
            return ["it opens for a visitor who is not signed in"]
        if forbidden:
            return ["it sends a visitor who is not signed in to the 403 page instead of to sign in"]
        return [f"it answers HTTP {status} to a visitor instead of sending them to sign in"]
    # expect == "403"
    if forbidden:
        return []
    if to_sign_in:
        return [f"it sends a signed-in {who} to sign in instead of refusing them"]
    if status < 400:
        return [f"a {who} can open {route}, which is not for them"]
    return []


def _fill(route: str, entity_name: str, records: dict[str, list[dict]]) -> str | None:
    """A concrete address for a `[param]` route, from a real record of the
    page's record type; None when there is none to open."""
    if "[" not in route:
        return route
    rows = records.get(entity_name) or []
    if not rows:
        return None
    return re.sub(r"\[[^\]]+\]", str(rows[0].get("id")), route)


def check_routes(app: Any, doc: dict, *, only: set[str] | None = None,
                 records: dict[str, list[dict]] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Ask every route as every person; `{total, green, red, untried}` with
    `green` the items that answered as declared."""
    from services.blueprint.process_trials import _records
    from services.smith.trials import _http, _session

    entities = {str(e.get("id")): str(e.get("name")) for e in (doc.get("data") or {}).get("entities") or []
                if isinstance(e, dict)}
    todo = [v for v in expected_outcomes(doc) if only is None or v["page"] in only]
    if records is None:
        try:
            records = _records(app, doc) if any("[" in v["route"] for v in todo) else {}
        except Exception:  # noqa: BLE001 — no records to fill with
            records = {}
    jars: dict[str, list[dict] | None] = {}
    no_session: dict[str, int] = {}
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    for v in todo:
        label = f"{v['name']} as {v['as']}"
        it = lambda why: item(f"{v['page']}::{v['as']}", label, why, v["page"])  # noqa: E731
        if cancelled():
            untried.append(it("stopped by the person"))
            continue
        path = _fill(v["route"], entities.get(v["entity"], ""), records)
        if path is None:
            untried.append(it("no record to open it on"))
            continue
        if v["as"] not in jars:
            try:
                jars[v["as"]] = _session(app, doc, v["as"])[1]
            except Exception as exc:  # noqa: BLE001 — a role the copy has no login for
                logger.warning("[route-check] no session for %s: %s", v["as"], exc)
                jars[v["as"]] = None
        jar = jars[v["as"]]
        if jar is None:
            # ONE CAUSE, SAID ONCE. 106 screens each reported "could not sign in"
            # (fyuhs16i, 2026-10-06); the fault is the sign-in, not the screens.
            if v["as"] not in no_session:
                no_session[v["as"]] = 0
            no_session[v["as"]] += 1
            untried.append(it(f"could not sign in as {v['as']} — one cause for every screen of that role, "
                              "not a fault of this screen"))
            continue
        try:
            status, location, _body = _http(app, "GET", path, None, jar)
        except Exception as exc:  # noqa: BLE001 — the app did not answer: the check's shortfall
            untried.append(it(f"the app did not answer: {str(exc)[:160]}"))
            continue
        found = outcome_findings(int(status), str(location or ""), v)
        (red if found else green).append(it(found[0] if found else f"answers as declared ({v['expect']})"))
    out = {"total": len(todo), "green": green, "red": red, "untried": untried}
    if no_session:
        out["causes"] = [f"could not sign in as {role}: {n} screens not tried" for role, n in no_session.items()]
    return out


__all__ = ["SIGNED_OUT", "check_routes", "expected_outcomes", "outcome_findings"]
