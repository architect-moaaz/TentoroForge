"""Who signs in, and what they must have done first — read off the Blueprint.

Tool Share (036farqu) had every piece and none of the connections: a template
signup that created a login and nothing else, a public "Create Profile" page
that created a Member belonging to nobody, a KYC form whose `memberId` no
login could fill, and "KYC approval required for listing and borrowing"
written as prose that nothing enforced. The build never knew which entity was
the person behind a login, so it could not connect them.

Everything here is derived, never authored:

* THE ACCOUNT ENTITY — the one entity marked `account: true`. Each row IS a
  login: its id is the login's id, so `$user.id` names the person's row in
  every workflow and every foreign key. Signup creates it with the login.
* THE AUTH PAGES — `/login` and `/signup`, as pages of pattern `auth`, so the
  UI engineer writes them like any other page and the editor lists them.
* PREREQUISITES — a business rule of kind `prerequisite` gates workflows; the
  workflow projection puts the check at the front of each (`guard`), and a
  new account is sent to the page where it is done.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from services.blueprint.geo_types import LOCATION_TYPES

#: The two auth pages every application with a sign-in has.
AUTH_PAGES: tuple[dict[str, str], ...] = (
    {"auth": "login", "route": "/login", "name": "Sign in",
     "purpose": "Let a person with an account sign in and continue where they left off."},
    {"auth": "signup", "route": "/signup", "name": "Create account",
     "purpose": "Let a new person create their account — their login and, where the application "
                "keeps one, their own record — and start using the application."},
)

#: Columns signup never asks a person for: the platform fills them.
_SYSTEM = {"id", "createdAt", "updatedAt", "created_at", "updated_at", "deletedAt"}
#: Field types a person types into a signup form.
_KIND = {
    "string": "text", "text": "textarea", "email": "email", "phone": "tel", "tel": "tel",
    "url": "url", "integer": "number", "number": "number", "decimal": "number", "float": "number",
    "boolean": "checkbox", "date": "date", "enum": "select",
}


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def account_entity(doc: dict) -> dict | None:
    """The entity each login IS, or None."""
    return next((e for e in _live((doc.get("data") or {}).get("entities")) if e.get("account")), None)


def signup_role(doc: dict) -> str | None:
    """The role a self-registered person gets: `security.signupRole`, else the
    application's only role, else — with the administrator's role set aside —
    the one role left. F&B had Admin and Customer and no `signupRole`: a
    person who signed up held no role at all, landed on the public home and
    saw none of the Customer's menu (2026-10-02). Two or more roles besides
    the administrator's stay undecided: that is a choice, not a default."""
    roles = _live(doc.get("roles"))
    rid = str(((doc.get("security") or {}).get("signupRole")) or "")
    if rid:
        hit = next((r for r in roles if str(r.get("id")) == rid), None)
        if hit and hit.get("name"):
            return str(hit["name"])
    if len(roles) == 1 and roles[0].get("name"):
        return str(roles[0].get("name"))
    admin = admin_role(doc)
    others = [r for r in roles if r.get("name") and str(r.get("name")) != admin]
    if not admin or len(others) != 1:
        return None
    # ONLY WHEN THE DEFINITION SAYS WHICH IS THE ADMINISTRATOR: a page
    # restricted to that role which the other cannot open. Two roles nothing
    # tells apart (a Member and a Moderator with the same screens) are a
    # choice, and `admin_role`'s tie-break must not make it.
    admin_id = next((str(r.get("id")) for r in roles if str(r.get("name")) == admin), "")
    other_id = str(others[0].get("id"))
    marked = any(str(p.get("access") or "") == "role_restricted"
                 and admin_id in [str(u) for u in p.get("users") or []]
                 and other_id not in [str(u) for u in p.get("users") or []]
                 for p in _live(doc.get("pages")))
    return str(others[0].get("name")) if marked else None


def demo_email(role: str) -> str:
    """The demo login the seed makes for a role — `seedRoleLogins` in
    templates/runtime/seed.ts derives it the same way.

    NEVER THE ADMINISTRATOR'S ADDRESS. A role named "Admin" that is not the
    built-in administrator's came out as admin@example.com — the seeded
    admin's own address — so it got no login of its own and the test-logins
    table listed one account under two roles (wz7a99ir, 2026-10-04)."""
    import re as _re

    from services.smith.accounts import SEEDED_ADMIN
    local = _re.sub(r"[^a-z0-9]+", ".", role.lower()).strip(".") or "user"
    email = f"{local}@example.com"
    return f"{local}.role@example.com" if email == SEEDED_ADMIN else email


