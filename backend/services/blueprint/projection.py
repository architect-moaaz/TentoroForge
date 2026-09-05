"""Projection — the Blueprint written out as artifacts the engines read.

The generated app is not bespoke source. It is a fixed scaffold plus vendored
engines (``@tentoroforge/engine`` for rendering, the workflow engine, the data
layer) that interpret Blueprint-derived files at run time. So turning a
Blueprint into a running application is a *projection*, not code generation —
and projection is deterministic, which is why these are service nodes and not
model calls.

This module covers the **data layer** — entities become Drizzle table modules
in ``src/db/schema/`` — and the **frontend**, where each page contract is
instantiated from its pattern template into an engine page schema under
``src/schemas/``. Neither involves a model call: the frontend one is
deterministic because A2UI already made the one creative decision (what the
pattern's structure is) once per pattern, leaving per-page work that is pure
substitution. The workflow and design projections are not done — see
:data:`REMAINING`.

Every file written is recorded in ``codeMap`` (§21), which is what makes the
§75 ``Blueprint↔Implementation`` edge checkable against real paths instead of
against a model's guess.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.catalog import WorkflowNodeCatalog, workflow_nodes
from services.workflow_nodes import workflow_node
logger = logging.getLogger(__name__)

#: What projection still owes, so a green data-layer run is not mistaken for a
#: runnable app.
REMAINING: tuple[str, ...] = (
    "assembly: scaffold + vendored engines + install + migrate + preview "
    "(the projections all land on disk; nothing has run them into a served app)",
)

#: Blueprint field type -> (drizzle builder, import name).
_TYPES: dict[str, str] = {
    "uuid": "uuid", "guid": "uuid",
    "text": "text", "string": "text", "str": "text", "email": "text",
    "url": "text", "enum": "text", "file": "text",
    "int": "integer", "integer": "integer", "number": "integer",
    "decimal": "numeric", "numeric": "numeric", "float": "numeric",
    "money": "numeric", "currency": "numeric",
    "bool": "boolean", "boolean": "boolean",
    "date": "date",
    "datetime": "timestamp", "timestamp": "timestamp", "time": "timestamp",
    "json": "jsonb", "jsonb": "jsonb", "object": "jsonb", "array": "jsonb",
}
_DEFAULT_TYPE = "text"


def _live(items: Any) -> list[dict]:
    """Artifacts still in play. A DEPRECATED page is not projected."""
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def to_snake(name: str) -> str:
    """``fullName`` -> ``full_name``. The column convention the scaffold uses."""
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", (name or "").strip())
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()


def _module_name(entity: dict) -> str:
    return to_snake(entity.get("name") or entity.get("table") or "entity")


def _var_name(entity: dict) -> str:
    """Drizzle export name — the table, as the scaffold writes it (``users``)."""
    table = entity.get("table") or to_snake(entity.get("name") or "")
    parts = table.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


#: Timestamps the application sets for itself. Imported from the planner so
#: "do not ask a person for this" and "the database must fill this" cannot
#: disagree about which columns they are.
from services.blueprint.page_planner import DERIVED_ON_CREATE


def drizzle_column(field: dict) -> tuple[str, str]:
    """One column line and the builder it needs imported."""
    builder = _TYPES.get(str(field.get("type") or "").lower(), _DEFAULT_TYPE)
    col = to_snake(field.get("name") or "col")
    line = f'{field.get("name")}: {builder}("{col}")'
    if field.get("primaryKey"):
        line += ".primaryKey()"
        if builder == "uuid":
            line += ".defaultRandom()"
    if field.get("required") and not field.get("primaryKey"):
        line += ".notNull()"
    if field.get("unique"):
        line += ".unique()"
    # A NOT NULL timestamp nobody can supply must default, or the row cannot be
    # written at all. `created_at` was `.notNull()` with no default, and
    # `form_fields_for` correctly refuses to ask a person for it — so every
    # insert this app could make failed with "null value in column created_at
    # violates not-null constraint", after the workflow had run every node
    # green. The two rules are one fact seen from both ends: DERIVED_ON_CREATE
    # says nothing will supply this column, and a column nothing supplies needs
    # the database to fill it.
    derived_now = (builder == "timestamp"
                   and str(field.get("name") or "").lower() in DERIVED_ON_CREATE)
    if field.get("defaultNow") or derived_now:
        line += ".defaultNow()"
    default = field.get("default")
    if default is not None:
        # A platform column's default is part of its contract, not decoration.
        # Dropping `isActive.default(true)` made every signup write NULL, and
        # NextAuth's authorize rejects a falsy isActive — so accounts were
        # created successfully and then could never log in.
        literal = ("true" if default is True else "false" if default is False
                   else str(default) if isinstance(default, (int, float))
                   else f'"{default}"')
        line += f".default({literal})"
    return line + ",", builder


#: Tables the platform owns. Auth is a platform service (§97) with a fixed
#: contract: the signup route writes `password` and `name`, `authorize` rejects
#: a falsy `isActive`, and NextAuth reads them back. The data model agent, asked
#: to design a recruitment app, reasonably authored a `User` entity with
#: `passwordHash`, `fullName` and `userRole` — projecting that over the
#: platform's table produced a schema where signup failed outright.
#:
#: So the rule is: the Blueprint may *extend* a platform table, never redefine
#: it. Platform columns are emitted as the platform declares them; anything the
#: Blueprint adds is appended and nullable, because platform code inserts rows
#: without knowing those columns exist.
#:
#: The declaration is PARSED from the scaffold rather than transcribed here.
#: Three separate bugs came from a hand-copy drifting off the original — wrong
#: column names, then a missing `.default(true)` on `isActive` that made every
#: account unable to log in, then `createdAt` omitted entirely. A copy of a
#: contract is a contract that will diverge.
PLATFORM_TABLE_SOURCES: dict[str, str] = {
    "users": "templates/app-foundation/src/db/schema/user.ts",
}

#: Drizzle builder -> the Blueprint field type that emits it again.
_BUILDER_TYPES: dict[str, str] = {
    "uuid": "uuid", "text": "text", "varchar": "text", "boolean": "boolean",
    "integer": "int", "numeric": "numeric", "timestamp": "timestamp",
    "date": "date", "jsonb": "json",
}

_COLUMN_RE = re.compile(
    r"(?P<field>\w+)\s*:\s*(?P<builder>\w+)\(\s*\"(?P<column>[^\"]+)\"\s*\)"
    r"(?P<mods>(?:\.\w+\([^()]*\))*)"
)


def parse_platform_table(source: str) -> tuple[dict, ...]:
    """Read a Drizzle ``pgTable`` declaration back into Blueprint field dicts.

    Only the parts that change what gets emitted: type, primary key, notNull,
    unique and the default. A modifier this does not understand is ignored
    rather than guessed at — better to under-describe a platform column than to
    invent a constraint the platform never declared.
    """
    body = source
    start = body.find("pgTable(")
    if start == -1:
        return ()
    fields: list[dict] = []
    for m in _COLUMN_RE.finditer(body[start:]):
        builder = m.group("builder")
        if builder not in _BUILDER_TYPES:
            continue
        mods = m.group("mods") or ""
        field: dict[str, Any] = {
            "name": m.group("field"),
            "type": _BUILDER_TYPES[builder],
        }
        if ".primaryKey()" in mods:
            field["primaryKey"] = True
        if ".notNull()" in mods:
            field["required"] = True
        if ".unique()" in mods:
            field["unique"] = True
        if ".defaultNow()" in mods:
            field["defaultNow"] = True
        default = re.search(r"\.default\(([^()]*)\)", mods)
        if default:
            raw = default.group(1).strip()
            field["default"] = (True if raw == "true" else False if raw == "false"
                                else raw.strip('"'))
        fields.append(field)
    return tuple(fields)


def platform_table(table: str) -> tuple[dict, ...]:
    """The platform's declaration for ``table``, or ``()`` if it owns none."""
    rel = PLATFORM_TABLE_SOURCES.get(table)
    if not rel:
        return ()
    path = Path(__file__).resolve().parents[2] / rel
    if not path.is_file():
        return ()
    return parse_platform_table(path.read_text("utf-8"))


#: Blueprint field names that mean the same thing as a platform column, so an
#: extension does not duplicate what the platform already stores.
_PLATFORM_SYNONYMS: dict[str, dict[str, str]] = {
    "users": {"passwordhash": "password", "fullname": "name",
              "displayname": "name", "active": "isActive"},
}


def reconcile_platform_table(entity: dict) -> tuple[list[dict], list[str]]:
    """Platform columns first, then whatever the Blueprint adds, made nullable.

    Returns the merged field list and the names of the Blueprint fields that
    were folded into a platform column rather than added.
    """
    table = entity.get("table") or to_snake(entity.get("name") or "")
    platform = platform_table(table)
    if not platform:
        return list(entity.get("fields") or []), []

    synonyms = _PLATFORM_SYNONYMS.get(table, {})
    reserved = {f["name"].lower() for f in platform}
    fields = [dict(f) for f in platform]
    folded: list[str] = []
    for field in entity.get("fields") or []:
        name = (field.get("name") or "")
        key = re.sub(r"[^a-z]", "", name.lower())
        if key in reserved or synonyms.get(key):
            folded.append(name)
            continue
        extra = dict(field)
        # Platform code inserts without these, so they cannot be NOT NULL.
        extra.pop("primaryKey", None)
        extra["required"] = False
        fields.append(extra)
    return fields, folded


