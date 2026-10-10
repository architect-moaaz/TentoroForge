"""Statements of what must happen (`expectations`): what they are written
from, the writer's task, and what in them names nothing.

A statement is the architect's, written from the requirements and the rules
before any screen is coded, in the application's own words — its roles, its
screens, its record types and their fields — and the few verbs every web
application shares. Nothing here knows what any application is for.
"""
from __future__ import annotations

import re
from typing import Any

GUEST = "guest"
ACTS = ("open", "do", "sign_in", "sign_out", "reload", "come_back", "wait")
CHECKS = ("on", "sees", "not_sees", "told", "gets", "stored", "not_stored", "sent")
#: A given record's id where a value is written: the whole value (`"@shirt"`)
#: or a part of an address (`/products/@shirt`, `?item=@shirt`). An email's
#: `@` is not one — `jane@example.com` names no record.
_VALUE_REF = re.compile(r"^@(\S.*)$")
_ADDRESS_REF = re.compile(r"(?:^|[/=?&])@([A-Za-z][\w\-]*)")


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "SUPERSEDED", "REMOVED")]


def expectations(doc: dict) -> list[dict]:
    return [e for e in _live(doc.get("expectations")) if isinstance(e.get("steps"), list)]


def _entities(doc: dict) -> dict[str, dict]:
    return {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("id")}


def _field_names(entity: dict) -> set[str]:
    return {str(f.get("name")) for f in entity.get("fields") or [] if isinstance(f, dict) and f.get("name")}


def stamp_columns(doc: dict, entity: dict) -> tuple[set[str], set[str]]:
    """`(filled with the signed-in person's id, filled with a guest's token)`
    — the columns of a record type the application fills from whoever makes
    it (`ownership_rules`), by their field names."""
    from services.blueprint.projection import _key_forms, ownership_rules
    rules = ownership_rules(doc)
    user: set[str] = set()
    guest: set[str] = set()
    camel = lambda c: re.sub(r"_([a-z])", lambda m: m.group(1).upper(), str(c))  # noqa: E731
    for form in _key_forms(str(entity.get("name") or "")) | _key_forms(str(entity.get("table") or "")):
        for r in rules.get(form) or []:
            if r.get("through"):
                continue                  # scoped through a record the statement gives
            if r.get("column") and r.get("column") != "id":
                user.add(camel(r["column"]))
            if r.get("guestColumn"):
                guest.add(camel(r["guestColumn"]))
    return user, guest


def stamped(doc: dict, entity: dict) -> set[str]:
    """The fields of a record type the application fills from whoever is
    signed in — its owner, who acted, a guest's token — and nobody sets."""
    from services.blueprint.projection import to_snake
    user, guest = stamp_columns(doc, entity)
    return {f for c in user | guest for f in (c, to_snake(c))}


def _sign_in_route(doc: dict) -> str:
    return next((str(p.get("route")) for p in _live(doc.get("pages"))
                 if str(p.get("pattern") or "") == "auth" and str(p.get("auth") or "login") == "login"),
                "/login")


def _audience(doc: dict, page: dict, roles: dict[str, str]) -> list[str]:
    """Who a screen is FOR — the people it is made for, not who may open it."""
    users = [roles.get(str(u), str(u)) for u in page.get("users") or []]
    if users:
        return users
    access = str(page.get("access") or "authenticated")
    if access == "public" or str(page.get("pattern") or "") == "auth":
        return ["anyone"]
    return ["anyone signed in"] if access == "authenticated" else []


def may_open(doc: dict, page: dict) -> list[str]:
    """Who the application lets open a screen, by its access rule: `anyone`,
    `anyone signed in`, or the role names it is restricted to. A screen made
    for customers with access `authenticated` opens for anyone signed in —
    ToroCommerce's statements expected the admin turned away from the cart,
    from who it was for rather than who may open it (torob1, 2026-10-09)."""
    access = str(page.get("access") or "authenticated")
    if access == "public" or str(page.get("pattern") or "") == "auth":
        return ["anyone"]
    if access == "role_restricted":
        from services.blueprint.projection import restricted_roles
        return restricted_roles(doc, page)
    return ["anyone signed in"]


# --------------------------------------------------------------------------- #
# What a statement is written from
# --------------------------------------------------------------------------- #

