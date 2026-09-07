"""Deterministic app-model.json builder — expands the plan into a dependency
graph + page/route manifest that downstream code and agents read.

The planner decides WHAT the app contains (entities, relations); this module
just expands those decisions faithfully into conventional file paths, a
bidirectional dependency graph, and a page/route manifest. Zero LLM cost.

Reads the canonical resource registry (same authority the api-client + schema
builder use) so entity route/table segments never re-derive names independently.
"""

import json
import logging
from pathlib import Path
from typing import Any

from services.name_normalizer import to_table as _to_table, to_slug as _to_slug
from services.route_slug import normalise_route

logger = logging.getLogger(__name__)


def _registry_entities(plan: dict, registry: dict | None) -> dict:
    """The canonical registry ``entities`` map (keyed by PascalName). Built once
    from the SAME plan when not supplied. Never raises — returns ``{}`` on
    failure so callers fall back to the name_normalizer trio."""
    if registry is None:
        try:
            from services.resource_registry import build_canonical_registry
            registry = build_canonical_registry(plan)
        except Exception as e:  # noqa: BLE001 — registry is best-effort here
            logger.warning("resource registry unavailable for app-model: %s", e)
            registry = {}
    return (registry or {}).get("entities") or {}


def _fam(entities: dict, name: str) -> dict:
    """Name family (``table``/``slug``) for ``name`` from the registry, falling
    back to the canonical normalizer when the entity isn't registered."""
    rec = entities.get(name)
    if isinstance(rec, dict) and rec.get("table"):
        return rec
    return {"table": _to_table(name), "slug": _to_slug(name)}


def _normalize_models(data_models: Any) -> list[dict]:
    """Accept ``data_models`` as a list of ``{"name", ...}`` OR a legacy dict
    keyed by name; normalize to a list of dicts each carrying ``name``."""
    if isinstance(data_models, dict):
        out: list[dict] = []
        for name, body in data_models.items():
            entry = dict(body) if isinstance(body, dict) else {}
            entry.setdefault("name", name)
            out.append(entry)
        return out
    if isinstance(data_models, list):
        return [m for m in data_models if isinstance(m, dict) and m.get("name")]
    return []


def _rel_endpoints(rel: dict) -> tuple[str | None, str | None]:
    """Read (source, target) from a relation, tolerating field-name variants."""
    src = rel.get("from") or rel.get("source")
    tgt = rel.get("to") or rel.get("target")
    return (src or None), (tgt or None)


