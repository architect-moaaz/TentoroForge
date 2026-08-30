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
import re
from pathlib import Path
from typing import Any

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
        code_map.append({"artifact": page_id, "service": [rel]})

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
    design = doc.get("designSystem") or {}
    colors = design.get("colors") or {}
    lines: list[str] = []

    # These four are the names the scaffold wraps in hsl(); the rest are ours
    # alone and keep their hex.
    WRAPPED = {"background", "foreground", "primary", "secondary"}
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
    body = (":root {\n" + "\n".join(lines) + "\n}\n") if lines else (
        "/* designSystem states no colour roles yet — the scaffold's own\n"
        "   defaults stand rather than inventing a palette here. */\n")
    (out / "tokens.css").write_text(header + body, "utf-8")

    return {"files": ["src/app/tokens.css"], "tokens": len(lines),
            "personality": design.get("visualPersonality")}


# ---------------------------------------------------------------------------
# workflows — the definitions the workflow engine executes
# ---------------------------------------------------------------------------

#: Blueprint step type -> the runtime node type the workflow engine dispatches.
_STEP_NODE_TYPE: dict[str, str] = {
    "action": "action", "approval": "approval", "human_task": "human_task",
    "condition": "condition", "notification": "notification",
    "integration": "action", "timer": "timer",
}

#: Blueprint step type -> the db action a mutating step performs.
_STEP_ACTION: dict[str, str] = {
    "action": "db_insert", "human_task": "db_update", "approval": "db_update",
}


def _wf_node(node_id: str, ntype: str, x: int, config: dict, label: str) -> dict:
    return {"id": node_id, "type": ntype, "position": {"x": x, "y": 0},
            "data": {"config": config, "label": label}}


def project_workflows(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/workflows/definitions/*.json`` from the Blueprint.

    A Blueprint workflow states what the business does; a definition states how
    the engine runs it. The translation is mechanical — steps become nodes in
    declared order, joined by edges from a trigger to an end — which is why
    this is a projection and not an agent. The old chain's own CRUD generator
    makes the same argument in its docstring: "Mechanical — no LLM, so no
    hallucinated names."
    """
    entities = {e.get("id"): e for e in (doc.get("data") or {}).get("entities") or []}
    workflows = [w for w in (doc.get("workflows") or [])
                 if w.get("status") != "DEPRECATED"]

    out = Path(app_root) / "src" / "lib" / "workflows" / "definitions"
    out.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    code_map: list[dict] = []
    for wf in workflows:
        slug = to_snake(wf.get("name") or wf.get("id") or "workflow").replace("_", "-")
        trigger = (wf.get("trigger") or {}).get("kind") or "manual"

        nodes = [_wf_node("trigger", "trigger", 0, {"type": trigger}, "Start")]
        chain = ["trigger"]
        # `start` and `end` are the Blueprint's own boundary markers, and this
        # function emits a `trigger` node and an `end` node for every workflow
        # regardless. Passing them through turned each into an action node with
        # no action — `_STEP_NODE_TYPE` has no entry for either, so both fell to
        # the "action" default, and `_STEP_ACTION` has none either, so both got
        # actionType "noop". Every workflow whose first step was `start` failed
        # on its first node with "Unregistered workflow actionType noop", which
        # is every workflow this planner writes.
        steps = [st for st in (wf.get("steps") or [])
                 if st.get("type") not in ("start", "end")]
        for i, step in enumerate(steps, start=1):
            step_id = f"s{i}"
            entity = entities.get(step.get("entity")) or {}
            config: dict[str, Any] = {
                "actionType": _STEP_ACTION.get(step.get("type"), "noop"),
            }
            if entity.get("table"):
                config["table"] = entity["table"]
                # WHAT TO WRITE, not just where. `db_insert` resolves
                # `config.values` — a column→expression map — and the node
                # carried none, so the insert named a table and supplied
                # nothing: "null value in column \"name\" of relation
                # \"plants\" violates not-null constraint". The workflow ran
                # every node and still wrote nothing.
                #
                # Referenced bare — `{{name}}`, not `{{input.name}}`.
                # `triggerWorkflow` passes the posted payload as ctx.variables
                # itself, so the column name IS the variable name. Same columns
                # the create form
                # asks for, by the same rule (`_asked_of_a_person`), so the
                # two cannot drift into asking for one set and storing another.
                if config["actionType"] in ("db_insert", "db_update"):
                    from services.blueprint.page_planner import form_fields_for

                    creating = config["actionType"] == "db_insert"
                    values = {
                        f["name"]: f"{{{{{f['name']}}}}}"
                        for f in form_fields_for(entity, creating=creating)
                        if f.get("name")
                    }
                    if values:
                        config["values"] = values
            if step.get("condition"):
                config["condition"] = step["condition"]
            nodes.append(_wf_node(
                step_id, _STEP_NODE_TYPE.get(step.get("type"), "action"),
                i * 200, config, step.get("name") or step_id,
            ))
            chain.append(step_id)
        nodes.append(_wf_node("end", "end", len(chain) * 200, {}, "End"))
        chain.append("end")

        edges = [{"id": f"e{i}", "source": a, "target": b}
                 for i, (a, b) in enumerate(zip(chain, chain[1:]))]

        definition = {
            "id": slug,
            "name": wf.get("name") or slug,
            "blueprintId": wf.get("id"),
            "processVariables": [],
            "definition": {"trigger": {"type": trigger},
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
    kind = str(field.get("type") or "text").lower()
    name = field.get("name") or "field"
    if field.get("values") or field.get("enum"):
        options = field.get("values") or field.get("enum")
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
    """Write ``src/app/page.tsx``.

    Next's `[...slug]` is a *required* catch-all: it matches `/roles` but never
    `/`. So the root always needs its own route file, and the scaffold shipped
    one that redirects to a hardcoded `/home`.

    Two cases, both read from the Blueprint. If a page claims `/`, render its
    schema exactly as the catch-all would. If none does, redirect to the
    declared landing route.
    """
    root_page = next((p for p in _live(doc.get("pages"))
                      if (p.get("route") or "") == "/"), None)
    out = Path(app_root) / "src" / "app"
    out.mkdir(parents=True, exist_ok=True)

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

    (out / "page.tsx").write_text(body, "utf-8")
    return {"files": ["src/app/page.tsx"], "claimedBy": claimed,
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
