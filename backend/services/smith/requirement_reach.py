"""A RULE CHANGE MUST REACH THE APP.

Colour and layout changes work because they apply directly. A rule ("the web
scraping should take place from fashion stores only") only edited the
requirements list: Smith recorded REQ-039, reworded REQ-019 and REQ-020, and
said "Nothing implements it yet", so the built app went on behaving the old
way while the document said otherwise (UAT SnapIT, ho6irnp6).

After a requirement is recorded or restated this finds what IMPLEMENTS it --
a workflow, a business rule, a page, a record type -- from the Blueprint's own
words, links the requirement to it (the artifact cites the requirement, which
is the trace Verify & Fix holds the app to: ``check_requirement_code``), and
changes it through the seam that already exists (``edit_workflow`` /
``edit_rule`` / ``compose_route``). When nothing fits, or the change fails, it
says so plainly and names what it proposes to add -- not "say what screen".

Also bounds the churn: a restatement that says the same thing is skipped, and
the implementers are told only the clause that differs.

Deterministic apart from the injected ``changers`` (the real ones call the
authoring agents).
"""
from __future__ import annotations

import re
from typing import Any, Callable

_STOP = frozenset("""a an and are as at be been but by can could do does for from has have how i if in into is it its
make me my not of on or our should so than that the their them then there these they this to up us was we were what
when where which while who will with would you your only all any also just now want need take takes place app
application system user users""".split())

#: Words that make a requirement a RESTRICTION on what exists: it limits, so
#: the thing that does the work is a process or a rule, not a screen.
_RESTRICTS = re.compile(r"\b(only|never|must not|cannot|can't|not allowed|restrict\w*|limit\w*|exclusive\w*|"
                        r"allowed|forbid\w*|block\w*|exclude\w*|at most|no more than|must be)\b", re.I)

#: A match worth acting on: this many significant words in common.
MIN_SHARED = 2


def _stem(w: str) -> str:
    """A crude stem so scrape/scraping and store/stores meet."""
    for suf in ("ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)] + ("y" if suf == "ies" else "")
            break
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


def tokens(text: Any) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text or ""))
    return {_stem(w) for w in re.split(r"[^a-z0-9]+", spaced.lower()) if len(w) > 2 and w not in _STOP}


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") not in ("DEPRECATED", "SUPERSEDED")]


#: Words that change what a rule SAYS even though they are short or common:
#: negations, modals, quantifiers, scope. A difference in any of them (or in a
#: number) is a different requirement, whatever else the two share.
_CRITICAL = frozenset("""not no never cannot cant can't without none nothing neither nor n't only all any each every
except least most within exactly more less than over under before after between at must should shall may can will
unless until once always both either""".split())
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _critical(text: str) -> tuple:
    low = (text or "").lower().replace("’", "'")
    words = re.findall(r"[a-z']+", low)
    crit = sorted(w for w in words if w in _CRITICAL or w.endswith("n't"))
    # "can not" is "cannot"
    return (tuple(sorted(set(crit))), tuple(sorted(_NUM.findall(low))))


def same_meaning(a: str, b: str) -> bool:
    """Two statements that say the same thing: the same numbers, negations,
    modals and scope words, and (nearly) the same significant words. When
    unsure they are DIFFERENT - a rule wrongly skipped never reaches the app."""
    if _critical(a) != _critical(b):
        return False
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return (a or "").strip().lower() == (b or "").strip().lower()
    return len(ta & tb) / len(ta | tb) >= 0.85


def clause_delta(before: str, after: str) -> str:
    """The part of ``after`` that is new: its clauses with words ``before``
    does not have. A restatement changes a clause, not the whole requirement."""
    seen = tokens(before)
    clauses = [c.strip() for c in re.split(r"(?<=[.;])\s+|,\s+(?=and\b|but\b)", after or "") if c.strip()]
    fresh = [c for c in clauses if tokens(c) - seen]
    return " ".join(fresh) or (after or "").strip()


def is_restriction(text: str) -> bool:
    return bool(_RESTRICTS.search(text or ""))


def _facets(kind: str, a: dict, doc: dict) -> str:
    if kind == "workflow":
        return " ".join([str(a.get("name") or ""), str(a.get("purpose") or "")]
                        + [str(s.get("name") or "") for s in a.get("steps") or [] if isinstance(s, dict)]
                        + [str(i.get("name") or "") for i in a.get("inputs") or [] if isinstance(i, dict)])
    if kind == "rule":
        return f"{a.get('name') or ''} {a.get('statement') or ''}"
    if kind == "page":
        return f"{a.get('name') or ''} {a.get('purpose') or ''} {a.get('route') or ''}"
    if kind == "entity":
        return f"{a.get('name') or ''} " + " ".join(str(f.get("name") or "") for f in a.get("fields") or [] if isinstance(f, dict))
    return f"{a.get('name') or ''} {a.get('purpose') or ''}"