def expect_brief(doc: dict) -> dict:
    """The requirements and their criteria, the rules, the people and where
    each starts, the record types and their fields, the screens and what each
    starts, the processes, and which outside services are connected."""
    from services.blueprint.account_model import landing_by_role

    roles = {str(r.get("id")): str(r.get("name") or r.get("id")) for r in _live(doc.get("roles"))}
    landing = landing_by_role(doc) or {}
    starts: dict[str, list[str]] = {}
    for w in _live(doc.get("workflows")):
        for pid in w.get("launchedFrom") or []:
            starts.setdefault(str(pid), []).append(str(w.get("id")))
    screens = []
    for p in _live(doc.get("pages")):
        screens.append({
            "id": p.get("id"), "name": p.get("name"), "route": p.get("route"),
            "access": p.get("access") or "authenticated", "for": _audience(doc, p, roles),
            "opens_for": may_open(doc, p),
            "purpose": p.get("purpose") or "",
            **({"tasks": p["primaryTasks"]} if p.get("primaryTasks") else {}),
            **({"sections": [{"key": s.get("key"), "label": s.get("label"), "actions": s.get("actions") or []}
                             for s in p.get("sections") or [] if isinstance(s, dict)]}
               if p.get("sections") else {}),
            **({"starts": starts[str(p.get("id"))]} if starts.get(str(p.get("id"))) else {}),
        })
    records = []
    for e in _entities(doc).values():
        fields = []
        for f in e.get("fields") or []:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            row: dict[str, Any] = {"name": f["name"], "type": f.get("type")}
            if f.get("required"):
                row["required"] = True
            values = f.get("values") or f.get("options") or f.get("enum")
            if values:
                row["values"] = values
            fields.append(row)
        records.append({"id": e.get("id"), "name": e.get("name"), "fields": fields})
    return {
        "people": [{"id": k, "name": v, "starts_on": landing.get(v, "")} for k, v in roles.items()],
        "sign_in": _sign_in_route(doc),
        "requirements": [{"id": r.get("id"), "says": r.get("description") or r.get("title") or "",
                          "criteria": r.get("acceptanceCriteria") or []}
                         for r in _live(doc.get("requirements"))],
        "rules": [{"id": r.get("id"), "name": r.get("name"), "says": r.get("statement") or r.get("description") or "",
                   "record": r.get("entity")} for r in _live(doc.get("businessRules"))],
        "records": records,
        "screens": screens,
        "processes": [{"id": w.get("id"), "name": w.get("name"), "purpose": w.get("purpose") or "",
                       "inputs": [str(i.get("name")) for i in w.get("inputs") or [] if isinstance(i, dict)],
                       "from": w.get("launchedFrom") or []} for w in _live(doc.get("workflows"))],
        "outside": [{"name": i.get("name"), "kind": i.get("kind") or i.get("type"),
                     "connected": str(i.get("status") or "").upper() in ("CONNECTED", "IMPLEMENTED", "VERIFIED")}
                    for i in _live(doc.get("integrations"))],
    }


