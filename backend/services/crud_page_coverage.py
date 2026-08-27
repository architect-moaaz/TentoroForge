"""Guarantee every user-facing entity with a Create workflow has a create page.

The page agent reliably builds full CRUD pages for the primary entity but often
skips the create form for secondary entities (e.g. a Projects list with no
`/projects/new`). The Create<Entity> workflow already declares the table and the
exact writable columns, so we can deterministically synthesize the missing create
form from it — always correct, no LLM, no guesswork.

A create page is only synthesized for entities that have a list page
(`src/schemas/<table>.json`); junction tables (task_tags …) have no list and are
skipped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_SYSTEM = {"id", "createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"}

# Column-name signals that an entity is auth-managed. When a plan's own
# authoritative "users" table (or any table with password_hash / password /
# hashed_password) shows up here, next-auth owns creation/edit — synthesizing
# a public `/users/new` or `/users/[id]/edit` page exposes the credential
# store to any browser. Skip CRUD scaffolding for these entities.
_AUTH_COLUMN_SIGNALS = {"password", "passwordhash", "password_hash", "hashedpassword", "hashed_password"}


def _is_auth_entity(table: str, values: list[str]) -> bool:
    """True when the entity is auth-managed and must NOT get public CRUD pages.

    Signals (any of):
      - table is 'users' or 'user'
      - any column name suggests a credential (password / password_hash)
    """
    if str(table or "").lower() in {"users", "user"}:
        return True
    return any(str(v).lower().replace("_", "") in _AUTH_COLUMN_SIGNALS for v in values)


def _label(col: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", col)        # camelCase -> "camel Case"
    s = s.replace("_", " ")
    s = re.sub(r"\bId\b", "", s).strip()             # drop trailing "Id"
    return (s[:1].upper() + s[1:]) if s else col


def _create_form(entity: str, table: str, fields: list[str]) -> dict:
    inputs = [{"type": "Input", "props": {"name": c, "label": _label(c)}} for c in fields]
    buttons = {"type": "Row", "props": {"gap": "tokens.spacing.2"}, "children": [
        {"type": "Button", "props": {"label": "Cancel", "variant": "ghost", "navigate": f"/{table}"}},
        # submit-only: the Button's requestSubmit() triggers the Form's onSubmit, which
        # collects FormData and dispatches the Form's workflow. Putting `workflow` here too
        # would ALSO fire a second, argument-less dispatch (empty insert → NOT NULL fail).
        {"type": "Button", "props": {"label": f"Create {entity}", "variant": "primary",
                                      "submit": True}},
    ]}
    return {"schemaVersion": "2", "id": f"{table}-new", "route": f"/{table}/new",
            "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": [
        {"type": "Heading", "props": {"content": f"Add New {entity}", "level": 1}},
        {"type": "Form", "props": {"workflow": f"Create{entity}"}, "children": [
            {"type": "Stack", "props": {"gap": "tokens.spacing.4"}, "children": [*inputs, buttons]},
        ]},
    ]}}


def _detail_page(entity: str, table: str, fields: list[str], has_delete: bool) -> dict:
    var = entity[:1].lower() + entity[1:]
    title_field = next((f for f in ("name", "title", "label") if f in fields), None)
    heading = f"{{{{{var}.{title_field}}}}}" if title_field else f"{entity} Details"
    rows = [{"type": "Row", "props": {"justify": "between"}, "children": [
        {"type": "Text", "props": {"content": _label(c), "color": "muted"}},
        {"type": "Text", "props": {"content": f"{{{{{var}.{c}}}}}", "weight": "medium"}},
    ]} for c in fields]
    actions = [{"type": "Button", "props": {"label": "Back", "variant": "ghost", "navigate": f"/{table}"}}]
    if has_delete:
        actions.append({"type": "Button", "props": {
            "label": "Delete", "variant": "destructive", "workflow": f"Delete{entity}"}})
    return {
        "schemaVersion": "2",
        "id": f"{table}-detail",
        "route": f"/{table}/[id]",
        "dataSources": [{"name": var, "entity": entity, "op": "get"}],
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": [
            {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
                {"type": "Heading", "props": {"content": heading, "level": 1}},
                {"type": "Row", "props": {"gap": "tokens.spacing.2"}, "children": actions},
            ]},
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": "tokens.spacing.3"}, "children": rows},
            ]},
        ]},
    }


def _bound_routes(schemas: Path) -> set[str]:
    """Every route a schema navigates to (Button.navigate / href / to / link).

    Used so a create page is synthesized whenever some button links to
    `/<table>/new` even if that entity has no list page (e.g. an admin
    "New User" button → /users/new where there's no /users list) — a bound
    route that 404s is worse than a junction table with no list page.
    """
    routes: set[str] = set()
    pat = re.compile(r'"(?:navigate|href|to|link)"\s*:\s*"(/[^"]+)"')
    for f in schemas.rglob("*.json"):
        try:
            routes.update(pat.findall(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return routes


def ensure_crud_pages(output_dir: str | Path) -> dict:
    base = Path(output_dir)
    wf_dir = base / "workflows"
    schemas = base / "src" / "schemas"
    report = {"created": []}
    if not wf_dir.is_dir() or not schemas.is_dir():
        return report

    bound = _bound_routes(schemas)

    # FK-role authority: hide only server-filled (actor/tenancy) FKs; a domain FK
    # (e.g. ownerId -> owners) is a real field and must survive into the form.
    try:
        from services.fk_semantics import hidden_fk_columns, default_hidden_fk_norms
        from services.form_scaffold import _load_registry
        _reg = _load_registry(str(output_dir))
    except Exception:
        hidden_fk_columns = None
        default_hidden_fk_norms = lambda: set()
        _reg = None

    for wf in sorted(wf_dir.glob("Create*.json")):
        try:
            data = json.loads(wf.read_text(encoding="utf-8"))
        except Exception:
            continue
        nodes = (data.get("definition") or {}).get("nodes") or data.get("nodes") or []
        cfg = next(((n.get("data") or {}).get("config") or {} for n in nodes
                    if ((n.get("data") or {}).get("config") or {}).get("actionType") == "db_insert"), {})
        table = cfg.get("table")
        values = list((cfg.get("values") or {}).keys())
        name = data.get("name") or ""
        entity = name[len("Create"):] if name.startswith("Create") else (table or "")
        if not (table and values and entity):
            continue
        # P1-G5: never scaffold public CRUD pages for auth-managed entities —
        # next-auth handles user creation via /register + /login, and exposing
        # /users/new + /users/[id]/edit as public schemas leaks the credential
        # store surface. If the app genuinely needs an admin user-management
        # page, it must be planner-authored (not deterministically synthesized).
        if _is_auth_entity(table, values):
            continue
        # User-facing entities: those with a list page OR a route that links to
        # their create/detail page. Skip pure junction tables (neither).
        has_list = (schemas / f"{table}.json").exists()
        new_bound = f"/{table}/new" in bound
        detail_bound = any(r.startswith(f"/{table}/") and r != f"/{table}/new" for r in bound)
        if not (has_list or new_bound or detail_bound):
            continue
        if hidden_fk_columns is not None and _reg is not None:
            hidden = hidden_fk_columns(entity, _reg, str(output_dir))
        else:
            hidden = default_hidden_fk_norms()
        fields = [c for c in values
                  if c.lower() not in _SYSTEM and re.sub(r"[^a-z0-9]", "", c.lower()) not in hidden]
        if not fields:
            continue
        has_delete = (wf_dir / f"Delete{entity}.json").exists()

        # Create page — synthesize if a list exists or a button links to /<t>/new.
        new_path = schemas / table / "new.json"
        if (has_list or new_bound) and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(json.dumps(_create_form(entity, table, fields), indent=2), encoding="utf-8")
            report["created"].append(f"{table}/new.json")

        # Detail page — only when there's a list or a bound detail route.
        detail_path = schemas / table / "[id].json"
        if (has_list or detail_bound) and not detail_path.exists():
            detail_path.parent.mkdir(parents=True, exist_ok=True)
            detail_path.write_text(json.dumps(_detail_page(entity, table, fields, has_delete), indent=2), encoding="utf-8")
            report["created"].append(f"{table}/[id].json")
    return report
