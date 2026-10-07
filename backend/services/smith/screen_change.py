"""What a screen holds, changed after the build — its sections (2026-10-07).

A screen is a job, and it holds its records as `sections`: a list, the panel
a chosen record opens in, tabs of related records, dialogs (`PageSection`).
The planner decides them; nothing after the build could change them. Smith
could rewrite a page's code, so "add a refunds tab to support" became code
with no section behind it: the menu could not open the tab, a notification
could not land on its record, the check never opened it, and the next whole
rewrite — written from the sections — took it away again.

THE SECTIONS FIRST, THEN EVERYTHING THAT FOLLOWS FROM THEM. Each change is
made to the definition, deterministically, and committed as one version;
then what the definition implies is brought into step:

  * an action named on a section with no workflow behind it gets one, the way
    the build gives a screen's actions theirs (`section_slots`);
  * the menu: an entry a section names is placed, an entry for a section that
    went comes off, an entry for one that moved follows it;
  * workflows started from the part that moved or went are started from where
    it went, or from nowhere (said);
  * the application is written out again (shell, breadcrumbs, notification
    links, routes);
  * the screen's code is changed to draw exactly its sections — a split
    screen gains or loses its part files (`ui_engineer.reshape_screen`) — and
    a screen laid out from the template is laid out again.

THE VARIATIONS, AS VERBS. Adding, changing (its label, its records, list or
board or calendar or map, main or tab or panel or dialog, which list opens it,
its link, adding records there, live, its menu entry, its actions, who sees
it), removing, reordering, moving to another screen, folding a whole screen
into another as a section, and taking a section out into a screen of its own.
Each refuses what it cannot do with the reason and the names it could have
used, so the loop can call again rather than guess.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError

logger = logging.getLogger(__name__)

VERBS = ("add_section", "edit_section", "remove_section", "reorder_sections",
         "move_section", "merge_screens", "split_section")

#: A section's settings, as `new_section` and `set` name them.
SETTABLE = ("label", "entity", "shows", "placement", "opensFrom", "param", "addsHere", "live",
            "menuEntry", "actions", "roles")

#: Item-wise changes to a list setting: `add_actions: ["Refund"]`.
LIST_EDITS = {"add_actions": ("actions", True), "remove_actions": ("actions", False),
              "add_roles": ("roles", True), "remove_roles": ("roles", False)}

#: Where a new section goes among the others (`new_section` only).
POSITION = ("first", "after", "before")

#: New actions given a workflow in one change; past this they are said.
MAX_NEW_WORKFLOWS = 6

#: Query parameters the app already reads for itself.
_RESERVED_PARAMS = frozenset({"tab", "view", "q", "page", "sort"})


class ScreenChangeError(SectionChangeError):
    """The change could not be made; the reason says what would work."""


# --------------------------------------------------------------------------- #
# Finding things
# --------------------------------------------------------------------------- #

def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _live_pages(doc: dict) -> list[dict]:
    return [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("status") != "DEPRECATED"]


def _sections(page: dict) -> list[dict]:
    return [s for s in page.get("sections") or [] if isinstance(s, dict) and s.get("key")]


def find_page(doc: dict, ref: str) -> dict | None:
    from services.smith.page_change import find_page as _find
    return _find(doc, ref)


def find_section(page: dict, ref: Any) -> dict | None:
    """The section a person means: its key, its label, or the one label that
    contains what they said (or is contained in it)."""
    want = _norm(ref)
    if not want:
        return None
    secs = _sections(page)
    for s in secs:
        if want in (_norm(s["key"]), _norm(s.get("label"))):
            return s
    hits = [s for s in secs if _norm(s.get("label"))
            and (want in _norm(s.get("label")) or _norm(s.get("label")) in want)]
    return hits[0] if len(hits) == 1 else None


def describe(page: dict) -> str:
    secs = _sections(page)
    return ", ".join(f"{s.get('label') or s['key']} [{s['key']}]" for s in secs) or "(it has no sections yet)"


def _screens(doc: dict) -> str:
    return ", ".join(str(p.get("route")) for p in _live_pages(doc)) or "(none)"


def _page_or_raise(doc: dict, ref: str) -> dict:
    page = find_page(doc, ref)
    if page is None:
        raise ScreenChangeError(f"I cannot tell which screen {ref!r} means. The screens are: {_screens(doc)}.")
    return page


def _section_or_raise(page: dict, ref: Any) -> dict:
    sec = find_section(page, ref)
    if sec is None:
        raise ScreenChangeError(f"{page.get('name') or page.get('route')} has no section {str(ref)!r}. "
                                f"Its sections are: {describe(page)}.")
    return sec


def _entities(doc: dict) -> list[dict]:
    return [e for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("status") != "DEPRECATED"]


def _entity_id(doc: dict, ref: Any) -> str | None:
    want = _norm(ref)
    if not want:
        return None
    for e in _entities(doc):
        names = {_norm(e.get("id")), _norm(e.get("name")), _norm(e.get("table"))}
        if want in names or want.rstrip("s") in names or f"{want}s" in names:
            return str(e.get("id"))
    return None


def _entity_name(doc: dict, eid: Any) -> str:
    return next((str(e.get("name")) for e in _entities(doc) if str(e.get("id")) == str(eid)), str(eid or ""))


def _roles(doc: dict) -> list[dict]:
    return [r for r in doc.get("roles") or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def _role_ids(doc: dict, given: Any) -> tuple[list[str], list[str]]:
    """Role names or ids as ids; and what named no role."""
    items = given if isinstance(given, list) else [x for x in re.split(r"\s*,\s*", str(given or "")) if x]
    ids, unknown = [], []
    for item in items:
        want = _norm(item)
        hit = next((r for r in _roles(doc) if want in (_norm(r.get("id")), _norm(r.get("name")))), None)
        if hit is None:
            unknown.append(str(item))
        elif str(hit["id"]) not in ids:
            ids.append(str(hit["id"]))
    return ids, unknown


def _role_names(doc: dict, ids: list[str]) -> list[str]:
    names = {str(r.get("id")): str(r.get("name")) for r in _roles(doc)}
    return [names.get(str(i), str(i)) for i in ids]


def _unique_key(page: dict, label: Any, taken: set[str] | None = None) -> str:
    from services.blueprint.screen_parts import part_key
    have = {str(s["key"]) for s in _sections(page)} | (taken or set())
    key = base = part_key(label)
    n = 2
    while key in have:
        key, n = f"{base}-{n}", n + 1
    return key


def _default_param(page: dict, entity_name: str, sec: dict) -> str:
    words = re.findall(r"[A-Za-z0-9]+", entity_name) or ["record"]
    base = words[0].lower() + "".join(w.capitalize() for w in words[1:])
    used = {str(s.get("param")) for s in _sections(page) if s is not sec and s.get("param")} | _RESERVED_PARAMS
    param, n = base, 2
    while param in used:
        param, n = f"{base}{n}", n + 1
    return param


# --------------------------------------------------------------------------- #
# A section's settings
# --------------------------------------------------------------------------- #

def _strings(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"\s*[,;]\s*", str(value or ""))
    return list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))


def settle(doc: dict, page: dict, sec: dict, given: dict) -> list[str]:
    """Lay `given` onto `sec` and hold the result to what a section is.
    Returns the problems, each saying what would work instead."""
    from services.blueprint.page_planner import SECTION_PLACEMENTS, SECTION_SHOWS

    problems: list[str] = []
    for k, v in given.items():
        if k in ("key",) + POSITION:
            continue                                   # keys are stable; position is placement's
        if k == "label":
            if str(v or "").strip():
                sec["label"] = str(v).strip()
        elif k == "entity":
            if v in (None, ""):
                sec.pop("entity", None)
            else:
                eid = _entity_id(doc, v)
                if eid is None:
                    problems.append(f"there is no record called {v!r}; the records are: "
                                    + ", ".join(str(e.get("name")) for e in _entities(doc)))
                else:
                    sec["entity"] = eid
        elif k == "shows":
            val = str(v or "").strip().lower()
            if val not in SECTION_SHOWS:
                problems.append(f"`shows` is one of {', '.join(SECTION_SHOWS)}, not {v!r}")
            else:
                sec["shows"] = val
        elif k == "placement":
            val = str(v or "").strip().lower()
            if val not in SECTION_PLACEMENTS:
                problems.append(f"`placement` is one of {', '.join(SECTION_PLACEMENTS)}, not {v!r}")
            else:
                sec["placement"] = val
        elif k == "opensFrom":
            if not v:
                sec.pop("opensFrom", None)
            else:
                target = find_section(page, v)
                if target is None or target is sec:
                    problems.append(f"`opensFrom` names another section of this screen, not {v!r}; "
                                    f"its sections are: {describe(page)}")
                else:
                    sec["opensFrom"] = str(target["key"])
        elif k == "param":
            val = re.sub(r"[^A-Za-z0-9]", "", str(v or ""))
            if not val:
                sec.pop("param", None)
            elif val in _RESERVED_PARAMS:
                problems.append(f"`param` {val!r} is one the app already reads; name it after the record")
            else:
                sec["param"] = val
        elif k in ("addsHere", "live"):
            if v in (True, "true", "yes", 1):
                sec[k] = True
            else:
                sec.pop(k, None)
        elif k == "menuEntry":
            if str(v or "").strip():
                sec["menuEntry"] = " > ".join(p.strip() for p in str(v).split(">") if p.strip())
            else:
                sec.pop("menuEntry", None)
        elif k == "actions":
            sec["actions"] = _strings(v)
        elif k == "roles":
            ids, unknown = _role_ids(doc, v)
            if unknown:
                problems.append(f"there is no role {', '.join(map(repr, unknown))}; the roles are: "
                                + ", ".join(str(r.get("name")) for r in _roles(doc)))
            sec["roles"] = ids
        elif k in LIST_EDITS:
            field, adding = LIST_EDITS[k]
            if field == "roles":
                items, unknown = _role_ids(doc, v)
                if unknown:
                    problems.append(f"there is no role {', '.join(map(repr, unknown))}; the roles are: "
                                    + ", ".join(str(r.get("name")) for r in _roles(doc)))
            else:
                items = _strings(v)
            have = list(sec.get(field) or [])
            if adding:
                sec[field] = have + [i for i in items if _norm(i) not in {_norm(h) for h in have}]
            else:
                gone = {_norm(i) for i in items}
                if field == "roles":
                    gone |= {_norm(n) for n in _role_names(doc, items)}
                sec[field] = [h for h in have if _norm(h) not in gone]
        else:
            problems.append(f"a section has no setting {k!r}; it has: {', '.join(SETTABLE)}"
                            + f" (and {', '.join(LIST_EDITS)})")
    sec.setdefault("shows", "list")
    sec.setdefault("placement", "main")
    placement, shows = sec["placement"], sec["shows"]
    # WHAT A PLACEMENT MEANS. Only a panel or a dialog opens from another
    # section, and only a panel is opened by a link; a section moved from a
    # panel to a tab no longer has either.
    if placement not in ("panel", "dialog"):
        sec.pop("opensFrom", None)
    if placement != "panel":
        sec.pop("param", None)
    if shows != "summary" and not sec.get("entity"):
        problems.append(f"which records does {sec.get('label') or sec['key']} show? Set `entity` "
                        "(or `shows: summary` for a summary of several)")
    if placement == "panel" and sec.get("entity"):
        if not sec.get("opensFrom"):
            home = next((s for s in _sections(page) if s is not sec and s.get("entity") == sec["entity"]
                         and s.get("placement", "main") in ("main", "tab")), None)
            if home is not None:
                sec["opensFrom"] = str(home["key"])
        if shows == "record" and not sec.get("param"):
            sec["param"] = _default_param(page, _entity_name(doc, sec["entity"]), sec)
    if sec.get("param") and any(s is not sec and s.get("param") == sec["param"] for s in _sections(page)):
        problems.append(f"another section of this screen already opens by ?{sec['param']}=; give this one "
                        "its own `param`")
    if sec.get("opensFrom") and not any(s.get("key") == sec["opensFrom"] for s in _sections(page)):
        sec.pop("opensFrom", None)
    sec.setdefault("actions", [])
    sec.setdefault("roles", [])
    return problems


def _said(doc: dict, sec: dict) -> str:
    """`Refunds — a tab, a list of Refund, only for Lead`."""
    bits = [f"a {sec.get('placement', 'main')}" if sec.get("placement") != "main" else "on the screen itself"]
    if sec.get("entity"):
        bits.append(f"a {sec.get('shows', 'list')} of {_entity_name(doc, sec['entity'])}")
    if sec.get("roles"):
        bits.append("only for " + ", ".join(_role_names(doc, sec["roles"])))
    return f"{sec.get('label') or sec['key']} — " + ", ".join(bits)


def _difference(doc: dict, before: dict, after: dict) -> list[str]:
    def shown(k: str, v: Any) -> str:
        if k == "entity":
            return _entity_name(doc, v) if v else "none"
        if k == "roles":
            return ", ".join(_role_names(doc, v)) if v else "everyone the screen is for"
        if isinstance(v, list):
            return ", ".join(map(str, v)) or "none"
        if isinstance(v, bool):
            return "yes" if v else "no"
        return str(v) if v not in (None, "") else "none"
    out = []
    for k in SETTABLE:
        a, b = before.get(k), after.get(k)
        if (a or None) != (b or None):
            out.append(f"{k}: {shown(k, a)} → {shown(k, b)}")
    return out


# --------------------------------------------------------------------------- #
# The menu
# --------------------------------------------------------------------------- #

def _nav(doc: dict) -> list:
    return doc.setdefault("navigation", {}).setdefault("tree", [])


def _drop_menu(doc: dict, page_id: str, key: str | None) -> list[str]:
    """Entries opening this section (or the whole screen, `key=None`) come off.
    An entry with children stays as their heading."""
    dropped: list[str] = []

    def prune(nodes: list) -> list:
        out = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            hit = str(n.get("page") or "") == page_id and (key is None or str(n.get("section") or "") == key)
            if n.get("children"):
                n["children"] = prune(n["children"])
            if hit:
                dropped.append(str(n.get("label") or ""))
                if n.get("children"):
                    n.pop("page", None)
                    n.pop("section", None)
                else:
                    continue
            out.append(n)
        return out

    nav = doc.setdefault("navigation", {})
    if nav.get("tree"):
        nav["tree"] = prune(nav["tree"])
    return dropped


def _repoint_menu(doc: dict, from_page: str, from_key: str | None, to_page: str, to_key: str | None) -> list[str]:
    """Entries that opened the section (or screen) open where it went."""
    moved: list[str] = []

    def walk(nodes: list) -> None:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if str(n.get("page") or "") == from_page and (from_key is None
                                                          or str(n.get("section") or "") == from_key):
                n["page"] = to_page
                if to_key:
                    n["section"] = to_key
                else:
                    n.pop("section", None)
                moved.append(str(n.get("label") or ""))
            walk(n.get("children") or [])
    walk(_nav(doc))
    return moved


def _place_menu(doc: dict, page: dict, sec: dict) -> str:
    """The section's `menuEntry` as an entry that opens it — found by its
    label path, or made (with its headings) when the menu has none yet."""
    from services.blueprint.menu_binding import SEP
    path = [p.strip() for p in str(sec.get("menuEntry") or "").split(">") if p.strip()]
    if not path:
        return ""
    nodes = _nav(doc)
    node: dict | None = None
    for i, label in enumerate(path):
        node = next((n for n in nodes if isinstance(n, dict) and _norm(n.get("label")) == _norm(label)), None)
        if node is None:
            node = {"label": label}
            nodes.append(node)
        if i < len(path) - 1:
            nodes = node.setdefault("children", [])
    assert node is not None
    node["page"] = str(page["id"])
    node["section"] = str(sec["key"])
    return SEP.join(path)


# --------------------------------------------------------------------------- #
# Who runs what
# --------------------------------------------------------------------------- #

def _claims(sec: dict, wf: dict) -> bool:
    """A workflow is a section's when the section names it as an action, or
    adds the records it creates."""
    from services.blueprint.functional_completeness import _workflow_db_ops
    from services.blueprint.screen_parts import _workflow_entities
    if _norm(wf.get("name")) in {_norm(a) for a in sec.get("actions") or []}:
        return True
    return bool(sec.get("addsHere") and sec.get("entity")
                and str(sec["entity"]) in _workflow_entities(wf)
                and "insert" in {str(o).lower().replace("db_", "") for o in _workflow_db_ops(wf)})


def _launched_here(doc: dict, page_id: str) -> list[dict]:
    return [w for w in doc.get("workflows") or [] if isinstance(w, dict) and w.get("status") != "DEPRECATED"
            and page_id in [str(x) for x in w.get("launchedFrom") or []]]


def _carry_workflows(doc: dict, page: dict, secs: list[dict], to_page: dict | None) -> list[str]:
    """The workflows `secs` ran are started from `to_page` — or, removed, from
    nowhere on `page` — unless a section left on `page` still runs them."""
    pid = str(page["id"])
    staying = [s for s in _sections(page) if not any(s is x for x in secs)]
    said = []
    for wf in _launched_here(doc, pid):
        if not any(_claims(s, wf) for s in secs):
            continue
        launched = [str(x) for x in wf.get("launchedFrom") or []]
        if not any(_claims(s, wf) for s in staying):
            launched = [x for x in launched if x != pid]
        if to_page is not None and str(to_page["id"]) not in launched:
            launched.append(str(to_page["id"]))
        wf["launchedFrom"] = launched
        if to_page is not None:
            said.append(f"{wf.get('name')} is started from {to_page.get('name') or to_page.get('route')}")
        elif not launched and str((wf.get("trigger") or {}).get("kind") or "manual") == "manual":
            said.append(f"no screen starts {wf.get('name')} now (it is kept; `remove_workflow` retires it)")
    return said


def _with_dependents(page: dict, sec: dict) -> list[dict]:
    """A section and the panels and dialogs that open from it."""
    return [sec] + [s for s in _sections(page) if s is not sec and s.get("opensFrom") == sec["key"]
                    and s.get("placement") in ("panel", "dialog")]


# --------------------------------------------------------------------------- #
# The changes, to the definition
# --------------------------------------------------------------------------- #

def add_section(doc: dict, page: dict, given: dict) -> dict:
    given = {"label": given} if isinstance(given, str) else dict(given or {})
    label = str(given.get("label") or "").strip()
    if not label:
        raise ScreenChangeError("a new section needs a `label` — what a person calls it (\"Refunds\").")
    if find_section(page, label) is not None and _norm(find_section(page, label).get("label")) == _norm(label):
        raise ScreenChangeError(f"{page.get('name')} already has a section {label!r}; change it with "
                                "`edit_section` instead.")
    sec: dict = {"key": _unique_key(page, label), "label": label}
    secs = list(page.get("sections") or [])
    page["sections"] = secs + [sec]                      # in place, so `settle` sees its siblings
    problems = settle(doc, page, sec, {k: v for k, v in given.items() if k != "label"})
    if problems:
        page["sections"] = secs
        raise ScreenChangeError("; ".join(problems))
    # WHERE IT GOES: last, unless they said.
    rest = [s for s in page["sections"] if s is not sec]
    if given.get("first"):
        page["sections"] = [sec] + rest
    elif given.get("after") or given.get("before"):
        anchor = find_section({"sections": rest}, given.get("after") or given.get("before"))
        if anchor is None:
            page["sections"] = secs
            raise ScreenChangeError(f"there is no section {str(given.get('after') or given.get('before'))!r} "
                                    f"to place it beside; the sections are: {describe(page)}")
        i = rest.index(anchor) + (1 if given.get("after") else 0)
        page["sections"] = rest[:i] + [sec] + rest[i:]
    menu = _place_menu(doc, page, sec) if sec.get("menuEntry") else ""
    return {"what": f"added {_said(doc, sec)}", "menu": [menu] if menu else [], "workflows": []}


def edit_section(doc: dict, page: dict, ref: Any, given: dict) -> dict:
    if not isinstance(given, dict) or not given:
        raise ScreenChangeError("say what to change as `set`: any of " + ", ".join(SETTABLE)
                                + ", or " + ", ".join(LIST_EDITS))
    sec = _section_or_raise(page, ref)
    before = copy.deepcopy(sec)
    problems = settle(doc, page, sec, given)
    if problems:
        sec.clear()
        sec.update(before)
        raise ScreenChangeError("; ".join(problems))
    changed = _difference(doc, before, sec)
    if not changed:
        raise ScreenChangeError(f"{sec.get('label')} already is that: nothing about it would change.")
    menu: list[str] = []
    if (before.get("menuEntry") or "") != (sec.get("menuEntry") or ""):
        _drop_menu(doc, str(page["id"]), str(sec["key"]))
        if sec.get("menuEntry"):
            menu.append(_place_menu(doc, page, sec))
    return {"what": f"changed {before.get('label') or sec['key']} — " + "; ".join(changed),
            "menu": menu, "workflows": []}


def remove_section(doc: dict, page: dict, ref: Any) -> dict:
    sec = _section_or_raise(page, ref)
    going = _with_dependents(page, sec)
    flows = _carry_workflows(doc, page, going, None)
    menu = [m for s in going for m in _drop_menu(doc, str(page["id"]), str(s["key"]))]
    page["sections"] = [s for s in page.get("sections") or [] if not any(s is g for g in going)]
    for s in _sections(page):
        if s.get("opensFrom") in {g["key"] for g in going}:
            s.pop("opensFrom", None)
    names = ", ".join(str(g.get("label") or g["key"]) for g in going)
    return {"what": f"took {names} off the screen", "menu_dropped": menu, "workflows": flows}


def reorder_sections(doc: dict, page: dict, order: Any) -> dict:
    refs = order if isinstance(order, list) else _strings(order)
    picked: list[dict] = []
    for ref in refs:
        sec = _section_or_raise(page, ref)
        if not any(sec is p for p in picked):
            picked.append(sec)
    if not picked:
        raise ScreenChangeError(f"say the order as section names; the sections are: {describe(page)}")
    rest = [s for s in page.get("sections") or [] if not any(s is p for p in picked)]
    before = [s.get("key") for s in _sections(page)]
    page["sections"] = picked + rest
    if [s.get("key") for s in _sections(page)] == before:
        raise ScreenChangeError("the sections are already in that order.")
    return {"what": "put the sections in this order: " + ", ".join(str(s.get("label")) for s in _sections(page)),
            "menu": [], "workflows": []}


def _rekey(target: dict, moving: list[dict]) -> dict[str, str]:
    """New keys for sections arriving on `target`, where theirs are taken."""
    out: dict[str, str] = {}
    taken: set[str] = set()
    for s in moving:
        key = str(s["key"])
        new = key if not find_section(target, key) and key not in taken else _unique_key(target, s.get("label") or key,
                                                                                            taken)
        out[key] = new
        taken.add(new)
    return out


def move_section(doc: dict, page: dict, ref: Any, to_page: dict) -> dict:
    if to_page is page:
        raise ScreenChangeError("that section is already on that screen; `reorder_sections` changes its place.")
    sec = _section_or_raise(page, ref)
    moving = _with_dependents(page, sec)
    flows = _carry_workflows(doc, page, moving, to_page)
    keys = _rekey(to_page, moving)
    menu = []
    for s in moving:
        menu += _repoint_menu(doc, str(page["id"]), str(s["key"]), str(to_page["id"]), keys[str(s["key"])])
    page["sections"] = [s for s in page.get("sections") or [] if not any(s is m for m in moving)]
    arrived = []
    for s in moving:
        s = dict(s, key=keys[str(s["key"])])
        if s.get("opensFrom") in keys:
            s["opensFrom"] = keys[s["opensFrom"]]
        arrived.append(s)
    to_page["sections"] = list(to_page.get("sections") or []) + arrived
    _widen_users(doc, to_page, page, arrived)
    return {"what": f"moved {sec.get('label')} to {to_page.get('name') or to_page.get('route')}",
            "menu": menu, "workflows": flows}


def _widen_users(doc: dict, target: dict, source: dict, arrived: list[dict]) -> None:
    """Who could see the arrivals still can. A section moving onto a screen
    for fewer people keeps its people: they are added to the screen, and the
    section says it is theirs."""
    theirs = [str(u) for u in source.get("users") or []]
    mine = [str(u) for u in target.get("users") or []]
    if not mine or not theirs or set(theirs) <= set(mine):
        return
    target["users"] = mine + [u for u in theirs if u not in mine]
    for s in arrived:
        if not s.get("roles"):
            s["roles"] = list(theirs)


def merge_screens(doc: dict, into: dict, from_page: dict) -> dict:
    """`from_page` becomes sections of `into`: its main sections as tabs (or a
    tab for the records it shows, when it names no sections), its panels and
    dialogs with them. Its menu entries, links, workflows, widgets and
    landing follow; the page itself is retired by the caller."""
    if into is from_page:
        raise ScreenChangeError("a screen cannot be folded into itself.")
    moving = [dict(s) for s in _sections(from_page)]
    if not moving:
        entity = (from_page.get("data") or {}).get("primaryEntity")
        if not entity:
            raise ScreenChangeError(f"{from_page.get('name')} names no records and no sections, so there is "
                                    "nothing to fold in as a section; describe it with `add_section` instead.")
        from services.blueprint.screen_parts import part_key
        moving = [{"key": part_key(from_page.get("name") or "records"), "label": str(from_page.get("name") or "Records"),
                   "entity": str(entity), "shows": "list", "placement": "main", "actions": [], "roles": []}]
    keys = _rekey(into, moving)
    arrived = []
    for s in moving:
        old = str(s["key"])
        s["key"] = keys[old]
        if s.get("opensFrom") in keys:
            s["opensFrom"] = keys[s["opensFrom"]]
        if s.get("placement", "main") == "main" and _sections(into):
            s["placement"] = "tab"
        arrived.append(s)
    into["sections"] = list(into.get("sections") or []) + arrived
    _widen_users(doc, into, from_page, arrived)
    first = next((s for s in arrived if s.get("placement") in ("main", "tab")), arrived[0])
    fid, iid = str(from_page["id"]), str(into["id"])
    menu = []
    for old, new in keys.items():
        menu += _repoint_menu(doc, fid, old, iid, new)
    menu += _repoint_menu(doc, fid, None, iid, str(first["key"]) if first.get("placement") == "tab" else None)
    for wf in _launched_here(doc, fid):
        launched = [str(x) for x in wf.get("launchedFrom") or [] if str(x) != fid]
        wf["launchedFrom"] = launched + ([iid] if iid not in launched else [])
    for p in _live_pages(doc):
        if fid in [str(x) for x in p.get("navigatesTo") or []]:
            p["navigatesTo"] = list(dict.fromkeys(iid if str(x) == fid else str(x)
                                                  for x in p["navigatesTo"] if str(x) != str(p.get("id"))))
    for w in doc.get("widgets") or []:
        if isinstance(w, dict) and str(w.get("page") or "") == fid and w.get("status") != "DEPRECATED":
            w["page"] = iid
    nav = doc.setdefault("navigation", {})
    initial = nav.get("initialRoute") if isinstance(nav.get("initialRoute"), dict) else None
    if initial:
        nav["initialRoute"] = {k: (into.get("route") if v == from_page.get("route") else v) for k, v in initial.items()}
    return {"what": f"folded {from_page.get('name')} into {into.get('name')} as "
                    + ", ".join(f"{s.get('label')} ({s.get('placement')})" for s in arrived),
            "menu": menu, "workflows": [], "tab": str(first["key"])}


def split_section(svc: Any, page: dict, ref: Any, new_route: str, request: str) -> tuple[dict, dict]:
    """The section (with its panels and dialogs) as a screen of its own."""
    from services.smith.compose import _ensure_page

    doc = svc.doc
    sec = _section_or_raise(page, ref)
    route = (new_route or "").strip() or f"{str(page.get('route') or '').rstrip('/')}/{sec['key']}"
    if not route.startswith("/"):
        route = "/" + route
    if "[" in route:
        raise ScreenChangeError("a screen of its own needs a fixed address, not one with [brackets].")
    if find_page(doc, route) is not None:
        raise ScreenChangeError(f"{route} is already a screen; `move_section` puts the section on it.")
    moving = _with_dependents(page, sec)
    new = _ensure_page(svc, route, request, entity=str(sec.get("entity") or ""))
    doc = svc.doc
    page = next(p for p in doc.get("pages") or [] if str(p.get("id")) == str(page["id"]))
    moving = [s for s in _sections(page) if any(s.get("key") == m.get("key") for m in moving)]
    new["name"] = str(sec.get("label") or new.get("name"))
    new["purpose"] = (f"{sec.get('label')} — taken out of {page.get('name')} into a screen of its own. "
                      + str(page.get("purpose") or ""))[:280]
    for k in ("module", "access"):
        if page.get(k):
            new[k] = page[k]
    new["users"] = list(sec.get("roles") or page.get("users") or [])
    flows = _carry_workflows(doc, page, moving, new)
    arrived = []
    for s in moving:
        s = dict(s)
        if s is moving[0] or s.get("key") == sec["key"]:
            s["placement"] = "main" if s.get("placement") in ("tab", "main") else s.get("placement")
            s["roles"] = []
        arrived.append(s)
    new["sections"] = arrived
    page["sections"] = [s for s in page.get("sections") or [] if not any(s.get("key") == m.get("key")
                                                                        for m in moving)]
    menu = []
    for s in moving:
        menu += _repoint_menu(doc, str(page["id"]), str(s["key"]), str(new["id"]), None)
    if not menu:
        menu.append(_menu_beside(doc, page, new))
    return new, {"what": f"took {sec.get('label')} out of {page.get('name')} into its own screen at {route}",
                 "menu": [m for m in menu if m], "workflows": flows}


def _menu_beside(doc: dict, page: dict, new: dict) -> str:
    """An entry for `new` right after the entry for `page`, or last."""
    def walk(nodes: list) -> bool:
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                continue
            if str(n.get("page") or "") == str(page["id"]) and not n.get("section"):
                nodes.insert(i + 1, {"label": new["name"], "page": str(new["id"])})
                return True
            if walk(n.get("children") or []):
                return True
        return False
    if not walk(_nav(doc)):
        _nav(doc).append({"label": new["name"], "page": str(new["id"])})
    return str(new["name"])


# --------------------------------------------------------------------------- #
# What it takes with it — shown before a yes
# --------------------------------------------------------------------------- #

def consequences(doc: dict, verb: str, *, route: str = "", section: str = "", from_route: str = "",
                 to_route: str = "", **_: Any) -> list[str]:
    """What a removal, a move or a fold takes beyond what was named."""
    page = find_page(doc, route)
    if page is None:
        return []
    takes: list[str] = []
    if verb in ("remove_section", "move_section"):
        sec = find_section(page, section)
        if sec is None:
            return []
        deps = _with_dependents(page, sec)[1:]
        if deps:
            takes.append("the parts that open from it go with it: "
                         + ", ".join(str(d.get("label") or d["key"]) for d in deps))
        pid = str(page["id"])
        menu = [str(n.get("label")) for n in _walk_nodes(doc)
                if str(n.get("page") or "") == pid and str(n.get("section") or "") in {s["key"] for s in [sec] + deps}]
        if menu and verb == "remove_section":
            takes.append("its menu entries come off: " + ", ".join(menu))
        if verb == "remove_section":
            flows = [str(w.get("name")) for w in _launched_here(doc, pid)
                     if any(_claims(s, w) for s in [sec] + deps)
                     and not any(_claims(s, w) for s in _sections(page) if not any(s is d for d in [sec] + deps))]
            if flows:
                takes.append("these processes are no longer started from this screen: " + ", ".join(flows))
    if verb == "merge_screens":
        other = find_page(doc, from_route)
        if other is None:
            return []
        takes.append(f"{other.get('name')} ({other.get('route')}) stops being a screen of its own — its address "
                     f"stops answering, and its menu entries and links open {page.get('name')} instead")
    return takes


def _walk_nodes(doc: dict) -> list[dict]:
    out: list[dict] = []

    def walk(nodes: Any) -> None:
        for n in nodes or []:
            if isinstance(n, dict):
                out.append(n)
                walk(n.get("children"))
    walk((doc.get("navigation") or {}).get("tree"))
    return out


# --------------------------------------------------------------------------- #
# Everything that follows
# --------------------------------------------------------------------------- #

def code_brief(doc: dict, page: dict, what: str) -> str:
    """What the page writer is asked when a screen's sections changed."""
    from services.blueprint.ui_engineer import SECTION_ROLES_RULE, brief_sections

    secs = brief_sections(doc, _sections(page))
    out = (f"The screen {page.get('name')} ({page.get('route')}) changes what it holds: {what}.\n\n"
           "Its sections are now — draw exactly these, each where it says:\n```json\n"
           + json.dumps(secs, indent=1) + "\n```\n"
           "`main` sits on the screen; a `tab` is chosen by `?tab=<key>`; a `panel` opens when a record "
           "is chosen in the section it `opensFrom` and when the address carries `?<param>=<id>`; a "
           "`dialog` opens from a control. A section no longer listed comes off the screen with its "
           "controls and whatever only it read. Keep everything else as it is.")
    if any(s.get("roles") for s in secs):
        out += "\n\n" + SECTION_ROLES_RULE
    return out