EXPECT_PROMPT = (
    "Write the EXPECTATIONS of this application: statements of what must happen when someone does "
    "something. Each one is tried later in the running application, as that person, and is the answer "
    "key the finished application is checked against. Write them from the requirements, their acceptance "
    "criteria and the rules — what the person must see and what must be kept — never from how a screen "
    "might be built.\n\n"
    "COVER the part of the application named below — no more, so each statement is written once:\n"
    "  * for requirements: every acceptance criterion with at least one statement (the requirement's "
    "id in `requirements`), and every rule named with the case it allows and the case it refuses (its "
    "id in `rules`), including what one person does that another must then see, or must not;\n"
    "  * for the people: each person's arrival — signing in through the sign-in form lands them where "
    "they start, and signing in after being sent away from a screen brings them back to it — and who "
    "may open each screen, by its `opens_for` (its access rule; `for` is only who it is made for): "
    "someone it opens for gets in, someone it does not open for is turned away, and someone signed out "
    "is asked to sign in.\n"
    "A statement says what a person SEES or what is STORED — never that something 'works' or 'is "
    "handled'.\n\n"
    "SHAPE. `says`: one plain sentence a non-engineer reads at the review. `kind`: arrival, reach, "
    "action, rule, cross-person, journey, first-use, recovery or background. `given`: the records that "
    "exist first — each a `ref` the statement calls it by, its record type (`entity`), its field "
    "`values` (a value written `@ref` is that given record's id), and `as` who makes it when that is not "
    "the administrator. Give each record a distinctive name or title, so it can be found on a screen. "
    "The people are already there: each role signs in as the application's own account for that role — "
    "never give the person themselves (their account, their profile row) as a record; a record they own "
    "is given `as` them, and the application stamps whose it is — never set the fields that say whose a "
    "record is (an owner, a session, a token). When the statement is about the person's OWN account — "
    "disabled, a profile filled in — give it with `self: true`, `as` them, its record type the account's "
    "and the `values` it holds: another record of that type would be someone else.\n"
    "`steps`, in order, each done `as` a role id or `guest` (someone signed out; `who` tells two people "
    "of one role apart): `open` a screen (`page`, with `record` when it opens one given record — or "
    "`address` as typed, `@ref` for a record's id, to try a screen by its address); `do`, with `what` "
    "said in the person's words — the purpose of the controls and the values entered, never a selector; "
    "one `do` for each thing they send or save, so two forms are two steps, and the id of the process it "
    "starts in `workflow` when it starts one; "
    "`sign_in` through the application's own sign-in form, done `as` the role they sign in as — that "
    "person is signed out until this step, so the steps before it are theirs too (`page` when they reach "
    "it from another screen); `sign_out`; `reload`; `come_back` (the same person returns later in the "
    "same browser); `wait` (`what` for).\n"
    "`then`, judged once every step is done — each person as they are at the end, so a story "
    "about two roles is two statements, not one person signing out — and each judged by code from what "
    "the browser and the database report: `on` (the screen they "
    "are on: `page`); `sees` / `not_sees` (a given `record`, found by its name, or `text` — words the screen must "
    "show exactly: a given record's value or wording a requirement fixes, never a guess at a label; "
    "`page` to open first, else where they are); `told` (`told`: success, refusal or error — the application's "
    "answer to that person's last `do`; `text` says what about); `gets` (`page` or `address`, and `gets`: "
    "shown, not_found, sign_in_asked or not_allowed — what opening it gives that person); `stored` / "
    "`not_stored` (`entity` and field `values`, or a given `record` and the `values` it now has); "
    "`sent` (a message: `entity` and to whom, in `values`). `as` on a check is whose view it is.\n\n"
    "WHEN THE REQUIREMENTS DO NOT DECIDE what must happen, do not decide silently: write the statement "
    "with the answer you judge right in `assumed`, and the question in `question` — the person answers "
    "it at the review. An outside service that is not connected is not tried; say what the application "
    "does without it, or ask.\n\n"
    "Return the statements as `expectations` proposals, one per statement."
)


# --------------------------------------------------------------------------- #
# Who writes which part
# --------------------------------------------------------------------------- #

#: The subject that writes the people's arrivals and who reaches which screen.
PEOPLE = "people"
#: The most requirements one call writes for. A call that wrote every
#: statement of a 14-requirement shop reasoned through 32,000 output tokens
#: and wrote none (TCommerce, 2026-10-08); an application ten times its size
#: is the same call, ten times over.
REQUIREMENTS_PER_SUBJECT = 4
#: The most processes one call writes starting statements for. Ecom L1's
#: 62 processes landed on the one requirement group there was, and the call
#: was cut off at 32,000 output tokens twice, five minutes and $0.38 each
#: time (2026-10-11).
PROCESSES_PER_SUBJECT = 8


