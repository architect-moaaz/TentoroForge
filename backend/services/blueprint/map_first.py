"""A map-first phone screen: the map IS the screen, and the pages that are states of one job fold into it.

Forge writes one phone screen for each web page. That is right for a back office and wrong for a person out on the road: a
ride-hailing driver's app is one map with a sheet that changes (waiting, an offer, to the pickup, arrived, in the trip,
done), not a Home page, an Incoming page and an Active Trip page that each carry a map in a card. So a page may say, on its
`phone` setting:

    "phone": {"experience": "map_first", "covers": ["PAGE-004", "PAGE-005", "PAGE-006"]}

The page is written as `MapScreen`, and the pages it covers get no screen and no tab of their own: their data and their
controls are states of its sheet, and their addresses open the same screen. The web app is not touched: it keeps every page.

The roles that get this are named in `mobile.mapFirstRoles` (the platform plan decides it from what a role does: share a
position as it moves, navigate, take jobs as they arrive). This module holds the rules that are pure facts of the Blueprint.
"""
from __future__ import annotations

from typing import Any

EXPERIENCE = "map_first"


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED", "SUPERSEDED")]


def is_map_page(page: dict) -> bool:
    phone = page.get("phone")
    return isinstance(phone, dict) and phone.get("experience") == EXPERIENCE


def map_pages(doc: dict) -> list[dict]:
    return [p for p in _live(doc.get("pages")) if is_map_page(p)]


def covered_by(doc: dict) -> dict[str, str]:
    """Covered page id -> the map page that covers it. A page is covered once (by the first map page that names it), a map page
    never covers itself or another map page, and an id that is not a live page covers nothing."""
    live = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    maps = {str(p.get("id")) for p in map_pages(doc)}
    out: dict[str, str] = {}
    for page in map_pages(doc):
        for pid in (page.get("phone") or {}).get("covers") or []:
            pid = str(pid)
            if pid in live and pid not in maps and pid not in out:
                out[pid] = str(page.get("id"))
    return out


def covered_pages(doc: dict, page: dict) -> list[dict]:
    live = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    mine = str(page.get("id"))
    return [live[pid] for pid, cover in covered_by(doc).items() if cover == mine]


def roles_of(doc: dict, page: dict) -> set[str]:
    """The role names that may open a page (empty: anyone signed in)."""
    from services.blueprint.projection import restricted_roles
    return set(restricted_roles(doc, page))


def brief(doc: dict, page: dict) -> str:
    """What the native engineer is told about a map screen: that it is one screen with states, which pages it folds in, and the
    controls and data each one brings. Nothing is invented here: the pages, their purposes and their workflows are the Blueprint's."""
    from services.blueprint.app_sdk import workflow_keys

    keys = workflow_keys(doc)
    folded = covered_pages(doc, page)
    lines = [
        "THIS SCREEN IS THE MAP-FIRST HOME OF A PERSON OUT AND MOVING. The web has several pages for this job; the phone has ONE "
        "screen, whose map fills the glass (`MapScreen`) and whose bottom sheet changes with where the job is. Ignore the web "
        "page's layout (cards, bands, lists): take its facts and its controls.",
        "",
        "Pages folded into this screen (each is a STATE of the sheet, not a screen of its own):",
    ]
    for p in [page, *folded]:
        mine = [w for w in _live(doc.get("workflows")) if str(p.get("id")) in [str(x) for x in (w.get("launchedFrom") or [])]]
        runs = ", ".join(f"{w.get('name')} (workflows.{keys.get(str(w.get('id')), '?')})" for w in mine) or "none"
        tag = "this page" if p is page else "folded in"
        lines.append(f"- {p.get('name')} ({p.get('id')}, {p.get('route')}; {tag}): {p.get('purpose') or ''} Workflows it launches: {runs}.")
    lines += [
        "",
        "Build it as a state machine over the DATA, never over local flags: read the person's own current record and the offered "
        "records with the SDK hooks, derive the state on every render from their statuses, and let `useLive()` keep it fresh. A "
        "reopened app lands in the same state, and no state can be skipped because each sheet only offers the next valid action.",
        "States (name each one in the code; use the page purposes above for the words):",
        "1. WAITING (online, nothing assigned): the map follows the device; a compact `FloatingPanel` on top (who, online or "
        "offline switch through the page's own workflows, earnings today); a low `BottomSheet` with today's few numbers.",
        "2. OFFER (a record is offered to this person): a sheet OVER the map, not another screen: the few facts that decide "
        "(fare, distance to the pickup, time, where), the pickup and the route on the map, a visible countdown to the record's OWN "
        "expiry (never an invented duration), one `accent` Accept and a quiet Decline. An expired offer disappears.",
        "3. WORKING (this person holds a record): the map shows the road to the CURRENT target (`useRoute` from the device "
        "position to the pickup, then to the drop-off) with the distance and time; the sheet shows only the current step and its "
        "ONE `accent` action, which is the workflow for that step. Each step is a state: on the way, arrived, in progress.",
        "4. DONE: a short confirmation (what was earned) and one button back to waiting.",
        "Rules: the map is never inside a card or a scroll; never two filled buttons; every workflow listed above has a control "
        "in the state where it belongs; a status the data does not carry is not drawn; no made-up position, route or timer. The "
        "tab bar already holds the app's other destinations (earnings, history, profile): do NOT repeat them as floating buttons, "
        "and do not link to the pages folded into this screen. Floating buttons are for what helps the job now (call the rider, "
        "open the road in a navigation app).",
    ]
    return "\n".join(lines)


def findings(doc: dict) -> list[dict]:
    """`[{rule, page, detail}]` for a map screen the Blueprint cannot honour."""
    out: list[dict] = []
    live = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    maps = {str(p.get("id")) for p in map_pages(doc)}
    taken: dict[str, str] = {}
    for page in map_pages(doc):
        pid = str(page.get("id"))
        mine = roles_of(doc, page)
        for cid in (page.get("phone") or {}).get("covers") or []:
            cid = str(cid)
            if cid not in live:
                out.append({"rule": "map-screen-covers-no-page", "page": pid,
                            "detail": f"{page.get('route') or pid} says its map screen covers {cid}, which is not a page of this application."})
            elif cid in maps or cid == pid:
                out.append({"rule": "map-screen-covers-a-map-screen", "page": pid,
                            "detail": f"{page.get('route') or pid} covers {cid}, which is a map screen itself: cover the pages that are states of the job."})
            elif cid in taken and taken[cid] != pid:
                out.append({"rule": "map-screen-covered-twice", "page": pid,
                            "detail": f"{cid} is covered by both {taken[cid]} and {pid}: a page is a state of one map screen."})
            else:
                taken[cid] = pid
                theirs = roles_of(doc, live[cid])
                if mine and theirs and not theirs <= mine:
                    out.append({"rule": "map-screen-hides-a-page-from-its-people", "page": pid,
                                "detail": f"{live[cid].get('route') or cid} is for {', '.join(sorted(theirs))} but the map screen that covers "
                                          f"it is for {', '.join(sorted(mine))}: someone would lose a page they use."})
    # a role named map-first needs a map screen to go to
    names = {str(n) for n in ((doc.get("mobile") or {}).get("mapFirstRoles") or [])}
    if names and not maps:
        out.append({"rule": "map-first-role-without-a-map-screen", "page": "",
                    "detail": f"{', '.join(sorted(names))} {'is' if len(names) == 1 else 'are'} a map-first role (mobile.mapFirstRoles) "
                              "but no page has `phone: {experience: \"map_first\", covers: [...]}`: give its home page that setting "
                              "and name the pages that are states of its job."})
    return out