def emit_entity_module(entity: dict, doc: dict) -> str:
    """A Drizzle table module for one entity, in the scaffold's shape."""
    entities = {e.get("id"): e for e in doc.get("data", {}).get("entities") or []}
    fields, _folded = reconcile_platform_table(entity)
    if not any(f.get("primaryKey") for f in fields):
        # Every generated entity carries a uuid id; the scaffold's own comment
        # explains why (a uuid FK cannot hold a serial id).
        fields.insert(0, {"name": "id", "type": "uuid", "primaryKey": True})

    lines, builders = [], set()
    for field in fields:
        line, builder = drizzle_column(field)
        lines.append("  " + line)
        builders.add(builder)

    # Foreign keys, from declared relationships — the reason relationships had
    # to become writable: without them a foreign key is only prose in a
    # description, and the data engine has nothing to join on.
    fk_lines: list[str] = []
    fk_imports: dict[str, str] = {}  # module -> exported table var
    for rel in doc.get("data", {}).get("relationships") or []:
        if rel.get("from") != entity.get("id"):
            continue
        target = entities.get(rel.get("to"))
        col = rel.get("fromField")
        if not target or not col or any(f.get("name") == col for f in fields):
            continue
        builders.add("uuid")
        target_mod, target_var = _module_name(target), _var_name(target)
        if target_mod != _module_name(entity):
            fk_imports[target_mod] = target_var
        fk_lines.append(
            f'  {col}: uuid("{to_snake(col)}")'
            f".references(() => {target_var}.id),"
        )

    header = [
        f"// {entity.get('name')} — projected from {entity.get('id')}.",
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.",
        f'import {{ pgTable, {", ".join(sorted(builders))} }} from "drizzle-orm/pg-core";',
    ]
    for mod in sorted(fk_imports):
        header.append(f'import {{ {fk_imports[mod]} }} from "./{mod}";')

    return "\n".join(header + [
        "",
        f'export const {_var_name(entity)} = pgTable("{entity.get("table")}", {{',
        *lines,
        *fk_lines,
        "});",
        "",
    ])