def expect_subjects(doc: dict) -> dict[str, dict]:
    """``{subject: {"requirements": [...], "rules": [...]}}`` — the people,
    then every requirement, an area's together, in even groups of at most
    REQUIREMENTS_PER_SUBJECT, each with the rules that name one of its
    requirements. A rule naming none goes with the last group. A subject is
    called by its first requirement's id; a group carrying more than
    PROCESSES_PER_SUBJECT processes hands the rest to further subjects, each
    called by its first process's id.

    EVERY REQUIREMENT, NOT ONLY THOSE WITH CRITERIA. A requirement is one
    testable statement; its criteria, when written, say what the words
    mean. Tried only when it carried criteria, Ecom L1's 43 requirements
    gave two, and every process fell into that one call (2026-10-11)."""
    reqs = [r for r in _live(doc.get("requirements")) if r.get("id")]
    # An area's requirements stay together, in the order the areas come.
    order: dict[str, int] = {}
    for r in reqs:
        order.setdefault(str(r.get("area") or r.get("module") or ""), len(order))
    reqs.sort(key=lambda r: order[str(r.get("area") or r.get("module") or "")])
    out: dict[str, dict] = {PEOPLE: {"requirements": [], "rules": []}}
    if reqs:
        n = -(-len(reqs) // REQUIREMENTS_PER_SUBJECT)
        size = -(-len(reqs) // n)
        for i in range(0, len(reqs), size):
            part = reqs[i:i + size]
            out[str(part[0]["id"])] = {"requirements": [str(r["id"]) for r in part], "rules": []}
    for k in out:
        out[k].setdefault("processes", [])
    groups = [k for k in out if k != PEOPLE]
    # EVERY PROCESS A PERSON STARTS is run by some statement: each goes to
    # the part whose requirements it serves, else the part whose screens
    # start it, else the last part.
    from services.blueprint.process_trials import manual_workflows
    req_part = {r: k for k in groups for r in out[k]["requirements"]}
    for w in manual_workflows(doc):
        home = next((req_part[str(r)] for r in w.get("requirements") or [] if str(r) in req_part), None)
        out[home or (groups[-1] if groups else PEOPLE)]["processes"].append(str(w.get("id")))
    for rule in _live(doc.get("businessRules")):
        named = {str(x) for x in (rule.get("requirements") or []) + (rule.get("appliesTo") or [])}
        home = next((k for k in groups if named & set(out[k]["requirements"])), groups[-1] if groups else PEOPLE)
        out[home]["rules"].append(str(rule.get("id")))
    final: dict[str, dict] = {}
    for k, part in out.items():
        procs = list(part.get("processes") or [])
        if k == PEOPLE or len(procs) <= PROCESSES_PER_SUBJECT:
            final[k] = part
            continue
        n = -(-len(procs) // PROCESSES_PER_SUBJECT)
        size = -(-len(procs) // n)
        chunks = [procs[i:i + size] for i in range(0, len(procs), size)]
        final[k] = {**part, "processes": chunks[0]}
        for chunk in chunks[1:]:
            final[str(chunk[0])] = {"requirements": [], "rules": [], "processes": chunk}
    return final


def subject_ask(doc: dict, subject: str) -> str:
    """What one call is asked to cover."""
    part = expect_subjects(doc).get(subject)
    if part is None:
        return ""
    if subject == PEOPLE:
        return ("THIS CALL: the people — every person's arrival, and who reaches each screen that is not "
                "for everyone. Nothing about the requirements' other behaviour; other calls write that.")
    rows = {str(r.get("id")): r for r in _live(doc.get("requirements"))}
    rules = {str(r.get("id")): r for r in _live(doc.get("businessRules"))}
    lines = ["THIS CALL: these requirements and rules, and nothing else — other calls write the rest."]
    flows = {str(w.get("id")): w for w in _live(doc.get("workflows"))}
    if part.get("processes"):
        lines.append("And every one of these processes is started by at least one statement's `do` step — its id "
                     "in that step's `workflow` — from the screen a person starts it on, as that person:")
        lines += [f"- {fid}: {(flows.get(fid) or {}).get('name') or ''} — {(flows.get(fid) or {}).get('purpose') or ''}"
                  for fid in part["processes"]]
    for rid in part["requirements"]:
        r = rows.get(rid) or {}
        lines.append(f"- {rid}: {r.get('description') or ''} Criteria: "
                     + "; ".join(str(c) for c in r.get("acceptanceCriteria") or []))
    for rid in part["rules"]:
        r = rules.get(rid) or {}
        lines.append(f"- {rid} ({r.get('name') or ''}): {r.get('statement') or r.get('description') or ''}")
    return "\n".join(lines)


def subject_written(doc: dict, subject: str) -> bool:
    """Whether a subject's statements are in the document."""
    part = expect_subjects(doc).get(subject)
    rows = expectations(doc)
    if part is None:
        return True
    if subject == PEOPLE:
        return any(st.get("kind") == "arrival" for st in rows)
    # WRITTEN WHEN COVERED, NOT WHEN TOUCHED. Another part's statement can
    # cite one of these requirements; a part refused three times then read
    # as written and was never asked again (torob1, 2026-10-09).
    covered = {str(r) for st in rows for r in st.get("requirements") or []}
    started = {str(s.get("workflow")) for st in rows for s in st.get("steps") or [] if s.get("workflow")}
    return set(part["requirements"]) <= covered and set(part.get("processes") or []) <= started


# --------------------------------------------------------------------------- #
# What in a statement names nothing
# --------------------------------------------------------------------------- #

def _label(st: dict) -> str:
    return str(st.get("id") or "") or repr(str(st.get("says") or "")[:60])


def named_through(given: list[dict], ref: str, seen: set[str] | None = None) -> str:
    """The name a given record is found by on a screen: its own, else that of
    a record it points at — a cart line shows its product's name, and has no
    name field to give (torob2, 2026-10-09). "" when there is none."""
    seen = seen or set()
    if ref in seen:
        return ""
    seen.add(ref)
    g = next((x for x in given if isinstance(x, dict) and str(x.get("ref")) == ref), None)
    if g is None:
        return ""
    values = g.get("values") or {}
    own = next((v for v in values.values() if isinstance(v, str) and v.strip() and not v.startswith("@")
                and not _VALUE_REF.match(v.strip())), "")
    if own:
        return own
    for v in values.values():
        m = _VALUE_REF.match(v.strip()) if isinstance(v, str) else None
        if m:
            found = named_through(given, m.group(1), seen)
            if found:
                return found
    return ""


def given_order(given: list[dict]) -> list[dict] | None:
    """The given records in an order each one's `@ref`s are made before it;
    None when they point at each other in a loop."""
    rows = [g for g in given if isinstance(g, dict)]
    names = {str(g.get("ref")) for g in rows}
    needs = {id(g): {m for v in (g.get("values") or {}).values() if isinstance(v, str)
                     for m in _VALUE_REF.findall(v.strip()) if m in names and m != str(g.get("ref"))}
             for g in rows}
    out: list[dict] = []
    made: set[str] = set()
    while len(out) < len(rows):
        ready = [g for g in rows if g not in out and needs[id(g)] <= made]
        if not ready:
            return None
        for g in ready:
            out.append(g)
            made.add(str(g.get("ref")))
    return out


_NUMERIC = re.compile(r"[\d.,$£€¥%\s+-]+")


def _the_apps_words(doc: dict) -> str:
    """Every word the definition puts in the application's mouth: the
    requirements and their criteria, the rules, the processes and what they
    say, the screens. Text a statement looks for on a screen comes from here
    or from a record — "Consider deactivating this variant" came from neither,
    and failed against a screen that says it its own way (torob1, 2026-10-09)."""
    import json as _json
    parts = []
    for r in _live(doc.get("requirements")):
        parts += [str(r.get("description") or ""), " ".join(map(str, r.get("acceptanceCriteria") or []))]
    for r in _live(doc.get("businessRules")):
        parts += [str(r.get("name") or ""), str(r.get("statement") or "")]
    for w in _live(doc.get("workflows")):
        parts += [str(w.get("name") or ""), str(w.get("purpose") or ""),
                  _json.dumps([(x.get("config") or {}).get("message", "") for x in w.get("steps") or []
                               if isinstance(x, dict)])]
    for pg in _live(doc.get("pages")):
        parts += [str(pg.get("name") or ""), str(pg.get("purpose") or "")]
    return " ".join(parts).lower()


def mend_statement(st: dict) -> dict:
    """ONE PERSON, ONE BROWSER, MENDED AT THE SEAM. An arrival statement is
    written as "a guest opens the page, then the role signs in" — the shape
    the words have — and the runner holds one browser per person, so the
    role's sign-in page is the guest's browser's to see. The steps before a
    role's sign-in are that person's, signed out until then; said in the
    writer's task and still written as `guest` (Ecom L1, 2026-10-11, an
    edit turn per build). The mend is the refusal's own instruction."""
    steps = st.get("steps") or []
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or s.get("act") != "sign_in" or s.get("page"):
            continue
        role = str(s.get("as") or "")
        if not role or role == GUEST:
            continue
        for t in steps[:i]:
            if isinstance(t, dict) and str(t.get("as") or "") == GUEST:
                t["as"] = role
                if s.get("who") and not t.get("who"):
                    t["who"] = s["who"]
    return st


def statement_findings(doc: dict, st: dict) -> list[str]:
    """What one statement names that the application does not have, or a
    check that has nothing to look at."""
    roles = {str(r.get("id")) for r in _live(doc.get("roles"))}
    role_names = {str(r.get("id")): str(r.get("name")) for r in _live(doc.get("roles"))}
    pages = {str(p.get("id")) for p in _live(doc.get("pages"))}
    pages_by_id = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    ents = _entities(doc)
    reqs = {str(r.get("id")) for r in _live(doc.get("requirements"))}
    rules = {str(r.get("id")) for r in _live(doc.get("businessRules"))}
    me = _label(st)
    out: list[str] = []

    def person(where: str, who: Any) -> None:
        if who is not None and str(who) != GUEST and str(who) not in roles:
            out.append(f"{me}: {where} is done as {who!r}, which is neither a role id nor {GUEST!r}")

    def page(where: str, pid: Any) -> None:
        if pid and str(pid) not in pages:
            out.append(f"{me}: {where} names the screen {pid}, which the application does not have")

    refs: dict[str, dict] = {}
    # A given record may point at one listed after it: the runner makes them
    # in the order they point at each other (`given_order`).
    all_refs = {str(g.get("ref")) for g in st.get("given") or [] if g.get("ref")}
    if given_order(st.get("given") or []) is None:
        out.append(f"{me}: the given records point at each other in a loop — one of them must not point back")
    for g in st.get("given") or []:
        ref = str(g.get("ref") or "")
        ent = ents.get(str(g.get("entity") or ""))
        if not ref:
            out.append(f"{me}: a given record has no `ref` to call it by")
        elif ref in refs:
            out.append(f"{me}: two given records are both called {ref!r}")
        if ent is None:
            out.append(f"{me}: the given {ref!r} is of record type {g.get('entity')!r}, which the application does not have")
        else:
            unknown = sorted(set((g.get("values") or {}).keys()) - _field_names(ent) - {"id"})
            if unknown:
                out.append(f"{me}: the given {ref!r} sets {', '.join(unknown)}, which {ent.get('name')} does not have")
            kinds = {str(f.get("name")): str(f.get("type") or "").lower() for f in ent.get("fields") or []
                     if isinstance(f, dict)}
            filled = stamped(doc, ent)
            # A RECORD THAT BELONGS TO SOMEONE is made as them. The admin's
            # orders were refused, and nothing could say whose they were
            # (torob2, 2026-10-09).
            user_cols, _guest_cols = stamp_columns(doc, ent)
            owner_required = any(f.get("required") for f in ent.get("fields") or []
                                 if isinstance(f, dict) and str(f.get("name")) in user_cols)
            if owner_required and not g.get("self") and str(g.get("as") or GUEST) == GUEST:
                out.append(f"{me}: the given {ref!r} is a {ent.get('name')}, which belongs to someone — give it "
                           f"`as` the role of the person it belongs to")
            needed = [str(f.get("name")) for f in ent.get("fields") or [] if isinstance(f, dict)
                      and f.get("required") and str(f.get("type") or "").lower() == "uuid"
                      and str(f.get("name")) not in ("id", *filled) and str(f.get("name")) not in (g.get("values") or {})]
            sets = sorted(set((g.get("values") or {})) & filled)
            if sets:
                out.append(f"{me}: the given {ref!r} sets {', '.join(sets)} — the application fills that from "
                           f"whoever makes it; give it `as` them instead")
            if needed:
                out.append(f"{me}: the given {ref!r} leaves out {', '.join(needed)} — a {ent.get('name')} points at "
                           f"them; give those records first and write @ref")
            for k, v in (g.get("values") or {}).items():
                if kinds.get(str(k)) == "uuid" and isinstance(v, str) and not _VALUE_REF.match(v.strip()):
                    out.append(f"{me}: the given {ref!r} sets {k} to {v!r}, which is not a record — write @ and "
                               f"the `ref` of a record given before it")
        for v in (g.get("values") or {}).values():
            for m in _VALUE_REF.findall(v.strip()) if isinstance(v, str) else []:
                if m not in all_refs:
                    known = ", ".join(repr(r) for r in all_refs) or "none"
                    out.append(f"{me}: the given {ref!r} points at @{m}, and no given record has the `ref` {m!r} "
                               f"(the given records: {known}) — give that record too")
        person(f"making the given {ref!r}", g.get("as"))
        if g.get("self"):
            from services.blueprint.account_model import account_entity
            acct = account_entity(doc) or {}
            if not g.get("as") or str(g.get("as")) == GUEST:
                out.append(f"{me}: the given {ref!r} is someone's own account (`self`) and names no role in `as`")
            elif str(g.get("entity")) != str(acct.get("id")):
                out.append(f"{me}: the given {ref!r} is someone's own account (`self`), and their account is a "
                           f"{acct.get('name') or 'record the application does not have'}, not {g.get('entity')}")
        refs[ref] = g

    def record(where: str, ref: Any) -> None:
        if ref and str(ref).lstrip("@") not in refs:
            out.append(f"{me}: {where} names the record {ref!r}, which is not among the given records")

    def address(where: str, text: Any) -> None:
        for m in _ADDRESS_REF.findall(str(text or "")):
            if m not in refs:
                out.append(f"{me}: {where} puts @{m} in an address, which is not among the given records")

    steps = st.get("steps") or []
    if not steps:
        out.append(f"{me}: nobody does anything")
    for i, s in enumerate(steps, 1):
        where = f"step {i}"
        act = str(s.get("act") or "")
        if act not in ACTS:
            out.append(f"{me}: {where} is {act!r}; a step is one of {', '.join(ACTS)}")
        person(where, s.get("as"))
        page(where, s.get("page"))
        record(where, s.get("record"))
        address(where, s.get("address"))
        if act == "open" and not (s.get("page") or s.get("address")):
            out.append(f"{me}: {where} opens nothing — give it a `page` or an `address`")
        if act == "sign_in" and str(s.get("as") or "") == GUEST:
            out.append(f"{me}: {where} signs in as {GUEST!r}; a sign-in is done as the role they sign in as "
                       f"— the same person, signed out until then, does the steps before it")
        if s.get("workflow") and str(s["workflow"]) not in {str(w.get("id")) for w in _live(doc.get("workflows"))}:
            out.append(f"{me}: {where} starts {s['workflow']}, which is not one of the application's processes")
        if act == "do" and not str(s.get("what") or "").strip():
            out.append(f"{me}: {where} does nothing in particular — say `what` the person does")

    # ONE PERSON, ONE BROWSER. A role that signs in is that person from the
    # start, signed out until then; a guest's steps before it are another
    # browser, whose sign-in page the role never sees.
    seen: set[str] = set()
    for i, s in enumerate(steps, 1):
        who = f"{s.get('as')}:{s.get('who') or ''}"
        if s.get("act") == "sign_in" and who not in seen and not s.get("page") and any(
                str(t.get("as")) == GUEST for t in steps[:i - 1]):
            out.append(f"{me}: step {i} signs {s.get('as')} in after a guest's steps — they are another "
                       f"browser. Write the steps before signing in as {s.get('as')}: they are signed out "
                       f"until step {i}")
        seen.add(who)
    # THE CHECKS ARE JUDGED AT THE END, each person as they then are.
    out_at = {f"{s.get('as')}:{s.get('who') or ''}": i for i, s in enumerate(steps, 1) if s.get("act") == "sign_out"}
    back_in = {f"{s.get('as')}:{s.get('who') or ''}": i for i, s in enumerate(steps, 1) if s.get("act") == "sign_in"}
    for c in st.get("then") or []:
        who = f"{c.get('as')}:{c.get('who') or ''}"
        if who in out_at and back_in.get(who, 0) < out_at[who]:
            out.append(f"{me}: {c.get('as')} signs out at step {out_at[who]} and is checked afterwards — the "
                       f"checks are judged once every step is done, so they would be judged signed out. Make "
                       f"it two statements")
            break

    checks = st.get("then") or []
    if not checks:
        out.append(f"{me}: nothing is checked afterwards")
    for i, c in enumerate(checks, 1):
        where = f"check {i}"
        kind = str(c.get("check") or "")
        if kind not in CHECKS:
            out.append(f"{me}: {where} is {kind!r}; a check is one of {', '.join(CHECKS)}")
            continue
        person(where, c.get("as"))
        page(where, c.get("page"))
        record(where, c.get("record"))
        address(where, c.get("address"))
        ent = ents.get(str(c.get("entity") or "")) if c.get("entity") else None
        if c.get("entity") and ent is None:
            out.append(f"{me}: {where} looks for record type {c.get('entity')!r}, which the application does not have")
        if kind == "on" and not c.get("page"):
            out.append(f"{me}: {where} says where they are without a `page`")
        if kind in ("sees", "not_sees") and str(c.get("text") or "").strip() and not c.get("record"):
            said = str(c["text"]).strip()
            given_words = " ".join(str(v) for g in st.get("given") or [] for v in (g.get("values") or {}).values())
            if not (_NUMERIC.fullmatch(said) or said.lower() in given_words.lower()
                    or said.lower() in _the_apps_words(doc)):
                out.append(f"{me}: {where} looks for {said!r}, which no given record holds and no requirement, rule, "
                           f"process or screen says — look for a record's value, or words the requirements use")
        if kind in ("sees", "not_sees"):
            if not (c.get("record") or str(c.get("text") or "").strip()):
                out.append(f"{me}: {where} looks for nothing — give it a given `record` or `text`")
            elif c.get("record"):
                if not named_through(st.get("given") or [], str(c["record"]).lstrip("@")):
                    out.append(f"{me}: {where} looks for {c['record']!r} on a screen, and neither it nor a record "
                               f"it points at has a name or title to be found by — give one of them one")
        if kind == "told" and c.get("told") not in ("success", "refusal", "error"):
            out.append(f"{me}: {where} is `told` without saying which: success, refusal or error")
        if kind == "gets" and c.get("page") and str(c["page"]) in pages_by_id:
            opens = may_open(doc, pages_by_id[str(c["page"])])
            who = str(c.get("as") or (steps[-1].get("as") if steps else "") or "")
            signed_out = who == GUEST or (who and any(str(x.get("as")) == who and x.get("act") == "sign_out"
                                                      for x in steps))
            role = role_names.get(who, "")
            if c.get("gets") == "sign_in_asked" and not signed_out:
                out.append(f"{me}: {where} expects {role or who} to be asked to sign in, but they are signed in "
                           f"when the checks are judged — check that as `guest`")
            if c.get("gets") == "not_allowed" and not signed_out and role and (
                    "anyone" in opens or "anyone signed in" in opens or role in opens):
                out.append(f"{me}: {where} expects {role} to be turned away from {pages_by_id[str(c['page'])].get('route')}, "
                           f"which opens for {', '.join(opens)} — its access says they may open it")
        if kind == "gets":
            if c.get("gets") not in ("shown", "not_found", "sign_in_asked", "not_allowed"):
                out.append(f"{me}: {where} is `gets` without saying what: shown, not_found, sign_in_asked or not_allowed")
            if not (c.get("page") or c.get("address")):
                out.append(f"{me}: {where} opens nothing — give it a `page` or an `address`")
        if kind in ("stored", "not_stored"):
            if not (c.get("entity") or c.get("record")):
                out.append(f"{me}: {where} looks in no record type — give it an `entity` or a given `record`")
            target = ent or ents.get(str((refs.get(str(c.get("record") or "").lstrip("@")) or {}).get("entity") or ""))
            if target is not None:
                unknown = sorted(set((c.get("values") or {}).keys()) - _field_names(target) - {"id"})
                if unknown:
                    out.append(f"{me}: {where} expects {', '.join(unknown)} on {target.get('name')}, which it does not have")

    for r in st.get("requirements") or []:
        if str(r) not in reqs:
            out.append(f"{me}: covers {r}, which is not a requirement")
    for r in st.get("rules") or []:
        if str(r) not in rules:
            out.append(f"{me}: covers {r}, which is not a rule")
    return out


def coverage_findings(doc: dict, statements: list[dict], subject: str | None = None) -> list[str]:
    """What a set leaves untried: a requirement, a
    rule, a person's arrival — of one subject's part, or of the whole
    application when `subject` is None."""
    from services.blueprint.account_model import landing_by_role

    parts = expect_subjects(doc)
    if subject is not None and subject not in parts:
        return []
    mine = [parts[subject]] if subject is not None else list(parts.values())
    want_reqs = {r for p in mine for r in p["requirements"]}
    want_rules = {r for p in mine for r in p["rules"]}
    want_flows = {f for p in mine for f in p.get("processes") or []}
    people = subject is None or subject == PEOPLE
    covered_reqs = {str(r) for st in statements for r in st.get("requirements") or []}
    covered_rules = {str(r) for st in statements for r in st.get("rules") or []}
    out = [f"{r.get('id')} ({str(r.get('description') or '')[:80]}) is a requirement no statement tries"
           for r in _live(doc.get("requirements"))
           if str(r.get("id")) in want_reqs and str(r.get("id")) not in covered_reqs]
    out += [f"{r.get('id')} ({r.get('name')}) is a rule no statement tries"
            for r in _live(doc.get("businessRules"))
            if str(r.get("id")) in want_rules and str(r.get("id")) not in covered_rules]
    started = {str(s.get("workflow")) for st in statements for s in st.get("steps") or [] if s.get("workflow")}
    out += [f"{w.get('id')} ({w.get('name')}) is a process no statement starts — give a `do` step its id in `workflow`"
            for w in _live(doc.get("workflows")) if str(w.get("id")) in want_flows and str(w.get("id")) not in started]
    if people:
        landing = landing_by_role(doc) or {}
        arrived = {str(s.get("as")) for st in statements if st.get("kind") == "arrival"
                   for s in st.get("steps") or [] if s.get("act") == "sign_in"}
        for r in _live(doc.get("roles")):
            if landing.get(str(r.get("name"))) and str(r.get("id")) not in arrived:
                out.append(f"{r.get('id')} ({r.get('name')}) starts on {landing[str(r.get('name'))]} and no "
                           f"arrival statement signs them in to see that they do")
    return out


def expectation_findings(doc: dict, statements: list[dict] | None = None, *,
                         subject: str | None = None, whole: bool = True) -> list[str]:
    """Every statement's findings, and what is left untried: of `subject`'s
    part when one is named, of the whole application when `whole`."""
    rows = expectations(doc) if statements is None else statements
    out = [f for st in rows for f in statement_findings(doc, st)]
    if subject is not None:
        out += coverage_findings(doc, rows, subject)
    elif whole:
        out += coverage_findings(doc, rows)
    return out


__all__ = ["expectations", "expect_brief", "EXPECT_PROMPT", "statement_findings", "coverage_findings", "mend_statement",
           "expectation_findings", "expect_subjects", "subject_ask", "subject_written", "PEOPLE",
           "GUEST", "ACTS", "CHECKS"]
