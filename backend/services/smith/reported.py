"""Who saw the problem, and where: the report a turn starts from.

A request to Smith carried only words. Who had seen the fault — a signed-out
shopper, a Merchant on /admin/orders, someone on a phone — was not in it, so
the trials ran as whoever the model guessed (the sign-up role, mostly), and
"Add to cart works — I ran it directly" was the answer to a button that
never called it (E-commerce, 2026-10-09). The panel now sends what it can
see — the screen they were on, who they were signed in as, the viewport —
and the turn reproduces as that person, on that screen, through the screen,
before it changes anything.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Mapping

#: The report of the turn in progress, for the trials to read who to be.
REPORTED: ContextVar[dict] = ContextVar("smith_reported", default={})

#: Trials that go through the screen, as a person would. `try_workflow` and
#: `try_request` post to the API and prove nothing about a button.
BROWSER_TRIALS: frozenset[str] = frozenset({"open_page", "try_expectation", "try_upload"})


def clean(report: Any) -> dict:
    """The report as a plain dict with the fields the turn reads."""
    if not isinstance(report, Mapping):
        return {}
    out: dict = {}
    for k in ("route", "role", "device", "screenshot"):
        v = report.get(k)
        if v not in (None, ""):
            out[k] = str(v)
    if "signedIn" in report and report.get("signedIn") is not None:
        out["signedIn"] = bool(report.get("signedIn"))
    vp = report.get("viewport")
    if isinstance(vp, Mapping) and vp.get("width"):
        out["viewport"] = {"width": int(vp.get("width") or 0), "height": int(vp.get("height") or 0)}
    return out


def who(report: Mapping[str, Any], roles: list[str] | None = None) -> str:
    """Whom to reproduce as: `guest` when they were signed out, their role
    when it is one of the app's, else nobody in particular."""
    if report.get("signedIn") is False:
        return "guest"
    role = str(report.get("role") or "")
    if role and (roles is None or role in roles):
        return role
    return ""


def block(report: Mapping[str, Any]) -> str:
    """What the turn is told first: who saw it, where, on what."""
    if not report:
        return ""
    person = ("a signed-out visitor" if report.get("signedIn") is False
              else (f"a {report['role']}" if report.get("role") else "someone signed in"))
    where = f" on {report['route']}" if report.get("route") else ""
    vp = report.get("viewport") or {}
    screen = ""
    if vp.get("width"):
        kind = "a phone" if vp["width"] < 768 else ("a tablet" if vp["width"] < 1024 else "a desktop")
        screen = f", {kind} ({vp['width']}×{vp.get('height') or '?'})"
    device = f" ({report['device']})" if report.get("device") else ""
    return (f"WHO SAW IT: {person}{where}{screen}{device}. Reproduce as them, on that screen, through the "
            f"screen (`open_page` as `{who(report) or 'them'}`" + (f" on `{report['route']}`" if report.get("route") else "")
            + "), before changing anything; a process run directly is not what they saw.\n\n")


__all__ = ["REPORTED", "BROWSER_TRIALS", "clean", "who", "block"]
