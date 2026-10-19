"""What Smith is doing, said as it does it.

Occupied time feels shorter than waiting. A person who can read "Opening
/orders as a Manager… it fails with HTTP 500. Reading the page's load code…
the query names a field that was renamed. Editing it. Trying /orders again…
it works" is following a story; one who reads "Still working on it" every
five minutes is standing at an empty carousel (2026-10-17). Every line here
is deterministic, from the step's tool and arguments or from what the step
reported — never from the model's reasoning, which streams separately.
"""
from __future__ import annotations

from typing import Any

from services.smith import tools


def _who(args: dict) -> str:
    who = str(args.get("as") or "").strip()
    return f" as {who}" if who else ""


def _first(text: str, n: int = 160) -> str:
    return " ".join((text or "").split("\n", 1)[0].split())[:n]


def _reason(args: dict) -> str:
    why = str(args.get("because") or args.get("why") or "").strip()
    why = " ".join(why.split())[:120]
    return f" — {why}" if why else ""


def _human(verb: str) -> str:
    return verb.replace("_", " ").strip().capitalize()


def starting(tool: str, args: dict | None) -> str:
    """The present-tense line for a step about to run; "" for a step that
    ends the turn (its answer speaks for itself)."""
    a = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    t = (tool or "").strip()
    if not t or t in tools.TERMINAL_NAMES:
        return ""
    if t == "open_page":
        route = str(a.get("route") or "/")
        if str(a.get("sign_in") or "").lower() in ("true", "1", "yes"):
            return f"Signing in through the sign-in form{_who(a)} and seeing where it lands…"
        if str(a.get("press") or "").lower() in ("all", "true", "1", "yes", "every"):
            return f"Opening {route}{_who(a)} and pressing every control on it…"
        return f"Opening {route}{_who(a)}…"
    if t == "try_workflow":
        return f"Running the {a.get('workflow') or 'process'} process{_who(a)}, the way its button would…"
    if t == "try_request":
        return f"Asking the app {str(a.get('method') or 'GET').upper()} {a.get('path') or '/'}{_who(a)}…"
    if t == "run_checks":
        what = str(a.get("what") or "all")
        return ("Running the application's own checks — every screen as every kind of person, every record "
                "scope, every rule…" if what == "all" else f"Running the application's {what} checks…")
    if t == "try_upload":
        return f"Uploading a small {a.get('kind') or 'image'}{_who(a)} the way the form's picker does…"
    if t == "read_file" and isinstance(a.get("paths"), list) and a.get("paths"):
        names = [str(p).rsplit("/", 1)[-1] for p in a["paths"][:3]]
        return f"Reading {', '.join(names)} together…"
    if t in ("read_file", "read_page_code"):
        return f"Reading {a.get('path') or a.get('route') or a.get('page') or 'the code'}…"
    if t == "open_error":
        return "Opening the code the error points at…"
    if t in ("grep", "find"):
        return f"Searching the code for “{a.get('pattern') or a.get('query') or a.get('text') or '…'}”…"
    if t == "list_files":
        return f"Looking at what is in {a.get('path') or 'the app'}…"
    if t == "read_rows":
        return f"Reading the {a.get('entity') or a.get('table') or ''} records…".replace("the  records", "the records")
    if t == "read_section":
        return f"Reading the definition's {a.get('section') or 'section'}…"
    if t == "dependents":
        return f"Finding what depends on {a.get('name') or a.get('path') or 'it'}…"
    if t == "edit_file":
        return f"Editing {a.get('path') or 'the file'}{_reason(a)}…"
    if t == "edit_definition":
        return f"Editing the definition{_reason(a)}…"
    if t == "write_page_code":
        return f"Rewriting the {a.get('page') or a.get('route') or ''} screen{_reason(a)}…".replace("the  screen", "the screen")
    if t == "rewrite_pages":
        pages = a.get("pages") or a.get("routes") or []
        n = len(pages) if isinstance(pages, list) else 0
        return (f"Laying out {n} screens again{_reason(a)}…" if n and pages != ["all"]
                else f"Laying out every screen again{_reason(a)}…")
    if t == "write_section":
        return f"Changing the definition's {a.get('section') or 'section'}{_reason(a)}…"
    if t == "write_frame":
        return f"Changing the frame around every screen{_reason(a)}…"
    if t == "write_phone_screens":
        return "Laying out the phone screens…"
    if t == "set_field":
        return f"Setting {a.get('field') or a.get('path') or 'the field'}…"
    if t == "verify_pages":
        return "Judging the screens against how they should look…"
    if t == "fetch_url":
        return f"Reading {a.get('url') or 'the page'}…"
    if t == "look_at_site":
        return f"Looking at {a.get('url') or 'the site'}…"
    if t == "list_services":
        return "Checking what the organisation has connected…"
    if t == "call_api":
        return f"Calling {str(a.get('method') or 'GET').upper()} {a.get('url') or 'the service'}…"
    if t == "app_mcp":
        act_ = str(a.get("action") or "status").lower()
        return {"on": "Turning on assistant access to the app…", "off": "Turning off assistant access to the app…"}.get(
            act_, "Checking what assistants can do in the app…")
    if t == "check_services":
        return "Checking the app's calls to outside services against their documentation…"
    if t == "call_mcp_tool":
        return f"Running {a.get('tool') or 'a tool'} on {a.get('server') or 'the MCP server'}…"
    if t == "open_decisions":
        return "Checking what the brief leaves unsaid…"
    if t == "define_application":
        return "Working out the application from the brief…"
    if t == "use_template":
        return "Starting from the template…"
    about = ""
    for key in ("route", "path", "name", "workflow", "entity", "page", "section", "field"):
        if a.get(key):
            about = f" {str(a[key])[:60]}"
            break
    return f"{_human(t)}{about}{_reason(a)}…"


