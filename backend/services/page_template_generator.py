"""Deterministic schema generator — produces a usable PageV2 schema dict
for any page type, using the entity context from plan.

Used as a fallback when the LLM call fails for a page. The generated
schemas use real components (Form/Input/Table/MetricTile/etc.) so the
user gets a working page they can refine, not an empty stub.
"""
from __future__ import annotations
from typing import Any


def generate_template_schema(page: dict, plan: dict | None = None) -> dict:
    """Generate a complete PageV2 schema for a page, deterministically.

    Inputs:
      page: { id, route, name, type, entity? } from plan.pages
      plan: full plan; used to look up entity fields if entity is set

    Returns: a valid PageV2 dict with id, schemaVersion, dataSources, root.

    Dispatches on page.type:
      - "auth"      -> login/signup form (no shell wrap)
      - "form"      -> Form with Input/Textarea/Select per entity field
      - "list"      -> Heading + FilterBar + Table/DataGrid + Pagination
      - "detail"    -> Heading + Card containing field rows + actions
      - "dashboard" -> Heading + Row of MetricTiles + Grid of Cards
      - "settings"  -> Tabbed Form sections
      - default     -> Heading + Card with description
    """
    page_type = (page.get("type") or "").lower()
    entity_name = page.get("entity") or ""
    # Dashboards frequently declare their backing entity via ``dataSource``
    # rather than the top-level ``entity`` field. Fall back to it so the
    # dashboard body has real fields to bind against instead of stub
    # ``{{stats.*}}`` bindings that never resolve.
    if not entity_name and page_type in ("dashboard", "home"):
        entity_name = _dashboard_entity(page)
    entity = (plan or {}).get("entities", {}).get(entity_name, {})
    fields = _coerce_fields(entity.get("fields") or {})

    page_id = page.get("id") or "page"
    # Prefer a route-derived human label over a raw class-name like
    # ``MemberHome`` / ``StudioSchedule`` that leaks through from
    # ``page.name`` (LLM planners echo the page-id back into ``name``).
    # Only fall back to page.name when it's already human-friendly.
    _raw_name = str(page.get("name") or "").strip()
    _route = str(page.get("route") or "").strip()
    if _looks_like_raw_pascal(_raw_name):
        title = _humanise_route(_route) or _humanise(page_id)
    else:
        title = _raw_name or _humanise_route(_route) or _humanise(page_id)

    builder = _BUILDERS.get(page_type, _generic)
    root = builder(title, page, fields)
    return {
        "schemaVersion": "2",
        "id": page_id,
        "dataSources": _data_sources_for(page_type, entity_name),
        "root": root,
    }


# ── Per-type builders ──────────────────────────────────────────────────

def _generic(title: str, page: dict, fields: list) -> dict:
    return _stack([
        _heading(title, 1),
        _text("Open the editor to customise this page.", "text-muted-foreground text-sm"),
    ])


def _auth_login(title: str, page: dict, fields: list) -> dict:
    return _stack([
        _container(className="max-w-md mx-auto py-12", children=[
            _stack([
                _heading(title or "Sign in", 1),
                _text("Sign in to access your workspace", "text-muted-foreground"),
                _form_node(workflow="auth.signIn", children=[
                    _input("email", "Email", "email", placeholder="you@example.com"),
                    _input("password", "Password", "password", placeholder="••••••••"),
                    _button("Sign in", workflow="auth.signIn", variant="primary"),
                ]),
            ]),
        ]),
    ])


def _auth_signup(title: str, page: dict, fields: list) -> dict:
    return _stack([
        _container(className="max-w-md mx-auto py-12", children=[
            _stack([
                _heading(title or "Create account", 1),
                _text("Sign up for a new account", "text-muted-foreground"),
                _form_node(workflow="auth.signUp", children=[
                    _input("name", "Full name", "text"),
                    _input("email", "Email", "email"),
                    _input("password", "Password", "password"),
                    _button("Create account", workflow="auth.signUp", variant="primary"),
                ]),
            ]),
        ]),
    ])


def _auth(title: str, page: dict, fields: list) -> dict:
    route = (page.get("route") or "").lower()
    if "signup" in route or "register" in route:
        return _auth_signup(title, page, fields)
    return _auth_login(title, page, fields)


def _form(title: str, page: dict, fields: list) -> dict:
    form_fields = [_field_for(f) for f in fields[:8]] if fields else [
        _input("name", "Name", "text"),
        _input("description", "Description", "text"),
    ]
    return _stack([
        _row_between(_heading(title, 1), _button("Cancel", variant="ghost")),
        _form_node(workflow="form.submit", children=[
            *form_fields,
            _row([
                _button("Cancel", variant="ghost"),
                _button("Save", workflow="form.submit", variant="primary"),
            ], className="justify-end gap-2 pt-4"),
        ]),
    ])