def _new_workflows(svc: Any, page_ids: set[str], app_root: str | None, reasoning: Any) -> tuple[list[str], list[str]]:
    """A workflow for each action the changed screens name that none does
    yet — declared and authored, its screen left to the rewrite that follows."""
    from services.blueprint.workflow_slots import section_slots
    from services.smith.workflow_change import WorkflowChangeError, add_workflow

    wanted = [s for s in section_slots(svc.doc) if s["page"] in page_ids]
    made, left = [], []
    for slot in wanted[:MAX_NEW_WORKFLOWS]:
        entity = _entity_name(svc.doc, slot.get("entity")) if slot.get("entity") else ""
        ask = (f"{slot['action']}" + (f" — on {entity} records" if entity else "")
               + f", from the {slot.get('section')} section of {slot['route']}"
               + (f"; done by {', '.join(slot['by'])}" if slot.get("by") else ""))
        try:
            out = add_workflow(svc, ask, route=slot["route"], app_root=app_root, reasoning=reasoning, compose=False)
            made.append(str(out.get("name") or slot["action"]))
        except WorkflowChangeError as exc:
            left.append(f"{slot['action']} on {slot['route']}: {exc}")
    left += [f"{s['action']} on {s['route']}: not attempted (more than {MAX_NEW_WORKFLOWS} at once) — "
             f"`add_workflow` it" for s in wanted[MAX_NEW_WORKFLOWS:]]
    return made, left


