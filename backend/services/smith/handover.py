"""The short guide an owner gives their staff — §06's "no document generation".

The phrasebook marks "can you write me a one-page guide for the team?" as
reaching nothing, and it marks it in the section where the app stops being the
owner's toy and is handed to the people who have to use it. The two asks
recorded immediately after it — "my staff say the form takes too long to fill
in", "two people complained they can't find the search" — are what the missing
guide costs. Nobody told them where the search was.

Nothing had to be discovered to write one. The Blueprint already knows every
screen and why it exists, every role and what it may open, every process and
what it does when a button is pressed, and every rule that will refuse a save.
That is a staff guide with the wrong audience: it is written for the machine
that builds the app, and this module rewrites it for the person who will use it.

WHAT IT IS DERIVED FROM, AND WHY THAT IS THE WHOLE GUARANTEE
------------------------------------------------------------
A guide that names a screen the build failed to compose is worse than no guide:
the reader goes looking for it, does not find it, and stops trusting the rest
of the page. So the guide is derived from ``pageLayouts`` — the composed trees —
and not from ``requirements``, which say what the app was meant to have.
:func:`sheet` joins every other section THROUGH that set: a page with no
composed layout contributes no purpose, no tasks, no workflow and no rule,
because it is not in the list the others are joined against.

That is the entire correctness argument, and it is structural. There is no pass
over the finished guide looking for screens that do not exist — a check like
that is a guess about prose, and it would need an exception list the first time
a guide legitimately said "the app" or named a tab. The writer cannot mention
an uncomposed screen because it is never told one exists.

WHAT IS GENERATED AND WHAT IS NOT
---------------------------------
The facts are arithmetic: which pages composed, who can open them, which
workflow a page launches, which rules cover its records. :func:`sheet` does
that with no model call, and a test can assert every line of it.

The *wording* is not arithmetic. "You'll see today's jobs; tap one to update
it" is not a transformation of "Let the borrower named on a specific rental
record submit photo or video evidence of its condition at return time" — it is
a rewrite by someone who understands both the business and the reader, and a
template producing it deterministically would produce the feature list of the
software, which is precisely the document nobody reads. So one model call turns
the sheet into the guide, and the sheet is all it is given.

WHERE IT GOES
-------------
Both. The text comes back into the conversation, because the owner asked in the
conversation and should not have to go and find the answer. And it is written
to ``TEAM-GUIDE.md`` at the root of the application, beside ``package.json``,
because the owner asked for something to hand over: a chat bubble does not
survive leaving the chat, and a file in the app tree travels with every export,
every zip and every deploy of the thing it describes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

#: At the application root, beside package.json — the first place anyone looks,
#: and inside everything that packages the app.
GUIDE_FILE = "TEAM-GUIDE.md"

#: One page. Long enough for four or five roles with a few screens each, short
#: enough that the model cannot drift into a manual nobody prints.
MAX_TOKENS = 2000

#: The audience when the Blueprint declares no roles at all. Not a default role
#: invented in the document — nothing is written back — just the name the guide
#: calls the reader when there is only one kind of them.
EVERYONE = "Everyone who uses it"


def _live(rows: Any) -> list[dict]:
    """Artifacts that still exist. `DEPRECATED` is how the Blueprint retires
    one without losing the record that it was there (§91)."""
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def _by_id(rows: Any) -> dict[str, dict]:
    return {str(r.get("id")): r for r in _live(rows) if r.get("id")}


def composed(doc: dict) -> dict[str, dict]:
    """The pages that actually render, by id.

    A page is composed when a live layout names it and that layout has a tree.
    `pages` is the declaration — it exists as soon as anything decides the app
    needs a screen — and `pageLayouts[].root` is the screen. The difference
    between the two is the set of screens a guide must not mention.
    """
    pages = _by_id((doc or {}).get("pages"))
    out: dict[str, dict] = {}
    for layout in _live((doc or {}).get("pageLayouts")):
        pid = str(layout.get("page") or "")
        if pid in pages and layout.get("root"):
            out[pid] = pages[pid]
    return out


def _menu(doc: dict) -> list[dict]:
    """The navigation tree flattened, parents before children.

    Order matters: the menu is the order the reader meets the app in, so it is
    the order the guide walks them through it. Depth does not — a guide that
    said "under Admin, then Nurses" would be describing the menu rather than
    the work.
    """
    out: list[dict] = []

    def walk(nodes: Any, under: str) -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            out.append({"label": str(node.get("label") or ""),
                        "page": str(node.get("page") or ""),
                        "under": under,
                        "roles": [str(r) for r in (node.get("roles") or [])]})
            walk(node.get("children"), str(node.get("label") or ""))

    walk(((doc or {}).get("navigation") or {}).get("tree"), "")
    return out


def _entities_of(page: dict) -> set[str]:
    data = page.get("data") or {}
    ids = {str(data.get("primaryEntity") or "")}
    ids |= {str(e) for e in (data.get("supportingEntities") or [])}
    return {e for e in ids if e}


#: `scope` says where a rule is enforced, and that is the difference between
#: something the reader will run into and something they will never see. A
#: guide that tells staff "it will not let you" about a rule the server applies
#: behind them has taught them to expect a refusal that never comes; one that
#: says nothing about a rule the form enforces has left them stuck at it. Split
#: on the declared field rather than on what the sentence sounds like.
STOPS_THEM = frozenset({"form", "entity"})


def _rules_for(doc: dict, page: dict) -> list[dict]:
    """The rules that govern this screen, joined on the records it works with.

    `statement` is the one field written as a sentence about the business
    rather than an expression for the engine, which is why it is the only one
    carried through.
    """
    want = _entities_of(page)
    out = []
    for rule in _live((doc or {}).get("businessRules")):
        covers = {str(e) for e in (rule.get("appliesTo") or [])} | {str(rule.get("entity") or "")}
        if want & {c for c in covers if c} and rule.get("statement"):
            out.append(rule)
    return out


def _flows_from(doc: dict, page_id: str) -> list[dict]:
    """The processes this screen starts — what happens after they press it."""
    return [w for w in _live((doc or {}).get("workflows"))
            if page_id in [str(p) for p in (w.get("launchedFrom") or [])]]


def _roles(doc: dict) -> list[dict]:
    roles = _live((doc or {}).get("roles"))
    if roles:
        return roles
    # No roles declared: one audience, named rather than invented. It is not
    # written back to the document — the guide has a reader either way.
    return [{"id": "", "name": EVERYONE, "description": ""}]


def _opens(page: dict, role_id: str) -> bool:
    """Whether this role can open this screen, as `access` defines it.

    `public` and `authenticated` are open to every role the app has; only
    `role_restricted` narrows, and it narrows to exactly `users`.
    """
    access = str(page.get("access") or "authenticated")
    if access in ("public", "authenticated"):
        return True
    return role_id in [str(u) for u in (page.get("users") or [])]


def sheet(doc: dict) -> dict:
    """Everything the guide is allowed to say, per audience. No model call.

    `omitted` is the honest half: screens that composed but that no declared
    role can open. They are left out rather than handed to some role that
    looks close, and named back to the owner so the omission is theirs to fix.
    """
    doc = doc or {}
    pages = composed(doc)
    product = doc.get("product") or {}
    menu = _menu(doc)
    order = {m["page"]: i for i, m in enumerate(menu) if m["page"]}
    labels = {m["page"]: m for m in menu if m["page"]}
    landing = {str(k): str(v) for k, v in ((doc.get("navigation") or {}).get("initialRoute") or {}).items()}

    audiences = []
    reached: set[str] = set()
    for role in _roles(doc):
        rid = str(role.get("id") or "")
        mine = [p for pid, p in pages.items() if _opens(p, rid)]
        mine.sort(key=lambda p: (order.get(str(p.get("id")), len(order)), str(p.get("name") or "")))
        reached |= {str(p.get("id")) for p in mine}
        screens = []
        for page in mine:
            pid = str(page.get("id"))
            entry = labels.get(pid) or {}
            rules = _rules_for(doc, page)
            screens.append({
                # The words on the menu are the words the reader will look for;
                # the page's own `name` is what the Blueprint calls it.
                "called": str(entry.get("label") or page.get("name") or ""),
                "in_menu": bool(entry),
                "grouped_under": str(entry.get("under") or ""),
                "route": str(page.get("route") or ""),
                "purpose": str(page.get("purpose") or ""),
                "tasks": [str(t) for t in (page.get("primaryTasks") or [])],
                "controls": [str(a) for a in (page.get("actions") or [])],
                "tabs": [str(v.get("label")) for v in (page.get("views") or [])
                         if isinstance(v, dict) and v.get("label")],
                "happens": [{"name": str(w.get("name") or ""),
                             "does": str(w.get("purpose") or ""),
                             "when": str((w.get("trigger") or {}).get("detail") or "")}
                            for w in _flows_from(doc, pid)],
                "refuses": [str(r.get("statement")) for r in rules
                            if str(r.get("scope") or "form") in STOPS_THEM],
                "behind_them": [str(r.get("statement")) for r in rules
                                if str(r.get("scope") or "form") not in STOPS_THEM],
                "signed_in": str(page.get("access") or "authenticated") != "public",
            })
        if not screens:
            continue
        # WHERE THEY ARRIVE, OR THE ADMISSION THAT IT IS NOT DECLARED.
        # `initialRoute` says it per role; `entry` says it per page ("where
        # its audience arrives"). With neither, the sheet SAYS so — a blank
        # line reads to a writer as no constraint, and the first guide written
        # from one told a nurse they would land somewhere nobody had said they
        # would land.
        arrive = landing.get(rid, "")
        if not arrive:
            first = next((p for p in mine if p.get("entry")), None)
            arrive = str(first.get("route") or "") if first else ""
        audiences.append({
            "role": str(role.get("name") or EVERYONE),
            "who": str(role.get("description") or ""),
            "lands_on": arrive,
            "screens": screens,
        })

    return {
        "app": str((doc.get("application") or {}).get("name") or ""),
        "for": [str(o) for o in (product.get("objectives") or [])],
        # The business's own words for its own things. Carried through so the
        # guide can use them instead of the Blueprint's — a reader who has
        # never heard "entity" has heard "rental".
        "words": {str(k): str(v) for k, v in (product.get("terminology") or {}).items()},
        "audiences": audiences,
        "omitted": sorted(str(p.get("name") or p.get("route") or pid)
                          for pid, p in pages.items() if pid not in reached),
    }


def as_text(data: dict) -> str:
    """The sheet as the writer reads it. Labelled, flat, and nothing else."""
    lines = [f"APPLICATION: {data.get('app') or '(unnamed)'}"]
    if data.get("for"):
        lines += ["", "WHAT IT IS FOR:"] + [f"- {o}" for o in data["for"]]
    if data.get("words"):
        lines += ["", "THE BUSINESS'S OWN WORDS (use these, not software terms):"]
        lines += [f"- {k}: {v}" for k, v in data["words"].items()]
    for aud in data.get("audiences") or []:
        lines += ["", f"=== AUDIENCE: {aud['role']} ==="]
        if aud.get("who"):
            lines.append(f"Who they are: {aud['who']}")
        lines.append(f"The app opens on: {aud['lands_on']}" if aud.get("lands_on")
                     else "The app opens on: NOT DECLARED — do not tell them "
                          "where they land or what they see first.")
        for i, s in enumerate(aud.get("screens") or [], start=1):
            lines.append("")
            where = (f"found in the menu as “{s['called']}”"
                     if s["in_menu"] else "not in the menu; reached from a link inside the app")
            if s.get("grouped_under"):
                where += f", under “{s['grouped_under']}”"
            # NOT LABELLED "SCREEN". The sheet's own words prime the guide's,
            # and a sheet that says SCREEN eight times gets back a guide that
            # says "the return screen" however plainly the instructions ban it.
            lines.append(f"{i}. “{s['called']}” — {where}")
            if s.get("purpose"):
                lines.append(f"   Why it exists: {s['purpose']}")
            for task in s.get("tasks") or []:
                lines.append(f"   They do here: {task}")
            for control in s.get("controls") or []:
                lines.append(f"   Control on it: {control}")
            for tab in s.get("tabs") or []:
                lines.append(f"   Tab on it: {tab}")
            for flow in s.get("happens") or []:
                lines.append(f"   When they submit: {flow['does'] or flow['name']}"
                             + (f" ({flow['when']})" if flow["when"] else ""))
            for rule in s.get("refuses") or []:
                lines.append(f"   They are stopped if: {rule}")
            for rule in s.get("behind_them") or []:
                lines.append(f"   Happens behind them, without being asked: {rule}")
            if not s["signed_in"]:
                lines.append("   Open without signing in.")
    return "\n".join(lines)


SYSTEM = """You are writing the one-page guide a small business owner prints \
and hands to their staff on the morning the app goes live.