_SECTIONS = (("workflow", "workflows"), ("rule", "businessRules"), ("page", "pages"), ("integration", "integrations"))


def candidates(doc: dict, text: str, *, exclude: str = "") -> list[dict]:
    """What in the Blueprint the requirement is about, best first:
    ``{kind, id, name, shared, score}``. Words the requirement shares with the
    artifact's name, purpose, steps and inputs."""
    want = tokens(text)
    out: list[dict] = []
    if not want:
        return out
    rows = [(k, a) for k, sec in _SECTIONS for a in _live(doc.get(sec))]
    rows += [("entity", a) for a in _live((doc.get("data") or {}).get("entities"))]
    for kind, a in rows:
        if exclude and exclude in (a.get("requirements") or []) and kind != "entity":
            continue
        shared = want & tokens(_facets(kind, a, doc))
        if shared:
            out.append({"kind": kind, "id": str(a.get("id")), "name": str(a.get("name") or a.get("route") or a.get("id")),
                        "shared": sorted(shared), "score": len(shared) / max(len(want), 1)})
    out.sort(key=lambda c: (-len(c["shared"]), -c["score"]))
    return out


def _default_changers() -> dict[str, Callable[..., Any]]:
    def workflow(svc, ref, request, **kw):
        from services.smith.workflow_change import edit_workflow
        return edit_workflow(svc, ref, request, **kw)

    def rule(svc, ref, request, **kw):
        from services.smith.rule_change import edit_rule
        return edit_rule(svc, ref, request, **kw)

    def page(svc, ref, request, **kw):
        from services.smith.compose import compose_route
        route = next((str(p.get("route")) for p in _live(svc.doc.get("pages")) if str(p.get("id")) == ref), ref)
        return compose_route(svc, route, request=request, **kw)
    return {"workflow": workflow, "rule": rule, "page": page}


#: What the requirement is ABOUT decides what may carry it: something shown is
#: a page's business, something limited or done is a process's or a rule's.
_DISPLAY = re.compile(r"\b(show|shows|display|displays|list|lists|sort|sorted|filter|grid|column|columns|layout|theme|"
                      r"dark|colou?rs?|logo|card|cards|board|screen|banner|badge|icon|font|page|view)\b", re.I)
#: Weighted words (a word in the artifact's NAME counts double) needed to pick it,
#: and how far ahead of the runner-up it must be.
MIN_WEIGHT = 3
MARGIN = 1


def want_kinds(text: str) -> tuple[str, ...]:
    if is_restriction(text):
        return ("rule", "workflow")
    if _DISPLAY.search(text or ""):
        return ("page",)
    return ("workflow", "rule")


def _weight(c: dict, doc: dict, want: set[str]) -> int:
    sec = dict((k, s) for k, s in _SECTIONS).get(c["kind"])
    a = next((x for x in _live(doc.get(sec)) if str(x.get("id")) == c["id"]), {}) if sec else {}
    name = tokens(a.get("name") or a.get("route") or "")
    return sum(2 if w in name else 1 for w in c["shared"] if w in want)


def _related_implementers(doc: dict, rid: str, text: str, kinds: tuple[str, ...]) -> set[str]:
    """What already implements a requirement about the same thing (REQ ids are
    the Blueprint's own trace): a new limit on scraping belongs where the
    earlier limit on scraping is carried."""
    mine = tokens(text)
    out: set[str] = set()
    for r in _live(doc.get("requirements")):
        if str(r.get("id")) == rid:
            continue
        theirs = str(r.get("description") or "")
        shared = mine & tokens(theirs)
        if len(shared) >= 2 or (shared and is_restriction(text) and is_restriction(theirs)):
            for k, sec in _SECTIONS:
                if k in kinds:
                    out |= {f"{k}:{a.get('id')}" for a in _live(doc.get(sec)) if r.get("id") in (a.get("requirements") or [])}
    return out