def _list(title: str, page: dict, fields: list) -> dict:
    columns = [_column_for(f) for f in fields[:6]] if fields else [
        {"key": "id", "label": "ID"},
        {"key": "name", "label": "Name"},
        {"key": "createdAt", "label": "Created"},
    ]
    return _stack([
        _row_between(
            _heading(title, 1),
            _button("+ New", variant="primary", workflow="item.create"),
        ),
        _container(className="flex items-center gap-3 mb-4", children=[
            _input("search", "", "text", placeholder="Search...", className="max-w-sm"),
        ]),
        {"type": "DataGrid", "props": {
            "columns": columns,
            "rows": [],
            "rowKey": "id",
        }},
    ])


def _detail(title: str, page: dict, fields: list) -> dict:
    rows = [_field_row(f) for f in fields[:8]] if fields else [
        {"type": "Text", "props": {"content": "Open the editor to add detail rows."}}
    ]
    return _stack([
        _row_between(_heading(title, 1), _row([
            _button("Edit", variant="ghost", workflow="item.edit"),
            _button("Delete", variant="danger", workflow="item.delete"),
        ], className="gap-2")),
        _container(className="border rounded-lg p-6 bg-card", children=[
            _stack(rows),
        ]),
    ])


def _dashboard(title: str, page: dict, fields: list) -> dict:
    # When we can infer a backing entity, render a real bound list — a
    # working landing page that shows real data. When we cannot, emit a
    # plain heading + explanatory empty state (no fake ``{{stats.*}}``
    # bindings that render literally in the browser).
    entity_name = _dashboard_entity(page)
    if entity_name:
        columns = _dashboard_columns_for(fields)
        return _stack([
            _heading(title, 1),
            _text(f"Recent {_pluralize(entity_name)}.", "text-muted-foreground"),
            _container(className="mt-4", children=[
                {"type": "Card", "props": {"elevation": "sm"},
                 "children": [{
                     "type": "Table",
                     "props": {
                         "dataSource": "activity",
                         "columns": columns,
                         "rowKey": "id",
                         "emptyDescription": f"No {_pluralize(entity_name)} yet.",
                     },
                 }]},
            ]),
        ])
    return _stack([
        _heading(title, 1),
        _text("Open the editor to bind this dashboard to real data.",
              "text-muted-foreground"),
    ])


def _settings(title: str, page: dict, fields: list) -> dict:
    return _stack([
        _heading(title, 1),
        _text("Manage your preferences.", "text-muted-foreground"),
        _container(className="border rounded-lg p-6 bg-card", children=[
            _stack([
                _heading("General", 3),
                _form_node(workflow="settings.save", children=[
                    _input("name", "Display name", "text"),
                    _input("email", "Email", "email"),
                    _button("Save changes", workflow="settings.save", variant="primary"),
                ]),
            ]),
        ]),
    ])


_BUILDERS = {
    "auth":      _auth,
    "form":      _form,
    "list":      _list,
    "detail":    _detail,
    "dashboard": _dashboard,
    "settings":  _settings,
    # 'home' often = dashboard
    "home":      _dashboard,
}


# ── Helpers ──────────────────────────────────────────────────────────────

def _coerce_fields(fields: Any) -> list:
    """Normalise entity fields into [{name, type, label?}]."""
    if isinstance(fields, dict):
        return [
            {
                "name": k,
                "type": (v.get("type", "text") if isinstance(v, dict) else "text"),
                "label": (v.get("label") if isinstance(v, dict) else None) or k.replace("_", " ").title(),
            }
            for k, v in fields.items()
        ]
    if isinstance(fields, list):
        return [
            f if isinstance(f, dict) else {"name": str(f), "type": "text", "label": str(f)}
            for f in fields
        ]
    return []


def _field_for(f: dict) -> dict:
    t = (f.get("type") or "text").lower()
    if t == "boolean":
        return _node("Checkbox", {"name": f["name"], "label": f.get("label") or f["name"]})
    if t in ("text-long", "textarea", "richtext"):
        return _node("Textarea", {"name": f["name"], "label": f.get("label") or f["name"]})
    if t == "enum" and f.get("options"):
        return _node("Select", {
            "name": f["name"],
            "label": f.get("label") or f["name"],
            "options": f["options"],
        })
    if t == "date":
        return _node("Input", {"name": f["name"], "label": f.get("label") or f["name"], "type": "date"})
    input_type = "email" if "email" in f["name"].lower() else "text"
    if t == "number":
        input_type = "number"
    return _node("Input", {"name": f["name"], "label": f.get("label") or f["name"], "type": input_type})


def _column_for(f: dict) -> dict:
    return {"key": f["name"], "label": f.get("label") or f["name"].replace("_", " ").title()}


def _field_row(f: dict) -> dict:
    label = f.get("label") or f["name"].replace("_", " ").title()
    return _node("Row", {"className": "py-2 border-b last:border-0 justify-between"}, children=[
        _text(label, "text-muted-foreground text-sm"),
        _text(f"{{{{item.{f['name']}}}}}", "text-sm font-medium"),
    ])


import re as _re

_RAW_PASCAL_RE = _re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+$")
_RAW_PASCAL_PAGE_RE = _re.compile(r"^[A-Z][a-zA-Z0-9]*Page$")


