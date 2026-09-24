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

from services.blueprint.embeddings import (
    EMBEDDING_DIMENSIONS, embedding_columns, is_embedding_field, is_image_field,
)
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
from services.blueprint.geo_types import LOCATION_TYPES, is_location_field  # noqa: E402

_TYPES: dict[str, str] = {
    "uuid": "uuid", "guid": "uuid",
    "text": "text", "string": "text", "str": "text", "email": "text",
    "url": "text", "enum": "text", "file": "text",
    # An image is a stored file: the column holds its forge_files id.
    "image": "text", "photo": "text", "picture": "text",
    "int": "integer", "integer": "integer", "number": "integer",
    "decimal": "numeric", "numeric": "numeric", "float": "numeric",
    "money": "numeric", "currency": "numeric",
    "bool": "boolean", "boolean": "boolean",
    "date": "date",
    "datetime": "timestamp", "timestamp": "timestamp", "time": "timestamp",
    "json": "jsonb", "jsonb": "jsonb", "object": "jsonb", "array": "jsonb",
    # A place: `{lat, lng}` (see geo_types).
    **{t: "jsonb" for t in LOCATION_TYPES},
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


def is_list_type(type_name: Any) -> bool:
    """`string[]`, `text[]`, `enum[]` — a column that holds several values."""
    t = str(type_name or "").strip().lower()
    return t.endswith("[]") or t in ("array", "list", "string list", "text list")


def drizzle_column(field: dict) -> tuple[str, str]:
    """One column line and the builder it needs imported."""
    type_name = str(field.get("type") or "").lower()
    # AN EMBEDDING IS FILLED BY THE PLATFORM, SO IT IS ALWAYS NULLABLE. The
    # vector arrives after the row does (the Data Engine embeds the source once
    # it is written), and a row whose image the model could not read must
    # still save. Its length is the platform model's, not the Blueprint's.
    if is_embedding_field(field):
        col = to_snake(field.get("name") or "embedding")
        return (f'{field.get("name")}: vector("{col}", '
                f'{{ dimensions: {EMBEDDING_DIMENSIONS} }}),'), "vector"
    # A LIST IS JSON. `string[]` fell through to the text default, so the
    # column held whatever shape reached it: the fixture's JSON text, the
    # create form's comma string. jsonb holds the array the tags field submits.
    builder = "jsonb" if is_list_type(type_name) else _TYPES.get(type_name, _DEFAULT_TYPE)
    col = to_snake(field.get("name") or "col")
    line = f'{field.get("name")}: {builder}("{col}")'
    if field.get("primaryKey"):
        line += ".primaryKey()"
        if builder == "uuid":
            line += ".defaultRandom()"
    # A required image is required of the FORM. The column stays nullable so
    # the seeded demo rows, which have no pictures, can still be written.
    if field.get("required") and not field.get("primaryKey") and not is_image_field(field):
        line += ".notNull()"
    # A PRIMARY KEY IS ALREADY UNIQUE, AND SAYING SO TWICE STOPS A DEPLOY.
    #
    # `.primaryKey().defaultRandom().unique()` emits a second constraint,
    # `<table>_id_unique`, over the column the primary key already covers. It
    # indexes nothing new — and `drizzle-kit push` asks before adding a unique
    # constraint to a table that holds rows:
    #
    #   You're about to add records_id_unique unique constraint to the table,
    #   which contains 3 items. Do you want to truncate records table?
    #
    # That prompt waits for an answer. On a Vercel build there is no terminal
    # to answer it, so the deployment sits there until it times out — and the
    # question it is asking is whether to destroy the user's data.
    #
    # `--force` is already passed and did not suppress this one, so the fix is
    # to stop asking: the constraint should never have been emitted. A unique
    # column that is NOT the key still gets one, because that is a real
    # constraint the entity asked for.
    if field.get("unique") and not field.get("primaryKey"):
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


#: Read back out of a projected module rather than recomputed from the
#: Blueprint, because the database holds what drizzle-kit pushed and drizzle
#: pushed what this file says. A second derivation of "which column is this
#: field" would be a second derivation that drifts, and the reader that drifts
#: is the one that SELECTs a column that is not there.
_TABLE_NAME_RE = re.compile(r"pgTable\(\s*\"(?P<table>[^\"]+)\"")


def parse_table_columns(source: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """``(table, ((field, column), …))`` for one ``src/db/schema/*.ts`` module.

    The field name is what the Blueprint calls the box and what a person
    reading a spreadsheet should see at the top of the column; the column name
    is what a ``SELECT`` has to say. Both come off the same declaration, so
    they cannot disagree.

    Returns ``("", ())`` for a file with no ``pgTable`` call — an index barrel,
    or a module that is not a table.
    """
    start = source.find("pgTable(")
    if start == -1:
        return "", ()
    named = _TABLE_NAME_RE.search(source[start:])
    table = named.group("table") if named else ""
    out: list[tuple[str, str]] = []
    for m in _COLUMN_RE.finditer(source[start:]):
        out.append((m.group("field"), m.group("column")))
    return table, tuple(out)


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

    # Nearest-neighbour search over an embedding reads an HNSW index; without
    # one every `op: "similar"` query is a sequential scan of the table.
    vector_indexes = [
        f'  index("{entity.get("table")}_{to_snake(f.get("name") or "")}_hnsw")'
        f'.using("hnsw", t.{f.get("name")}.op("vector_cosine_ops")),'
        for f in fields if is_embedding_field(f)
    ]
    if vector_indexes:
        builders.add("index")

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
        *(["}, (t) => [", *vector_indexes, "]);"] if vector_indexes else ["});"]),
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
    from services.blueprint.assembly import SCAFFOLD_DEFAULTS, SCAFFOLD_OWNED

    projected = {_module_name(e) for e in entities}
    platform = sorted(
        Path(rel).stem for rel in (*SCAFFOLD_OWNED, *SCAFFOLD_DEFAULTS)
        if rel.startswith("src/db/schema/") and rel.endswith(".ts")
        and Path(rel).stem not in projected   # an entity that claimed it is exported above
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
        # A declared page that only has the placeholder fallback must NEVER
        # overwrite a real layout that was composed on an earlier run — a page
        # whose composition was withdrawn keeps its last good schema rather than
        # degrading to "not laid out yet". A page that was already a placeholder
        # is refreshed. Either way the route keeps a schema; it is never blanked.
        if (schema.get("meta") or {}).get("fallback") and target.exists():
            try:
                prev = json.loads(target.read_text("utf-8"))
            except Exception:  # noqa: BLE001 — unreadable file, rewrite it
                prev = None
            if isinstance(prev, dict) and not (prev.get("meta") or {}).get("fallback"):
                written.append(rel)                 # keep it, and protect it below
                code_map.append({"artifact": page_id, "frontend": [rel]})
                continue
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
    # `shell.json` is the rail, written by `project_shell`, not a page: the
    # sweep deleted it on every frontend projection and the layout fell back
    # to its flat menu.
    written_set = set(written) | {"src/schemas/shell.json"}
    stale = sorted(
        str(f.relative_to(root)) for f in root.rglob("*.json")
        if f"src/schemas/{f.relative_to(root)}" not in written_set
    )
    for name in stale:
        (root / name).unlink()

    _write_route_registry(root, written, doc)

    return {
        "files": written,
        "pages": len(written),
        "removed": stale,
        "skipped": result["skipped"],
        "failed": result["failed"],
        # Pages that got the honest placeholder because nothing composed them —
        # surfaced so the build report can say "N screens need composing" rather
        # than leaving it silent.
        "fellBack": result.get("fellBack") or [],
        "templates": result["templates"],
        "codeMap": code_map,
    }


def project_page_schema(doc: dict, page_id: str, app_root: str | Path) -> str | None:
    """Persist ONE page's schema to disk the moment its layout is composed.

    The whole-app projection (``apply_frontend_projection``) runs in the frontend
    node, AFTER every page has composed — so a build interrupted at page_layouts
    kept the composed pages in the Blueprint but had none of them on disk, and
    could render nothing. This writes the just-composed page's schema (and keeps
    the route registry current so it resolves immediately), so a partial build
    persists — and can render — the pages it has made.

    Best-effort and idempotent: it writes only THIS page, never prunes another,
    and skips a page that only planned to a placeholder (nothing real yet). The
    frontend node still re-projects the whole app — shell, tokens, pruning — at
    the end; this is the incremental head-start, not a replacement.

    Returns the slug written, or ``None`` when there was nothing to persist.
    """
    from services.blueprint.page_planner import load_catalog, plan_pages

    if not page_id or not app_root:
        return None
    try:
        planned = (plan_pages(doc, load_catalog()) or {}).get("planned") or {}
    except Exception:  # noqa: BLE001 — planning must not fail the run it records
        return None
    schema = planned.get(page_id)
    if not isinstance(schema, dict) or (schema.get("meta") or {}).get("fallback"):
        return None  # not composed to anything real yet — nothing to write

    pages = {p.get("id"): p for p in doc.get("pages") or [] if isinstance(p, dict)}
    name = _route_slug((pages.get(page_id) or {}).get("route") or page_id)
    root = Path(app_root) / "src" / "schemas"
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{name}.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", "utf-8")
        # Keep the registry in step with what is on disk, so the route resolves
        # the instant its schema lands — a schema with no registry entry is a
        # page that may never render.
        present = sorted(
            f"src/schemas/{p.stem}.json" for p in root.glob("*.json"))
        _write_route_registry(root, present)
    except Exception:  # noqa: BLE001 — a failed early write is retried at the node
        return None
    return name


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


def _entry_route(doc: dict | None) -> str:
    """Where someone arriving at "/" should be sent when no page IS "/".

    MOST APPLICATIONS DECLARE NO PAGE AT THE ROOT. A master-data app is
    `/add-data` and `/master-data`; nothing is at "/". The scaffold used to
    ship a landing page there, and it had to be retired because a route group
    contributes nothing to the URL — so that file WAS "/" and collided with
    the catch-all that serves every other page. Retiring it left the root with
    nothing behind it: a sign-in redirect, and a 404 on the way back.

    The Blueprint already says where to go. `entry: true` marks the page each
    audience arrives at (§ the page contract), and the navigation tree's first
    item is where a reader would click anyway. Read in that order, and "" when
    the application genuinely has a page at "/" — then the catch-all renders it
    and there is nothing to redirect to.
    """
    pages = [p for p in ((doc or {}).get("pages") or []) if isinstance(p, dict)]
    live = [p for p in pages if str(p.get("status") or "") not in ("DEPRECATED", "SUPERSEDED")]
    routes = {str(p.get("route") or "") for p in live}
    if "/" in routes:
        return ""

    for page in live:
        if page.get("entry") and str(page.get("route") or "").startswith("/"):
            return str(page["route"])

    nav = ((doc or {}).get("navigation") or {}).get("tree") or []
    by_id = {str(p.get("id")): str(p.get("route") or "") for p in live}
    for item in nav:
        if isinstance(item, dict) and by_id.get(str(item.get("page"))):
            return by_id[str(item.get("page"))]

    return next((str(p["route"]) for p in live
                 if str(p.get("route") or "").startswith("/")), "")


def _write_route_registry(root: Path, written: list[str],
                          doc: dict | None = None) -> None:
    """Emit ``src/schemas/registry.ts`` — the authoritative live-route map.

    The catch-all route treats this as authoritative and only falls back to
    probing the filesystem, so a page schema with no registry entry is a page
    that may never resolve. Generated from what was actually written, so the
    two cannot disagree.

    Also carries `entryRoute`: where "/" sends a visitor when no page is "/".
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
        + "// Where \"/\" sends a visitor when no page IS \"/\". Empty when one is.\n"
        + f'export const entryRoute = "{_entry_route(doc)}";\n\n'
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

def brand_mark(doc: dict) -> dict[str, Any]:
    """The rail props that carry the owner's logo — ``{}`` when there is none.

    Split out because two things need the same answer and must not disagree:
    `project_shell` writes the reference into `shell.json`, and
    `project_brand_logo` puts the file at the path that reference resolves to.

    The alt text falls back to the application's name rather than to the file
    name: a mark in the corner of every screen says WHICH APPLICATION this is,
    and "a7f3c1e9.png" says nothing to anyone listening.
    """
    logo = (doc.get("designSystem") or {}).get("logo")
    if not isinstance(logo, dict) or not str(logo.get("file") or "").strip():
        return {}
    from services import brand_logo

    if not brand_logo.STORED_NAME.match(str(logo["file"])):
        # A hand-edited path. The projection refuses to build a URL from it
        # for the same reason `path_of` refuses to read one (§49: the absence
        # is visible in the log, not swallowed).
        logger.warning("[shell] logo path %r is not one we stored — ignored",
                       logo["file"])
        return {}
    app_name = str((doc.get("application") or {}).get("name") or "App")
    out: dict[str, Any] = {
        "logoSrc": "/" + str(logo["file"]),
        "logoAlt": str(logo.get("alt") or "").strip() or app_name,
    }
    width, height = logo.get("width"), logo.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        out["logoAspect"] = round(width / height, 4)
    return out


def project_brand_logo(doc: dict, app_root: str | Path,
                       output_dir: str | Path | None = None) -> dict[str, Any]:
    """Copy the owner's logo into the generated tree's ``public/``.

    The mark is stored once beside the Blueprint (``<output_dir>/brand/…``) and
    copied into the app on every projection, because the app tree is
    re-scaffolded and the Blueprint is not: a build that read the definition and
    rebuilt the tree would otherwise leave `shell.json` pointing at a file that
    is no longer there.

    ``output_dir`` defaults to the app root's parent, which is where every
    caller puts it (``app_root = <output_dir>/app``); it is a parameter so a
    caller with the project directory in hand does not have to reconstruct it.

    ALWAYS WRITES ``src/contracts/brand.ts``, including when there is no logo.
    The rail reads the mark off `shell.json`, but the pages that render OUTSIDE
    the rail — sign-in, sign-up, 404, 403 — have no shell to read, and they are
    exactly the pages an anonymous visitor sees. They import this module, so it
    has to exist on every application whether or not one was given: an import
    of a file the tree does not contain does not fail the page, it fails the
    build. (The scaffold ships the same module exporting `null`, as a
    `SCAFFOLD_DEFAULT`, for the case where this projection never ran at all.)
    """
    written = [_write_brand_module(doc, app_root)]
    logo = (doc.get("designSystem") or {}).get("logo")
    if not isinstance(logo, dict):
        return {"files": written}
    from services import brand_logo

    root = Path(output_dir) if output_dir is not None else Path(app_root).parent
    src = brand_logo.path_of(root, logo)
    if src is None:
        # THE DOCUMENT CLAIMS A MARK THE PROJECT DOES NOT HAVE. Said out loud
        # rather than swallowed: the shell will render the reference, the image
        # will 404, and a line here is the only place that names why.
        logger.warning("[brand] designSystem.logo names %r and there is no such "
                       "file under %s — the shell will reference a missing image",
                       logo.get("file"), root)
        return {"files": written, "reason": "logo file missing"}

    rel = str(logo["file"])                       # brand/<digest>.<ext>
    dest = Path(app_root) / "public" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    written.append(f"public/{rel}")
    return {"files": written}


#: The module every chrome-less page imports to find the owner's mark. Kept
#: beside the projector that writes it AND shipped by the scaffold with a
#: `null` body, so the two cannot describe different shapes.
BRAND_MODULE = "src/contracts/brand.ts"


def _write_brand_module(doc: dict, app_root: str | Path) -> str:
    """``src/contracts/brand.ts`` — the mark, for the pages with no shell.

    A TypeScript module rather than JSON because its readers are CLIENT
    components. `login/page.tsx` carries "use client" and cannot read a file at
    render time; it can import a constant, which the bundler inlines.

    Built from the same `brand_mark(doc)` the rail is, so the rail and the
    sign-in screen cannot disagree about which image the application signs its
    name with.
    """
    mark = brand_mark(doc)
    body = "null" if not mark else json.dumps({
        "src": mark["logoSrc"],
        "alt": mark["logoAlt"],
        **({"aspect": mark["logoAspect"]} if "logoAspect" in mark else {}),
    }, indent=2, sort_keys=True)
    out = Path(app_root) / "src" / "contracts"
    out.mkdir(parents=True, exist_ok=True)
    (out / "brand.ts").write_text(
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        "//\n"
        "// The owner's mark, for the pages that render with no shell around them —\n"
        "// sign-in, sign-up, 404, 403. The rail reads the same thing from\n"
        "// shell.json; both come from one function, so they cannot disagree.\n"
        "//\n"
        "// `null` is the normal case: an application described in words has no mark,\n"
        "// and each page then draws the initial it has always drawn.\n"
        "export type BrandLogo = {\n"
        "  /** Served from the app's own `public/`. */\n"
        "  src: string;\n"
        "  /** The application's name unless the owner said otherwise. */\n"
        "  alt: string;\n"
        "  /** width / height of the source image, when it could be measured. */\n"
        "  aspect?: number;\n"
        "};\n\n"
        f"export const BRAND_LOGO: BrandLogo | null = {body};\n",
        "utf-8")
    return BRAND_MODULE


#: A bottom tab bar holds this many destinations; the rest stay in the menu.
MOBILE_TABS = 5


def mobile_style(doc: dict) -> str:
    """`tabs` or `drawer`: the Blueprint's `navigation.mobile` when it says,
    else tabs when most pages say a phone is their primary device."""
    said = str(((doc.get("navigation") or {}).get("mobile")) or "")
    if said in ("tabs", "drawer"):
        return said
    pages = [p for p in doc.get("pages") or []
             if isinstance(p, dict) and p.get("status") != "DEPRECATED" and p.get("pattern") != "auth"]
    phone_first = [p for p in pages if str(((p.get("responsive") or {}).get("mobile")) or "") == "primary"]
    return "tabs" if pages and len(phone_first) * 2 > len(pages) else "drawer"


def mobile_tabs(doc: dict, groups: list[dict]) -> list[dict]:
    """The bottom tab bar of a mobile-first application: the destinations the
    architect marked `tab: true`, in rail order. Only when it marked none, the
    first main destinations stand in (a group contributes its first item)."""
    if mobile_style(doc) != "tabs":
        return []
    marked = [it for g in groups for it in [g, *(g.get("items") or [])] if it.get("tab") and it.get("route")]
    if marked:
        out = []
        seen: set[str] = set()
        for it in marked:
            if it["route"] in seen or len(out) == MOBILE_TABS:
                continue
            seen.add(it["route"])
            tab = {"label": str(it.get("label") or ""), "route": it["route"]}
            if it.get("icon"):
                tab["icon"] = str(it["icon"])
            if it.get("roles"):
                tab["roles"] = list(it["roles"])   # the bar hides what the rail hides
            out.append(tab)
        return out
    out: list[dict] = []
    for g in groups:
        first = g if g.get("route") else next((i for i in g.get("items") or [] if i.get("route")), None)
        if first and first["route"] not in [t["route"] for t in out]:
            tab = {"label": str(first.get("label") or g.get("label") or ""), "route": first["route"]}
            if first.get("icon") or g.get("icon"):
                tab["icon"] = str(first.get("icon") or g.get("icon"))
            if first.get("roles") or g.get("roles"):
                tab["roles"] = list(first.get("roles") or g.get("roles"))
            out.append(tab)
        if len(out) == MOBILE_TABS:
            break
    return out if len(out) >= 2 else []


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
    # A FLAT RAIL IS STILL A RAIL. This returned without writing when no node
    # had children, so a one-screen application had no shell file at all and
    # the root page, which reads it, failed to compile.
    if not tree:
        return {"files": [], "groups": 0, "reason": "no navigation"}

    routes = {str(p.get("id")): str(p.get("route") or "")
              for p in (doc.get("pages") or []) if p.get("id")}
    # WHO THE DESTINATION IS FOR — the menu's half of the gate. A
    # role-restricted page names the roles that may open it, and the rail
    # offered it to everyone: a neighbour who had just signed up was shown
    # "Admin — Dispute Queue, Member Verification" and got a 403 for pressing
    # it (0l133sp2). Only `role_restricted` is a permission (a page's `users`
    # is its audience, §100), so only that narrows the rail.
    role_names = {str(r.get("id")): str(r.get("name") or "") for r in doc.get("roles") or []
                  if isinstance(r, dict) and r.get("id")}
    page_roles = {str(p.get("id")): sorted({role_names.get(str(u), str(u)) for u in p.get("users") or []})
                  for p in (doc.get("pages") or [])
                  if p.get("id") and str(p.get("access") or "") == "role_restricted"}

    # A DYNAMIC ROUTE IS NOT A RAIL DESTINATION. `/rentals/[id]/return` is
    # reached through a row or an action that fills a concrete id, never from the
    # sidebar: Next's <Link> refuses a literal "[id]" href ("Dynamic href … not
    # supported"), and landing there passes the string "[id]" to the database as
    # a uuid. So a nav node pointing at one carries no route (it drops from the
    # rail); a group left with no linkable child drops entirely.
    def _navigable(route: str | None) -> bool:
        return bool(route) and "[" not in route

    def item(node: dict) -> dict[str, Any] | None:
        """A rail entry, or None when the node points at a page that cannot be a
        rail destination. A node with NO page is kept route-less and visible
        (§49); a node whose page is a DYNAMIC route is dropped — Next refuses a
        literal "[id]" href and landing there crashes on the uuid."""
        page_id = str(node.get("page") or "")
        route = routes.get(page_id)
        if page_id and route and not _navigable(route):
            return None
        out: dict[str, Any] = {"label": str(node.get("label") or "")}
        if _navigable(route):
            view = str(node.get("view") or "").strip()
            out["route"] = f"{route}?view={view}" if view else route
        if node.get("icon"):
            out["icon"] = str(node["icon"])
        if node.get("tab"):
            out["tab"] = True
        if page_roles.get(page_id):
            out["roles"] = page_roles[page_id]
        return out

    groups: list[dict[str, Any]] = []
    for node in tree:
        kids = [k for k in (node.get("children") or []) if isinstance(k, dict)]
        if kids:
            group: dict[str, Any] = {"label": str(node.get("label") or "")}
            if node.get("icon"):
                group["icon"] = str(node["icon"])
            if node.get("tab"):
                group["tab"] = True
            group["items"] = [it for it in (item(k) for k in kids) if it is not None]
            # A group is for whoever its children are for: "Admin" holding two
            # Admin-only screens is an Admin group, and says so, so the whole
            # heading goes rather than emptying out.
            kid_roles = [set(it.get("roles") or []) for it in group["items"]]
            if kid_roles and all(kid_roles):
                group["roles"] = sorted(set.union(*kid_roles))
            if group["items"]:
                groups.append(group)
        else:
            leaf = item(node)
            if leaf is not None:
                groups.append(leaf)

    app_name = str((doc.get("application") or {}).get("name") or "App")
    # WHERE THE APPLICATION OPENS. The scaffold's root page redirected to a
    # hard-coded /home, which no application has: every signed-in user landed
    # on a 404 and had to find the rail. The Blueprint's navigation names the
    # initial route; failing that, the first destination in the rail.
    initial = ((nav.get("initialRoute") or {}).get("default")
               if isinstance(nav.get("initialRoute"), dict) else nav.get("initialRoute"))
    # The landing route must be concrete — a dynamic "[id]" initialRoute lands
    # the app on a route it cannot render. Reject it and fall back to the first
    # navigable rail destination (which is already dynamic-free above).
    if not initial or str(initial) in ("/", "/home") or not _navigable(str(initial)):
        first = next((it for g in groups for it in (g.get("items") or [g]) if it.get("route")), None)
        initial = first.get("route") if first else None
    # THE RAIL IS PAINTED FROM THE DESIGN. Without colours here it fell back
    # to the library's navy and a blue mark, on an app whose design is a warm
    # paper and a forest green (0l133sp2). The design's dark lead surface, its
    # text and its accent, as the tokens the page already reads.
    rail: dict[str, Any] = {"groups": groups, "appName": app_name, "mode": "dark",
                            "bg": "hsl(var(--inverse))", "text": "hsl(var(--inverse-foreground) / 0.82)",
                            "muted": "hsl(var(--inverse-foreground) / 0.55)", "accent": "hsl(var(--accent))"}
    # THE OWNER'S MARK GOES WHERE THE APPLICATION'S NAME IS. The rail's brand
    # block draws a square with the first letter of the name in it; given a
    # logo it draws the logo instead. Only the reference is written here —
    # `project_brand_logo` is what puts the file where this src resolves, and
    # it writes nothing when the Blueprint names no logo, so a rail with no
    # mark is the same rail it has always been.
    rail.update(brand_mark(doc))
    shell = {
        "type": "AppShell",
        "frame": "topbar" if nav.get("style") == "topbar" else "sidebar",
        "children": [{"type": "SideNav", "props": rail}],
    }
    if initial:
        shell["initialRoute"] = str(initial)
    tabs = mobile_tabs(doc, groups)
    if tabs:
        shell["mobile"] = {"style": "tabs", "tabs": tabs}
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
            # WHO MAY OPEN IT, for the rail that merges pages the curated menu
            # does not list: a role-restricted page added later would
            # otherwise be offered to everyone, which is the fault this file
            # is read to avoid.
            **({"roles": sorted({str((roles.get(u) or {}).get("name") or u) for u in page.get("users") or []})}
               if access == "role_restricted" and page.get("users") else {}),
            "presentation": page.get("presentation") or "page",
            # By route, because that is what a router follows — resolved from
            # the page ids the contract carries, so a rename cannot break it.
            "navigatesTo": sorted({
                str(by_id[t].get("route")) for t in (page.get("navigatesTo") or [])
                if t in by_id and by_id[t].get("route")
            }),
        })
        # The GATED entry must be concrete — it is the login redirect and the
        # landing page, and a dynamic "[id]" route has no id to fill (Next
        # refuses the href, the DB gets "[id]" as a uuid). A PUBLIC entry may be
        # a pattern (`/survey/[slug]`, opened via a real link), so it is allowed
        # to be dynamic; only the authenticated/gated door is held concrete.
        if page.get("entry") and access not in entry_by_access and (
                access == "public" or "[" not in route):
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

    # A gated app still needs a concrete front door when no page was marked as
    # the entry (or the only one marked was dynamic): fall back to the first
    # non-dynamic gated route, so the login redirect and "back to the app" link
    # always have a route that renders.
    if "authenticated" not in entry_by_access:
        concrete = next((r for r in gated_routes if "[" not in r), None)
        if concrete:
            entry_by_access["authenticated"] = concrete

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


import functools


@functools.lru_cache(maxsize=1)
def _token_contract() -> dict:
    """The library's design-token contract — THE single source for which
    ``var(--…)`` names exist, which Blueprint role feeds each, and the default
    each falls back to. Read from the library package the backend runs beside
    (the staged tree and the repo both carry ``packages/library``); an absent
    file leaves the projector on its legacy alias path rather than crashing."""
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "packages" / "library" / "src" / "theme" / "token-contract.json"
        if cand.is_file():
            try:
                return json.loads(cand.read_text("utf-8"))
            except (OSError, ValueError):
                return {}
    return {}


_TRIPLET = re.compile(r"^-?\d+(\.\d+)?\s+\d+(\.\d+)?%\s+\d+(\.\d+)?%$")


def _as_triplet(value: str) -> str | None:
    """A Blueprint colour as the HSL triplet the contract stores — `#B91C1C` ->
    `0 74% 42%`, and a value already in triplet form passes through. Anything
    else (a named colour, an rgb()) has no triplet and is skipped, so the
    contract's default stands rather than a poisoned `hsl(<garbage>)`."""
    v = str(value).strip()
    if _TRIPLET.match(v):
        return v
    return _hsl_triplet(v)


def triplet_luminance(triplet: str) -> float | None:
    """WCAG relative luminance of an `H S% L%` triplet, or None if unparseable.
    The one place HSL→sRGB→luminance is computed; verification imports it so the
    projector's chosen foreground and the contrast check agree."""
    try:
        h, s, l = triplet.split()
        h = float(h) % 360
        s = float(s.rstrip("%")) / 100
        l = float(l.rstrip("%")) / 100
    except (ValueError, AttributeError):
        return None
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    r, g, b = {0: (c, x, 0), 1: (x, c, 0), 2: (0, c, x),
               3: (0, x, c), 4: (x, 0, c), 5: (c, 0, x)}[int(h // 60) % 6]

    def _lin(v: float) -> float:
        v += m
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _deepen_to_read(fg: str, bg: str, ratio: float = 4.5) -> str:
    """`fg` darkened (or, on a dark `bg`, lightened) in its own hue until it
    reads on `bg`. The accent's text on the accent's tint is the case: a
    terracotta on its own peach is 3.5:1, and the chip should say it in a
    deeper terracotta, not in black."""
    try:
        h, sat, light = fg.split()
        lum_bg = triplet_luminance(bg)
        L = float(light.rstrip("%"))
    except (ValueError, AttributeError):
        return fg
    if lum_bg is None:
        return fg
    step = -2.0 if lum_bg > 0.179 else 2.0
    for _ in range(50):
        cand = f"{h} {sat} {max(0.0, min(100.0, L)):g}%"
        lf = triplet_luminance(cand)
        if lf is not None and (max(lf, lum_bg) + 0.05) / (min(lf, lum_bg) + 0.05) >= ratio:
            return cand
        if not 0 < L < 100:
            break
        L += step
    return _readable_on(bg)


#: Role tokens whose colour is the design's accent reused as text on the
#: accent's own tint — deepened until they read rather than refused.
_DEEPEN_ON = {"accent-subtle-foreground": "accent-subtle"}


def _readable_on(triplet: str, ink: str | None = None, paper: str | None = None) -> str:
    """A near-black or near-white foreground for a background triplet, chosen by
    WCAG luminance (not HSL lightness — a saturated amber reads bright at L=50%
    and needs DARK text, which a lightness threshold gets wrong). 0.179 is the
    crossover where black and white contrast equally. Fills a `contrastOf` token
    whose Blueprint role states no text colour, so a tint or a dark fill never
    renders unreadable default text."""
    lum = triplet_luminance(triplet)
    if lum is None:
        return "0 0% 100%"
    # THE PALETTE'S OWN INK AND PAPER FIRST. A computed foreground was always
    # the scaffold's blue-black or pure white, so a forest-green design wrote
    # its card text in navy and its buttons in a white the page never uses.
    # The design's text colour (dark) or page ground (light) is used whenever
    # it reads on this base; the neutral pair only when it does not.
    def reads(candidate: str | None) -> bool:
        cl = triplet_luminance(candidate) if candidate else None
        if cl is None:
            return False
        hi, lo = max(lum, cl), min(lum, cl)
        return (hi + 0.05) / (lo + 0.05) >= 4.5
    if lum > 0.179:
        return ink if reads(ink) else "222 84% 5%"
    return paper if reads(paper) and (triplet_luminance(paper) or 0) > 0.8 else "0 0% 100%"


def _ink_and_paper(colors: dict) -> tuple[str | None, str | None]:
    """The design's own text colour and page ground, as triplets — only what
    the Blueprint states, never a contract default."""
    ink = _resolve_role(colors, ["textPrimary", "foreground", "text"])
    paper = _resolve_role(colors, ["background"])
    return (_as_triplet(ink) if ink else None), (_as_triplet(paper) if paper else None)


def _resolve_role(colors: dict, roles: list[str]) -> str | None:
    """The first Blueprint colour that matches one of `roles`, by exact key or
    kebab-insensitive match (`textPrimary` == `text-primary`)."""
    by_kebab = {_kebab(k): v for k, v in colors.items()
                if isinstance(v, str) and v}
    for role in roles:
        v = colors.get(role)
        if isinstance(v, str) and v:
            return v
        v = by_kebab.get(_kebab(role))
        if isinstance(v, str) and v:
            return v
    return None


def resolved_palette(doc: dict, theme: str = "light") -> dict[str, str]:
    """Every contract colour token as the HSL triplet that WILL render — the
    Blueprint-fed value where the design states the role (and computed
    foregrounds), the contract's own default otherwise. Verification judges
    contrast on this, the palette that actually ships, so a palette the user
    chooses is refused before it renders unreadable text rather than after."""
    colors = (doc.get("designSystem") or {}).get("colors") or {}
    contract = _token_contract().get("colorTokens") or []
    # 1. Role tokens: the Blueprint value where it states the role, else the
    #    contract default for this theme.
    out: dict[str, str] = {}
    for spec in contract:
        tok = str(spec["token"])
        if spec.get("contrastOf"):
            continue
        raw = _resolve_role(colors, spec.get("role") or [])
        trip = _as_triplet(raw) if raw is not None else None
        out[tok] = trip or spec.get(theme) or spec.get("light") or ""
    # 2. Foregrounds: ALWAYS computed for readability against the RESOLVED base,
    #    never a hand-set default that could disagree with a base the design
    #    changed (a white default over an amber accent is the bug this avoids).
    ink, paper = _ink_and_paper(colors)
    for spec in contract:
        base = spec.get("contrastOf")
        if base and out.get(base):
            out[str(spec["token"])] = _readable_on(out[base], ink, paper)
    for tok, base in _DEEPEN_ON.items():
        if out.get(tok) and out.get(base):
            out[tok] = _deepen_to_read(out[tok], out[base])
    return {k: v for k, v in out.items() if v}


def _project_contract_colors(colors: dict) -> list[str]:
    """Emit every contract token the Blueprint feeds, in the contract's order.

    Role tokens are filled from the Blueprint colour that matches; `contrastOf`
    tokens are computed from the resolved value of the token they contrast. A
    token the Blueprint does not drive is left unset here so the library's
    `theme.css` default stands — the projector overrides exactly what the design
    states, nothing more. Returns [] when the contract is unavailable, and the
    caller falls back to the legacy alias emission.
    """
    color_tokens = (_token_contract().get("colorTokens") or [])
    if not color_tokens:
        return []
    emitted: dict[str, str] = {}
    consumed: set[str] = set()          # blueprint roles a contract token claims
    for spec in color_tokens:
        roles = spec.get("role")
        if not roles:
            continue
        consumed.update(_kebab(r) for r in roles)
        raw = _resolve_role(colors, roles)
        if raw is None:
            continue
        trip = _as_triplet(raw)
        if trip is not None:
            emitted[str(spec["token"])] = trip
    ink, paper = _ink_and_paper(colors)
    for spec in color_tokens:
        base = spec.get("contrastOf")
        if base and base in emitted:
            emitted[str(spec["token"])] = _readable_on(emitted[base], ink, paper)
    for tok, base in _DEEPEN_ON.items():
        if tok in emitted:
            against = emitted.get(base) or next((str(t.get("light")) for t in color_tokens
                                                 if t.get("token") == base), None)
            if against:
                emitted[tok] = _deepen_to_read(emitted[tok], against)
    lines = [f"  --{spec['token']}: {emitted[spec['token']]};"
             for spec in color_tokens if spec["token"] in emitted]

    # PASS THROUGH THE ROLES THE CONTRACT DOES NOT CLAIM. The Blueprint may name
    # app-specific colours the shadcn contract has no slot for — `sidebarBackground`
    # that the rail reads, a `primaryHover` a scaffold uses. Emit each under its
    # own name so nothing an app depends on is dropped, but skip any role a
    # contract token already consumed, so a `danger` that became `--destructive`
    # does not also reappear as a dead `--danger` twin. Wrapped-set names keep the
    # hsl() triplet; the rest keep their value (a custom colour is read raw).
    contract_names = {str(spec["token"]) for spec in color_tokens}
    for role, value in sorted(colors.items()):
        if not (isinstance(value, str) and value):
            continue
        name = _kebab(role)
        if name in consumed or name in contract_names:
            continue
        out_value = (_hsl_triplet(value) or value) if role in _WRAPPED_ROLES else value
        lines.append(f"  --{name}: {out_value};")
    return lines


#: shadcn names the scaffold wraps in `hsl()`, so a passthrough role among them
#: must be a triplet. The contract covers these already; this only matters for a
#: legacy tree whose Blueprint names one directly.
_WRAPPED_ROLES = {"background", "foreground", "primary", "primaryForeground",
                  "secondary", "secondaryForeground", "accent", "accentForeground",
                  "muted", "mutedForeground", "destructive", "destructiveForeground",
                  "border", "input", "ring", "card", "cardForeground"}


#: A CSS length unit, or none for a bare `0`. `fr`/`%` included: spacing and
#: radius scales legitimately use them.
_CSS_UNIT = (r"(?:px|rem|em|%|fr|vh|vw|vmin|vmax|vi|vb|svh|lvh|dvh|svw|lvw|dvw|"
             r"ch|ex|cap|ic|lh|rlh|pt|pc|cm|mm|in|q)")
_CSS_DIMENSION = re.compile(
    rf"^-?(?:\d+\.?\d*|\.\d+){_CSS_UNIT}?$", re.IGNORECASE)
_CSS_FUNC = re.compile(r"^(?:calc|clamp|min|max|var|round)\(.*\)$",
                       re.IGNORECASE | re.DOTALL)


def _is_css_dimension(value: str) -> bool:
    """Is this the TYPE a length scale requires — a dimension, not prose?

    A `radius`/`spacing` scale is `{step: <css-length>}`, but the Blueprint
    contract types it as an open string→string map, so a design pass can nest a
    `rationale` (a whole sentence) beside the real steps. Emitted verbatim as a
    custom property, that prose carries a `;` that ends the declaration early
    and the next word is `Unknown word` — the whole `tokens.css`, and so the
    preview build, fails. The rationale is not a scale step; a value that is not
    a dimension is simply not part of the scale. `0`, `12px`, `0.5rem`, `50%`,
    and `calc(...)`/`var(...)` forms are; a sentence is not.
    """
    v = str(value).strip()
    return bool(v) and (bool(_CSS_DIMENSION.match(v)) or bool(_CSS_FUNC.match(v)))


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


#: Families every machine has; asking Google Fonts for them is a wasted request.
_SYSTEM_FAMILIES = {"system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "sans-serif", "serif",
                    "monospace", "-apple-system", "blinkmacsystemfont", "arial", "helvetica",
                    "georgia", "times new roman", "inherit"}

#: WHAT THE DESIGNER CALLS A FONT. The projector read `fontFamilyBase` and
#: `fontFamilyHeading`; Tool Share's design system said `fontFamily: "Inter,
#: system-ui, sans-serif"`, so no family was written, none was loaded, and the
#: pages' `font-serif` headings rendered in the browser's Times.
_FONT_ALIASES = {
    "fontFamilyBase": ("fontFamilyBase", "fontFamilyBody", "bodyFontFamily", "fontBody", "fontFamily"),
    "fontFamilyHeading": ("fontFamilyHeading", "fontFamilyDisplay", "headingFontFamily",
                          "displayFontFamily", "fontHeading", "fontDisplay"),
    "fontFamilyNumeric": ("fontFamilyNumeric", "fontFamilyMono", "monoFontFamily", "fontMono"),
}


def _font_roles(typography: dict) -> dict:
    """`typography` with its font families under the names the projector
    reads, whatever the designer called them."""
    out = dict(typography)
    for role, names in _FONT_ALIASES.items():
        for name in names:
            v = typography.get(name)
            if isinstance(v, str) and v.strip():
                out[role] = v.strip()
                break
    return out


def _first_family(value: str) -> str:
    """`"Fraunces", Georgia, serif` → `Fraunces`."""
    return value.split(",")[0].strip().strip("'\"").strip()


def _font_stack(value: str) -> str:
    """A family or a stack, each multi-word family quoted, as CSS reads it."""
    parts = []
    for raw in value.split(","):
        name = raw.strip().strip("'\"").strip()
        if not name:
            continue
        parts.append(f'"{name}"' if " " in name and name.lower() not in _SYSTEM_FAMILIES else name)
    return ", ".join(parts)


#: What the shell reads its frame from. The scaffold's layout has six
#: navigation chromes and its sign-in page six compositions, chosen from this
#: file — which only the old pipeline wrote, so every Blueprint app fell back
#: to the same rail and the same sign-in (0 of 70 apps had one, 2026-09-24).
SHELL_IDENTITY_PATH = "src/contracts/design-dna.json"

CHROMES = ("standard-rail", "wide-rail", "icon-rail", "floating-rail", "right-rail", "topbar", "dock")
AUTH_LAYOUTS = ("split-editorial", "split-reversed", "side-panel", "centered-minimal", "brand-wash", "top-anchored")


def derive_shell(doc: dict) -> dict[str, str]:
    """The frame: the design's own `shell` when it states one, otherwise read
    off what it did say — the navigation approach, the mobile style, the
    density and the personality. Deterministic, so the same Blueprint always
    gets the same frame."""
    design = doc.get("designSystem") or {}
    stated = design.get("shell") if isinstance(design.get("shell"), dict) else {}
    chrome = str(stated.get("chrome") or "")
    auth = str(stated.get("auth") or "")
    nav = doc.get("navigation") or {}
    approach = str(design.get("navigationApproach") or "").lower()
    personality = str(design.get("visualPersonality") or "").lower()
    density = str(design.get("informationDensity") or "comfortable")
    pages = [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("status") != "DEPRECATED"]

    # WHOLE WORDS. "Persistent left sidebar on desktop" contains "top" and
    # "bar", and read by substring it was a top bar (every app was, first
    # time round).
    # THE DESKTOP CLAUSE DECIDES THE FRAME. An approach reads "persistent
    # left sidebar on desktop; collapses to a bottom tab bar on mobile" —
    # the phone's tabs are the scaffold's own business, and read whole they
    # made every app a dock. Only an approach that LEADS with the phone is
    # mobile-first.
    desktop = approach if approach.startswith(("mobile-first", "mobile first")) else \
        re.split(r"\bcollaps|\bon (?:mobile|phones?|small screens|narrow)|\bmobile[:/]|;", approach)[0]
    said = lambda *words: any(re.search(r"\b" + w + r"\b", desktop) for w in words)  # noqa: E731
    if chrome not in CHROMES:
        # `navigation.mobile: tabs` is nearly universal (a phone gets tabs
        # either way) and says nothing about the desktop frame; only an
        # approach that leads with the phone earns the dock.
        if said("bottom tab bar", "tab bar", "bottom tabs", "mobile-first", "mobile first"):
            chrome = "dock"
        elif said("top bar", "topbar", "top nav", "top navigation", "header bar") or nav.get("style") == "topbar":
            chrome = "topbar"
        elif said("icon rail", "icons", "narrow rail", "minimal rail") or len(pages) <= 4:
            chrome = "icon-rail"
        elif said("right"):
            chrome = "right-rail"
        elif any(w in personality for w in ("editorial", "playful", "warm", "friendly", "calm")):
            chrome = "floating-rail"
        elif density == "compact" or len(pages) >= 14:
            chrome = "wide-rail"
        else:
            chrome = "standard-rail"
    if auth not in AUTH_LAYOUTS:
        if chrome == "dock" or any(w in personality for w in ("consumer", "playful", "warm", "friendly")):
            auth = "brand-wash"
        elif any(w in personality for w in ("stark", "utility", "minimal", "tool")):
            auth = "centered-minimal"
        elif density == "compact" or any(w in personality for w in ("dense", "back-office", "operations")):
            auth = "top-anchored"
        elif chrome in ("right-rail", "topbar"):
            auth = "split-reversed"
        elif chrome == "icon-rail":
            auth = "side-panel"
        else:
            auth = "split-editorial"
    return {"chrome": chrome, "auth": auth, "density": density}


def project_shell_identity(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write the frame the shell and the sign-in page read (see
    :data:`SHELL_IDENTITY_PATH`). Idempotent: rewritten from the Blueprint on
    every projection, like tokens.css."""
    shell = derive_shell(doc)
    out = Path(app_root) / SHELL_IDENTITY_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    body = {"_generated": "from the Living Blueprint (designSystem.shell) — edit the Blueprint, not this file",
            "layout": {"chrome": shell["chrome"], "auth": shell["auth"], "density": shell["density"]},
            "skin": ""}
    out.write_text(json.dumps(body, indent=2) + "\n", "utf-8")
    return {"files": [SHELL_IDENTITY_PATH], **shell}


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

    # ONE CONTRACT, emitted from the library's token-contract.json: every
    # `var(--…)` a component reads has a home, filled from the Blueprint role
    # that feeds it, in the HSL-triplet form the scaffold wraps in `hsl()`.
    # This replaced a hand-kept `WRAPPED` set + alias table + a pile of
    # role-named hex twins nothing read: status colours reached the app under
    # one name in one place (`--success`, not both a dead `--success` hex twin
    # AND Badge's unfed `--color-success-100`), and `surface` finally reached
    # `--card`/`--popover`. When the contract file is not beside the backend the
    # projector falls back to the legacy alias emission below rather than
    # emitting nothing.
    lines.extend(_project_contract_colors(colors))
    if not lines:
        # THE NAMES THE SCAFFOLD WRAPS IN hsl(). Legacy path — kept for a tree
        # that carries no token-contract.json. The wrapped set is shadcn's,
        # which is what the scaffold is.
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
            if isinstance(value, str) and _is_css_dimension(value):
                lines.append(f"  --radius-{_kebab(key)}: {value};")
        # Components ask for a bare `--radius`; `md` is the sane middle.
        for key in ("md", "control", "card"):
            if isinstance(radius.get(key), str) and _is_css_dimension(radius[key]):
                lines.append(f"  --radius: {radius[key]};")
                break

    typography = _font_roles(design.get("typography") or {})
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
            lines.append(f"  {token}: {_font_stack(value) if key.startswith('fontFamily') else value};")

    spacing = design.get("spacing")
    if isinstance(spacing, dict):
        for key, value in sorted(spacing.items()):
            if isinstance(value, str) and _is_css_dimension(value):
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
    families = [_first_family(str(v)) for k, v in (typography or {}).items()
                if k in ("fontFamilyBase", "fontFamilyHeading", "fontFamilyNumeric") and v]
    families = [f for f in families if f and f.lower() not in _SYSTEM_FAMILIES]
    fonts_import = ""
    if families:
        query = "&".join("family=" + f.replace(" ", "+") + ":wght@400;500;600;700"
                         for f in dict.fromkeys(families))
        fonts_import = f'@import url("https://fonts.googleapis.com/css2?{query}&display=swap");\n'
    # THE SAME GAP, ONE TOKEN OVER. `--font-size-base` was emitted right next
    # to `--font-body` and had the identical bug: nothing set the body's own
    # font-size, so picking "18 px" in the Look tab changed the variable and
    # nothing on the page.
    body_decls = []
    if (typography or {}).get("fontFamilyBase"):
        body_decls.append("  font-family: var(--font-body), ui-sans-serif, system-ui, sans-serif;")
    if (typography or {}).get("baseSize"):
        body_decls.append("  font-size: var(--font-size-base);")
    body_rule = "body {\n" + "\n".join(body_decls) + "\n}\n" if body_decls else ""
    if (typography or {}).get("fontFamilyHeading"):
        # Headings in the display face without every page having to ask.
        body_rule += ("h1, h2, h3, .font-heading {\n  font-family: var(--font-heading), "
                      "var(--font-body), ui-sans-serif, system-ui, sans-serif;\n}\n")
    # THE BRAND GRADIENT, AS TWO CLASSES. `bg-gradient-to-br from-gradient-start
    # to-gradient-end` works too (the tailwind config names both stops); these
    # are the short spelling pages are told to use, with the primary and the
    # accent standing in when the design states no gradient of its own.
    body_rule += (
        ".bg-brand-gradient {\n  background-image: linear-gradient(135deg, "
        "hsl(var(--gradient-start, var(--primary))), hsl(var(--gradient-end, var(--accent))));\n"
        "  color: hsl(var(--gradient-foreground, var(--primary-foreground)));\n}\n"
        ".text-brand-gradient {\n  background-image: linear-gradient(135deg, "
        "hsl(var(--gradient-start, var(--primary))), hsl(var(--gradient-end, var(--accent))));\n"
        "  -webkit-background-clip: text;\n  background-clip: text;\n  color: transparent;\n}\n")
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


#: WHO A HUMAN STEP WAITS ON. The Blueprint states `assignType: "role"` and
#: `assignTarget: ["Reception", "Front Office Manager"]`; the runtime reads
#: `assigneeRole` / `assignee` (or `assignment: {strategy, value}`), and with
#: neither present it filed the task under "admin" — a user that does not
#: exist — so a guest's refund request created a task no inbox showed
#: (Criterion Refunds v2, 2026-09-14). Several roles ride as one
#: comma-joined `assigneeRole`; the inbox matches a role by membership.
_HUMAN_STEPS = frozenset({"user_task", "approval", "assignment", "task_pool"})


def _name_the_assignee(config: dict[str, Any], wf_id: str, step: dict) -> None:
    if config.get("assignee") or config.get("assigneeRole") or config.get("assignment"):
        return
    kind = str(config.get("assignType") or "").strip().lower()
    target = config.get("assignTarget")
    targets = [str(t).strip() for t in (target if isinstance(target, list) else [target])
               if t not in (None, "")]
    if not targets:
        return
    if kind in ("user", "person", "email"):
        config["assignee"] = targets[0]
    elif kind in ("role", "roles", "") :
        config["assigneeRole"] = ",".join(targets)
    elif kind in ("group", "team"):
        config["assignmentStrategy"] = "group"
        config["assigneePool"] = targets
    else:
        logger.warning("[projection] %s/%s: assignType %r is not one the runtime "
                       "resolves — task will be unassigned", wf_id, step.get("key"), kind)


#: WHAT A HUMAN STEP ASKS THE PERSON. The Blueprint states what later steps
#: read from a task — `{{triage_with_override.overrideReason}}` — and never
#: a form; the generic task page collected a decision and a comment, the
#: placeholder stayed text, and the insert failed on a uuid column. The
#: names the workflow reads off a task that the runtime does not provide
#: are the fields the task must ask for.
_TASK_RUNTIME_OUTPUTS = frozenset({"userId", "completedBy", "decision", "comment", "output", "value"})
_STEP_REF = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")


def task_form_fields(step_key: str, steps: list[dict]) -> list[dict[str, Any]]:
    """Fields a human step must collect: `{{<key>.<field>}}` read by any step."""
    names: list[str] = []
    for other in steps:
        if not isinstance(other, dict) or other.get("key") == step_key:
            continue
        for src, field in _STEP_REF.findall(json.dumps(other.get("config") or {})):
            if src == step_key and field not in _TASK_RUNTIME_OUTPUTS and field not in names:
                names.append(field)
    fields = []
    for name in names:
        label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").strip().capitalize()
        kind = "textarea" if re.search(r"reason|note|comment|description|justification", name, re.I) else "text"
        fields.append({"name": name, "label": label, "kind": kind, "required": True})
    return fields


#: A SET-VARIABLE THAT COMPUTES. The runtime evaluates `expression` and stores
#: `value` as it is; an author who writes the rule into `value` —
#: `refundType in ["Gesture (SR)", …]` — stored the rule's text as the flag.
_EXPRESSION_MARKS = re.compile(r"\b(and|or|not|in)\b|[=<>()+*/]|\bcount\(|\bdate\(|\bnow\(")


def _reads_as_expression(value: Any) -> bool:
    return (isinstance(value, str) and "{{" not in value
            and bool(_EXPRESSION_MARKS.search(value)))


#: A WORKFLOW CONDITION SPEAKS FEEL. The engine evaluates `expression` with
#: FEEL-lite and, unlike the page renderer, folds nothing: `caseRow == null`
#: failed to parse and the gate that was meant to bar a poster failed the
#: whole run instead. JavaScript spelling — `==`, `===`, `!==`, `&&`, `||` —
#: is translated outside string literals.
_WF_JS_SPELLING = (
    (re.compile(r"!=="), "!="),
    (re.compile(r"==="), "="),
    (re.compile(r"(?<![!<>=])==(?!=)"), "="),
    (re.compile(r"\s*&&\s*"), " and "),
    (re.compile(r"\s*\|\|\s*"), " or "),
)
_WF_STRING_LITERAL = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")


def feel_condition(expr: Any) -> Any:
    if not isinstance(expr, str) or not expr.strip():
        return expr
    out: list[str] = []
    for i, part in enumerate(_WF_STRING_LITERAL.split(expr)):
        if i % 2 == 0:
            for pat, rep in _WF_JS_SPELLING:
                part = pat.sub(rep, part)
        out.append(part)
    return "".join(out)


#: Step config keys that name a role.
_ROLE_KEYS = ("recipientRole", "toRole", "assigneeRole", "role")


def _roles_by_name(config: dict[str, Any], role_names: dict[str, str]) -> dict[str, Any]:
    """Role ids in a step's config, as the role names the runtime compares."""
    for key in _ROLE_KEYS:
        value = config.get(key)
        if isinstance(value, str) and value:
            config[key] = ",".join(role_names.get(v.strip(), v.strip()) for v in value.split(","))
        elif isinstance(value, list):
            config[key] = [role_names.get(str(v), v) for v in value]
    return config


def _step_config(step: dict, entity: dict, catalog: WorkflowNodeCatalog,
                 wf_id: str = "", steps: list[dict] | None = None) -> dict[str, Any]:
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
    if ntype in _HUMAN_STEPS:
        _name_the_assignee(config, wf_id, step)
        if not config.get("formBinding") and steps:
            fields = task_form_fields(str(step.get("key")), steps)
            if fields:
                config["formBinding"] = {"fields": fields}
    if ntype == "action" and config.get("actionType") == "set_variable":
        if "expression" not in config and _reads_as_expression(config.get("value")):
            config["expression"] = config.pop("value")
    if ntype == "condition" and isinstance(config.get("expression"), str):
        config["expression"] = feel_condition(config["expression"])
    if ntype == "action" and config.get("actionType") == "set_variable" and isinstance(config.get("expression"), str):
        config["expression"] = feel_condition(config["expression"])
    if ntype == "condition" and steps and isinstance(config.get("expression"), str):
        # A db_query answers `{rows, count}`; `count(<step>)` counted the
        # object's keys, so "Duplicate case found?" was always yes.
        queries = {str(o.get("key")) for o in steps
                   if isinstance(o, dict) and o.get("type") == "action"
                   and str((o.get("config") or {}).get("actionType") or "") == "db_query"}
        config["expression"] = re.sub(
            r"\bcount\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
            lambda m: f"{m.group(1)}.count" if m.group(1) in queries else m.group(0),
            config["expression"])

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
        # A straight line — but an end is an end. Chaining the list in order
        # ran one end node into the next ("Record Created" into "Validation
        # Failed"); nothing flows out of a step with no out handle.
        for a, b in zip(chain, chain[1:]):
            node = catalog.node((by_key.get(a) or {}).get("type")) or {}
            if not node.get("handles", {}).get("out", True):
                continue
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


class WorkflowGraphInvalid(ValueError):
    """A projected workflow the engine would loop on or could not follow."""


def _check_graph(name: str, nodes: list[dict], edges: list[dict],
                 catalog: WorkflowNodeCatalog) -> None:
    """What the engine needs of a graph, checked where the graph is made.

    A node id used twice, an edge from a node to itself, an edge out of an
    end: each is a workflow that loops until the engine's cycle guard stops it
    or that runs past where it should stop — shipped, and found by someone
    pressing a button (22lzrc2p's Delete, 2026-09-19). The authoring check
    (`WorkflowNodeCatalog.flow_errors`) keeps the Blueprint from saying so;
    this keeps the projection from ever writing it, whatever it was given."""
    ids = [n.get("id") for n in nodes]
    problems = [f"node id {i!r} is used twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    types = {n.get("id"): n.get("type") for n in nodes}
    for e in edges:
        if e["source"] == e["target"]:
            problems.append(f"{e['source']!r} flows into itself")
        node = catalog.node(types.get(e["source"])) or {}
        if types.get(e["source"]) != "trigger" and not node.get("handles", {}).get("out", True):
            problems.append(f"{e['source']!r} is an end but flows on to {e['target']!r}")
    if problems:
        raise WorkflowGraphInvalid(f"workflow {name}: " + "; ".join(problems))


def _table_of(doc: dict, entity_id: str) -> str:
    """The table an entity's rows live in, for a workflow's record input."""
    for e in (doc.get("data") or {}).get("entities") or []:
        if isinstance(e, dict) and str(e.get("id")) == entity_id and e.get("status") != "DEPRECATED":
            return str(e.get("table") or to_snake(str(e.get("name") or "")))
    return ""


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
    # A step names a role as the Blueprint does (`ROLE-002`); the session,
    # the inbox and /api/notifications know it by its name ("Admin"). An id
    # there matched nobody — 0l133sp2's "awaiting KYC verification" was
    # stored for role "ROLE-002" and no admin ever saw it.
    role_names = {str(r.get("id")): str(r.get("name")) for r in doc.get("roles") or []
                  if isinstance(r, dict) and r.get("id") and r.get("name")}
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
        #
        # A step of type `trigger` is the same boundary under the catalog's own
        # name, and the same rule holds: the Start node is projected from
        # `wf.trigger` below. Kept, it became a SECOND node — and when its key
        # was `trigger` too, the same id as Start, with the edge
        # `trigger -> trigger`. The engine re-entered Start until its cycle
        # guard stopped it at 200 executions, so a generated Delete button
        # could never delete (22lzrc2p, 2026-09-19). What the marker hands off
        # to is where Start goes first.
        declared = [s for s in (wf.get("steps") or []) if isinstance(s, dict) and s.get("key")]
        markers = [s for s in declared if s.get("type") in ("start", "trigger")]
        steps = [s for s in declared if s.get("type") not in ("start", "trigger")]
        first = next((t for m in markers for t in (m.get("next") or [])
                      if any(x.get("key") == t for x in steps)), None)
        if first:
            steps.sort(key=lambda x: x.get("key") != first)       # stable: only `first` moves
        # Top-to-bottom, one node per row: the editor's handles are top (in)
        # and bottom (out), so this is the layout its edges are drawn for.
        nodes = [_wf_node("trigger", "trigger", 0, trigger_cfg, "Start")]
        chain = ["trigger"]
        for s in steps:
            entity = entities.get(s.get("entity")) or {}
            nodes.append(_wf_node(
                s["key"], s.get("type"), len(chain),
                _roles_by_name(_step_config(s, entity, catalog, wf_id=str(wf.get("id") or slug), steps=steps),
                               role_names),
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
        # WHAT A PERSON MUST HAVE DONE FIRST, CHECKED FIRST. A `prerequisite`
        # rule gating this workflow puts its check between the trigger and
        # the first step — here, from the rule, so no author can leave it out.
        from services.blueprint.account_model import guard_workflow
        guard_workflow(doc, wf, nodes, edges,
                       lambda k, t, cfg, lbl: _wf_node(k, t, len(nodes), cfg, lbl))
        _check_graph(str(wf.get("name") or wf.get("id")), nodes, edges, catalog)

        definition = {
            "id": slug,
            "name": wf.get("name") or slug,
            "blueprintId": wf.get("id"),
            # WHAT THE RUN CANNOT START WITHOUT. The browser knew (the SDK's
            # `wf(...)` lists them and the form marks the boxes), the server
            # did not — so a run that reached the engine without the identity
            # document set `kycStatus: pending` and wrote NULL over the photo
            # column, and the member's submission looked filed with nothing
            # in it (0l133sp2). Carried here, the engine can refuse instead.
            "requiredInputs": [str(i.get("name")) for i in wf.get("inputs") or []
                               if isinstance(i, dict) and i.get("name")
                               and i.get("required", True)],
            # AND WHICH OF THEM IS A RECORD. A control sends an id; a step
            # reads `member.kycStatus`. Nothing loaded the row, so the guard
            # on "Approve verification" was false for every member who WAS
            # pending, and `{{member.displayName}}` was stored as "".
            "recordInputs": [{"name": str(i.get("name")), "table": _table_of(doc, str(i.get("entity") or ""))}
                             for i in wf.get("inputs") or []
                             if isinstance(i, dict) and i.get("kind") == "record" and i.get("name")
                             and _table_of(doc, str(i.get("entity") or ""))],
            "processVariables": [],
            "definition": {"trigger": dict(trigger_cfg),
                           "nodes": nodes, "edges": edges},
        }
        (out / f"{slug}.json").write_text(
            json.dumps(definition, indent=2, sort_keys=True) + "\n", "utf-8")
        rel = f"src/lib/workflows/definitions/{slug}.json"
        written.append(rel)
        code_map.append({"artifact": wf.get("id"), "service": [rel]})

    # A retired workflow's definition goes with it: the engine registers every
    # file in this directory, so a stale one would keep a DEPRECATED workflow
    # runnable — and a Verify would find a definition the Blueprint disowns.
    live_slugs = {_workflow_slug(wf) for wf in workflows}
    for wf in (doc.get("workflows") or []):
        if wf.get("status") == "DEPRECATED":
            slug = _workflow_slug(wf)
            if slug not in live_slugs:
                (out / f"{slug}.json").unlink(missing_ok=True)

    written.append(project_launch_roles(doc, app_root)["files"][0])
    return {"files": written, "workflows": len(written), "codeMap": code_map}


#: Everyone with a session, in `launch-roles.ts`. A page open to anyone signed
#: in admits any of them, and the API has to say so in the same words.
SIGNED_IN = "@signed-in"


def launch_roles(doc: dict) -> dict[str, list[str] | None]:
    """Each workflow -> who may launch it: the union over the pages it is
    launched from. A public page admits everyone ("*"); a page open to anyone
    SIGNED IN admits any of them ("@signed-in"); a role-restricted page admits
    the roles it names. None when the Blueprint names no launching page.

    A page's `users` is its AUDIENCE — who it is for — and only
    `role_restricted` makes that audience a permission: the middleware gates
    nothing else, so the application shows a page and its controls to anyone
    signed in. Reading `users` regardless made the API stricter than the app
    that calls it: 0l133sp2's admin opened "List a Tool", filled it in,
    uploaded a photo, pressed the button and got 403 from an application that
    had just offered it."""
    names = {r.get("id"): r.get("name") for r in _live(doc.get("roles")) if r.get("id")}
    pages = {p.get("id"): p for p in _live(doc.get("pages")) if p.get("id")}
    out: dict[str, list[str] | None] = {}
    for w in _live(doc.get("workflows")):
        if not w.get("id"):
            continue
        launched = [pages[pid] for pid in (w.get("launchedFrom") or []) if pid in pages]
        if not launched:
            out[w["id"]] = None
            continue
        roles: set[str] = set()
        for pg in launched:
            access = str(pg.get("access") or "authenticated")
            if access == "public":
                roles.add("*")
                continue
            if access != "role_restricted":
                roles.add(SIGNED_IN)
                continue
            for u in pg.get("users") or []:
                nm = names.get(u, u)
                roles.add("*" if nm == "Guest" else str(nm))
        out[w["id"]] = sorted(roles)
    return out


def _workflow_slug(w: dict) -> str:
    return to_snake(w.get("name") or w.get("id") or "workflow").replace("_", "-")


def project_dispatches(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/contracts/dispatches.json``: every control→workflow wire
    with the payload the control sends (sampled per key). The build-time dry
    run (`verify-dispatches.ts`) executes each through the real engine — the
    same `_buildWhere`, the same Drizzle columns — without touching the
    database, so "verified" covers the app that ships, not the document."""
    from services.blueprint.dispatch_contract import dispatches
    out = Path(app_root) / "src" / "contracts"
    out.mkdir(parents=True, exist_ok=True)
    entries = dispatches(doc)
    (out / "dispatches.json").write_text(
        json.dumps({"dispatches": entries}, indent=2, sort_keys=True) + "\n", "utf-8")
    files = ["src/contracts/dispatches.json",
             project_incident_map(doc, entries, app_root)["files"][0]]
    return {"files": files, "dispatches": len(entries)}


def project_incident_map(doc: dict, entries: list[dict],
                         app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/incident-map.ts`` — what the running app needs to
    describe its own failures in the owner's words rather than in ids.

    THE SAME CONTRACT, READ AT THE OTHER END. `verify_dispatches` fails a
    build naming the route, the control and the workflow; when the same wire
    breaks in front of a customer months later, the reporter has only a
    workflow id and a browser path. These two tables close that: the routes
    let a concrete path (`/cases/8f2a…`) be reported as the pattern it matched
    (`/cases/[id]`) and never as itself, and the controls let a failed
    dispatch be named `Approve` on the case page.

    Written from `entries` — the dispatch manifest already computed above —
    so there is one source for what the build checked and what the run
    reports, not two that can disagree.
    """
    routes = sorted({str(p.get("route")) for p in _live(doc.get("pages")) if p.get("route")}
                    | {str(e.get("route")) for e in entries if e.get("route")})
    # KEYED BY BOTH NAMES THE RUNTIME MIGHT USE. A control's `workflow` prop
    # carries the Blueprint id; the projected definition is filed under its
    # slug, and the execute route sees whichever the dispatcher sent. This is
    # the same doubling `project_launch_roles` does, for the same reason — a
    # lookup that misses names no control and the crash reads as an id again.
    slugs = {str(w.get("id")): _workflow_slug(w)
             for w in _live(doc.get("workflows")) if w.get("id")}
    controls: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        wf = str(entry.get("workflow") or "")
        if not wf:
            continue
        wired = {"route": str(entry.get("route") or ""),
                 "control": str(entry.get("control") or ""),
                 "label": str(entry.get("label") or "")}
        for key in {wf, slugs.get(wf, wf)}:
            controls.setdefault(key, []).append(dict(wired))
    lib = Path(app_root) / "src" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "incident-map.ts").write_text(
        "// Written by the Blueprint projection (project_incident_map) from the same\n"
        "// dispatch contract the build-time dry run reads. Edit the Blueprint, not\n"
        "// this file.\n"
        "\n"
        "/** Every route the application declares, as patterns (`/cases/[id]`). */\n"
        f"export const ROUTES: string[] = {json.dumps(routes, indent=2)};\n"
        "\n"
        "/** workflow id -> the controls wired to it. */\n"
        "export const CONTROLS: Record<string, Array<{ route: string; control: string; "
        "label: string }>> =\n"
        f"{json.dumps(controls, indent=2, sort_keys=True)};\n",
        "utf-8")
    return {"files": ["src/lib/incident-map.ts"], "routes": len(routes),
            "workflows": len(controls)}


def project_launch_roles(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/workflows/launch-roles.ts`` - who may launch each workflow."""
    roles = launch_roles(doc)
    slugs = {w.get("id"): _workflow_slug(w) for w in _live(doc.get("workflows")) if w.get("id")}
    lines = [
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.",
        "//",
        "// A workflow may be launched by the roles the pages it launches from serve;",
        '// "*" admits an anonymous caller (a public page), "@signed-in" anyone with',
        "// a session (a page open to everyone signed in); null leaves it open.",
        "export const LAUNCH_ROLES: Record<string, string[] | null> = {",
    ]
    for wid, allowed in roles.items():
        val = "null" if allowed is None else json.dumps(allowed)
        lines.append(f"  {json.dumps(wid)}: {val},")
        if slugs.get(wid) and slugs[wid] != wid:
            lines.append(f"  {json.dumps(slugs[wid])}: {val},")
    lines += ["};", ""]
    out = Path(app_root) / "src" / "lib" / "workflows"
    out.mkdir(parents=True, exist_ok=True)
    (out / "launch-roles.ts").write_text(chr(10).join(lines), "utf-8")
    return {"files": ["src/lib/workflows/launch-roles.ts"], "workflows": len(roles)}


#: The module the runtime reads to know what this application is actually
#: connected to. Its absence means "nothing is declared", which is why
#: `runtime_injector` writes an empty one for an app whose Blueprint declared
#: no integration: a static import must always resolve.
CONNECTED_SERVICES_FILE = "src/lib/integrations/connected.ts"


def connected_services(doc: dict) -> list[dict[str, Any]]:
    """Every integration that SERVES a workflow action, in document order.

    A row with no `serves` is a note for a developer — recorded, not wired —
    and is deliberately absent here. Only the names of the secrets travel;
    a value never reaches a projected file any more than it reaches the
    Blueprint (§42).
    """
    from services.smith.email_connect import FROM_KEY, LIVE_KEY

    out: list[dict[str, Any]] = []
    for row in _live(doc.get("integrations")):
        serves = str(row.get("serves") or "").strip()
        if not serves:
            continue
        provider = str(row.get("provider") or "")
        keys = [str(k) for k in row.get("secretRefs") or []]
        # NO ADAPTER, NO CONNECTION. A row may name a provider nothing in the
        # runtime can talk to — a hand-authored Blueprint can say
        # `provider: "mailchimp", serves: "send_email"` — and handing it to
        # the app would make the step try to send through a path that does not
        # exist. It is dropped with a reason in the log, and the application
        # says no service is connected, which is the truth for it.
        if provider not in LIVE_KEY:
            logger.warning(
                "[projection] integration %s serves %s through %r, which has no "
                "adapter — not projected as a connection",
                row.get("id"), serves, provider)
            continue
        out.append({
            "action": serves,
            "name": str(row.get("name") or provider or "an outside service"),
            "provider": provider,
            "keys": keys,
            # Which key makes it live, and which carries the from-address.
            # Declared once, in `email_connect`, so the runtime does not
            # re-decide the provider precedence in TypeScript.
            "liveKey": LIVE_KEY[provider],
            "fromKey": FROM_KEY if FROM_KEY in keys else "",
        })
    return out


def project_integrations(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/integrations/connected.ts`` — the declared connections.

    A DECLARATION IS NOT A CONNECTION, and until this file existed the
    application could not tell the difference. `integrations` recorded the
    name of a service and the names of its secrets; the `send_email` step
    read `process.env` directly, sent nothing when it found nothing, and
    returned `{sent: true}` with an in-app notification instead — so the owner
    was told the workflow completed and the customer never got the email.

    What this gives the runtime is the one thing it could not derive: WHICH
    service this application's owner chose, and the name of the variable whose
    presence means it is live. The value stays where it belongs — the
    platform's credential store, shipped into the app's environment by
    `env_writer` locally and by the publish for a deployment.
    """
    entries = connected_services(doc)
    lines = [
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.",
        "//",
        "// What this application is CONNECTED to: for each workflow action that",
        "// talks to an outside service, the service its owner chose and the NAME",
        "// of the environment variable that carries the credential. Never a",
        "// value \u2014 the value is set once on the platform and arrives in this",
        "// app's environment (.env.local locally, the deployment's env on publish).",
        "//",
        "// An action absent from this map has no connected service. A step for it",
        "// must say so rather than report a send it did not make.",
        "",
        "export type ConnectedService = {",
        "  /** The service as its owner names it, e.g. \"Microsoft 365 / Outlook\". */",
        "  name: string;",
        "  /** The adapter that carries it, e.g. \"smtp\" or \"resend\". */",
        "  provider: string;",
        "  /** Every variable NAME this provider's path reads. */",
        "  keys: string[];",
        "  /** The variable whose presence means the service is live. */",
        "  liveKey: string;",
        "  /** The variable carrying the from-address, when the action has one. */",
        "  fromKey: string;",
        "};",
        "",
        "export const CONNECTED_SERVICES: Record<string, ConnectedService> = {",
    ]
    for entry in entries:
        lines.append(f"  {json.dumps(entry['action'])}: " + json.dumps({
            "name": entry["name"], "provider": entry["provider"],
            "keys": entry["keys"], "liveKey": entry["liveKey"],
            "fromKey": entry["fromKey"],
        }) + ",")
    lines += [
        "};",
        "",
        "/** The service declared for a workflow action, or undefined. */",
        "export function connectedService(action: string): ConnectedService | undefined {",
        "  return CONNECTED_SERVICES[action];",
        "}",
        "",
    ]
    out = Path(app_root) / "src" / "lib" / "integrations"
    out.mkdir(parents=True, exist_ok=True)
    (out / "connected.ts").write_text(chr(10).join(lines), "utf-8")
    return {"files": [CONNECTED_SERVICES_FILE], "services": len(entries)}


def entity_access(doc: dict) -> dict[str, dict[str, list[str]]]:
    """Each entity slug -> the roles that may read it and the roles that may
    write it, from the pages that use it.

    Reception read every user account through the data API: the Users page
    was Admin's, but nothing carried that to the endpoint. A role may read an
    entity when one of its pages binds it (a list, a record, a dropdown's
    source) or an ownership rule names it unscoped; it may write an entity
    when one of its pages is ABOUT it. "*" admits an anonymous reader for an
    entity a public page reads."""
    names = {r.get("id"): r.get("name") for r in _live(doc.get("roles")) if r.get("id")}
    entities = {e.get("id"): e for e in (doc.get("data") or {}).get("entities") or [] if e.get("id")}
    by_name = {e.get("name"): eid for eid, e in entities.items()}
    slug_of = {eid: str(e.get("table") or str(e.get("name")).lower()) for eid, e in entities.items()}
    layouts = {l.get("page"): l for l in _live(doc.get("pageLayouts"))}
    readers: dict[str, set[str]] = {eid: set() for eid in entities}
    writers: dict[str, set[str]] = {eid: set() for eid in entities}
    for pg in _live(doc.get("pages")):
        roles = {("*" if names.get(u, u) == "Guest" else str(names.get(u, u))) for u in (pg.get("users") or [])}
        if (pg.get("access") or "authenticated") == "public":
            roles.add("*")
        primary = (pg.get("data") or {}).get("primaryEntity")
        if primary in entities:
            readers[primary] |= roles
            writers[primary] |= roles
        for s in (layouts.get(pg.get("id"), {}).get("dataSources") or []):
            eid = by_name.get(s.get("entity"), s.get("entity"))
            if eid in entities:
                readers[eid] |= roles
        for eid in (pg.get("data") or {}).get("supportingEntities") or []:
            if eid in entities:
                readers[eid] |= roles
    # Ownership rules are dicts beside prose notes.
    for rule in ((doc.get("security") or {}).get("ownershipRules") or []):
        if isinstance(rule, dict) and rule.get("status") != "DEPRECATED" and by_name.get(rule.get("entity")) in entities:
            readers[by_name[rule["entity"]]] |= {str(r) for r in (rule.get("unscopedRoles") or [])}
    return {slug_of[eid]: {"read": sorted(readers[eid]), "write": sorted(writers[eid])} for eid in entities}


def project_entity_access(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/entity-access.ts`` - who may read and write each entity."""
    access = entity_access(doc)
    lines = [
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.",
        "//",
        "// The roles that may read and write each entity, from the pages that use",
        "// it. An entity absent here is open to any signed-in role.",
        "export const ENTITY_ACCESS: Record<string, { read: string[]; write: string[] }> = "
        + json.dumps(access, indent=2) + ";",
        "",
    ]
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "entity-access.ts").write_text(chr(10).join(lines), "utf-8")
    return {"files": ["src/lib/entity-access.ts"], "entities": len(access)}


# ---------------------------------------------------------------------------
# seed — enough rows that a preview shows something
# ---------------------------------------------------------------------------

def _seed_value(field: dict, entity_name: str, row: int,
                tables_by_id: dict | None = None) -> Any:
    # A FOREIGN KEY IS A REFERENCE, NOT A LABEL. Written as "Committee Id 1"
    # it failed every child insert as an invalid uuid and the demo database
    # held nothing but the admin. The seeder resolves `ref:<table>[i]` to the
    # i-th parent row it inserted, so that is what is written.
    if field.get("references") and tables_by_id is not None:
        parent = tables_by_id.get(str(field.get("references")))
        if parent:
            return f"ref:{parent}[{(row - 1) % 3}]"
    from services.blueprint.page_planner import enum_values

    kind = str(field.get("type") or "text").lower()
    name = field.get("name") or "field"
    if kind in LOCATION_TYPES:
        # NO INVENTED PLACE. Demo rows sat a few streets apart in central
        # London for every application, so a reader in Bangalore saw each
        # demo tool "4995 mi" away. A place is the people's own, shared from
        # their browser; demo rows have none.
        return None
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


#: A field the seed must not invent a value for, however the Blueprint spells
#: it. Anything this writes is either a plaintext password — a readable
#: credential in a file that is committed, exported and published (§42) — or a
#: label like "Password Hash 1", and BOTH produce an account that cannot be
#: signed into, because `auth.ts` bcrypt-compares what it finds.
#:
#: THREE RULES ABOUT CREDENTIAL-SHAPED NAMES, because they answer three
#: different questions, and each is narrower than the last on purpose:
#:
#:   * `sensitive_column_guard.is_sensitive_column` — what never reaches a
#:     SCREEN or a generated payload. The widest: reset tokens, client
#:     secrets and private keys have no business being displayed either.
#:   * `functional_completeness._CREDENTIAL_COLUMNS` — what a WORKFLOW may
#:     not write to a platform table. Wide is free there: a workflow has no
#:     business writing `salt` to `users` either.
#:   * this one — what the seed may not DERIVE A VALUE FOR, in any table.
#:     Over-reaching here corrupts demo data: `salt` is a real column in a
#:     recipe app and `passes` in a gym one, and blanking them to protect a
#:     credential trades one broken application for another. It is also held
#:     to what the runtime can fill (`_unusableCredentials` fills a
#:     password column and nothing else), so omitting more than that would
#:     lose the whole row to a NOT NULL constraint instead.
#:
#: A column whose name contains "password" is a credential in every
#: application there is. That is the whole rule, with no exceptions to keep.
def _is_credential_field(name: str) -> bool:
    return "password" in re.sub(r"[^a-z]", "", str(name or "").lower())


def _link_target(doc: dict, entity: dict, field: dict) -> str | None:
    """The entity a foreign key points at, for seeding a real link rather than
    the text "Owner Id 1" a uuid column refuses (0l133sp2 seeded nothing but
    the admin: no field carried `references`, and only five of ten links were
    in `data.relationships`). The field's own `references`, else the declared
    relationship, else an entity named by the field (`toolId` → Tool), else —
    an id naming a person (`ownerId`, `borrowerId`) — the account entity."""
    name = str(field.get("name") or "")
    ents = [e for e in (doc.get("data") or {}).get("entities") or [] if e.get("status") != "DEPRECATED"]
    eid = str(entity.get("id") or "")
    for r in (doc.get("data") or {}).get("relationships") or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("to")) == eid and r.get("toField") == name:
            return str(r.get("from"))
        if str(r.get("from")) == eid and r.get("fromField") == name and r.get("toField") in (None, "", "id"):
            return str(r.get("to"))
    m = re.match(r"^(.*?)(Id|_id)$", name)
    if not m or str(field.get("type") or "").lower() not in ("uuid", "string", "text", ""):
        return None
    stem = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
    for e in ents:
        if re.sub(r"[^a-z0-9]", "", str(e.get("name") or "").lower()) in (stem, stem.rstrip("s")):
            return str(e.get("id"))
    account = next((e for e in ents if e.get("account")), None)
    return str(account.get("id")) if account and str(account.get("id")) != eid else None


def project_seed(doc: dict, app_root: str | Path, rows: int = 3) -> dict[str, Any]:
    """Write ``src/db/seed.json`` — a few rows per entity.

    A preview of an empty database shows empty states everywhere, which looks
    identical to a broken one. Values are derived, never random, so the same
    Blueprint seeds the same rows and a screenshot is reproducible.

    NO CREDENTIAL IS DERIVED. A `password`/`passwordHash` field is left out of
    every row: the seed cannot produce a value that works (a hash is not
    derivable from a Blueprint) and every value it could produce is a readable
    credential in a file that ships. The runtime seed fills the column with a
    hash nobody holds, so the row exists as data and the account cannot be
    signed into — `admin@example.com` and the invited accounts are the ways in.

    AN ENTITY THE OWNER HAS LOADED DATA INTO GETS NONE. The demo rows exist so
    an empty screen is not mistaken for a broken one; an entity holding the
    business's real records does not have that problem, and "Customer 1" sat
    beside four hundred real customers is not demo data, it is a mistake in
    their data. `data.imports` is the declaration
    (`services.smith.data_import`); the rows themselves are in the app's own
    database, never here.
    """
    entities = [e for e in (doc.get("data") or {}).get("entities") or []
                if e.get("status") != "DEPRECATED"]
    imported = {str(i.get("entity")) for i in ((doc.get("data") or {}).get("imports") or [])
                if isinstance(i, dict) and i.get("entity")}
    tables_by_id = {str(e.get("id")): (e.get("table") or to_snake(e.get("name") or "entity"))
                    for e in entities if e.get("id")}

    seed: dict[str, list[dict]] = {}
    for entity in entities:
        table = entity.get("table") or to_snake(entity.get("name") or "entity")
        name = entity.get("name") or table
        if str(entity.get("id")) in imported:
            continue
        out_rows = []
        for row in range(1, rows + 1):
            record = {}
            for field in entity.get("fields") or []:
                if field.get("primaryKey"):
                    continue
                if _is_credential_field(field.get("name")):
                    continue
                if not field.get("references"):
                    target = _link_target(doc, entity, field)
                    if target:
                        field = {**field, "references": target}
                # No picture to seed, and a made-up file id is a broken image
                # plus an embedding that fails; the vector is the platform's.
                if is_image_field(field) or is_embedding_field(field):
                    continue
                record[field.get("name")] = _seed_value(field, name, row, tables_by_id)
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
        # THE COLUMN THE RUNTIME KNOWS, NOT THE FIELD THE BLUEPRINT NAMED. On a
        # platform table the Blueprint's `passwordHash` folds into the
        # platform's `password` (reconcile_platform_table); a manifest keyed by
        # `passwordHash` masks nothing, and the users list returned the bcrypt
        # hash to every caller.
        table_name = entity.get("table") or to_snake(entity.get("name") or "")
        synonyms = _PLATFORM_SYNONYMS.get(table_name, {}) if platform_table(table_name) else {}
        for field in entity.get("fields") or []:
            name = field.get("name") or ""
            name = synonyms.get(re.sub(r"[^a-z]", "", name.lower()), name)
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


#: The string family a free-text search can query. The check that consumes this
#: used to accept only "text"/"string"/"str", so an entity whose columns were
#: typed `varchar` (what the registry and Drizzle actually emit — `fullName`,
#: `email`, `phoneNumber`) read as having NO text column, and its page's search
#: box was refused every round with a defect the page composer cannot fix (the
#: columns exist; only the type vocabulary was too narrow). `varchar(255)` and
#: friends carry a length, so the type is compared with the length stripped.
_TEXT_TYPES = {
    "text", "string", "str", "varchar", "char", "nvarchar", "nchar", "citext",
    "longtext", "mediumtext", "tinytext", "clob",
    "email", "tel", "phone", "url", "slug", "name",
}  # deliberately NOT uuid/enum/number/date — those are not free-text search targets


def _is_text_type(t: Any) -> bool:
    """Whether a column type is free-text a search can match against — the whole
    string family, not just the word "text"; a `varchar(255)` length is ignored."""
    base = str(t or "").lower().split("(")[0].strip()
    return base in _TEXT_TYPES


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
            if _is_text_type(f.get("type"))
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


def project_embedding_columns(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``src/lib/embedding-columns.ts`` — which column the Data Engine
    fills from which field, on every write path.

    Always written, even when empty, for the same reason as the search
    manifest: the runtime imports it statically.
    """
    manifest = embedding_columns(doc)
    out = Path(app_root) / "src" / "lib"
    out.mkdir(parents=True, exist_ok=True)
    (out / "embedding-columns.ts").write_text(
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        "//\n"
        "// Keys are every reachable form of the entity name and its table;\n"
        "// `property` is the column's key on the Drizzle table, `of` the field\n"
        "// it embeds, `source` whether that field holds an image or text.\n\n"
        "export type EmbeddingColumn = {\n"
        "  property: string; column: string; of: string; source: \"image\" | \"text\";\n"
        "};\n\n"
        f"export const EMBEDDING_DIMENSIONS = {EMBEDDING_DIMENSIONS};\n\n"
        "export const EMBEDDING_COLUMNS: Record<string, EmbeddingColumn[]> = "
        f"{json.dumps(manifest, indent=2, sort_keys=True)};\n\n"
        "export function embeddingColumnsFor(entity: string): EmbeddingColumn[] {\n"
        "  if (!entity) return [];\n"
        "  return EMBEDDING_COLUMNS[entity]\n"
        "    ?? EMBEDDING_COLUMNS[entity.toLowerCase()]\n"
        "    ?? [];\n"
        "}\n",
        "utf-8",
    )
    return {"files": ["src/lib/embedding-columns.ts"],
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
        # WHERE THE ACTOR'S VALUE COMES FROM. The users column a workspace
        # scope compares against; the session carries it and the engine reads
        # it. Without one, `scope: "workspace"` compared every row to nothing.
        if item.get("actorColumn"):
            rule["actorColumn"] = str(item["actorColumn"])
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
        "  /** For scope \"workspace\": the users column whose value is the actor's workspace. */\n"
        "  actorColumn?: string;\n"
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
#:
#: `login` and `signup` are here, not just `api/auth`: `withAuth` special-cases
#: only the `signIn` page (`/login`), so `/login` slipped through by luck while
#: `/signup` was gated — the gate redirected the very visitor who has no account
#: yet straight back to `/login`, so "Sign up" never opened the signup page.
#: The pages that create or restore a session cannot themselves require one.
#:
#: `set-password` is the third of them. It is where a setup link lands — the
#: screen on which someone the owner invited, or someone whose password was
#: reset, chooses a password. Gated, it would redirect the one visitor who
#: certainly cannot sign in yet to the sign-in they cannot complete. It leaks
#: nothing: the page shows only the email its own one-time token resolves to.
_ALWAYS_OPEN: tuple[str, ...] = (
    "api/auth", "_next", "favicon.ico",
    "login", "signup", "set-password",
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
    project_entity_access(doc, app_root)
    return {"files": ["src/lib/public-resources.ts", "src/lib/entity-access.ts"], "resources": slugs}


def role_routes(doc: dict) -> list[dict[str, Any]]:
    """Each role-restricted page's route and the role NAMES that may open it.

    A page declares `access: "role_restricted"` and `users: [ROLE-…]`; the
    middleware compared nothing to those and gated the route on a session
    alone, so Reception opened the Income Auditor's queue and the Users
    admin page, and could act there (Criterion Refunds v2, 2026-09-14). The
    session carries the role's NAME, so that is what is projected.
    """
    names = {r.get("id"): r.get("name") for r in _live(doc.get("roles"))
             if r.get("id") and r.get("name")}
    out: list[dict[str, Any]] = []
    for page in _live(doc.get("pages")):
        if (page.get("access") or "authenticated") != "role_restricted":
            continue
        roles = sorted({names.get(u, u) for u in (page.get("users") or []) if u})
        if not roles:
            continue   # nothing to compare to; the session gate still applies
        out.append({"route": page.get("route") or "/", "roles": roles})
    return sorted(out, key=lambda r: r["route"])


def _route_regex(route: str) -> str:
    """`/refund-cases/[id]` → `^/refund-cases/[^/]+$`, a regex source string.

    Emitted through `new RegExp(<json string>)`, not a `/…/` literal: a route's
    own slashes would end a literal early, and `re.escape` spells `-` as `\-`.
    """
    parts = []
    for seg in route.strip("/").split("/"):
        if not seg:
            continue
        if seg.startswith("[") and seg.endswith("]"):
            parts.append("[^/]+")
        else:
            parts.append(re.sub(r"([.+*?^${}()|\[\]\\])", r"\\\1", seg))
    return "^/" + "/".join(parts) + "$" if parts else "^/$"


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
    #
    # AND SO DOES A ROOT THAT ONLY FORWARDS. Most applications declare no page
    # at "/" — a master-data app is `/add-data` and `/master-data` — so the
    # root renders nothing of its own and the catch-all sends the visitor to
    # the entry page. Gating that forward puts a sign-in screen in front of a
    # public page, which is a login for nothing: the visitor signs in, arrives
    # back at "/", and is forwarded to the page they could always have seen.
    #
    # It leaks nothing. The root holds no content, and the page it forwards to
    # is public by its own declaration or this does not fire.
    root_public = "/" in access["public"] or (
        _entry_route(doc) and _entry_route(doc) in access["public"])

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
    gated_by_role = role_routes(doc)
    role_lines = [
        f'  {{ route: new RegExp({json.dumps(_route_regex(r["route"]))}), roles: {json.dumps(r["roles"])} }},'
        for r in gated_by_role
    ]
    lines += [
        '',
        'import { withAuth } from "next-auth/middleware";',
        # THE SAME COOKIE THE APP SETS. `withAuth` asks `getToken` for
        # next-auth's DEFAULT cookie name unless it is told otherwise, and
        # this application names its own (one browser, two apps on one host).
        # Unnamed here, a signed-in person was bounced to /login by every
        # page while a valid session sat in the browser (Vercel, 0l133sp2).
        'import { sessionCookies } from "@/lib/session-cookie";',
        'import { NextResponse } from "next/server";',
        '',
        '// A role-restricted page names the roles that may open it; the session',
        '// carries the role. Anyone else is sent to the 403 page, signed in or',
        '// not-yet — a session alone is not a permission.',
        'const ROLE_ROUTES: Array<{ route: RegExp; roles: string[] }> = [',
        *role_lines,
        '];',
        '',
        'export default withAuth(',
        '  function middleware(req) {',
        '    const role = String((req.nextauth.token as { role?: unknown } | null)?.role ?? "");',
        '    const path = req.nextUrl.pathname;',
        '    for (const r of ROLE_ROUTES) {',
        '      if (r.route.test(path) && !r.roles.includes(role)) {',
        '        return NextResponse.redirect(new URL("/403", req.url));',
        '      }',
        '    }',
        '    return NextResponse.next();',
        '  },',
        '  { pages: { signIn: "/login" }, cookies: sessionCookies() },',
        ');',
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
        "byRole": gated_by_role,
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


#: Written into every route file this projector emits, and the only way the
#: sweep below can tell a file it owns from one the scaffold shipped or a
#: person wrote. A marker rather than a manifest: a manifest is a second
#: statement of which routes are public, and the two would drift.
_PUBLIC_ROUTE_MARKER = "@generated forge:public-route"

#: Top-level directories under `src/app` that belong to the scaffold or to
#: Next. A Blueprint page that claims one of these routes is refused rather
#: than written, because writing it would replace the sign-in screen with a
#: form, or shadow the API the application talks to.
_RESERVED_APP_SEGMENTS = frozenset({
    "api", "login", "signup", "403", "_next", "favicon.ico",
})

#: A path segment is a plain slug or a single dynamic parameter. `route` comes
#: out of a JSON document and becomes a DIRECTORY NAME; `..` in it would put a
#: generated file anywhere on the disk the process can write.
#:
#: THE FIRST VERSION OF THIS PATTERN ADMITTED `..`, because `[A-Za-z0-9._-]+`
#: matches it and the comment above says what the author meant rather than what
#: the regex did. `/a/../b` wrote outside the directory it was given. A segment
#: has to CONTAIN something that is not a dot.
_ROUTE_SEGMENT = re.compile(
    r"^(?:(?=[^.])[A-Za-z0-9._-]+|\[[A-Za-z_][A-Za-z0-9_]*\])$")


def _public_route_file(route: str) -> str:
    """The `page.tsx` that renders one public route, outside the gated group.

    It is a thin call into `renderSchemaPage`, the same one every other route
    file makes; what makes it different is only WHERE it sits.
    """
    segments = [seg for seg in route.split("/") if seg]
    params = [seg[1:-1] for seg in segments if seg.startswith("[")]
    head = (
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        f"// {_PUBLIC_ROUTE_MARKER}\n"
        "//\n"
        f"// {route} is declared PUBLIC, and a public page must not sit inside\n"
        "// `(dashboard)` — that group's layout opens with `if (!session)\n"
        "// redirect(\"/login\")`, so the projected middleware opened the route and\n"
        "// the layout closed it again. A static segment outranks the group's\n"
        "// `[entity]`, so this file is what Next matches, and the visitor gets the\n"
        "// page instead of a sign-in screen.\n"
        "//\n"
        "// It also renders with no rail, which is what `nav-flow` already says\n"
        "// about it (`shell: false`): navigation into a product the visitor\n"
        "// cannot reach is worse than no navigation.\n"
        "\n"
        'import { renderSchemaPage } from "@/lib/schema-page";\n'
        'import { PublicPageFrame } from "@/components/PublicPageFrame";\n'
        "\n"
    )
    search = ("  searchParams?: Promise<Record<string, string | string[] | "
              "undefined>>;\n")
    if not params:
        return (
            head
            + "export default async function PublicPage({ searchParams }: {\n"
            + search
            + "}) {\n"
            + f'  const request = new Request("internal:?path={_encode(route)}");\n'
            + "  return (\n"
            + "    <PublicPageFrame>\n"
            + f'      {{await renderSchemaPage("{route}", request, await searchParams)}}\n'
            + "    </PublicPageFrame>\n"
            + "  );\n"
            + "}\n"
        )
    # The CONCRETE path is rebuilt from the params so breadcrumb ancestors
    # resolve (renderer's `resolveCrumbHrefs` reads it), and the LAST dynamic
    # segment rides as `id` — the key `data-engine-bridge` reads to turn a
    # detail page into `engine.findById`. Right-to-left is the same preference
    # the catch-all applies when it decides which segment was the record.
    fields = ", ".join(f"{name}: string" for name in params)
    literal = "/".join(
        ("${encodeURIComponent(p." + seg[1:-1] + ")}") if seg.startswith("[") else seg
        for seg in segments
    )
    return (
        head
        + "export default async function PublicPage({ params, searchParams }: {\n"
        + f"  params: Promise<{{ {fields} }}>;\n"
        + search
        + "}) {\n"
        + "  const p = await params;\n"
        + f"  const path = `/{literal}`;\n"
        + f"  const request = new Request(\n"
        + f"    `internal:?id=${{encodeURIComponent(p.{params[-1]})}}"
          "&path=${encodeURIComponent(path)}`,\n"
        + "  );\n"
        + "  return (\n"
        + "    <PublicPageFrame>\n"
        + f'      {{await renderSchemaPage("{route}", request, await searchParams)}}\n'
        + "    </PublicPageFrame>\n"
        + "  );\n"
        + "}\n"
    )


def _encode(route: str) -> str:
    from urllib.parse import quote
    return quote(route, safe="")


def public_route_segments(page: dict) -> list[str] | None:
    """The directory segments a PUBLIC page's own route file sits at, outside
    `(dashboard)` — or None when the page is not public, is the root (the
    catch-all serves it), or cannot be a directory there. One rule, read by
    every writer of a page's route file, so two of them can never put a page
    at two paths that resolve to the same URL."""
    if (page.get("access") or "authenticated") != "public":
        return None
    route = str(page.get("route") or "")
    if not route.startswith("/") or route == "/":
        return None
    segments = [seg for seg in route.split("/") if seg]
    if not all(_ROUTE_SEGMENT.match(seg) for seg in segments):
        return None
    if segments[0].lower() in _RESERVED_APP_SEGMENTS:
        return None
    return segments


def project_public_routes(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Give every PUBLIC page its own route file, outside ``(dashboard)``.

    THE MIDDLEWARE OPENED THE DOOR AND THE LAYOUT CLOSED IT. `project_middleware`
    builds its matcher from what each page declares, so `/nurse-registration`
    was excluded from the gate exactly as the Blueprint asked. But Next matches
    a one-segment URL against `src/app/(dashboard)/[entity]/page.tsx`, and that
    group's layout begins `if (!session) redirect("/login")` — it has no notion
    of a public route and never did. So an anonymous visitor to a page declared
    public got the sign-in screen, and `entity_access`'s `"*"` readers and
    `launch_roles`'s `"*"` launchers — both already projected for exactly this
    visitor — were never reached by anyone.

    A static segment outranks a dynamic one in Next's matcher, so a file at
    `src/app/nurse-registration/page.tsx` is what a request resolves to, and it
    sits outside the group and therefore outside the gate. Which is also the
    honest structure: a public page is not part of the dashboard, and saying so
    with a directory is better than teaching the dashboard's layout to render
    some of its children without itself.

    `/` is left alone: the optional catch-all already serves it from outside
    the group, so a public root page was the one case that always worked.

    Files this projector wrote before and would not write now are removed. A
    page that stops being public must stop having a door around the gate, and
    the sweep is by the marker each file carries rather than by a manifest —
    a manifest would be a second statement of which routes are public.
    """
    app = Path(app_root) / "src" / "app"
    wanted: dict[Path, str] = {}
    refused: list[str] = []

    # A page with code has its own route file at the same place (see
    # `app_sdk.code_page_dir`); writing this one too would be two pages at
    # one URL, which Next refuses to build.
    coded = {str(r.get("page")) for r in _live(doc.get("pageCode"))}
    for page in _live(doc.get("pages")):
        if (page.get("access") or "authenticated") != "public":
            continue
        if str(page.get("id")) in coded:
            continue
        route = str(page.get("route") or "")
        if not route.startswith("/") or route == "/":
            continue
        segments = [seg for seg in route.split("/") if seg]
        if not all(_ROUTE_SEGMENT.match(seg) for seg in segments):
            refused.append(route)
            logger.warning("[public-routes] %s is not a shape we can make a "
                           "directory of — left inside the gate", route)
            continue
        if segments[0].lower() in _RESERVED_APP_SEGMENTS:
            # Writing this would replace the sign-in screen, or shadow the API
            # the application talks to. Named, not silently skipped: the page
            # will not be reachable and someone has to know why.
            refused.append(route)
            logger.warning("[public-routes] %s collides with a route the scaffold "
                           "owns (%s) — not written", route, segments[0])
            continue
        wanted[app.joinpath(*segments, "page.tsx")] = _public_route_file(route)

    written: list[str] = []
    for dest, body in sorted(wanted.items()):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, "utf-8")
        written.append(str(dest.relative_to(Path(app_root))))

    removed: list[str] = []
    # LISTED BEFORE ANYTHING IS DELETED. `rglob` walks the tree lazily, so
    # removing a directory mid-iteration makes it raise FileNotFoundError on
    # the descent it had already queued — the sweep died partway through and
    # left some of the files it had decided to take out.
    stale = sorted(app.rglob("page.tsx")) if app.is_dir() else []
    for existing in stale:
        if existing in wanted:
            continue
        try:
            if _PUBLIC_ROUTE_MARKER not in existing.read_text("utf-8"):
                continue
        except OSError:                          # unreadable: not ours to delete
            continue
        existing.unlink()
        removed.append(str(existing.relative_to(Path(app_root))))
        # A directory that held nothing but that file is now noise Next still
        # walks; take it back out, parents included, up to `src/app`.
        parent = existing.parent
        while parent != app and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    return {"files": sorted(written), "removed": sorted(removed),
            "refused": sorted(refused)}


def public_nav(doc: dict) -> dict[str, Any]:
    """The public pages a visitor can move between, in navigation order.

    A page that needs a record (`[id]` in its route) is reached from a list,
    never from the menu. Order follows the navigation tree where it names the
    page, then the order the pages were declared in."""
    pages = [p for p in _live(doc.get("pages"))
             if (p.get("access") or "authenticated") == "public"
             and str(p.get("pattern") or "") != "auth"      # the header has its own sign-in link
             and not re.search(r"\[[^\]]+\]", str(p.get("route") or ""))
             and str(p.get("route") or "").startswith("/")]
    order: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("page", "pageId", "id"):
                if isinstance(node.get(key), str):
                    order.append(node[key])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk((doc.get("navigation") or {}).get("tree"))
    rank = {pid: i for i, pid in enumerate(dict.fromkeys(order))}
    # Home first, wherever the tree lists it: a menu starts where the app does.
    pages.sort(key=lambda p: (str(p.get("route")) != "/",
                              rank.get(str(p.get("id")), len(rank)), _live(doc.get("pages")).index(p)))
    signed_in = any((p.get("access") or "authenticated") != "public"
                    for p in _live(doc.get("pages")))
    return {"appName": str((doc.get("application") or {}).get("name") or ""),
            "items": [{"label": str(p.get("name") or p.get("route")), "route": str(p.get("route"))}
                      for p in pages],
            "signIn": signed_in}


def project_public_nav(doc: dict, app_root: str | Path) -> str:
    """Write ``src/contracts/public-nav.ts`` — the public frame's menu."""
    nav = public_nav(doc)
    path = Path(app_root) / "src" / "contracts" / "public-nav.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "// Generated from the Living Blueprint. Edit the Blueprint, not this file.\n"
        "// The public pages a visitor can move between; `PublicPageFrame` renders them.\n"
        "export type PublicNavItem = { label: string; route: string };\n\n"
        "export const PUBLIC_NAV: { appName: string; items: PublicNavItem[]; signIn: boolean } = "
        + json.dumps(nav, indent=2) + ";\n", "utf-8")
    return str(path.relative_to(Path(app_root)))


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


# ---------------------------------------------------------------------------
# business rules with effects → the runtime's rules directory
# ---------------------------------------------------------------------------

def project_business_rules(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Write ``rules/blueprint-rules.json`` — the Blueprint's condition-action
    rules, in the row shape the runtime's ``loadRules`` reads.

    Only rules the panel authored reached the runtime before; a rule the
    agent wrote had a statement and no effect on any form. This projects
    the ones that declare effects, beside the panel's, in the same shape
    (rule_type, model_name, config.whenFeel/then/otherwise/scope/salience),
    so the form-rules route serves them together. Always written, so an
    empty file and a never-run projection stay distinguishable.
    """
    entities = {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or []}
    rows = []
    for rule in doc.get("businessRules") or []:
        if not isinstance(rule, dict) or rule.get("status") == "DEPRECATED":
            continue
        if rule.get("kind") != "condition_action" or not rule.get("entity"):
            continue
        ent = entities.get(str(rule["entity"])) or {}
        model = ent.get("name") or str(rule["entity"])
        rows.append({
            "id": rule.get("id"), "name": rule.get("name") or rule.get("id"),
            "rule_type": "condition_action", "model_name": model,
            "field_name": None, "is_active": True, "source": "blueprint",
            "config": {
                "whenFeel": rule.get("when") or rule.get("expression") or "true",
                "then": [{"id": f"{rule.get('id')}-then-{i}", **a} for i, a in enumerate(rule.get("then") or [])],
                "otherwise": [{"id": f"{rule.get('id')}-else-{i}", **a} for i, a in enumerate(rule.get("otherwise") or [])],
                "scope": rule.get("scope") or "form",
                "salience": int(rule.get("salience") or 0),
            },
        })
    out = Path(app_root) / "rules"
    out.mkdir(parents=True, exist_ok=True)
    (out / "blueprint-rules.json").write_text(json.dumps(rows, indent=2), "utf-8")
    return {"files": ["rules/blueprint-rules.json"], "rules": len(rows)}