def demo_logins(doc: dict) -> list[tuple[str, str]]:
    """(email, role) for every way into a freshly seeded application: the
    administrator first, then one demo person per other role."""
    from services.smith.accounts import SEEDED_ADMIN
    admin = admin_role(doc)
    out = [(SEEDED_ADMIN, admin or "Admin")]
    for r in _live(doc.get("roles")):
        name = str(r.get("name") or "")
        if name and name != admin:
            out.append((demo_email(name), name))
    return out


def admin_role(doc: dict) -> str | None:
    """The role the built-in admin account holds: the one that opens the
    back office — the pages the Blueprint restricts to named roles
    (`access: role_restricted`), then the pages no other role opens, then all
    it opens. The admin was seeded with the sign-up role, so 0l133sp2's
    admin@example.com was a Member, and the verification queue and every
    notification to "Admin" were somebody else's."""
    roles = _live(doc.get("roles"))
    if not roles:
        return None
    # THE ROLE PEOPLE GIVE THEMSELVES IS NOT THE BACK OFFICE'S. Anyone who
    # signs up holds it, so it is never the administrator's while another
    # role exists. F&B's admin pages named no role and the customer pages
    # named Customer; the ranking below then made admin@example.com a
    # Customer, and the admin never saw an admin menu (wz7a99ir, 2026-10-04).
    signup = str(((doc.get("security") or {}).get("signupRole")) or "")
    if signup and len(roles) > 1:
        others = [r for r in roles if signup not in (str(r.get("id")), str(r.get("name")))]
        roles = others or roles
    pages = [p for p in _live(doc.get("pages")) if str(p.get("pattern") or "") != "auth"]

    def opens(rid: str) -> list[dict]:
        return [p for p in pages if not p.get("users") or rid in [str(u) for u in p.get("users")]]

    def rank(role: dict) -> tuple[int, int, int]:
        rid = str(role.get("id"))
        mine = opens(rid)
        restricted = sum(1 for p in mine if str(p.get("access") or "") == "role_restricted")
        only = sum(1 for p in mine if [str(u) for u in p.get("users") or []] == [rid])
        return restricted, only, len(mine)

    best = max(roles, key=rank)
    return str(best.get("name")) if best.get("name") else None