def _looks_like_raw_pascal(s: str) -> bool:
    """True for multi-word PascalCase (``MemberHome``, ``StudioSchedule``)
    or class-name-with-``Page`` suffix — anything a user shouldn't see
    verbatim in a Heading."""
    if not s:
        return False
    return bool(_RAW_PASCAL_RE.match(s)) or bool(_RAW_PASCAL_PAGE_RE.match(s))


def _humanise_route(route: str) -> str:
    """Last meaningful route segment → title case. ``/`` → ``"Home"``."""
    if not route:
        return ""
    r = route.split("?", 1)[0].split("#", 1)[0]
    segs = [s for s in r.split("/") if s and not s.startswith("[") and not s.startswith(":")]
    if not segs:
        return "Home"
    return _humanise(segs[-1])


def _dashboard_entity(page: dict) -> str:
    """Resolve the backing entity for a dashboard page.

    Order: ``page.entity`` → ``page.dataSource.entity`` (rich plan form).
    Returns ``""`` when neither yields a usable name.
    """
    for name in (page.get("entity"),
                 (page.get("dataSource") or {}).get("entity")):
        if isinstance(name, str) and name.strip() and name.lower() not in ("unknown", "n/a", "none"):
            return name.strip()
    return ""


def _pluralize(name: str) -> str:
    """Cheap plural — good enough for empty-state prose. Preserves case."""
    if not name:
        return ""
    lower = name.lower()
    if lower.endswith("s") or lower.endswith("x") or lower.endswith("z"):
        return name + "es"
    if lower.endswith("y") and len(name) > 1 and name[-2].lower() not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _dashboard_columns_for(fields: list) -> list:
    """Pick up to 4 columns from the entity's fields for the dashboard
    Table. Skips lifecycle/audit columns (``id``/``*At``/``*By``).
    """
    skip = {"id", "createdat", "updatedat", "deletedat", "createdby", "updatedby"}
    out: list = []
    for f in fields:
        name = str(f.get("name") or "")
        if not name or name.lower() in skip or name.lower().endswith("id"):
            continue
        out.append({"key": name,
                    "header": _humanise(name),
                    "binding": f"row.{name}"})
        if len(out) >= 4:
            break
    if not out:
        out.append({"key": "id", "header": "ID", "binding": "row.id"})
    return out


def _data_sources_for(page_type: str, entity_name: str) -> list:
    if not entity_name or entity_name.lower() in ("unknown", "n/a", "none"):
        return []
    if page_type == "list":
        return [{"name": "items", "entity": entity_name, "op": "list"}]
    if page_type == "detail":
        return [{"name": "item", "entity": entity_name, "op": "get"}]
    if page_type == "form":
        return [{"name": "draft", "entity": entity_name, "op": "draft"}]
    if page_type == "dashboard":
        return [
            {"name": "stats", "entity": entity_name, "op": "aggregate"},
            {"name": "activity", "entity": entity_name, "op": "list", "limit": 5},
        ]
    return []


# Tiny node-builder helpers — keep generation readable
def _node(type_: str, props: dict, children: list | None = None) -> dict:
    out: dict = {"type": type_, "props": props}
    if children is not None:
        out["children"] = children
    return out


def _stack(children: list, className: str = "gap-6") -> dict:
    return _node("Stack", {"className": className}, children)


def _row(children: list, className: str = "items-center gap-4") -> dict:
    return _node("Row", {"className": className}, children)


def _row_between(left: dict, right: dict) -> dict:
    return _node("Row", {"className": "items-center justify-between mb-4"}, [left, right])


def _container(children: list, className: str = "") -> dict:
    return _node("Container", {"className": className}, children)


def _heading(content: str, level: int = 1) -> dict:
    return _node("Heading", {"content": content, "level": level})


def _text(content: str, className: str = "") -> dict:
    return _node("Text", {"content": content, "className": className})


def _input(name: str, label: str, type_: str, placeholder: str = "", className: str = "") -> dict:
    props: dict = {"name": name, "label": label, "type": type_}
    if placeholder:
        props["placeholder"] = placeholder
    if className:
        props["className"] = className
    return _node("Input", props)


def _button(label: str, variant: str = "primary", workflow: str | None = None,
            navigate: str | None = None, className: str = "") -> dict:
    props: dict = {"label": label, "variant": variant}
    if workflow:
        props["workflow"] = workflow
    if navigate:
        props["navigate"] = navigate
    if className:
        props["className"] = className
    return _node("Button", props)


def _form_node(workflow: str, children: list) -> dict:
    return _node("Form", {"workflow": workflow, "className": "flex flex-col gap-4"}, children)


def _metric(label: str, value: str, hint: str = "") -> dict:
    props: dict = {"label": label, "value": value}
    if hint:
        props["hint"] = hint
    return _node("MetricTile", props)


def _humanise(slug: str) -> str:
    # Split camelCase/PascalCase runs so ``bookedAt`` → ``Booked At`` and
    # ``cancellationType`` → ``Cancellation Type`` — column headers derived
    # from Drizzle field names need this or they read as one flat word.
    spaced = _re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(slug))
    return " ".join(w.capitalize() for w in spaced.replace("-", " ").replace("_", " ").split())