def _write_out(svc: Any, app_root: str | None) -> list[str]:
    if not app_root:
        return []
    try:
        from services.smith.sync_app import sync
        out = sync(svc, app_root)
        return sorted(set(out.get("changed") or []) | set(out.get("added") or []))
    except Exception as exc:  # noqa: BLE001 — the narrower projection still runs
        logger.warning("[screen] sync failed (%s); projecting the frontend only", exc)
        from services.smith.page_change import _project
        return _project(svc, app_root)


def _rewrite(svc: Any, page: dict, brief: str, app_root: str | None, reasoning: Any) -> tuple[list[str], str]:
    """The screen's code (or template layout) brought to its sections:
    `(paths, refusal)`."""
    from services.smith.compose import ComposeError, code_row, coded_app, recode_page
    if not app_root:
        return [], ""
    route = str(page.get("route"))
    if code_row(svc.doc, str(page["id"])) is not None or coded_app(svc.doc):
        try:
            out = recode_page(svc, route, app_root=app_root, request=brief, reasoning=reasoning)
        except ComposeError as exc:
            return [], str(exc)
        except Exception as exc:  # noqa: BLE001 — the definition stands; the code is said
            logger.exception("[screen] rewriting %s failed", route)
            return [], f"{type(exc).__name__}: {exc}"
        if not out.get("applied"):
            return [], str(out.get("reason") or "the page writer changed nothing")
        return list(out.get("committed") or []), ""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
    from services.blueprint.orchestrator import DAG
    from services.blueprint.template_page import template_layout
    body = template_layout(svc.doc, page)
    try:
        apply_agent_result(svc, AgentResult(
            task_id=f"TASK-smith-screen-{page['id']}", agent=DAG["page_layouts"].agent, confidence=1.0,
            proposals=[ArtifactProposal(section="pageLayouts", natural_key=str(page["id"]), body=body)]),
            commit=True)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    return [f"src/schemas{route}.json"], ""