def _dedup(seq: list[str]) -> list[str]:
    """Stable dedup preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_app_model(plan: dict, registry: dict | None = None) -> dict:
    """Expand the plan into the app-model dependency graph + page/route manifest.

    ``registry`` is the canonical resource registry (built from the SAME plan);
    when omitted it's built here. Entity ``table``/``slug`` segments come from it,
    so a planner ``table`` hint (e.g. uncountable ``equipment``) is honored and
    never re-pluralized."""
    models = _normalize_models(plan.get("data_models"))
    names = [m["name"] for m in models]
    known = set(names)
    reg_entities = _registry_entities(plan, registry)

    relations = plan.get("relations") or []
    depends: dict[str, list[str]] = {n: [] for n in names}
    used_by: dict[str, list[str]] = {n: [] for n in names}
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        src, tgt = _rel_endpoints(rel)
        if src in known and tgt in known and src != tgt:
            depends[src].append(tgt)
            used_by[tgt].append(src)

    entities: dict[str, Any] = {}
    routes: list[dict] = []

    for name in names:
        # `table` (camelCase plural) is the Drizzle table constant AND the
        # api-client fetch segment (api-client.ts uses _to_table). `slug`
        # (kebab plural) is the filesystem segment for schema/type/page files
        # and page routes — this is what schema_builder writes and what the
        # app actually routes on. Keeping them distinct is the platform's
        # existing convention, not a new choice.
        fam = _fam(reg_entities, name)
        table = fam["table"]   # Order -> orders, ExpenseReport -> expenseReports, hint honored
        slug = fam["slug"]     # Order -> orders, ExpenseReport -> expense-reports
        name_lc = name.lower()
        entities[name] = {
            "table": table,
            "schema": f"src/db/schema/{slug}.ts",
            "type": f"src/types/{slug}.ts",
            "api": [
                f"src/app/api/{table}/route.ts",
                f"src/app/api/{table}/[id]/route.ts",
            ],
            "components": [
                f"src/components/{slug}/{name}Table.tsx",
                f"src/components/{slug}/{name}Form.tsx",
            ],
            "pages": [
                f"src/app/{slug}/page.tsx",
                f"src/app/{slug}/[id]/page.tsx",
            ],
            "depends_on": _dedup(depends[name]),
            "used_by": _dedup(used_by[name]),
        }

        routes.extend([
            {"method": "GET", "path": f"/api/{table}", "description": f"List {table}"},
            {"method": "POST", "path": f"/api/{table}", "description": f"Create {name_lc}"},
            {"method": "GET", "path": f"/api/{table}/[id]", "description": f"Get {name_lc}"},
            {"method": "PATCH", "path": f"/api/{table}/[id]", "description": f"Update {name_lc}"},
            {"method": "DELETE", "path": f"/api/{table}/[id]", "description": f"Delete {name_lc}"},
        ])

    return {
        "name": plan.get("name", ""),
        "entities": entities,
        "pages": _build_pages(plan, names, reg_entities),
        "routes": routes,
    }


def _build_pages(plan: dict, names: list[str], reg_entities: dict | None = None) -> list[dict]:
    """Page manifest for app-model.json.

    Faithful to the planner's OWN pages (their real routes — including non-CRUD
    archetypes like kanban/report/calendar/inbox that entity-derivation would
    miss) when ``plan.pages`` is present; otherwise derives list/create/detail
    per entity. Always guarantees the four fixed pages (dashboard, login,
    signup, error) so phase_gates + auth flows are satisfied. Every entry
    carries a ``route`` (the one field phase_gates reads)."""
    out: list[dict] = []
    seen: set[str] = set()

    for p in (plan.get("pages") or []):
        if not isinstance(p, dict):
            continue
        raw = p.get("route") or ""
        if not raw:
            continue
        route = normalise_route(raw)  # ":id" -> "[id]"
        if route in seen:
            continue
        seen.add(route)
        entry = {
            "route": route,
            "component": p.get("name") or "",
            "description": p.get("description") or "",
        }
        if p.get("entity"):
            entry["entity"] = p["entity"]
        out.append(entry)

    if not out:  # planner emitted no pages — derive CRUD routes per entity
        for name in names:
            slug = _fam(reg_entities or {}, name)["slug"]
            for route, comp, desc in [
                (f"/{slug}", f"{name}ListPage", f"{name} list"),
                (f"/{slug}/new", f"{name}CreatePage", f"Create {name}"),
                (f"/{slug}/[id]", f"{name}DetailPage", f"{name} detail"),
            ]:
                out.append({"route": route, "component": comp, "description": desc, "entity": name})
                seen.add(route)

    for route, comp, desc in [
        ("/", "DashboardPage", "Dashboard"),
        ("/login", "LoginPage", "Sign in"),
        ("/signup", "SignupPage", "Sign up"),
        ("/error", "ErrorPage", "Error"),
    ]:
        if route not in seen:
            out.append({"route": route, "component": comp, "description": desc})
            seen.add(route)

    return out


def write_app_model(output_dir: str, plan: dict, registry: dict | None = None) -> str:
    """Build the app-model and write it to
    ``<output_dir>/src/contracts/app-model.json`` (indent=2). Returns the path."""
    model = build_app_model(plan, registry)
    path = Path(output_dir) / "src" / "contracts" / "app-model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    logger.info("Wrote app-model.json: %d entities", len(model["entities"]))
    return str(path)
