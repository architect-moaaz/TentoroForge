"""How people sign in is Smith's to change.

"Sign in by magic link only", "turn passwords off", "people in the Finance
group are Accountants", "only @acme.com may sign in": the policy lives in
`security.signIn`, is projected into the app and read by its sign-in. A
change that would leave nobody a way in is refused in words.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

VERBS = ("set_sign_in_method", "map_sso_roles", "restrict_sign_in_domains")
_DOMAIN = re.compile(r"@?\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.I)


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None, **more: Any) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or []), **more}


def _sign_in(svc: Any) -> dict:
    sec = svc.doc.setdefault("security", {})
    si = sec.setdefault("signIn", {})
    si.setdefault("password", True)
    si.setdefault("magicLink", False)
    si.setdefault("sso", [])
    return si


def _project(svc: Any, app_root: Any) -> list[str]:
    if app_root is None:
        return []
    from services.blueprint.projection import project_sign_in
    return list(project_sign_in(svc.doc, app_root).get("files") or [])


def _said(si: dict) -> str:
    ways = ([("email and password")] if si.get("password") is not False else []) \
        + (["a link by email"] if si.get("magicLink") else []) \
        + [str(e.get("name") or e.get("id")) for e in si.get("sso") or [] if isinstance(e, dict)]
    return "People sign in with " + (", ".join(ways[:-1]) + " or " + ways[-1] if len(ways) > 1 else ways[0]) + "."


def set_sign_in_method(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    text = (change or "").lower()
    si = _sign_in(svc)
    before = svc.snapshot()
    want = dict(si)
    off = any(w in text for w in ("off", "no password", "without password", "no more password", "remove password", "drop password", "instead of password"))
    only = "only" in text
    magic = any(w in text for w in ("magic link", "magic-link", "link by email", "email link", "sign-in link", "login link", "by link", "emailed link"))
    password_word = "password" in text
    if magic:
        want["magicLink"] = not ("off" in text and "magic" in text and not only)
        if only or off:
            want["password"] = False
    elif password_word:
        if off:
            want["password"] = False
        elif only:
            want["password"], want["magicLink"] = True, False
        else:
            want["password"] = True
    else:
        return _envelope(False, reason="Which way in? Say \"sign in by magic link only\", \"turn passwords off\", \"turn on magic links\" or \"passwords only\".",
                         options=["Sign in by magic link only", "Turn on magic links as well", "Passwords only"])
    if want.get("password") is False and not want.get("magicLink") and not want.get("sso"):
        return _envelope(False, reason="With passwords off and no magic link or identity provider, nobody could sign in. Turn on magic links or connect a provider first.",
                         options=["Sign in by magic link only", "Connect sign-in to Microsoft 365"])
    si.update(want)
    svc.save()
    svc.commit(user_request=change, smith_interpretation=_said(si), before=before, affected=[])
    files = _project(svc, app_root)
    tell(reasoning, _said(si), "step")
    note = "" if si.get("password") is not False else " There is no sign-up page now: a person arrives by link or through their organisation."
    return _envelope(True, diff=_said(si) + note, paths=files)


def _entries(si: dict, text: str) -> list[dict]:
    named = [e for e in si.get("sso") or [] if isinstance(e, dict)
             and (str(e.get("name") or "").lower() in text or str(e.get("id") or "").lower() in text)]
    return named or [e for e in si.get("sso") or [] if isinstance(e, dict)]


def map_sso_roles(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    from services.smith.section_change import find_named
    si = _sign_in(svc)
    entries = _entries(si, (change or "").lower())
    if not entries:
        return _envelope(False, reason="No identity provider is connected yet. Say \"connect sign-in to Microsoft 365\" (or Google, Okta, SAML) first.",
                         options=["Connect sign-in to Microsoft 365"])
    roles = [r for r in svc.doc.get("roles") or [] if isinstance(r, dict)]
    text = (change or "").strip().rstrip(".")
    pairs: list[tuple[str, str]] = []
    default: str | None = None
    for part in re.split(r"[;,]\s*|\s+and\s+", text):
        m = re.search(r"(?:^|\s)(?:in|from|of|the)\s+(?:the\s+)?[\"“']?([A-Za-z0-9 _-]+?)[\"”']?\s+group\s+"
                      r"(?:signs?\s+in\s+as|logs?\s+in\s+as|are|is|become|get|maps?\s+to|→|->)\s+(?:an?\s+)?([A-Za-z][A-Za-z ]*)$", part.strip(), re.I) \
            or re.search(r"^[\"“']?([A-Za-z0-9 _-]+?)[\"”']?\s*(?:→|->|=|maps to)\s*(?:an?\s+)?([A-Za-z][A-Za-z ]*)$", part.strip(), re.I)
        d = re.search(r"(?:everyone else|anyone else|others|by default|default)\s+(?:is|are|gets|:)?\s*(?:an?\s+)?([A-Za-z][A-Za-z ]*)$", part.strip(), re.I)
        if d:
            default = d.group(1).strip()
        elif m:
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    if not pairs and not default:
        return _envelope(False, reason="Say which group is which role: \"people in the Finance group are Accountants, everyone else is a Viewer\".")
    unknown = [r for _, r in pairs if find_named(roles, r, id_prefix="ROLE-") is None] + ([default] if default and find_named(roles, default, id_prefix="ROLE-") is None else [])
    if unknown:
        return _envelope(False, reason=f"{', '.join(sorted(set(unknown)))}: not a role of this application. Roles are: {', '.join(str(r.get('name')) for r in roles)}.",
                         options=[str(r.get("name")) for r in roles][:4])
    before = svc.snapshot()
    for e in entries:
        rf = e.setdefault("roleFrom", {"claim": "groups", "map": {}})
        rf.setdefault("claim", "groups")
        rf.setdefault("map", {})
        for group, role in pairs:
            rf["map"][group] = str(find_named(roles, role, id_prefix="ROLE-").get("id"))
        if default:
            rf["default"] = str(find_named(roles, default, id_prefix="ROLE-").get("id"))
    svc.save()
    said = "; ".join(f"the {g} group signs in as {r}" for g, r in pairs) + (f"; everyone else as {default}" if default else "")
    svc.commit(user_request=change, smith_interpretation=said, before=before, affected=[])
    files = _project(svc, app_root)
    tell(reasoning, said.capitalize() + ".", "step")
    return _envelope(True, diff=f"For {', '.join(str(e.get('name')) for e in entries)}: {said}. The provider's groups decide the role on every sign-in.", paths=files)


def restrict_sign_in_domains(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    si = _sign_in(svc)
    text = (change or "")
    entries = _entries(si, text.lower())
    if not entries:
        return _envelope(False, reason="No identity provider is connected yet; domains limit who may sign in through one. Say \"connect sign-in to Google\" first.",
                         options=["Connect sign-in to Google Workspace"])
    clear = any(w in text.lower() for w in ("any domain", "anyone", "every domain", "no restriction", "remove the restriction", "lift"))
    domains = [] if clear else sorted({m.group(1).lower() for m in _DOMAIN.finditer(text)})
    if not domains and not clear:
        return _envelope(False, reason="Which domains? Say \"only @acme.com may sign in\" or \"anyone may sign in\".")
    before = svc.snapshot()
    for e in entries:
        e["domains"] = domains
    svc.save()
    said = ("Anyone the provider knows may sign in." if clear else f"Only {', '.join('@' + d for d in domains)} may sign in") + \
        (f" through {', '.join(str(e.get('name')) for e in entries)}." if not clear else "")
    svc.commit(user_request=change, smith_interpretation=said, before=before, affected=[])
    files = _project(svc, app_root)
    tell(reasoning, said, "step")
    return _envelope(True, diff=said + ("" if clear else " Anyone else is refused in words."), paths=files)


def run(output_dir: str, verb: str, *, change: str = "", reasoning: Any = None) -> dict:
    from pathlib import Path

    from services.blueprint.service import BlueprintService
    if verb not in VERBS:
        return _envelope(False, reason=f"not a sign-in verb: {verb}")
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _envelope(False, reason="this project has no Blueprint yet.")
    app_root = Path(output_dir) / "app"
    fn = {"set_sign_in_method": set_sign_in_method, "map_sso_roles": map_sso_roles, "restrict_sign_in_domains": restrict_sign_in_domains}[verb]
    try:
        return fn(svc, output_dir, change=change, app_root=app_root if app_root.is_dir() else None, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sign-in-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["VERBS", "map_sso_roles", "restrict_sign_in_domains", "run", "set_sign_in_method"]
