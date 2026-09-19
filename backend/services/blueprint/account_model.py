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
    application's only role, else none."""
    roles = _live(doc.get("roles"))
    rid = str(((doc.get("security") or {}).get("signupRole")) or "")
    if rid:
        hit = next((r for r in roles if str(r.get("id")) == rid), None)
        if hit and hit.get("name"):
            return str(hit["name"])
    return str(roles[0].get("name")) if len(roles) == 1 and roles[0].get("name") else None


def _humanise(name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").split()
    return " ".join(words).capitalize() if words else name


def account_fields(doc: dict) -> list[dict]:
    """What signup asks for the person's own record: the account entity's
    fields a person types — not system columns, not references to other
    records (those are made later), not files or vectors."""
    ent = account_entity(doc)
    if ent is None:
        return []
    out = []
    for f in ent.get("fields") or []:
        name = str(f.get("name") or "")
        ftype = str(f.get("type") or "string").lower()
        if not name or name in _SYSTEM or f.get("primaryKey") or f.get("references"):
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


def prerequisites(doc: dict) -> list[dict]:
    return [r for r in _live(doc.get("businessRules")) if r.get("kind") == "prerequisite"]


def _route_of(doc: dict, page_id: str | None) -> str | None:
    page = next((p for p in _live(doc.get("pages")) if str(p.get("id")) == str(page_id or "")), None)
    route = str((page or {}).get("route") or "")
    return route if route and "[" not in route else None


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
        + f"export const SIGNUP_ROLE: string | null = {json.dumps(signup_role(doc))};\n\n"
        + f"export const AFTER_SIGNUP: string = {json.dumps(after_signup_route(doc))};\n\n"
        + f"export const HOME: string = {json.dumps(home_route(doc))};\n", "utf-8")
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


__all__ = ["AUTH_PAGES", "account_entity", "account_fields", "after_signup_route", "auth_page_bodies",
           "guard_workflow", "has_sign_in", "home_route", "is_auth_page", "prerequisites",
           "project_account", "signup_role"]