def project_data_layer(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/db/schema/`` and return codeMap entries for what was written.

    Idempotent: the same Blueprint produces byte-identical files, so a re-run
    is a no-op rather than a churn of diffs.
    """
    root = Path(app_root) / "src" / "db" / "schema"
    root.mkdir(parents=True, exist_ok=True)
    entities = [e for e in (doc.get("data", {}).get("entities") or [])
                if e.get("status") != "DEPRECATED"]

    written: list[str] = []
    code_map: list[dict] = []
    for entity in entities:
        mod = _module_name(entity)
        path = root / f"{mod}.ts"
        path.write_text(emit_entity_module(entity, doc), "utf-8")
        rel = f"src/db/schema/{mod}.ts"
        written.append(rel)
        code_map.append({
            "artifact": entity.get("id"),
            "entity": entity.get("id"),
            "service": [rel],
        })

    # The platform's own tables live in this directory beside the projected
    # ones and are not Blueprint entities, so nothing here would name them.
    # drizzle resolves the schema through this barrel: a module no one
    # re-exports is invisible to it, so `user.ts` was on disk, absent from
    # every migration, and the generated app had nothing to authenticate
    # against — login failed with "relation \"user\" does not exist" rather
    # than a wrong password.
    # Named, not globbed. Globbing the directory looked right and ran at the
    # wrong time: the data layer writes this barrel while `user.ts` is still in
    # the scaffold, and assembly does not copy it in until the preview node,
    # several levels later. The glob saw the _forge_* tables (written here) and
    # missed the one it was added for, so the users table was absent from every
    # migration and login failed with "relation does not exist" — the same
    # symptom as before the fix, from the opposite cause.
    from services.blueprint.assembly import SCAFFOLD_OWNED

    platform = sorted(
        Path(rel).stem for rel in SCAFFOLD_OWNED
        if rel.startswith("src/db/schema/") and rel.endswith(".ts")
    )
    platform += sorted(
        f.stem for f in root.glob("_forge_*.ts") if f.stem not in platform
    )
    barrel = ["// Re-exports every projected entity schema, and the platform",
              "// tables that share this directory.",
              "// Generated from the Living Blueprint."]
    barrel += [f'export * from "./{_module_name(e)}";' for e in entities]
    barrel += [f'export * from "./{name}";' for name in platform]
    (root / "index.ts").write_text("\n".join(barrel) + "\n", "utf-8")
    written.append("src/db/schema/index.ts")

    return {"files": written, "entities": len(entities), "codeMap": code_map}


#: Every derived endpoint is served by one catch-all route, so an API has no
#: file of its own to be mapped to.
_DATA_ROUTE = "src/app/api/data/[...path]/route.ts"


def api_code_map(doc: dict) -> list[dict]:
    """A ``codeMap`` entry per declared API, pointing at the route that serves it.

    Nothing recorded APIs at all. Entities, workflows and pages each project to
    their own file and were mapped; endpoints are derived and served
    generically, so `project_backend` wrote no file per API and therefore no
    entry — and absence in `codeMap` is indistinguishable from absent code.
    `code_intelligence.unimplemented` read six endpoints as unbuilt on an app
    that serves all six, which is §115's divergence check crying wolf on every
    application it runs against.

    Many artifacts to one file, which the resolver already expects:
    `artifacts_for` on this path returns every endpoint, because a file
    genuinely can implement more than one thing.
    """
    return [
        {"artifact": str(a["id"]), "service": [_DATA_ROUTE]}
        for a in _live(doc.get("apis"))
        if a.get("id")
    ]


def apply_data_projection(svc: Any, app_root: str | Path) -> dict[str, Any]:
    """Project, then record every file in ``codeMap`` so §75's
    Blueprint↔Implementation edge has real paths to check."""
    result = project_data_layer(svc.doc, app_root)
    for entry in result["codeMap"]:
        svc.upsert("codeMap", entry, natural_key=entry["artifact"])
    # Recorded here because this is the projection that stands up the data
    # layer the endpoints read; the route itself ships with the scaffold.
    for entry in api_code_map(svc.doc):
        svc.upsert("codeMap", entry, natural_key=entry["artifact"])
    svc.save()
    return result


def project_frontend(doc: dict, app_root: str | Path,
                     catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write ``src/schemas/`` — one page schema per page the engine can render.

    Pages whose pattern has no template are *reported*, not skipped quietly: a
    frontend projection that silently emitted eleven of eighteen pages would
    look exactly like a successful one.
    """
    from services.blueprint.page_planner import load_catalog, plan_pages

    result = plan_pages(doc, catalog or load_catalog())
    root = Path(app_root) / "src" / "schemas"
    root.mkdir(parents=True, exist_ok=True)

    pages = {p.get("id"): p for p in doc.get("pages") or []}
    written: list[str] = []
    code_map: list[dict] = []
    for page_id, schema in sorted(result["planned"].items()):
        name = _route_slug((pages.get(page_id) or {}).get("route") or page_id)
        rel = f"src/schemas/{name}.json"
        target = root / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", "utf-8")
        written.append(rel)
        # `frontend`, not `service`: §21's own example files a page's
        # implementation under frontend, and `code_intel.where` is what
        # answers "where is this page implemented". A page schema is what the
        # UI engine renders — it is the page's frontend here, the same way a
        # .tsx file is in a bespoke app. Filed under `service` it reported no
        # frontend at all, while claiming a service layer it does not have.
        code_map.append({"artifact": page_id, "frontend": [rel]})

    # A page that stopped planning must not leave its last good schema behind:
    # the directory would still hold eighteen files and read as a complete
    # projection while one of them was silently out of date.
    written_set = set(written)
    stale = sorted(
        str(f.relative_to(root)) for f in root.rglob("*.json")
        if f"src/schemas/{f.relative_to(root)}" not in written_set
    )
    for name in stale:
        (root / name).unlink()

    _write_route_registry(root, written)

    return {
        "files": written,
        "pages": len(written),
        "removed": stale,
        "skipped": result["skipped"],
        "failed": result["failed"],
        "templates": result["templates"],
        "codeMap": code_map,
    }


def _route_slug(route: str) -> str:
    """``/roles/[id]`` -> ``roles/[id]``; ``/`` -> ``home``.

    The path must mirror the route, because the scaffold's catch-all resolves
    a URL by trying ``src/schemas/<segments>.json`` and substituting ``[id]``
    right-to-left. Flattening to ``roles-id.json`` writes a file the router can
    never find — the page would exist on disk and 404 in the browser.
    """
    from services.route_slug import slugify_route

    return slugify_route(route or "/")


def apply_frontend_projection(svc: Any, app_root: str | Path) -> dict[str, Any]:
    """Project pages, then record each file in ``codeMap`` (§21)."""
    result = project_frontend(svc.doc, app_root)
    for entry in result["codeMap"]:
        svc.upsert("codeMap", entry, natural_key=entry["artifact"])
    svc.save()
    return result


def _write_route_registry(root: Path, written: list[str]) -> None:
    """Emit ``src/schemas/registry.ts`` — the authoritative live-route map.

    The catch-all route treats this as authoritative and only falls back to
    probing the filesystem, so a page schema with no registry entry is a page
    that may never resolve. Generated from what was actually written, so the
    two cannot disagree.
    """
    from services.route_slug import route_from_slug

    entries = []
    for rel in written:
        slug = rel[len("src/schemas/"):-len(".json")]
        entries.append(f'  "{route_from_slug(slug)}": () => import("./{slug}.json"),')

    # `schema-page.tsx` imports BOTH `schemas` and `getSchema` from here.
    # Emitting only the map compiles and then fails at render with "getSchema
    # is not exported" — the route resolves, the page does not.
    (root / "registry.ts").write_text(
        "// Generated from the Living Blueprint by the frontend projection.\n"
        "// Keys are routes; paths mirror src/schemas/.\n\n"
        'import { loadSchema } from "./load";\n\n'
        "export const schemas: Record<string, () => Promise<unknown>> = {\n"
        + "\n".join(entries) + "\n};\n\n"
        "export async function getSchema(route: string) {\n"
        "  const loader = schemas[route];\n"
        "  if (!loader) throw new Error(`unknown route '${route}'`);\n"
        "  const raw = await loader();\n"
        "  return loadSchema(route, (raw as any).default ?? raw);\n"
        "}\n",
        "utf-8",
    )

    # `loadSchema` lives beside the registry and is template-owned, not
    # projected — copy it in if the scaffold layer did not bring it.
    load_ts = root / "load.ts"
    if not load_ts.exists():
        from services.schema_pipeline import _SCHEMA_LOAD_TS

        load_ts.write_text(_SCHEMA_LOAD_TS, "utf-8")


# ---------------------------------------------------------------------------
# navigation — the route graph the guards and breadcrumbs read
# ---------------------------------------------------------------------------

def project_shell(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/schemas/shell.json`` from ``navigation.tree``.

    THE SHELL READS ONE FILE, AND NOTHING WROTE IT. The scaffold's layout builds
    its rail from `shell.json` — a `SideNav` node whose `props.groups` carry
    grouped destinations — and only falls back to a flat menu from nav-flow's
    page list when the file is absent. Every Blueprint application was absent
    it, so every rail was the fallback: one flat list of page titles, whatever
    `navigation.tree` said. When the tree began carrying a connected design's
    own groups (Overview, Cases, Approvals…), they had nowhere to go.

    Written only when the tree has grouped nodes: a flat tree is exactly what
    the fallback already renders, and writing it again would be a second
    representation of one fact. Destinations resolve `page` ids to routes
    through the page list, so a rename cannot break the rail; a drawn
    destination with no page is kept, route-less, so its absence is visible
    in the rail rather than silent (§49).
    """
    nav = doc.get("navigation") or {}
    tree = [n for n in (nav.get("tree") or []) if isinstance(n, dict)]
    if not any(n.get("children") for n in tree):
        return {"files": [], "groups": 0, "reason": "no grouped navigation"}

    routes = {str(p.get("id")): str(p.get("route") or "")
              for p in (doc.get("pages") or []) if p.get("id")}

    def item(node: dict) -> dict[str, Any]:
        out: dict[str, Any] = {"label": str(node.get("label") or "")}
        route = routes.get(str(node.get("page") or ""))
        if route:
            out["route"] = route
        if node.get("icon"):
            out["icon"] = str(node["icon"])
        return out

    groups: list[dict[str, Any]] = []
    for node in tree:
        kids = [k for k in (node.get("children") or []) if isinstance(k, dict)]
        if kids:
            group: dict[str, Any] = {"label": str(node.get("label") or "")}
            if node.get("icon"):
                group["icon"] = str(node["icon"])
            group["items"] = [item(k) for k in kids]
            groups.append(group)
        else:
            groups.append(item(node))

    app_name = str((doc.get("application") or {}).get("name") or "App")
    shell = {
        "type": "AppShell",
        "frame": "topbar" if nav.get("style") == "topbar" else "sidebar",
        "children": [{"type": "SideNav",
                      "props": {"groups": groups, "appName": app_name, "mode": "dark"}}],
    }
    out = Path(app_root) / "src" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    (out / "shell.json").write_text(json.dumps(shell, indent=2), "utf-8")
    return {"files": ["src/schemas/shell.json"], "groups": len(groups)}


def project_nav_flow(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/contracts/nav-flow.json`` from navigation + pages.

    The route graph is consumed by more than the sidebar: breadcrumb ancestors
    resolve against it, the action guard checks transitions against it, and the
    root redirect is derived from it. Assembled from the Blueprint rather than
    accumulated a page at a time, so it cannot drift from the pages that exist.
    """
    from services.route_slug import slugify_route

    pages = [p for p in (doc.get("pages") or []) if p.get("status") != "DEPRECATED"]
    roles = {r.get("id"): r for r in (doc.get("roles") or [])}

    # Two lists, because they are two facts. Both keys were written from the
    # same set, so `/survey/[slug]` was simultaneously reachable without a
    # session and requiring one — a contradiction the middleware then read.
    public_routes: list[str] = []
    gated_routes: list[str] = []
    entries: list[dict] = []
    guards: dict[str, Any] = {}
    by_id = {p.get("id"): p for p in pages if p.get("id")}
    # An app has as many front doors as it has audiences (§108, §112).
    entry_by_access: dict[str, str] = {}

    for page in pages:
        route = page.get("route") or "/"
        slug = slugify_route(route)
        access = page.get("access") or "authenticated"
        # A public page renders without the app shell: navigation into a
        # product the visitor cannot reach is worse than no navigation.
        entries.append({
            "id": slug,
            "route": route,
            "title": page.get("name") or slug,
            "schemaFile": f"src/schemas/{slug}.json",
            "shell": access != "public",
            "access": access,
            "presentation": page.get("presentation") or "page",
            # By route, because that is what a router follows — resolved from
            # the page ids the contract carries, so a rename cannot break it.
            "navigatesTo": sorted({
                str(by_id[t].get("route")) for t in (page.get("navigatesTo") or [])
                if t in by_id and by_id[t].get("route")
            }),
        })
        if page.get("entry") and access not in entry_by_access:
            entry_by_access[access] = route
        # A page addressed to specific roles is a guarded route. Read from the
        # page contract, never invented — an invented guard locks people out.
        named = [roles[r].get("name") for r in (page.get("users") or []) if r in roles]
        if named:
            guards[route] = {"roles": sorted(named)}
        # Read from the contract, not guessed from the route name. A page
        # called /login in an app with no auth is not an auth route, and a
        # public /pricing is not gated however it is spelled.
        (public_routes if access == "public" else gated_routes).append(route)

    # Transitions come from declared navigation, not from guessing which page
    # links to which.
    # Declared navigation first; a page's own `navigatesTo` fills the rest.
    # `transitions` shipped as [] on every application ever generated, because
    # the `navigation` section carries edges nobody authors — so the arrows now
    # come from the pages, which are authored per page and cannot go stale
    # against them.
    transitions = []
    seen: set[tuple[str, str]] = set()
    for edge in (doc.get("navigation") or {}).get("transitions") or []:
        if edge.get("from") and edge.get("to"):
            transitions.append({"from": edge["from"], "to": edge["to"],
                                "trigger": edge.get("trigger", "")})
            seen.add((edge["from"], edge["to"]))
    for page in pages:
        src = page.get("route")
        for target in (page.get("navigatesTo") or []):
            dst = (by_id.get(target) or {}).get("route")
            if src and dst and (src, dst) not in seen:
                seen.add((src, dst))
                transitions.append({"from": src, "to": dst, "trigger": ""})

    out = Path(app_root) / "src" / "contracts"
    out.mkdir(parents=True, exist_ok=True)
    (out / "nav-flow.json").write_text(json.dumps({
        "version": "1.0",
        "pages": entries,
        # The guards read this as "reachable without a session".
        "public_routes": sorted(set(public_routes)),
        "auth_routes": sorted(set(gated_routes)),
        "transitions": transitions,
        "guards": guards,
        # Where each audience arrives.
        "entries": entry_by_access,
        # NAMED FOR WHAT IT IS. Calling this `initialPage` claimed a neutrality
        # it does not have: it is the GATED entry, chosen because a login
        # redirect and a "back to the application" link both need one and both
        # need a concrete URL — a public entry is often a pattern
        # (`/survey/[slug]`), which is why guessing "the first route" produced
        # an href Next refuses. For an app that is mostly public that choice is
        # arguable, so the name should carry the assumption rather than hide it.
        #
        # `initialPage` also stays, and stays a page ID, because that is what
        # the visual editor reads (VisualEditorWorkspace falls back to
        # `pages[0].id`). Writing a route into it would have handed that reader
        # something it cannot look up.
        "gatedEntry": entry_by_access.get("authenticated"),
        "initialPage": slugify_route(entry_by_access["authenticated"])
        if entry_by_access.get("authenticated") else None,
    }, indent=2, sort_keys=True) + "\n", "utf-8")

    return {"files": ["src/contracts/nav-flow.json"], "pages": len(entries),
            "guarded": len(guards), "authRoutes": sorted(set(gated_routes)),
            "transitions": len(transitions), "entries": entry_by_access}


# ---------------------------------------------------------------------------
# design — the token layer every component styles against
# ---------------------------------------------------------------------------

#: Token -> the designSystem colour role it comes from. Anything the design
#: system does not state is left to the scaffold's own defaults rather than
#: invented here, because a guessed accent is worse than an unopinionated one.
_COLOR_TOKENS: tuple[tuple[str, str], ...] = (
    ("--background", "background"),
    ("--foreground", "foreground"),
    ("--primary", "primary"),
    ("--primary-foreground", "primaryForeground"),
    ("--secondary", "secondary"),
    ("--muted", "muted"),
    ("--muted-foreground", "mutedForeground"),
    ("--accent", "accent"),
    ("--destructive", "destructive"),
    ("--border", "border"),
    ("--input", "input"),
    ("--ring", "ring"),
)


def _hsl_triplet(value: str) -> str | None:
    """`#125E8A` -> `203 78% 30%`, the bare triplet shadcn wraps in `hsl()`.

    The scaffold writes `hsl(var(--primary))`, so a hex under that name yields
    `hsl(#125E8A)` — invalid, silently dropped, and the component falls back to
    a default. Emitting hex for the aliases did not lose the cascade; it
    poisoned it. Blueprint-named roles keep their hex, since nothing wraps
    those.
    """
    v = str(value).strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return None
    try:
        r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    hi, lo = max(r, g, b), min(r, g, b)
    light = (hi + lo) / 2
    if hi == lo:
        hue = sat = 0.0
    else:
        d = hi - lo
        sat = d / (2 - hi - lo) if light > 0.5 else d / (hi + lo)
        hue = {r: (g - b) / d + (6 if g < b else 0),
               g: (b - r) / d + 2, b: (r - g) / d + 4}[hi] * 60
    return f"{round(hue)} {round(sat * 100)}% {round(light * 100)}%"


def _kebab(name: str) -> str:
    """`mutedForeground` -> `muted-foreground`."""
    return re.sub(r"(?<!^)(?=[A-Z])", "-", str(name)).lower()


#: Where a component expects a shadcn name the Blueprint does not use, the
#: nearest declared role stands in. Only aliases — every declared role is
#: emitted under its own name regardless, so nothing depends on this table
#: being complete.
_TOKEN_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("--foreground", ("foreground", "text", "textPrimary")),
    ("--primary-foreground", ("primaryForeground", "onPrimary", "background")),
    ("--muted", ("muted", "primarySubtle", "surfaceMuted")),
    ("--muted-foreground", ("mutedForeground", "textMuted", "textSecondary")),
    ("--secondary", ("secondary", "accent")),
    ("--destructive", ("destructive", "danger")),
    ("--ring", ("focusRing", "primary")),
)


def project_design_tokens(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/app/tokens.css`` from ``designSystem``.

    Emitted as its own file imported by ``globals.css`` rather than rewritten
    into it: ``globals.css`` is one of the files the app emitter deliberately
    preserves, and a projection that edits preserved files in place would make
    re-projection destructive.

    This wrote four variables from a thirteen-section design system, and every
    generated app looked unstyled as a result. It read a fixed list of shadcn
    role names — foreground, mutedForeground, destructive — against a Blueprint
    that declares its own: primaryHover, dangerSubtle, focusRing, borderStrong,
    statusAwaitingParts. Four names overlapped; the other seven lookups
    returned None and were skipped in silence, because a missing CSS variable
    is not an error. `radius` was read as a string and the Blueprint emits an
    object, so every corner token was dropped, and typography and spacing were
    never read at all.

    So it emits what the Blueprint declares, under the Blueprint's own names,
    and aliases the handful of shadcn names components ask for onto the nearest
    declared role. A design system that grows a new role now reaches the app
    without anyone editing a list here.
    """
    # `html:root`, NOT `:root`, AND ON PURPOSE. The scaffold's globals.css
    # imports this file first and says the design's tokens win because they are
    # unlayered and its own defaults sit in `@layer base`. Under Tailwind v3
    # that is false: `@layer base` is Tailwind's directive, not a CSS cascade
    # layer, and the compiled sheet has no layers — both `:root` blocks are
    # unlayered and source order decides, so the scaffold's later `:root` beat
    # this file on every token it also declared. `--accent` was the visible one:
    # a design's gold became the stock grey on the sign-in page. `html:root`
    # is one point of specificity higher than `:root` and `.dark`, which is
    # exactly enough, and it still reads as what it is: the root element.

    design = doc.get("designSystem") or {}
    colors = design.get("colors") or {}
    lines: list[str] = []

    # THE NAMES THE SCAFFOLD WRAPS IN hsl(). This said "these four… the rest
    # keep their hex" — and the scaffold's sign-in page paints its brand panel
    # with `hsl(var(--accent))`, so a hex accent became `hsl(#c9a84c)`: invalid,
    # silently dropped, and the design's gold never reached the one page every
    # user sees first. The wrapped set is shadcn's, which is what the scaffold
    # is — the same names `_COLOR_TOKENS` below already lists.
    WRAPPED = {"background", "foreground", "primary", "primaryForeground",
               "secondary", "secondaryForeground", "accent", "accentForeground",
               "muted", "mutedForeground", "destructive", "destructiveForeground",
               "border", "input", "ring", "card", "cardForeground"}
    for role, value in sorted(colors.items()):
        if isinstance(value, str) and value:
            out_value = (_hsl_triplet(value) or value) if role in WRAPPED else value
            lines.append(f"  --{_kebab(role)}: {out_value};")
    for token, candidates in _TOKEN_ALIASES:
        if any(line.startswith(f"  {token}:") for line in lines):
            continue
        for role in candidates:
            raw = colors.get(role)
            if isinstance(raw, str) and raw:
                triplet = _hsl_triplet(raw)
                lines.append(f"  {token}: {triplet or raw};")
                break

    radius = design.get("radius")
    if isinstance(radius, str) and radius:
        lines.append(f"  --radius: {radius};")
    elif isinstance(radius, dict):
        for key, value in sorted(radius.items()):
            if isinstance(value, str) and value:
                lines.append(f"  --radius-{_kebab(key)}: {value};")
        # Components ask for a bare `--radius`; `md` is the sane middle.
        for key in ("md", "control", "card"):
            if isinstance(radius.get(key), str):
                lines.append(f"  --radius: {radius[key]};")
                break

    typography = design.get("typography") or {}
    for key, token in (("fontFamilyBase", "--font-family-base"),
                       ("fontFamilyNumeric", "--font-family-numeric"),
                       # The names the scaffold's Tailwind config and its sign-in
                       # page actually read: `fontFamily.heading` is
                       # `var(--font-heading)` and nothing defined it, so a
                       # design's serif headings (Fraunces on a real file)
                       # fell through to system-ui on every page.
                       ("fontFamilyHeading", "--font-heading"),
                       ("fontFamilyBase", "--font-body"),
                       ("baseSize", "--font-size-base"),
                       ("lineHeightBase", "--line-height-base")):
        value = typography.get(key)
        if isinstance(value, str) and value:
            lines.append(f"  {token}: {value};")

    spacing = design.get("spacing")
    if isinstance(spacing, dict):
        for key, value in sorted(spacing.items()):
            if isinstance(value, str) and value:
                lines.append(f"  --space-{_kebab(key)}: {value};")

    out = Path(app_root) / "src" / "app"
    out.mkdir(parents=True, exist_ok=True)
    header = ("/* Generated from the Living Blueprint (designSystem).\n"
              "   Edit the Blueprint, not this file. */\n")
    # THE FAMILIES THE DESIGN NAMES ARE LOADED, AND THE BODY IS SET IN ONE.
    # `--font-body: Inter` was emitted and nothing read it: no rule set the
    # body's family, and a face that is not installed on the viewer's machine
    # is not there to be read anyway. Every family the design system names is
    # requested from Google Fonts (Inter, Fraunces, JetBrains Mono all live
    # there; a family that does not is simply not served and falls back), and
    # the body is set in the base family with the system sans behind it.
    families = [str(v).strip() for k, v in (typography or {}).items()
                if k in ("fontFamilyBase", "fontFamilyHeading", "fontFamilyNumeric") and v]
    fonts_import = ""
    if families:
        query = "&".join("family=" + f.replace(" ", "+") + ":wght@400;500;600;700"
                         for f in dict.fromkeys(families))
        fonts_import = f'@import url("https://fonts.googleapis.com/css2?{query}&display=swap");\n'
    body_rule = ""
    if (typography or {}).get("fontFamilyBase"):
        body_rule = "body {\n  font-family: var(--font-body), ui-sans-serif, system-ui, sans-serif;\n}\n"
    body = (fonts_import + "html:root {\n" + "\n".join(lines) + "\n}\n" + body_rule) if lines else (
        "/* designSystem states no colour roles yet — the scaffold's own\n"
        "   defaults stand rather than inventing a palette here. */\n")
    (out / "tokens.css").write_text(header + body, "utf-8")

    return {"files": ["src/app/tokens.css"], "tokens": len(lines),
            "personality": design.get("visualPersonality")}


# ---------------------------------------------------------------------------
# workflows — the definitions the workflow engine executes
# ---------------------------------------------------------------------------

def _wf_node(node_id: str, ntype: str, row: int, config: dict, label: str) -> dict:
    return workflow_node(node_id, ntype, row, config, label)

#: What the Blueprint's `config.operation` means to the workflow engine. The
#: step type says a person or the system acts; the operation says WHICH act,
#: and only the operation can tell a read from a write.
_OPERATION_ACTION: dict[str, str] = {
    "create": "db_insert",
    "update": "db_update",
    "delete": "db_delete",
    "list": "db_query",
    "read": "db_query",
    "query": "db_query",
}

#: Values in `sets` the engine cannot evaluate. `now()` and CURRENT_DATE are
#: SQL the Blueprint writes to mean "stamped by the system"; the engine writes
#: a values map through Drizzle and would store them as the literal text.
#: Dropped rather than mistranslated — the projected column already carries
#: `defaultNow()` for exactly these, so the database supplies what the
#: Blueprint intended.
_DB_EVALUATED = {"now()", "current_date", "current_timestamp", "current_time"}


def _step_config(step: dict, entity: dict, catalog: WorkflowNodeCatalog,
                 wf_id: str = "") -> dict[str, Any]:
    """The node config for one step: the catalog's defaults for that node and
    variant, then what the step declares.

    The Blueprint may state a condition as ``condition``; the engine evaluates
    ``expression``. THE OPERATION DECIDES which act an action performs when
    the step names one and no ``actionType``: mapping on step type alone made
    every ``action`` a db_insert, so "Set status Closed" inserted a second
    ticket and two reads inserted too. A db_insert/db_update against an entity
    with no ``values`` of its own gets the same columns the entity's form asks
    for, so the two cannot drift into asking for one set and storing another;
    ``sets`` is where the Blueprint states the values a person never types,
    and it wins over the form.
    """
    ntype = step.get("type")
    declared = dict(step.get("config")) if isinstance(step.get("config"), dict) else {}
    if ntype == "condition" and "expression" not in declared and declared.get("condition"):
        declared["expression"] = declared.pop("condition")
    if ntype == "action" and "actionType" not in declared:
        operation = str(declared.get("operation") or "").strip().lower()
        if operation in _OPERATION_ACTION:
            declared["actionType"] = _OPERATION_ACTION[operation]
    config: dict[str, Any] = {**catalog.defaults(ntype, declared), **declared}
    if entity.get("table") and "table" not in config:
        config["table"] = entity["table"]

    if (ntype == "action" and config.get("actionType") in ("db_insert", "db_update")
            and entity.get("table")):
        values = dict(config["values"]) if isinstance(config.get("values"), dict) else None
        if values is None:
            from services.blueprint.page_planner import form_fields_for

            creating = config["actionType"] == "db_insert"
            # Referenced bare — `{{name}}`, not `{{input.name}}`: the posted
            # payload is ctx.variables itself, so the column name IS the variable.
            values = {
                f["name"]: f"{{{{{f['name']}}}}}"
                for f in form_fields_for(entity, creating=creating)
                if f.get("name")
            }
        # A MAP, OR NOTHING — never a crash. `config` is a free-form bag, so
        # `sets` has arrived as a list of prose; a shape the projection cannot
        # honour is named in the log and skipped.
        sets = config.get("sets")
        if sets and not isinstance(sets, dict):
            logger.warning(
                "[projection] %s/%s: `sets` is %s, expected a column-to-value map "
                "— step overrides ignored: %.160s",
                wf_id, step.get("key"), type(sets).__name__, sets)
            sets = None
        for col, val in (sets or {}).items():
            if isinstance(val, str) and val.strip().lower() in _DB_EVALUATED:
                values.pop(col, None)
                continue
            values[col] = val
        if values:
            config["values"] = values
    return config


def _edges(chain: list[str], steps: list[dict], catalog: WorkflowNodeCatalog,
           end_id: str) -> list[dict]:
    """Edges from declared connectivity, or a linear chain when none is declared.

    A step's ``next`` lists the keys it hands to. A branching node's first
    target is the then-branch and its second the else-branch, which is how the
    editor's handles and the engine's ``edgeType`` both read it. A non-terminal
    step that names nothing flows to the end node.
    """
    by_key = {s.get("key"): s for s in steps}
    declared = any(s.get("next") for s in steps)
    branching = set(catalog.branching_types())
    edges: list[dict] = []

    def add(src: str, tgt: str, kind: str = "default") -> None:
        e: dict[str, Any] = {"id": f"e_{src}_{tgt}", "source": src, "target": tgt,
                             "data": {"edgeType": kind}}
        if kind == "else":
            e["sourceHandle"] = "else"
        edges.append(e)

    if not declared:
        for a, b in zip(chain, chain[1:]):
            add(a, b)
        return edges

    add("trigger", steps[0]["key"]) if steps else add("trigger", end_id)
    for s in steps:
        key, ntype = s.get("key"), s.get("type")
        node = catalog.node(ntype) or {}
        if not node.get("handles", {}).get("out", True):
            continue
        targets = [t for t in (s.get("next") or []) if t in by_key]
        if not targets:
            add(key, end_id)
            continue
        if ntype in branching:
            add(key, targets[0], "then")
            for t in targets[1:2]:
                add(key, t, "else")
        else:
            for t in targets:
                add(key, t)
    return edges


def project_workflows(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/workflows/definitions/*.json`` from the Blueprint.

    A Blueprint workflow states what the business does in the workflow node
    catalog's vocabulary; a definition is those nodes assembled for the
    engine. The translation is mechanical — a step is a catalog node carrying
    the step's configuration, joined by the edges the step declares — which is
    why this is a projection and not an agent. There is no mapping table: a
    step whose type is not in the catalog was refused before it got here.
    """
    catalog = workflow_nodes()
    entities = {e.get("id"): e for e in (doc.get("data") or {}).get("entities") or []}
    workflows = [w for w in (doc.get("workflows") or [])
                 if w.get("status") != "DEPRECATED"]

    out = Path(app_root) / "src" / "lib" / "workflows" / "definitions"
    out.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    code_map: list[dict] = []
    for wf in workflows:
        slug = to_snake(wf.get("name") or wf.get("id") or "workflow").replace("_", "-")
        declared_trigger = wf.get("trigger") or {}
        trigger_cfg: dict[str, Any] = {
            **catalog.defaults("trigger"),
            "type": declared_trigger.get("kind") or "manual",
        }
        detail = declared_trigger.get("detail")
        if detail:
            trigger_cfg["event" if trigger_cfg["type"] == "api_event" else
                        "condition" if trigger_cfg["type"] == "db_change" else
                        "cron" if trigger_cfg["type"] == "schedule" else
                        "description"] = detail

        # `start` is the Blueprint's own boundary marker (the trigger node is
        # the start); documents predating the catalog are migrated on load,
        # but a projection must never turn one into an action with no action.
        steps = [s for s in (wf.get("steps") or [])
                 if isinstance(s, dict) and s.get("key") and s.get("type") != "start"]
        # Top-to-bottom, one node per row: the editor's handles are top (in)
        # and bottom (out), so this is the layout its edges are drawn for.
        nodes = [_wf_node("trigger", "trigger", 0, trigger_cfg, "Start")]
        chain = ["trigger"]
        for s in steps:
            entity = entities.get(s.get("entity")) or {}
            nodes.append(_wf_node(
                s["key"], s.get("type"), len(chain),
                _step_config(s, entity, catalog, wf_id=str(wf.get("id") or slug)),
                s.get("name") or s["key"],
            ))
            chain.append(s["key"])
        end_id = next((s["key"] for s in steps
                       if not (catalog.node(s.get("type")) or {}).get("handles", {}).get("out", True)),
                      None)
        if end_id is None:
            end_id = "end"
            nodes.append(_wf_node(end_id, "end", len(chain), {}, "End"))
            chain.append(end_id)

        edges = _edges(chain, steps, catalog, end_id)

        definition = {
            "id": slug,
            "name": wf.get("name") or slug,
            "blueprintId": wf.get("id"),
            "processVariables": [],
            "definition": {"trigger": dict(trigger_cfg),
                           "nodes": nodes, "edges": edges},
        }
        (out / f"{slug}.json").write_text(
            json.dumps(definition, indent=2, sort_keys=True) + "\n", "utf-8")
        rel = f"src/lib/workflows/definitions/{slug}.json"
        written.append(rel)
        code_map.append({"artifact": wf.get("id"), "service": [rel]})

    return {"files": written, "workflows": len(written), "codeMap": code_map}


# ---------------------------------------------------------------------------
# seed — enough rows that a preview shows something
# ---------------------------------------------------------------------------

def _seed_value(field: dict, entity_name: str, row: int) -> Any:
    from services.blueprint.page_planner import enum_values

    kind = str(field.get("type") or "text").lower()
    name = field.get("name") or "field"
    # Spread across rows on purpose: with three rows and three states, the
    # seeded data holds one record in each, which is what lets a page that only
    # means something once something is submitted be reviewed at all.
    options = enum_values(field)
    if options:
        return options[(row - 1) % len(options)]
    if kind in ("int", "integer", "number"):
        return row
    if kind in ("decimal", "numeric", "float", "money", "currency"):
        return row * 100
    if kind in ("bool", "boolean"):
        return row % 2 == 1
    if kind in ("date", "datetime", "timestamp"):
        return f"2026-0{(row % 9) + 1}-15T09:00:00Z"
    if kind == "email":
        return f"{to_snake(entity_name)}{row}@example.com"
    return f"{entity_name} {row}" if name.lower() in ("name", "title") else \
        f"{_humanise_field(name)} {row}"


def _humanise_field(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").strip().title()


def project_seed(doc: dict, app_root: str | Path, rows: int = 3) -> dict[str, Any]:
    """Write ``src/db/seed.json`` — a few rows per entity.

    A preview of an empty database shows empty states everywhere, which looks
    identical to a broken one. Values are derived, never random, so the same
    Blueprint seeds the same rows and a screenshot is reproducible.
    """
    entities = [e for e in (doc.get("data") or {}).get("entities") or []
                if e.get("status") != "DEPRECATED"]

    seed: dict[str, list[dict]] = {}
    for entity in entities:
        table = entity.get("table") or to_snake(entity.get("name") or "entity")
        name = entity.get("name") or table
        out_rows = []
        for row in range(1, rows + 1):
            record = {}
            for field in entity.get("fields") or []:
                if field.get("primaryKey"):
                    continue
                record[field.get("name")] = _seed_value(field, name, row)
            out_rows.append(record)
        seed[table] = out_rows

    out = Path(app_root) / "src" / "db"
    out.mkdir(parents=True, exist_ok=True)
    (out / "seed.json").write_text(
        json.dumps(seed, indent=2, sort_keys=True) + "\n", "utf-8")
    return {"files": ["src/db/seed.json"], "tables": len(seed),
            "rows": sum(len(v) for v in seed.values())}


# ---------------------------------------------------------------------------
# sensitive columns — what the data engine encrypts and masks
# ---------------------------------------------------------------------------

#: Field-name hints -> the mask the data engine applies. §42 is explicit that
#: sensitive values must not surface in logs, exports or generated source, and
#: the engine cannot honour that without being told which columns they are.
_MASK_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("email",), "email"),
    (("phone", "mobile", "tel"), "phone"),
    (("ssn", "nationalid", "taxid", "aadhaar", "passport",
      "cardnumber", "iban", "accountnumber"), "last4"),
    (("password", "secret", "token", "apikey"), "full"),
)


def _entity_readers(doc: dict, entity: dict) -> list[str]:
    """Roles holding a read permission on this entity — read, never invented.

    Same rule the API derivation follows: policy is a security decision, so it
    is looked up rather than assumed. A masked column with no reader is one
    nobody can ever unmask, which is the right default only when the security
    agent genuinely granted nobody access.
    """
    roles = {r.get("id"): r.get("name") for r in (doc.get("roles") or [])}
    names: set[str] = set()
    for perm in doc.get("permissions") or []:
        if perm.get("action") != "read":
            continue
        subject = perm.get("subject") or ""
        if subject != entity.get("id") and \
                subject.lower() != (entity.get("name") or "").lower():
            continue
        for role in doc.get("roles") or []:
            if perm.get("id") in (role.get("permissions") or []):
                names.add(role.get("name"))
    return sorted(n for n in names if n)


def sensitive_columns(doc: dict) -> dict[str, dict[str, dict]]:
    """Columns the data engine masks on read.

    Masking and sensitivity are not the same thing, and conflating them breaks
    the product. The data model marks a candidate's `fullName`, `location` and
    `linkedinUrl` as ``sensitive`` — correctly, they are personal data — but a
    name masked from everyone means every page renders rows of asterisks. What
    ``sensitive`` earns a field is encryption at rest and permission control;
    what earns it a *mask* is having a meaningful masked form, like the last
    four digits of an account or the local part of an email.

    So the manifest covers exactly the fields with a natural masked
    representation, and everything else sensitive is governed by §100
    permissions instead.
    """
    out: dict[str, dict[str, dict]] = {}
    for entity in [e for e in ((doc.get("data") or {}).get("entities") or [])
                   if e.get("status") != "DEPRECATED"]:
        readers = _entity_readers(doc, entity)
        cols: dict[str, dict] = {}
        for field in entity.get("fields") or []:
            name = field.get("name") or ""
            mask = field.get("mask")
            if not mask:
                lowered = re.sub(r"[^a-z]", "", name.lower())
                for hints, kind in _MASK_HINTS:
                    if any(h in lowered for h in hints):
                        mask = kind
                        break
            if not mask:
                continue
            # A credential is never unmasked for anyone, whatever the roles say.
            never = mask == "full" and any(
                h in re.sub(r"[^a-z]", "", name.lower())
                for h in ("password", "secret", "token", "apikey")
            )
            cols[name] = {"mask": mask,
                          "readers": [] if never
                          else list(field.get("readers") or readers)}
        if not cols:
            continue
        name = entity.get("name") or ""
        table = entity.get("table") or to_snake(name)
        for key in {name, name.lower(), table, table.lower()}:
            if key:
                out[key] = cols
    return out


def project_sensitive_columns(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/sensitive-columns.ts`` — imported by the data engine."""
    manifest = sensitive_columns(doc)
    body = json.dumps(manifest, indent=2, sort_keys=True)
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sensitive-columns.ts").write_text(
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        '//\n'
        '// The data engine reads this at write time (encrypt + precompute the\n'
        '// masked value) and at read time (mask by default; unmask only when the\n'
        "// caller's role is in `readers` and it asks to).\n\n"
        'export type MaskKind = "last4" | "email" | "phone" | "full";\n\n'
        "export interface SensitiveColumnSpec {\n"
        "  mask: MaskKind;\n"
        "  readers: string[];\n"
        "}\n\n"
        "export const SENSITIVE_COLUMNS: Record<\n"
        "  string,\n"
        "  Record<string, SensitiveColumnSpec>\n"
        f"> = {body} as const;\n\n"
        "export function sensitiveColumnsFor(\n"
        "  entity: string,\n"
        "): Record<string, SensitiveColumnSpec> {\n"
        "  return SENSITIVE_COLUMNS[entity]\n"
        "    ?? SENSITIVE_COLUMNS[entity?.toLowerCase?.()]\n"
        "    ?? {};\n"
        "}\n",
        "utf-8",
    )
    return {"files": ["src/lib/sensitive-columns.ts"],
            "entities": len({k.lower() for k in manifest}),
            "columns": sum(len(v) for v in manifest.values())}


def searchable_columns(doc: dict) -> dict[str, list[str]]:
    """Columns a search op may query, per entity.

    A page whose contract declares a search action needs the data engine to
    know *what* to search. Text-bearing columns on the entity are the
    candidates; masked columns are excluded, because searching a value the
    caller is not allowed to read back would leak it a character at a time.
    """
    masked = sensitive_columns(doc)
    out: dict[str, list[str]] = {}
    for entity in [e for e in ((doc.get("data") or {}).get("entities") or [])
                   if e.get("status") != "DEPRECATED"]:
        name = entity.get("name") or ""
        hidden = set(masked.get(name, {}))
        cols = [
            f.get("name") for f in entity.get("fields") or []
            if str(f.get("type") or "").lower() in ("text", "string", "str")
            and not f.get("primaryKey")
            and f.get("name") not in hidden
        ]
        if not cols:
            continue
        table = entity.get("table") or to_snake(name)
        for key in {name, name.lower(), table, table.lower()}:
            if key:
                out[key] = cols
    return out


def project_searchable_columns(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/searchable-columns.ts`` — imported by the data engine.

    Always written, even when empty: the runtime imports it statically, so a
    missing file is a compile error rather than a degraded search.
    """
    manifest = searchable_columns(doc)
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "searchable-columns.ts").write_text(
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        "//\n"
        "// Keys are every reachable form of the entity name; values are the\n"
        "// plaintext column names a search op may target.\n\n"
        "export const SEARCHABLE_COLUMNS: Record<string, string[]> = "
        f"{json.dumps(manifest, indent=2, sort_keys=True)};\n\n"
        "export function searchableColumnsFor(entity: string): string[] {\n"
        "  if (!entity) return [];\n"
        "  return SEARCHABLE_COLUMNS[entity]\n"
        "    ?? SEARCHABLE_COLUMNS[entity.toLowerCase()]\n"
        "    ?? [];\n"
        "}\n\n"
        "export function hasSearchableColumns(entity: string): boolean {\n"
        "  return searchableColumnsFor(entity).length > 0;\n"
        "}\n",
        "utf-8",
    )
    return {"files": ["src/lib/searchable-columns.ts"],
            "entities": len({k.lower() for k in manifest})}


# ---------------------------------------------------------------------------
# ownership — which rows an actor may reach
# ---------------------------------------------------------------------------


def _canonical_key(name: str) -> str:
    """``Rent_Payment`` / ``rentPayments`` -> ``rentpayment``-ish canonical form.

    Separator- and case-insensitive, because the same entity is spelled four
    ways across the stack: the Blueprint's ``RentPayment``, the table's
    ``rent_payments``, the API route's ``rent-payments`` and the SSR source's
    ``rentPayments``. A scoping rule that misses because the caller spelled the
    entity differently is a rule that silently stops scoping, so the key is
    normalised identically here and in ``ownershipRulesFor`` at run time.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _key_forms(name: str) -> set[str]:
    """Every canonical spelling of one name, singular and plural.

    The ``-es`` strip is conditional on what it leaves behind, because the
    unconditional form turns ``roles`` into ``rol`` and ``candidates`` into
    ``candidat`` — keys nothing will ever ask for, and one more chance for a
    rule to land on the wrong entity. English only writes ``-es`` after a
    sibilant, so that is the only case where stripping it yields a singular.
    """
    canon = _canonical_key(name)
    if not canon:
        return set()
    forms = {canon}
    if canon.endswith("ies"):
        forms.add(canon[:-3] + "y")
    elif canon.endswith("es") and re.search(r"(s|x|z|ch|sh)$", canon[:-2]):
        forms.add(canon[:-2])
    if canon.endswith("s"):
        forms.add(canon[:-1])
    else:
        forms.add(canon + "s")
    return {f for f in forms if f}


def ownership_rules(doc: dict) -> dict[str, list[dict]]:
    """Row-scoping predicates the data engine adds to every read and write.

    ``security.ownershipRules`` holds two kinds of item. A string states policy
    in prose and enforces nothing — useful documentation, but the reason a
    generated app could be authenticated and still hand every signed-in user
    every other user's rows. An object is enforceable, and this is what turns it
    into the manifest the engine reads.

    An object rule is one of two kinds, and the difference is the whole reason
    the field exists. A ``scope`` column decides who may reach a row: it is
    filled from the session and becomes a WHERE predicate. An ``attribution``
    column only records who acted: it is filled from the session, a body value
    is ignored, and it is never a filter.

    Nothing here infers the kind from a column name. ``createdByUserId`` looks
    like ownership and often is not — an ATS records it for the audit trail
    while every recruiter is meant to see every candidate, so scoping on it
    would narrow an application designed to be shared. The Blueprint says which
    columns do which (§100), so an entity with no rule is projected with no
    predicate: deliberately and visibly, rather than by a guess that happens to
    be right some of the time.

    Keys are canonical entity spellings (see :func:`_key_forms`); values are the
    rules that apply to that entity.
    """
    entities = [e for e in ((doc.get("data") or {}).get("entities") or [])
                if e.get("status") != "DEPRECATED"]
    by_key: dict[str, dict] = {}
    for entity in entities:
        name = entity.get("name") or ""
        table = entity.get("table") or to_snake(name)
        for form in _key_forms(name) | _key_forms(table):
            by_key.setdefault(form, entity)

    out: dict[str, list[dict]] = {}
    for item in ((doc.get("security") or {}).get("ownershipRules") or []):
        if not isinstance(item, dict):
            continue                      # prose — documents policy, enforces none
        column = item.get("column")
        named = item.get("entity") or ""
        if not column or not named:
            continue
        rule = {
            "column": column,
            "kind": item.get("kind") or "scope",
            "scope": item.get("scope") or "user",
            "unscopedRoles": list(item.get("unscopedRoles") or []),
        }
        # Key the rule under every spelling of the entity it actually resolves
        # to, so an SSR source asking for `rentPayments` and a route asking for
        # `rent-payments` both find it. An unresolved entity is still emitted
        # under what the rule spelled: dropping it here would fail open.
        entity = by_key.get(_canonical_key(named))
        if entity is not None:
            forms = _key_forms(entity.get("name") or "") | _key_forms(
                entity.get("table") or to_snake(entity.get("name") or ""))
        else:
            forms = _key_forms(named)
        for form in forms:
            out.setdefault(form, [])
            if rule not in out[form]:
                out[form].append(rule)
    return out


def render_ownership_rules_module(manifest: dict[str, list[dict]]) -> str:
    """The ``src/lib/ownership-rules.ts`` source for a manifest.

    Rendered here rather than at each call site because two pipelines emit this
    file — the Blueprint projection and the legacy ``schema_builder`` — and a
    second copy of the lookup would be a second copy that drifts. The lookup
    below has to agree with :func:`_canonical_key` exactly; a disagreement is
    not a compile error, it is an entity that silently stops being scoped.
    """
    return (
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        "//\n"
        "// security.ownershipRules -> what the data engine does with a column that\n"
        "// names the acting user. Both kinds are filled from the session on create,\n"
        "// so a value in the request body never decides who a row is attributed to.\n"
        "// Only kind:\"scope\" also becomes a WHERE predicate on reads and writes.\n"
        "//\n"
        "// An entity absent from this manifest is NOT scoped, and a column recorded\n"
        "// as kind:\"attribution\" never narrows a read — the right answer for an\n"
        "// application authorised by role rather than by record, and the wrong one\n"
        "// everywhere else. The engine never guesses either from a column name.\n\n"
        "export interface OwnershipRule {\n"
        "  /** Column carrying the actor's value. */\n"
        "  column: string;\n"
        '  /** "scope" -> also filters reads and writes; "attribution" -> fill only. */\n'
        '  kind: "scope" | "attribution";\n'
        '  /** "user" -> the actor\'s id; "workspace" -> their workspace/tenant id. */\n'
        '  scope: "user" | "workspace";\n'
        "  /** Roles exempt: they read unscoped, and may write the column themselves. */\n"
        "  unscopedRoles: string[];\n"
        "}\n\n"
        "export const OWNERSHIP_RULES: Record<string, OwnershipRule[]> = "
        f"{json.dumps(manifest, indent=2, sort_keys=True)};\n\n"
        "/** Canonical key — must match _canonical_key in projection.py. */\n"
        "function canonical(entity: string): string {\n"
        '  return String(entity ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");\n'
        "}\n\n"
        "/** Rules for an entity, or [] when the Blueprint declared none.\n"
        " *\n"
        " * Tries the canonical spelling and its singular/plural forms, because the\n"
        " * same entity arrives as `RentPayment`, `rent_payments` and `rent-payments`\n"
        " * from the three call sites. A miss returns [] = unscoped, so the key set\n"
        " * the projection emits is deliberately generous. Must stay identical to\n"
        " * _key_forms in projection.py.\n"
        " */\n"
        "export function ownershipRulesFor(entity: string): OwnershipRule[] {\n"
        "  const canon = canonical(entity);\n"
        "  if (!canon) return [];\n"
        "  const forms = [canon];\n"
        '  if (canon.endsWith("ies")) forms.push(canon.slice(0, -3) + "y");\n'
        '  else if (canon.endsWith("es") && /(s|x|z|ch|sh)$/.test(canon.slice(0, -2)))\n'
        "    forms.push(canon.slice(0, -2));\n"
        '  if (canon.endsWith("s")) forms.push(canon.slice(0, -1));\n'
        '  else forms.push(canon + "s");\n'
        "  for (const form of forms) {\n"
        "    const rules = OWNERSHIP_RULES[form];\n"
        "    if (rules) return rules;\n"
        "  }\n"
        "  return [];\n"
        "}\n"
    )


def project_ownership_rules(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/ownership-rules.ts`` — imported by the data engine.

    Always written, even when empty: the engine imports it statically, so a
    missing file is a compile error rather than an app that silently stops
    scoping.
    """
    manifest = ownership_rules(doc)
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ownership-rules.ts").write_text(
        render_ownership_rules_module(manifest), "utf-8")
    return {"files": ["src/lib/ownership-rules.ts"],
            "keys": len(manifest),
            "rules": sum(len(v) for v in manifest.values())}