def _pick(cands: list[dict], restriction: bool, *, doc: dict | None = None, text: str = "", rid: str = "") -> dict | None:
    """The implementer to change, or None (then a proposal is made).

    Only artifacts of a kind that FITS the requirement are considered; what
    already implements a related requirement is preferred; a word-overlap
    pick needs a weighted score and a margin over the runner-up. A wrong edit
    is worse than a proposal."""
    if doc is None:
        good = [c for c in cands if len(c["shared"]) >= MIN_SHARED and c["kind"] in ("workflow", "rule", "page")]
        return good[0] if good else None
    kinds = want_kinds(text)
    related = _related_implementers(doc, rid, text, kinds)
    want = tokens(text)
    scored = []
    have = {f"{c['kind']}:{c['id']}" for c in cands}
    for key in sorted(related - have):               # carried by a related requirement, though no words are shared
        k, _, i = key.partition(":")
        sec = dict((a, b) for a, b in _SECTIONS).get(k)
        art = next((x for x in _live(doc.get(sec)) if str(x.get("id")) == i), None)
        if art is not None:
            cands = cands + [{"kind": k, "id": i, "name": str(art.get("name") or art.get("route") or i),
                              "shared": [], "score": 0.0}]
    for c in cands:
        if c["kind"] not in kinds:
            continue
        w = _weight(c, doc, want) + (4 if f"{c['kind']}:{c['id']}" in related else 0)
        scored.append((w, c))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return None
    top, runner = scored[0][0], (scored[1][0] if len(scored) > 1 else 0)
    if top < MIN_WEIGHT or top - runner < MARGIN:
        return None
    return scored[0][1]


def _cite(svc: Any, kind: str, art_id: str, req_id: str) -> None:
    """The trace: the implementer cites the requirement."""
    sec = dict((k, s) for k, s in _SECTIONS).get(kind)
    rows = (svc.doc.get(sec) if sec else None) or []
    for a in rows:
        if isinstance(a, dict) and str(a.get("id")) == art_id:
            if req_id not in (a.get("requirements") or []):
                a["requirements"] = list(a.get("requirements") or []) + [req_id]
    svc.save()


def propose(doc: dict, text: str, cands: list[dict]) -> str:
    """What to build when nothing existing can carry the requirement."""
    near = ", ".join(f"{c['name']} ({c['kind']})" for c in cands[:3])
    if is_restriction(text):
        proto = next((c for c in cands if c["kind"] == "workflow"), None)
        ents = [c for c in cands if c["kind"] == "entity"]
        if proto:
            return (f"I propose changing {proto['name']} so it applies this limit "
                    f"(say \"yes, change {proto['name']}\"), or adding a business rule that refuses what falls outside it.")
        if ents:
            return (f"I propose a business rule on {ents[0]['name']} that refuses anything outside this limit, "
                    "and a setting listing what is allowed, so it can be changed without a rebuild.")
        return ("I propose a business rule that refuses anything outside this limit, plus a setting listing "
                "what is allowed. Name the process or record it applies to and I will add it.")
    return ("I propose a new process for it" + (f" next to {near}" if near else "")
            + ": say \"add a process for it\" and I will author it, or name the screen it belongs on.")


def reach(svc: Any, req: dict, *, delta: str = "", app_root: str | None = None, executor: Any = None,
          reasoning: Any = None, changers: dict | None = None) -> dict:
    """Find what implements ``req`` and change it. Returns::

        {traced: [ids], changed: [names], failed: [str], proposal: str, candidates: [...]}
    """
    rid, text = str(req.get("id")), str(req.get("description") or "")
    out: dict = {"traced": [], "changed": [], "failed": [], "proposal": "", "candidates": []}
    claimed = [(k, str(a.get("id")), str(a.get("name") or a.get("route")))
               for k, sec in _SECTIONS for a in _live(svc.doc.get(sec)) if rid in (a.get("requirements") or [])]
    cands = candidates(svc.doc, text, exclude="")
    out["candidates"] = [{k: c[k] for k in ("kind", "id", "name", "shared")} for c in cands[:5]]
    pick = _pick([c for c in cands if not any(c["id"] == cid for _, cid, _ in claimed)] or cands,
                 is_restriction(text), doc=svc.doc, text=text, rid=rid)
    targets = []
    if claimed:                                 # what already cites it is what changes
        targets = [{"kind": k, "id": i, "name": n} for k, i, n in claimed if k in ("workflow", "rule", "page")]
    elif pick:
        targets = [pick]
    if not targets:
        out["proposal"] = propose(svc.doc, text, cands)
        return out
    do = changers or _default_changers()
    ask = f"{rid} now says: {text}" + (f" (what differs: {delta})" if delta else "")
    for t in targets:
        try:
            do[t["kind"]](svc, t["id"], ask, app_root=app_root, executor=executor, reasoning=reasoning)
        except Exception as exc:  # noqa: BLE001 — one refused implementer is reported, the rest still run
            out["failed"].append(f"{t['name']}: {str(exc)[:160]}")
            continue
        _cite(svc, t["kind"], t["id"], rid)
        out["traced"].append(t["id"])
        out["changed"].append(t["name"])
    if not out["changed"]:
        out["proposal"] = propose(svc.doc, text, cands)
    return out


__all__ = ["candidates", "clause_delta", "is_restriction", "propose", "reach", "same_meaning", "tokens"]