def _humanise(name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    return " ".join(words).capitalize() if words else name


def _written_by_workflows(doc: dict, entity_id: str) -> dict[str, dict]:
    """`{field: {"decided": values a process writes, "typed": bool}}`.

    A field a process DECIDES is the application's, not a question at signup:
    0l133sp2 asked a new neighbour for their "Kyc status" and "Kyc verified
    at" — the two things the verification workflow decides — beside "Password
    hash", which is the login's.

    A field a workflow writes FROM AN INPUT (`{{displayName}}`) is still the
    person's: "Update Member Profile" saves the display name they typed, and
    reading that as "the system decides it" took the name and the bio off the
    signup form.
    """
    out: dict[str, dict] = {}
    for wf in doc.get("workflows") or []:
        if not isinstance(wf, dict) or wf.get("status") == "DEPRECATED":
            continue
        for step in wf.get("steps") or []:
            if not isinstance(step, dict):
                continue
            config = step.get("config") or {}
            if str(config.get("actionType") or "") not in ("db_update", "db_insert"):
                continue
            if str(step.get("entity") or config.get("entity") or "") != entity_id:
                continue
            for field, value in (config.get("values") or {}).items():
                written = out.setdefault(str(field), {"decided": set(), "typed": False})
                if isinstance(value, str) and "{{" in value:
                    written["typed"] = True          # the person's own value, passed through
                elif isinstance(value, str) and value.startswith("$"):
                    written["decided"].add(value)    # $now, $user.id — the runtime's
                elif isinstance(value, str) and value:
                    written["decided"].add(value)    # a state the process names
    return out


def _system_owned(written: dict[str, dict], name: str) -> bool:
    """A field only ever written by a process, never from what someone typed."""
    entry = written.get(name)
    return bool(entry) and not entry["typed"] and bool(entry["decided"])


def account_initial(doc: dict) -> dict[str, Any]:
    """What the application fills in for the fields it does not ask about.

    A required field the person never types still has to hold something. For
    a state a workflow moves through, the record starts in the state no
    workflow writes — `unverified`, when the workflows only ever set pending,
    verified and rejected — else the first value the field allows.
    """
    ent = account_entity(doc)
    if ent is None:
        return {}
    written = _written_by_workflows(doc, str(ent.get("id") or ""))
    out: dict[str, Any] = {}
    for f in ent.get("fields") or []:
        name = str((f or {}).get("name") or "")
        if not name or not f.get("required") or name in _SYSTEM or f.get("primaryKey"):
            continue
        if not _system_owned(written, name) and not _is_credential(name):
            continue          # the person is asked for it, so they supply it
        values = [str(v) for v in f.get("enumValues") or []]
        if values:
            decided = written.get(name, {}).get("decided") or set()
            unwritten = [v for v in values if v not in decided]
            out[name] = unwritten[0] if unwritten else values[0]
        elif _is_credential(name):
            # An older Blueprint put a credential on the account entity (new
            # ones are refused). The column is NOT NULL and the person must
            # never be asked for it, so the row carries a value nobody can
            # sign in with — the login itself lives in the platform's table.
            out[name] = UNUSABLE_CREDENTIAL
    return out


def account_fields(doc: dict) -> list[dict]:
    """What signup asks for the person's own record: the account entity's
    fields a person types — not system columns, not references to other
    records (those are made later), not files or vectors."""
    ent = account_entity(doc)
    if ent is None:
        return []
    # WHAT A PERSON TYPES, AND NOTHING ELSE. Their login holds their password,
    # and a field a workflow sets is that process's to set — asked at signup
    # they read as nonsense ("Password hash", "Kyc status", "Kyc verified
    # at"), and answering them would let a new account claim it was already
    # verified. New apps cannot declare a credential on the account entity at
    # all; this is what keeps one off the form when an older Blueprint has it.
    written = _written_by_workflows(doc, str(ent.get("id") or ""))
    out = []
    for f in ent.get("fields") or []:
        name = str(f.get("name") or "")
        ftype = str(f.get("type") or "string").lower()
        if not name or name in _SYSTEM or f.get("primaryKey") or f.get("references"):
            continue
        if _is_credential(name) or _system_owned(written, name):
            continue
        if ftype in ("vector", "image", "file", "json", "jsonb", "uuid") or "[]" in ftype \
                or ftype in LOCATION_TYPES:
            continue
        kind = "email" if "email" in name.lower() and ftype == "string" else _KIND.get(ftype, "text")
        if kind == "text" and re.search(r"phone|mobile|tel$", name, re.I):
            kind = "tel"
        spec: dict[str, Any] = {"name": name, "label": _humanise(name), "kind": kind,
                                "required": bool(f.get("required"))}
        if kind == "select":
            spec["options"] = [{"label": _humanise(str(v)), "value": str(v)} for v in f.get("enumValues") or []]
        out.append(spec)
    # What is required first, as a person fills a form top to bottom.
    return sorted(out, key=lambda s: not s["required"])


#: Written into a credential column an older Blueprint declared on the account
#: entity, so the row inserts and nobody can authenticate with it.
UNUSABLE_CREDENTIAL = "@unusable"


def _is_credential(name: str) -> bool:
    from services.blueprint.projection import _is_credential_field

    return _is_credential_field(name)


def prerequisites(doc: dict) -> list[dict]:
    return [r for r in _live(doc.get("businessRules")) if r.get("kind") == "prerequisite"]


def _route_of(doc: dict, page_id: str | None) -> str | None:
    page = next((p for p in _live(doc.get("pages")) if str(p.get("id")) == str(page_id or "")), None)
    route = str((page or {}).get("route") or "")
    return route if route and "[" not in route else None


def landing_by_role(doc: dict) -> dict[str, str]:
    """Where each kind of user lands, by the role's NAME (what the session
    carries): the Blueprint's `navigation.initialRoute`, whose keys may name a
    role or give its id. F&B's said `{"ROLE-001": "/admin/categories"}`; only
    names were matched, the map came out empty, and an administrator who
    signed in landed on the customers' menu (2026-10-01). `default`,
    `authenticated` and any key that is no role are not a person's landing."""
    roles = [r for r in doc.get("roles") or [] if isinstance(r, dict) and r.get("name")]
    by_key = {str(r.get("name")).strip().lower(): str(r.get("name")) for r in roles}
    by_key.update({str(r.get("id")).strip().lower(): str(r.get("name")) for r in roles if r.get("id")})
    declared = (doc.get("navigation") or {}).get("initialRoute")
    out: dict[str, str] = {}
    for key, route in (declared.items() if isinstance(declared, dict) else ()):
        name = by_key.get(str(key).strip().lower())
        if name and isinstance(route, str) and route.startswith("/") and "[" not in route:
            out[name] = route
    return out


def home_route(doc: dict) -> str:
    init = (doc.get("navigation") or {}).get("initialRoute") or {}
    if isinstance(init, dict):
        return str(init.get("authenticated") or init.get("default") or "/")
    return str(init or "/")


def after_signup_route(doc: dict) -> str:
    """Where a new account goes first: the page that satisfies the first
    prerequisite, else home."""
    for rule in prerequisites(doc):
        route = _route_of(doc, rule.get("page"))
        if route:
            return route
    return home_route(doc)


# ---------------------------------------------------------------------------
# The auth pages
# ---------------------------------------------------------------------------

def has_sign_in(doc: dict) -> bool:
    return str(((doc.get("security") or {}).get("authentication")) or "email_password") != "none"


def auth_page_bodies(doc: dict) -> list[dict]:
    """The `/login` and `/signup` page contracts an application with sign-in
    has and does not have yet."""
    if not has_sign_in(doc):
        return []
    have = {str(p.get("route")) for p in _live(doc.get("pages"))}
    return [{"name": a["name"], "route": a["route"], "purpose": a["purpose"], "pattern": "auth",
             "auth": a["auth"], "access": "public"}
            for a in AUTH_PAGES if a["route"] not in have]


def is_auth_page(page: dict) -> bool:
    return str(page.get("pattern") or "") == "auth"


# ---------------------------------------------------------------------------
# Projection: what signup reads
# ---------------------------------------------------------------------------

def project_account(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """`src/lib/account.ts` (safe on the client) and `src/lib/account-table.ts`
    (server-only: the account entity's table, for signup to write its row)."""
    from services.blueprint.projection import _module_name, _var_name

    root = Path(app_root) / "src" / "lib"
    root.mkdir(parents=True, exist_ok=True)
    ent = account_entity(doc)
    header = ("// Generated from the Living Blueprint (services/blueprint/account_model.py).\n"
              "// Edit the Blueprint, not this file.\n\n")
    from services.blueprint.projection import is_location_field
    location = next((f.get("name") for f in (ent or {}).get("fields") or [] if is_location_field(f)), None)
    account = ("null" if ent is None else json.dumps({
        "entity": ent.get("name"), "fields": account_fields(doc), "labelField": ent.get("labelField"),
        "locationField": location}, indent=2))
    (root / "account.ts").write_text(
        header
        + "export interface AccountField {\n  name: string;\n  label: string;\n"
          '  kind: "text" | "textarea" | "email" | "tel" | "url" | "number" | "date" | "select" | "checkbox";\n'
          "  required: boolean;\n  options?: { label: string; value: string }[];\n}\n\n"
        + f"export const ACCOUNT: null | {{ entity: string; fields: AccountField[]; labelField: string | null; locationField: string | null }} = {account};\n\n"
        + "/** What the app writes on a new account for the fields it does not ask about. */\n"
        + f"export const ACCOUNT_INITIAL: Record<string, unknown> = {json.dumps(account_initial(doc), indent=2)};\n\n"
        + f"export const SIGNUP_ROLE: string | null = {json.dumps(signup_role(doc))};\n\n"
        + "/** The role the built-in admin account holds: the one that reaches the most of the app. */\n"
        + f"export const ADMIN_ROLE: string | null = {json.dumps(admin_role(doc))};\n\n"
        + "/** Every role of the application, by name: the seed signs a demo person into each. */\n"
        + f"export const ROLES: string[] = {json.dumps([str(r.get('name')) for r in _live(doc.get('roles')) if r.get('name')])};\n\n"
        + f"export const AFTER_SIGNUP: string = {json.dumps(after_signup_route(doc))};\n\n"
        + f"export const HOME: string = {json.dumps(home_route(doc))};\n\n"
        + "/** Where each role lands once signed in, by the role's name; anyone else goes HOME. */\n"
        + f"export const LANDING_FOR: Record<string, string> = {json.dumps(landing_by_role(doc), indent=2)};\n", "utf-8")
    if ent is None:
        table = "// eslint-disable-next-line @typescript-eslint/no-explicit-any\nexport const accountTable: any = null;\n"
    else:
        table = (f'import {{ {_var_name(ent)} }} from "@/db/schema/{_module_name(ent)}";\n\n'
                 f"export const accountTable = {_var_name(ent)};\n")
    (root / "account-table.ts").write_text(header + table, "utf-8")
    return {"files": ["src/lib/account.ts", "src/lib/account-table.ts"]}


# ---------------------------------------------------------------------------
# Projection: every gated workflow starts with its prerequisite
# ---------------------------------------------------------------------------

def guard_nodes(doc: dict, workflow: dict) -> list[tuple[dict, dict]]:
    """``[(query config, rule)]`` for each prerequisite gating `workflow`."""
    ents = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    out = []
    for rule in prerequisites(doc):
        if str(workflow.get("id")) not in [str(g) for g in rule.get("gates") or []]:
            continue
        req = rule.get("requires") or {}
        ent = ents.get(str(req.get("entity") or ""))
        if ent is None or not req.get("account"):
            continue
        where = {str(req["account"]): "$user.id", **{str(k): v for k, v in (req.get("where") or {}).items()}}
        out.append(({"actionType": "db_query", "table": ent.get("table"), "where": where}, rule))
    return out


def guard_workflow(doc: dict, workflow: dict, nodes: list[dict], edges: list[dict],
                   make_node: Any) -> None:
    """Put each prerequisite of `workflow` between its trigger and its first
    step, in place: a query for the satisfying record, a condition on its
    count, and a refused end carrying the rule's message."""
    guards = guard_nodes(doc, workflow)
    if not guards:
        return
    first = [e for e in edges if e.get("source") == "trigger"]
    targets = [e.get("target") for e in first]
    for e in first:
        edges.remove(e)
    def edge(src: str, tgt: str, kind: str = "default") -> None:
        # The projection's own edge shape (`projection._edges`).
        e: dict[str, Any] = {"id": f"e_{src}_{tgt}", "source": src, "target": tgt, "data": {"edgeType": kind}}
        if kind == "else":
            e["sourceHandle"] = "else"
        edges.append(e)

    # A GUARD ALREADY THERE IS NOT ADDED TWICE. A workflow whose steps were
    # written back from its projected file carries the guard's nodes; added
    # again, every id was "used twice" and the whole workflow projection
    # stopped — ToroCommerce's notification links were never rewritten
    # (forge-v3, 2026-10-07).
    have = {str(n.get("id")) for n in nodes if isinstance(n, dict)}
    guards = [(q, r) for i, (q, r) in enumerate(guards)
              if "prereq_" + re.sub(r"[^a-z0-9]+", "_", str(r.get("id") or f"rule_{i}").lower()) not in have]
    if not guards:
        for e in first:
            edges.append(e)
        return
    prev = "trigger"
    for i, (query, rule) in enumerate(guards):
        rid = re.sub(r"[^a-z0-9]+", "_", str(rule.get("id") or f"rule_{i}").lower())
        q, c, stop = f"prereq_{rid}", f"prereq_{rid}_met", f"prereq_{rid}_refused"
        nodes.append(make_node(q, "action", query, f"Check: {rule.get('name') or 'prerequisite'}"))
        nodes.append(make_node(c, "condition", {"expression": f"{q}.count > 0"},
                               f"Has {rule.get('name') or 'the prerequisite'}?"))
        nodes.append(make_node(stop, "end", {"refused": True,
                                             "message": rule.get("message") or rule.get("statement") or
                                             "This cannot be done yet."}, "Refused: prerequisite not met"))
        edge(prev, q, "then" if prev != "trigger" else "default")
        edge(q, c)
        edge(c, stop, "else")
        prev = c
    for t in targets:
        edge(prev, t, "then")


__all__ = ["AUTH_PAGES", "account_entity", "admin_role", "account_fields", "account_initial", "after_signup_route", "auth_page_bodies",
           "guard_workflow", "has_sign_in", "home_route", "is_auth_page", "prerequisites",
           "project_account", "signup_role"]