# ---------------------------------------------------------------------------
# access — which routes the middleware gates
# ---------------------------------------------------------------------------

#: Routes the auth flow itself needs, plus build output. A gate that catches
#: its own login page locks everyone out.
_ALWAYS_OPEN: tuple[str, ...] = (
    "api/auth", "_next", "favicon.ico",
)


def _matcher_segment(route: str) -> str:
    """`/roles/[id]` -> `roles/[^/]+` for a middleware negative lookahead."""
    body = (route or "/").strip("/")
    if not body:
        return ""
    # Escape only what is special in a JS regex. `re.escape` also escapes
    # hyphens, so `/sign-in` came out as `sign\\-in` — legal but noise in a
    # generated file someone has to read.
    def lit(part: str) -> str:
        return re.sub(r"([.*+?^${}()|\[\]\\])", r"\\\1", part)

    parts = [r"[^/]+" if p.startswith("[") else lit(p) for p in body.split("/")]
    return "/".join(parts)


def access_map(doc: dict) -> dict[str, list[str]]:
    """Routes grouped by how they are reached: public, authenticated, by role."""
    out: dict[str, list[str]] = {"public": [], "authenticated": [],
                                 "role_restricted": []}
    for page in _live(doc.get("pages")):
        route = page.get("route") or "/"
        access = page.get("access") or "authenticated"
        out.setdefault(access, []).append(route)
    for key in out:
        out[key] = sorted(set(out[key]))
    return out