Write for the person who will USE it. Not a feature list of the software, not a \
description of what was built. "You'll see today's jobs; tap one to update it" \
is the register — second person, present tense, the thing they came to do first.

RULES, IN ORDER OF IMPORTANCE

1. Say only what the sheet says. Every screen, control, tab, rule and \
consequence you mention must be on it. If the sheet does not say how someone \
gets to a screen, do not say. If it does not say what a button is called, \
describe the act rather than naming a button. You are not being cautious: a \
guide that sends someone looking for something that is not there is worse than \
no guide, because they stop believing the parts that are true.

2. Never use the software's vocabulary. No screen, page, route, entity, record, \
field, form, workflow, dispatch, component, role, permission, rule, status, or \
URL path. Use the business's own words from the sheet, and where you must name \
a screen, name it the way the menu names it, in quotes. Some lines on the sheet \
were written by the builder and carry its names — anything with underscores, \
capitals in the middle of a word, or a path in it is a machine's name for \
something, never a thing the reader will see. Describe the act instead.

3. The sheet's own lines were written for the builder and carry its \
vocabulary. Say what they MEAN for the reader, in the reader's words: "you have \
to be signed in", not "an unauthenticated user cannot access it".

4. A line that says people are stopped is worth a sentence of advice — "it \
won't let you save until you've ticked it". A line that says something happens \
behind them is worth mentioning only if not knowing would surprise them; \
usually it is not worth a line at all.

