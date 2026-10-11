"""Organisations and who belongs to them are Smith's.

"Add an organisation called Northside Clinic", "move dave@clinic.com to
Northside as a Nurse": organisations are rows of the tenant entity, made
by the seed from the roster; a person's organisation and role live on the
roster beside their login, so a rebuild still knows. Every change is said
back with what it means for who sees what.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

VERBS = ("add_organisation", "move_login")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None, **more: Any) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or []), **more}


def _policy(doc: dict) -> dict:
    from services.blueprint.projection import tenancy_policy
    return tenancy_policy(doc)


def _name_in(text: str, lead: tuple[str, ...]) -> str:
    """The organisation's name after one of `lead` ("called", "named", "to")."""
    for word in lead:
        m = re.search(rf"\b{word}\s+[\"\u201c']?([^\"\u201d'\n,]+?)[\"\u201d']?\s*(?:\bas\b|$)", text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def add_organisation(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    policy = _policy(svc.doc)
    if policy["kind"] != "organisation":
        return _envelope(False, reason="This application serves one organisation. Say which record type IS the organisation "
                                       "(\"a clinic is an organisation; nurses belong to one\") and I will set it up for several.",
                         options=["Set the application up for several organisations"])
    text = (change or "").strip().rstrip(".")
    name = _name_in(text, ("called", "named", "organisation", "org", "branch,", "branch"))
    if not name:
        tail = re.split(r",\s*", text)
        name = tail[-1].strip() if len(tail) > 1 else ""
    if not name:
        return _envelope(False, reason="What is the organisation called?")
    from services.smith import accounts
    roster = accounts.load(output_dir)
    orgs = roster.setdefault("organisations", [])
    if any(str(o.get("name") or "").lower() == name.lower() for o in orgs):
        return _envelope(True, diff=f"{name} already exists.")
    orgs.append({"name": name})
    accounts.save(output_dir, roster)
    files = accounts.project(output_dir, app_root)
    tell(reasoning, f"Added the organisation {name}.", "step")
    member = policy["memberRoles"][0] if policy["memberRoles"] else "a member"
    return _envelope(True, diff=f"Added the organisation {name}. It exists the next time the app starts; its first member joins by "
                                f"invite (\"add a login for x@y.com in {name} as {member}\").", paths=files)


def move_login(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    policy = _policy(svc.doc)
    if policy["kind"] != "organisation":
        return _envelope(False, reason="This application serves one organisation; there is nowhere to move a login to.")
    m = _EMAIL.search(change or "")
    if not m:
        return _envelope(False, reason="Which login? Give the email address they sign in with.")
    email = m.group(0).lower()
    rest = (change or "")[m.end():]
    role = ""
    rm = re.search(r"\bas\s+(?:an?\s+)?([A-Za-z][A-Za-z ]*?)\s*$", rest)
    if rm:
        role = rm.group(1).strip()
        rest = rest[:rm.start()]
    org = _name_in(rest, ("to", "into", "in"))
    org = re.sub(r"^(the)\s+", "", org, flags=re.I).strip()
    org = re.sub(r"\s+(branch|organisation|org)$", "", org, flags=re.I).strip() or org
    if not org:
        return _envelope(False, reason=f"Move {email} to which organisation?")
    if role and policy["memberRoles"] and role not in policy["memberRoles"]:
        return _envelope(False, reason=f"{role!r} is not a member role. Members are: {', '.join(policy['memberRoles'])}.",
                         options=policy["memberRoles"][:4])
    from services.smith import accounts
    roster = accounts.load(output_dir)
    entry = accounts._entry(roster, email)
    if entry is None:
        return _envelope(False, reason=f"{email} has no login on the roster. Say \"add a login for {email} in {org}\" to make one.")
    entry["organisation"] = org
    if role:
        entry["role"] = role
    orgs = roster.setdefault("organisations", [])
    if not any(str(o.get("name") or "").lower() == org.lower() for o in orgs):
        orgs.append({"name": org})
    accounts.save(output_dir, roster)
    files = accounts.project(output_dir, app_root)
    tell(reasoning, f"{email} is in {org} now.", "step")
    return _envelope(True, diff=f"{email} belongs to {org}" + (f" as {role}" if role else "") + " from the next start; they see that organisation's records and no other's.",
                     paths=files)


def run(output_dir: str, verb: str, *, change: str = "", reasoning: Any = None) -> dict:
    from pathlib import Path

    from services.blueprint.service import BlueprintService
    if verb not in VERBS:
        return _envelope(False, reason=f"not a tenancy verb: {verb}")
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _envelope(False, reason="this project has no Blueprint yet.")
    app_root = Path(output_dir) / "app"
    fn = {"add_organisation": add_organisation, "move_login": move_login}[verb]
    try:
        return fn(svc, output_dir, change=change, app_root=app_root if app_root.is_dir() else None, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tenancy-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["VERBS", "add_organisation", "move_login", "run"]