def public_apis(doc: dict) -> list[str]:
    """The endpoints a public page has to be able to reach.

    A page's access declaration stopped at the page. `/plants` was public and
    rendered for anyone; `/api/data/plants` and `/api/workflows/FLOW-002/execute`
    were not, so the table came up empty and adding a plant did nothing — a
    generated app that looks broken on first open, with no error anywhere,
    because a 307 to /login is a perfectly successful HTTP exchange.

    Derived per page rather than opened wholesale. `/api/data` as a blanket
    exclusion would expose every entity in the application because one page is
    public; what a public page needs is the data behind *its own* bindings and
    the workflows *it* launches, and the Blueprint states both.
    """
    public_pages = {p.get("id") for p in _live(doc.get("pages"))
                    if (p.get("access") or "authenticated") == "public"}
    if not public_pages:
        return []

    entities = {e.get("id"): e for e in
                ((doc.get("data") or {}).get("entities") or [])}
    by_name = {e.get("name"): e for e in entities.values()}

    slugs: set[str] = set()
    layouts = {l.get("page"): l for l in _live(doc.get("pageLayouts"))}
    for page in _live(doc.get("pages")):
        if page.get("id") not in public_pages:
            continue
        named = [s.get("entity") for s
                 in (layouts.get(page.get("id"), {}).get("dataSources") or [])]
        named.append((entities.get((page.get("data") or {})
                                   .get("primaryEntity")) or {}).get("name"))
        for name in named:
            ent = by_name.get(name)
            if ent:
                slugs.add(str(ent.get("table") or str(name).lower()))

    out = [f"api/data/{slug}" for slug in sorted(slugs)]
    out += [f"api/workflows/{w['id']}" for w in sorted(
        (w for w in _live(doc.get("workflows"))
         if w.get("id") and public_pages & set(w.get("launchedFrom") or [])),
        key=lambda w: w["id"])]
    return out


