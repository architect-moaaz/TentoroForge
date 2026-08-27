"""Fill in missing pages the LLM referenced but never emitted, for the
**singleton-shape** class of routes (``/profile``, ``/profile/edit``,
``/account``, ``/account/edit``, ``/settings/profile``, …).

Bug 4 in the cabin-crew ATS: the Profile view had an "Edit" button
that navigated to ``/profile/edit`` — but no schema at that route
exists in the registry, so the page rendered blank. ``ensure_crud_pages``
covers entity-shaped routes (``/x/new``, ``/x/[id]/edit``) but not the
singleton case where the "current user's X" doesn't have an ``[id]``.

This reconciler generalizes: for every navigation target the LLM emits
that isn't backed by a schema and matches a singleton pattern, we
synthesize a session-bound page and register it. The LLM's intent is
preserved (dead links are fixed) without asking the LLM to author the
missing page.

Contract:
  * ``reconcile_singleton_pages(output_dir) -> {"created": [routes]}``
    — pure result, safe to call idempotently. Never raises.

Detection rules:
  1. The target route matches ``^/<noun>(/edit)?$`` — one non-dynamic
     segment (plus optional ``/edit``).
  2. The target route has no schema file (``src/schemas/<slug>.json``).
  3. The noun aligns with the User entity in the registry (``profile``,
     ``account``, ``me``) — this is the "current user's X" pattern.

For each match we synthesize:
  * ``/profile`` → a read-only detail card bound to a session-filtered
    User row.
  * ``/profile/edit`` → an editable Form over the User entity's
    editable columns, bound to session, dispatching an ``UpdateUser``
    workflow (or the registry-declared update workflow if named).

Both variants get registered in ``src/schemas/registry.ts`` so the
runtime resolver finds them.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Noun → entity mapping. Keep this small and explicit — the singleton
# class is inherently narrow. Extend when a real domain needs it.
_SINGLETON_NOUNS: dict[str, str] = {
    "profile":  "User",
    "account":  "User",
    "me":       "User",
}

_SYSTEM_COLS = {"id", "password", "createdat", "updatedat", "deletedat",
                "created_at", "updated_at", "deleted_at"}

_TARGET_RE = re.compile(r'"(?:navigate|href|to|link)"\s*:\s*"(/[^"]+)"')
_SINGLETON_ROUTE_RE = re.compile(r"^/([a-z][a-z0-9_-]*)(/edit)?$")


def reconcile_singleton_pages(output_dir: str | Path) -> dict[str, Any]:
    """Detect + synthesize singleton pages the LLM referenced but never
    emitted. Returns ``{"created": [route, ...]}`` — routes new to the
    app after this pass. Idempotent; never raises.

    Record Authority does NOT disable this pass, despite an earlier
    comment here claiming the record composer's tail-fill made it
    redundant. It doesn't: the composer fills routes listed in the
    *plan*, and never reads ``nav-flow.json`` — while this reconciler
    exists precisely to catch routes the LLM *linked to* but nobody
    emitted (``/profile``, ``/profile/edit``). Different inputs, so
    different coverage.

    Nor can it race the composer: synthesis is skipped for any route
    whose file already exists, so this only ever ADDS a page the
    composer would otherwise have nothing to compose.
    """
    try:
        result = _reconcile(Path(output_dir))
        result.setdefault("asserts_logged", 0)
        return result
    except Exception:  # noqa: BLE001
        log.exception("singleton_page_reconciler: failed — continuing")
        return {"created": [], "asserts_logged": 0}


def _reconcile(base: Path) -> dict[str, Any]:
    schemas = base / "src" / "schemas"
    if not schemas.is_dir():
        return {"created": []}

    # Load registry to know what entities exist + their editable columns.
    reg = _load_registry(base)
    entities = reg.get("entities") or {}
    if not entities:
        return {"created": []}

    # Every navigation target across every emitted schema — the LLM's
    # declared intent set.
    nav_targets: set[str] = set()
    for f in schemas.rglob("*.json"):
        try:
            nav_targets.update(_TARGET_RE.findall(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue

    # Every route already backed by a schema — the fulfilled set.
    fulfilled = _bound_schema_routes(schemas)

    created: list[str] = []
    for route in sorted(nav_targets - fulfilled):
        m = _SINGLETON_ROUTE_RE.match(route)
        if not m:
            continue
        noun = m.group(1)
        is_edit = m.group(2) is not None
        entity_name = _SINGLETON_NOUNS.get(noun.lower())
        if not entity_name or entity_name not in entities:
            continue

        # Emit the schema file + record for registry update below.
        slug = f"{noun}/edit" if is_edit else noun
        target_file = schemas / f"{slug}.json"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.exists():
            continue

        entity = entities[entity_name]
        fields = _editable_fields(entity, entity_name)
        if is_edit:
            doc = _singleton_edit_schema(entity_name, noun, fields)
        else:
            doc = _singleton_detail_schema(entity_name, noun, fields)
        target_file.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        created.append(route)

    if created:
        _register_in_registry_ts(base, created)
    return {"created": created}


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _load_registry(base: Path) -> dict:
    reg = base / "registry.json"
    if not reg.is_file():
        return {}
    try:
        return json.loads(reg.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _bound_schema_routes(schemas: Path) -> set[str]:
    """Every route with an emitted schema. Derived from filename layout —
    ``foo/bar.json`` → ``/foo/bar``, root ``foo.json`` → ``/foo``."""
    out: set[str] = set()
    for f in schemas.rglob("*.json"):
        rel = f.relative_to(schemas).with_suffix("")
        parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
        if not parts:
            continue
        out.add("/" + "/".join(parts))
    return out


def _editable_fields(entity: dict, entity_name: str) -> list[tuple[str, dict]]:
    """Yield ``(name, meta)`` for columns editable on the form. Filters PK,
    audit/lifecycle timestamps, and password columns. Keeps first-seen order."""
    fields = entity.get("fields") or {}
    if isinstance(fields, dict):
        it = fields.items()
    elif isinstance(fields, list):
        it = ((f.get("name"), f) for f in fields if isinstance(f, dict) and f.get("name"))
    else:
        return []
    out: list[tuple[str, dict]] = []
    for name, meta in it:
        if not isinstance(name, str):
            continue
        m = meta if isinstance(meta, dict) else {}
        if m.get("primaryKey") or m.get("primary_key"):
            continue
        low = "".join(ch for ch in name.lower() if ch.isalnum())
        if low in _SYSTEM_COLS:
            continue
        out.append((name, m))
    return out


def _label(col: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", col)
    s = s.replace("_", " ")
    s = re.sub(r"\bId\b", "", s).strip()
    return (s[:1].upper() + s[1:]) if s else col


def _singleton_detail_schema(entity_name: str, noun: str, fields: list[tuple[str, dict]]) -> dict:
    """A read-only card showing the current user's ``entity`` record.

    dataSource uses ``op: "readOne"`` with a session-bound predicate;
    ``{{session.user.id}}`` is resolved by the workflow runtime. Renderer
    resolvers already understand this binding shape (`optionsFrom`,
    dataSource `where` clauses).
    """
    var = noun
    label_field = next((n for n, _ in fields if n.lower() in ("name", "fullname",
                                                              "displayname", "email")), None)
    heading_expr = f"{{{{{var}.{label_field}}}}}" if label_field else f"{entity_name} Profile"
    rows = [{"type": "Row", "props": {"justify": "between"}, "children": [
        {"type": "Text", "props": {"content": _label(n), "color": "muted"}},
        {"type": "Text", "props": {"content": f"{{{{{var}.{n}}}}}"}},
    ]} for n, _ in fields]
    actions = [
        {"type": "Button", "props": {"label": "Edit", "variant": "primary",
                                     "navigate": f"/{noun}/edit"}},
    ]
    return {
        "schemaVersion": "2",
        "id": f"{noun}",
        "route": f"/{noun}",
        "layout": "main",
        "dataSources": [{
            "name": var,
            "entity": entity_name,
            "op": "readOne",
            "where": {"id": "{{session.user.id}}"},
        }],
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": [
            {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
                {"type": "Heading", "props": {"content": heading_expr, "level": 1}},
                {"type": "Row", "props": {"gap": "tokens.spacing.2"}, "children": actions},
            ]},
            {"type": "Card", "children": [
                {"type": "Stack", "props": {"gap": "tokens.spacing.3"}, "children": rows},
            ]},
        ]},
    }


def _singleton_edit_schema(entity_name: str, noun: str, fields: list[tuple[str, dict]]) -> dict:
    """Form that updates the current user's record.

    Dispatches an ``Update<Entity>`` workflow whose write clause is
    session-bound (``id = session.user.id``). The workflow generator
    already emits ``UpdateUser`` when the plan declares a User update
    action; we just point the form at it. If it doesn't exist, the form
    still renders — the workflow-dispatcher surfaces an error on submit,
    which is a strictly better failure mode than a blank page.
    """
    var = noun
    inputs = []
    for n, meta in fields:
        # Use the label + defaultValue-from-session-record so the form pre-fills.
        inputs.append({"type": "Input", "props": {
            "name": n,
            "label": _label(n),
            "defaultValue": f"{{{{{var}.{n}}}}}",
        }})
    buttons = {"type": "Row", "props": {"gap": "tokens.spacing.2"}, "children": [
        {"type": "Button", "props": {"label": "Cancel", "variant": "ghost",
                                      "navigate": f"/{noun}"}},
        {"type": "Button", "props": {"label": "Save", "variant": "primary",
                                      "submit": True}},
    ]}
    return {
        "schemaVersion": "2",
        "id": f"{noun}-edit",
        "route": f"/{noun}/edit",
        "layout": "main",
        "dataSources": [{
            "name": var,
            "entity": entity_name,
            "op": "readOne",
            "where": {"id": "{{session.user.id}}"},
        }],
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"}, "children": [
            {"type": "Heading", "props": {"content": f"Edit {entity_name}", "level": 1}},
            {"type": "Form", "props": {"workflow": f"Update{entity_name}"}, "children": [
                {"type": "Stack", "props": {"gap": "tokens.spacing.4"},
                 "children": [*inputs, buttons]},
            ]},
        ]},
    }


def _register_in_registry_ts(base: Path, routes: list[str]) -> None:
    """Append the new route entries to ``src/schemas/registry.ts`` so the
    runtime resolver can find them. Idempotent — never adds a key twice."""
    reg_ts = base / "src" / "schemas" / "registry.ts"
    if not reg_ts.is_file():
        return
    try:
        txt = reg_ts.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return
    lines: list[str] = []
    for route in routes:
        if f'"{route}"' in txt:
            continue
        slug = route.lstrip("/")
        lines.append(f'  "{route}": () => import("./{slug}.json"),')
    if not lines:
        return
    # Splice before the closing brace of the `schemas` record.
    marker_re = re.compile(r"(export\s+const\s+schemas[^{]*\{)([\s\S]*?)(\n\};?\s*$)")
    m = marker_re.search(txt)
    if not m:
        return
    inserted = m.group(2).rstrip() + "\n" + "\n".join(lines) + "\n"
    new_txt = txt[: m.start(2)] + inserted + txt[m.end(2) :]
    try:
        reg_ts.write_text(new_txt, encoding="utf-8")
    except Exception:  # noqa: BLE001
        log.warning("singleton_page_reconciler: registry.ts write failed")