def seen(tool: str, args: dict | None, status: str, said: str, *, after_change: bool = False) -> str:
    """What the step showed, for the lines that change what the person
    expects: a try that failed (the fault is found), a try that passed after
    a change (it works), a change that landed, a step that could not be
    done. Reads are silent — their line was the start."""
    from services.smith import trials
    t = (tool or "").strip()
    head = _first(said or "")
    if tools.is_trial(t):
        if trials.SERVER_RESTARTED in (said or "") or trials._SERVER_GONE.search(said or ""):
            return "The app's server was not there to answer that; trying it again."
        if (said or "").startswith("The app could not be started"):
            return f"Could not try it: {head}"
        if t == "run_checks":
            bad = [l.strip() for l in (said or "").splitlines() if l.strip().startswith(trials.CHECK_RED)]
            heads = [l.strip() for l in (said or "").splitlines() if l.startswith("checks ·")]
            line = "; ".join(h.replace("checks · ", "") for h in heads[:3])
            return (f"Checks: {line}. Not right: {bad[0].lstrip(trials.CHECK_RED).strip()}"
                    + (f" (and {len(bad) - 1} more)" if len(bad) > 1 else "") if bad else f"Checks: {line}.")
        if trials.failed(said or ""):
            return f"Found it: {head}" if not after_change else f"Still failing after the change: {head}"
        return f"It works now: {head}" if after_change else f"Seen: {head}"
    if tools.is_write(t) or t in tools.REQUIRED_BY_VERB or t in tools.DEFINITION_NAMES:
        if status == "finding":
            return f"Could not do that: {head}"
        if status in ("resolved",):
            return f"Changed: {head}" if head else "Changed."
        if status == "needs_user":
            return ""
        return ""
    return ""


def opening(known: bool, has_app: bool, defined: bool = True) -> str:
    """The first word, before any model call."""
    if not defined:
        return "Reading what you have said so far…"
    if not has_app:
        return ("Picking up from what I learned on this last time…" if known
                else "On it: reading the definition and what that points at…")
    if known:
        return "Picking up from what I learned on this last time, then looking at it the way you did…"
    return "On it: I will see it the way you did, read what that points at, change it, and try it again…"


__all__ = ["starting", "seen", "opening"]