def project_public_resources(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/public-resources.ts`` — the entities a public page reads.

    The middleware honours a page's access declaration, so `/plants` rendered
    for anyone; the data route then asked for a session regardless and answered
    401 to every fetch that page made. The plant was in the database and the
    page allowed to show it could not read it.

    Reads only. A public page writes through its workflows, and those routes
    the middleware already opens — `/api/data` POST/PATCH/DELETE build their
    context from `session.user` and stay gated.
    """
    slugs = sorted(a.split("/", 2)[2] for a in public_apis(doc)
                   if a.startswith("api/data/"))
    body = ",\n".join(f'  "{s}"' for s in slugs)
    lines = [
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.",
        "//",
        "// Entities behind a public page's own bindings. Read access only —",
        "// writes go through the workflow routes.",
        "",
        "export const PUBLIC_RESOURCES: string[] = [",
        body,
        "];",
        "",
    ]
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "public-resources.ts").write_text("\n".join(lines), "utf-8")
    return {"files": ["src/lib/public-resources.ts"], "resources": slugs}


def project_middleware(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/middleware.ts`` from what the pages declare.

    The scaffold shipped one hardcoded matcher gating everything except the
    login flow, so an app with any public surface could not be expressed. This
    generates the matcher from the pages themselves, which is the only way a
    partly-public app works — and it means the gate cannot drift from the
    contract, because it *is* the contract.

    Fails closed: a page is gated unless it says it is public.
    """
    access = access_map(doc)
    open_routes = [_matcher_segment(r) for r in access["public"]]
    open_routes = [r for r in open_routes if r]
    # A public route at "/" needs the bare root excluded too.
    root_public = "/" in access["public"]

    # A public page is only public if what it fetches is reachable too.
    apis = public_apis(doc)
    excluded = list(_ALWAYS_OPEN) + open_routes + apis
    pattern = "|".join(excluded)
    # A negative lookahead cannot exclude the empty path, so `/` is matched by
    # `.*` no matter what is listed. When the landing route is public, requiring
    # at least one character after the slash is what actually leaves it open.
    tail = "+" if root_public else "*"
    matcher = f"/((?!{pattern}|.*\\\\..*).{tail})"

    lines = [
        '// Generated from the Living Blueprint. Edit the Blueprint, not this file.',
        '//',
        '// Every page declares its own access (§100). Routes listed below are',
        '// public because a page said so; everything else is gated, because the',
        '// default is to gate — an accidentally public page leaks data, an',
        '// accidentally gated one merely annoys.',
        '//',
    ]
    for route in access["public"]:
        lines.append(f'//   public: {route}')
    for route in access["role_restricted"]:
        lines.append(f'//   by role: {route}')
    for route in apis:
        lines.append(f'//   public: /{route}  (reached by a public page)')
    lines += [
        '',
        'import { withAuth } from "next-auth/middleware";',
        '',
        'export default withAuth({',
        '  pages: { signIn: "/login" },',
        '});',
        '',
        'export const config = {',
        f'  matcher: ["{matcher}"],',
        '};',
        '',
    ]

    out = Path(app_root) / "src"
    out.mkdir(parents=True, exist_ok=True)
    (out / "middleware.ts").write_text("\n".join(lines), "utf-8")
    return {
        "files": ["src/middleware.ts"],
        "public": access["public"],
        "publicApis": apis,
        "gated": len(access["authenticated"]) + len(access["role_restricted"]),
    }


# ---------------------------------------------------------------------------
# the root route — `/` is not reachable by the catch-all
# ---------------------------------------------------------------------------

def landing_route(doc: dict) -> str:
    """Where `/` should send someone when no page claims it.

    The declared landing route if navigation names one, else the first page
    that is not an auth screen — never a guess. The scaffold guessed `/home`,
    a route this application does not have, so the root redirected into a 404
    and the 404 redirected into the login gate.
    """
    nav = doc.get("navigation") or {}
    for key in ("landing", "home", "root"):
        route = nav.get(key)
        if isinstance(route, str) and route.startswith("/"):
            return route
    for page in _live(doc.get("pages")):
        route = page.get("route") or ""
        if route and route != "/" and not any(
            k in route for k in ("sign-in", "signin", "login", "sign-up", "register")
        ):
            return route
    return "/"


def project_root_route(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Make sure `/` resolves — inside the shell, not beside it.

    Next's `[...slug]` is a *required* catch-all: it matches `/roles` but never
    `/`, so the root needs a page of its own. This used to write
    ``src/app/page.tsx``, on the stated grounds that "the scaffold shipped one
    that redirects to a hardcoded /home".

    It does not any more. The scaffold ships
    ``src/app/(dashboard)/page.tsx``, which renders the `/` schema exactly as
    the catch-all would — so this was writing a SECOND handler for a route that
    already had one. Route groups do not affect the URL, so both resolved to
    `/`, and the one this wrote sat outside `(dashboard)` and therefore outside
    `(dashboard)/layout.tsx`, which is where the sidebar lives.

    The result: every route in the application rendered with the shell except
    the one everybody lands on. The content was identical — same schema, same
    registry key — so it looked like a styling bug rather than a routing one.

    So the root page is owned in one place now, inside the group:

      * a page claims `/`  — the scaffold's file already does the right thing;
        leave it alone.
      * nothing claims `/` — overwrite it with a redirect to the declared
        landing route, still inside the group.

    Either way any ``src/app/page.tsx`` a previous build left behind is
    removed, because while it exists it shadows the in-group page and the
    sidebar goes missing again.
    """
    root_page = next((p for p in _live(doc.get("pages"))
                      if (p.get("route") or "") == "/"), None)
    app = Path(app_root) / "src" / "app"
    out = app / "(dashboard)"
    out.mkdir(parents=True, exist_ok=True)

    # A root page from a previous build shadows the in-group one. Removed
    # whichever branch runs — leaving it is what loses the sidebar.
    stale = app / "page.tsx"
    removed = stale.is_file()
    if removed:
        stale.unlink()

    if root_page:
        body = (
            '// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n'
            '//\n'
            '// `[...slug]` is a required catch-all and never matches "/", so the\n'
            f'// root needs its own route. {root_page.get("name")} claims it.\n'
            '\n'
            'import { renderSchemaPage } from "@/lib/schema-page";\n'
            '\n'
            'export default async function RootPage() {\n'
            '  return renderSchemaPage("/", new Request("internal:?path=%2F"));\n'
            '}\n'
        )
        claimed = root_page.get("id")
    else:
        target = landing_route(doc)
        body = (
            '// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n'
            '//\n'
            '// No page claims "/", so the root forwards to the declared landing\n'
            '// route. The scaffold hardcoded "/home", which this application does\n'
            '// not have — the root 404d and the 404 redirected into the gate.\n'
            '\n'
            'import { redirect } from "next/navigation";\n'
            '\n'
            'export default function RootPage() {\n'
            f'  redirect("{target}");\n'
            '}\n'
        )
        claimed = None

    # Only the redirect is written. When a page claims `/` the scaffold's
    # in-group file already renders it, and rewriting it with an identical
    # body would be this projection claiming ownership of something it does
    # not need to own.
    written: list[str] = []
    if not root_page:
        (out / "page.tsx").write_text(body, "utf-8")
        written.append("src/app/(dashboard)/page.tsx")
    return {"files": written, "claimedBy": claimed,
            "removedStaleRoot": removed,
            "redirectsTo": None if root_page else landing_route(doc)}


def project_append_only_entities(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/append-only-entities.ts`` — imported by the data engine.

    The catch-all imports this to reject PUT/DELETE on a ledger with a 405. The
    scaffold ships the route but not the module, so every generated app failed
    to compile on `Can't resolve '@/lib/append-only-entities'`. Nothing caught
    it because nothing had ever run `next build` on a generated app.

    The Blueprint has no append-only declaration yet, so the set is empty and
    the file exists — which is what the reference app ships too. When entities
    gain the flag, this reads it; until then it is honest about knowing of no
    ledgers rather than guessing at which tables look like one.
    """
    names = sorted({
        str(n) for entity in (doc.get("data") or {}).get("entities") or []
        if entity.get("appendOnly")
        for n in (entity.get("name"), entity.get("table"), entity.get("id"))
        if n
    })
    names += [n.lower() for n in names if n.lower() not in names]
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "append-only-entities.ts").write_text(
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        "//\n"
        "// Every entity listed here is a ledger: rows INSERTed only, never\n"
        "// UPDATEd or DELETEd. The Data Engine catch-all imports this Set and\n"
        '// rejects PUT/DELETE with a 405 { error: { code: "LEDGER_IMMUTABLE" } }.\n\n'
        "export const APPEND_ONLY_ENTITIES: ReadonlySet<string> = new Set([\n"
        + "".join(f'  "{n}",\n' for n in sorted(set(names)))
        + "]);\n\n"
        "export function isAppendOnly(entity: string): boolean {\n"
        "  if (!entity) return false;\n"
        "  return APPEND_ONLY_ENTITIES.has(entity)\n"
        "    || APPEND_ONLY_ENTITIES.has(String(entity).toLowerCase());\n"
        "}\n",
        "utf-8",
    )
    return {"files": ["src/lib/append-only-entities.ts"], "entities": len(set(names))}