5. One page. A short opening line saying what the app is for, then one section \
per audience, headed with what those people are called. Inside a section, walk \
them through what they will actually do in the order they will do it, in a few \
sentences or a short numbered list.

6. If there is only one audience, do not head a section for it; just write the \
guide.

7. No invented anything: no company name, no placeholder in brackets, no \
sign-in instructions unless the sheet says a screen needs signing in, no \
support address, no closing note about who to contact.

Return markdown only: a level-1 title, then the guide. No preamble, no fences, \
no closing commentary about what you wrote."""


def compose(data: dict, *, provider: Any = None, reasoning: Any = None) -> str:
    """The guide, written from `data` and nothing else."""
    if provider is None:
        from services.llm_client import complete

        def provider(prompt: str) -> str:  # noqa: E306
            return complete(system=SYSTEM, content=prompt, max_tokens=MAX_TOKENS)

    tell(reasoning, "Writing the guide from the screens that actually composed.", "step")
    return (provider(as_text(data)) or "").strip()


def footer(doc: dict) -> str:
    """What the printed page says about its own age.

    A guide is handed over once and then the application changes underneath it,
    and a staff guide nobody can tell is out of date is how people end up being
    trained on a screen that moved. Written here rather than asked of the
    writer: the version is a fact about the document, not a sentence about the
    business, and it has to say the same thing every time.
    """
    name = str((doc.get("application") or {}).get("name") or "this application")
    version = int(doc.get("version") or 0)
    return (f"---\n\n*Describes {name} as it stood at version {version}. "
            f"Ask for the guide again after you change anything.*")


def run(output_dir: str | Path, *, app_root: str | Path | None = None,
        provider: Any = None, reasoning: Any = None) -> dict:
    """Write the guide for the application at `output_dir`."""
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "there is no application here yet, so there is "
                          "nothing to write a guide about."}

    data = sheet(svc.doc)
    if not data["audiences"]:
        # NOT AN EMPTY GUIDE. Nothing composed, or nothing anyone can open:
        # either way the honest answer names the state and the way out of it.
        return {"applied": False, "edited_paths": [], "sheet": data,
                "reason": "none of this application's screens have been built "
                          "yet, so a guide would describe screens nobody can "
                          "open. Build it first and ask me again."}

    try:
        text = compose(data, provider=provider, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("[smith] guide failed")
        return {"applied": False, "edited_paths": [], "sheet": data,
                "reason": f"I could not write the guide ({type(exc).__name__}: {exc})."}
    if not text:
        return {"applied": False, "edited_paths": [], "sheet": data,
                "reason": "I could not write the guide — nothing came back."}

    root = Path(app_root) if app_root else Path(output_dir) / "app"
    path = root / GUIDE_FILE
    written = ""
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{text}\n\n{footer(svc.doc)}\n", "utf-8")
        written = GUIDE_FILE
    except OSError as exc:
        # The guide exists; only the copy that survives the chat does not.
        logger.warning("[smith] guide not written to %s: %s", path, exc)

    return {"applied": True, "guide": text, "path": written,
            "edited_paths": [written] if written else [],
            "omitted": data["omitted"], "reason": ""}


def summary_of(out: dict) -> str:
    """The guide in the conversation, and what it does not cover."""
    lines = [out.get("guide") or ""]
    if out.get("path"):
        lines += ["", f"Saved as **{out['path']}** at the top of the application, "
                      "so you can print it or hand the file on."]
    if out.get("omitted"):
        lines += ["", "Left out because no one is allowed to open them yet: "
                      + ", ".join(f"**{n}**" for n in out["omitted"]) + "."]
    return "\n".join(lines)


__all__ = ["GUIDE_FILE", "composed", "sheet", "as_text", "compose", "footer",
           "run", "summary_of", "SYSTEM", "EVERYONE", "STOPS_THEM"]
