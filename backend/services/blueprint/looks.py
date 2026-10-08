"""One look per audience: the frame and the page rhythm each kind of person gets.

A shop's customers and its staff are two kinds of people in two kinds of
product. One frame and one rhythm for an application made its storefront a
console or its console a storefront, and when the design said nothing the
code filled the gap by reading words like "child" or "back-office" off the
personality paragraph (2026-10-08). Now the director decides a look for every
audience — every role, and `public` for visitors — from the product's domain
and category and how those people use it (`composition.looks`), and this
module only reads the decision: which look a page or a role has, what it
resolves to when a value is missing, and what is missing from it.

A value the Blueprint does not state is the platform's one default — the
application's own stated frame, else the frame every app had before any of
this was decided. Nothing here infers a look from words.
"""
from __future__ import annotations

from typing import Any

#: What the visitors who are not signed in are called in a look's audience.
PUBLIC = "public"


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def audiences(doc: dict) -> list[str]:
    """Who needs a look: every live role by id, and the visitors when any
    page is open to the public."""
    out = [str(r.get("id")) for r in _live(doc.get("roles")) if r.get("id")]
    if any(str(p.get("access") or "") == "public" for p in _live(doc.get("pages"))):
        out.append(PUBLIC)
    return out


def _role_names(doc: dict) -> dict[str, str]:
    return {str(r.get("id")): str(r.get("name") or r.get("id")) for r in _live(doc.get("roles"))}


def stated_looks(doc: dict) -> list[dict]:
    looks = (doc.get("composition") or {}).get("looks")
    return [lk for lk in looks or [] if isinstance(lk, dict) and lk.get("audience")]


def resolve(doc: dict, look: dict | None) -> dict[str, Any]:
    """A look with every value one the shell knows: the stated value, else the
    application's own frame (`designSystem.shell`) and rhythm
    (`composition.rhythm`), else the platform's default."""
    from services.blueprint.projection import CHROMES, TONES, derive_shell
    from services.blueprint.ui_engineer import RHYTHM_DEFAULT, RHYTHM_OPTIONS

    look = look or {}
    app = derive_shell(doc)
    stated_rhythm = (doc.get("composition") or {}).get("rhythm")
    base = dict(RHYTHM_DEFAULT)
    for source in (stated_rhythm, look.get("rhythm")):
        if isinstance(source, dict):
            base.update({k: str(v) for k, v in source.items()
                         if k in RHYTHM_OPTIONS and str(v) in RHYTHM_OPTIONS[k]})
    names = _role_names(doc)
    audience = [str(a) for a in look.get("audience") or []]
    return {
        "audience": audience,
        "names": [("visitors" if a == PUBLIC else names.get(a, a)) for a in audience],
        "experience": str(look.get("experience") or ""),
        "chrome": str(look.get("chrome")) if str(look.get("chrome") or "") in CHROMES else app["chrome"],
        "tone": str(look.get("tone")) if str(look.get("tone") or "") in TONES else app["tone"],
        "rhythm": base,
        "why": str(look.get("why") or ""),
    }


def resolved_looks(doc: dict) -> list[dict]:
    """Every stated look, resolved. Empty when the director stated none."""
    return [resolve(doc, lk) for lk in stated_looks(doc)]


def look_for(doc: dict, audience: str) -> dict[str, Any]:
    """The look of one audience (a role id or `public`): its own, or the
    application's frame and rhythm when it has none."""
    for lk in stated_looks(doc):
        if audience in [str(a) for a in lk.get("audience") or []]:
            return resolve(doc, lk)
    return resolve(doc, None)


def page_audience(doc: dict, page: dict) -> str | None:
    """Whose look a page is drawn in: the visitors' for a public page; else the
    first of its users that has a look; else nobody in particular."""
    if str(page.get("access") or "") == "public":
        return PUBLIC
    stated = {str(a) for lk in stated_looks(doc) for a in lk.get("audience") or []}
    for u in page.get("users") or []:
        if str(u) in stated:
            return str(u)
    return None


def look_for_page(doc: dict, page: dict | None) -> dict[str, Any]:
    if not page:
        return resolve(doc, None)
    who = page_audience(doc, page)
    return look_for(doc, who) if who else resolve(doc, None)


def look_findings(doc: dict, looks: list[dict]) -> list[str]:
    """What a set of looks leaves out or says twice, named so the director can
    mend it: every audience exactly once, nobody who is not an audience."""
    from services.blueprint.projection import CHROMES, TONES
    from services.blueprint.ui_engineer import RHYTHM_OPTIONS

    names = _role_names(doc)
    want = audiences(doc)
    said = lambda a: "the visitors (`public`)" if a == PUBLIC else f"{names.get(a, a)} (`{a}`)"  # noqa: E731
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, lk in enumerate(looks or [], 1):
        aud = [str(a) for a in lk.get("audience") or []] if isinstance(lk, dict) else []
        if not aud:
            out.append(f"look {i} names nobody it is for")
            continue
        for a in aud:
            if a not in want:
                out.append(f"look {i} is for {a}, who is not one of this application's audiences "
                           f"({', '.join(want)})")
            seen[a] = seen.get(a, 0) + 1
        if str(lk.get("chrome") or "") not in CHROMES and PUBLIC not in aud:
            out.append(f"look {i} ({', '.join(said(a) for a in aud)}) names no navigation (`chrome`)")
        if str(lk.get("tone") or "") not in TONES:
            out.append(f"look {i} ({', '.join(said(a) for a in aud)}) names no `tone`")
        rhythm = lk.get("rhythm") if isinstance(lk.get("rhythm"), dict) else {}
        missing = [k for k in RHYTHM_OPTIONS if str(rhythm.get(k) or "") not in RHYTHM_OPTIONS[k]]
        if missing:
            out.append(f"look {i} ({', '.join(said(a) for a in aud)}) has no page rhythm for "
                       + ", ".join(f"`{k}`" for k in missing))
    for a in want:
        if seen.get(a, 0) == 0:
            out.append(f"{said(a)} has no look")
        elif seen[a] > 1:
            out.append(f"{said(a)} has {seen[a]} looks — give them one")
    return out