def _relink(svc: Any, gone: dict, into: dict, tab: str, keys: dict[str, str], app_root: str | None,
            reasoning: Any) -> tuple[list[str], list[str]]:
    """Coded screens linking to a folded-in screen link to its tab instead.
    `keys` are the SDK's page names from before it was retired — a retired
    page has none, and its name is what the linking code calls."""
    import re as _re

    from services.smith.compose import pages_using, recode_pages_using
    old, new = keys.get(str(gone["id"]), ""), keys.get(str(into["id"]), "")
    if not old or not new:
        return [], []
    linking = [p for p in pages_using(svc, rf"\bpages\.{_re.escape(old)}\b")
               if str(p.get("id")) not in (str(gone["id"]), str(into["id"]))]
    return recode_pages_using(svc, app_root, linking, reasoning=reasoning, request=(
        f"The screen {gone.get('name')} ({gone.get('route')}) is now the \"{tab}\" tab of "
        f"{into.get('name')} ({into.get('route')}): every link to pages.{old} links to "
        f"pages.{new}({{}}, {{ tab: \"{tab}\" }}) instead. Keep everything else."))


def run(output_dir: str, verb: str, *, route: str = "", section: str = "", new_section: Any = None,
        settings: Any = None, order: Any = None, to_route: str = "", from_route: str = "",
        new_route: str = "", request: str = "", reasoning: Any = None) -> dict:
    """`{applied, edited_paths, diff_summary, reason, left}` — the change to
    the definition, then everything that follows from it. `left` is what did
    not follow (a screen's code that was refused, an action with no workflow):
    the definition stands, and those are for the loop to finish."""
    from services.blueprint.service import BlueprintService

    if verb not in VERBS:
        return {"applied": False, "edited_paths": [], "reason": f"unknown screen verb {verb!r}"}
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no definition yet, so there are no screens to change."}
    app_root = str(Path(output_dir) / "app") if (Path(output_dir) / "app").is_dir() else None
    before = svc.snapshot()
    try:
        doc = svc.doc
        page = _page_or_raise(doc, route)
        changed: list[dict] = [page]
        retired: dict | None = None
        if verb == "add_section":
            out = add_section(doc, page, new_section if new_section not in (None, "", {}) else {"label": section})
        elif verb == "edit_section":
            out = edit_section(doc, page, section, settings if isinstance(settings, dict) else {})
        elif verb == "remove_section":
            out = remove_section(doc, page, section)
        elif verb == "reorder_sections":
            out = reorder_sections(doc, page, order)
        elif verb == "move_section":
            target = _page_or_raise(doc, to_route)
            out = move_section(doc, page, section, target)
            changed.append(target)
        elif verb == "merge_screens":
            other = _page_or_raise(doc, from_route)
            out = merge_screens(doc, page, other)
            retired = other
        else:
            new, out = split_section(svc, page, section, new_route, request or f"split {section} out of {route}")
            doc = svc.doc
            page = next(p for p in doc.get("pages") or [] if str(p.get("id")) == str(page["id"]))
            changed = [page, new]
        from services.blueprint.app_sdk import page_keys
        sdk_names = page_keys(svc.doc)
        if retired is not None:
            from services.smith.page_change import refusal, retire
            why = refusal(svc.doc, retired)
            if why:
                raise ScreenChangeError(why)
            retire(svc, [retired])
        from services.blueprint.menu_binding import bind_menu
        bind_menu(svc.doc)
        svc.validate()
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        if not isinstance(exc, ScreenChangeError):
            logger.exception("[screen] %s failed", verb)
        # NOTHING HALF-MADE IS KEPT: a split saves the screen it creates
        # before the rest of the change is checked.
        svc.doc = before
        svc.save()
        reason = str(exc) if isinstance(exc, ScreenChangeError) else f"{type(exc).__name__}: {exc}"
        return {"applied": False, "edited_paths": [], "reason": reason.replace("\n", " ")[:800]}
    affected = sorted({str(p["id"]) for p in changed} | ({str(retired["id"])} if retired else set()))
    svc.commit(user_request=request or f"{verb.replace('_', ' ')} on {route}",
               smith_interpretation=out["what"], before=before, affected=affected)
    tell(reasoning, out["what"][0].upper() + out["what"][1:] + ".", "step")

    left: list[str] = []
    made, missing = _new_workflows(svc, {str(p["id"]) for p in changed}, app_root, reasoning)
    left += missing
    touched = _write_out(svc, app_root)
    rewritten: list[str] = []
    for p in changed:
        live = next((x for x in svc.doc.get("pages") or [] if str(x.get("id")) == str(p["id"])), p)
        tell(reasoning, f"Changing {live.get('route')} to draw its sections.", "step")
        paths, refused = _rewrite(svc, live, code_brief(svc.doc, live, out["what"]), app_root, reasoning)
        touched += paths
        if refused:
            left.append(f"{live.get('route')} still draws its old sections — its code was refused: {refused[:400]}. "
                        f"Change it with `write_page_code`, saying: {out['what']}")
        else:
            rewritten.append(str(live.get("route")))
    if retired is not None:
        done, notes = _relink(svc, retired, page, out.get("tab") or "", sdk_names, app_root, reasoning)
        rewritten += done
        left += notes
    said = out["what"][0].upper() + out["what"][1:] + "."
    if out.get("menu"):
        said += " In the menu: " + ", ".join(m for m in out["menu"] if m) + "."
    if out.get("menu_dropped"):
        said += " Off the menu: " + ", ".join(out["menu_dropped"]) + "."
    if out.get("workflows"):
        said += " " + "; ".join(out["workflows"]) + "."
    if made:
        said += " New processes for its actions: " + ", ".join(made) + "."
    if rewritten:
        said += " Rewrote " + ", ".join(rewritten) + " to match."
    return {"applied": True, "edited_paths": sorted(set(touched)), "diff_summary": said, "reason": "",
            "left": left, "workflows_added": made, "rewritten": rewritten, "pages": affected}


__all__ = ["VERBS", "SETTABLE", "LIST_EDITS", "ScreenChangeError", "find_section", "describe", "settle",
           "add_section", "edit_section", "remove_section", "reorder_sections", "move_section",
           "merge_screens", "split_section", "consequences", "code_brief", "run"]
