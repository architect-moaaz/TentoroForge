"""
Post-hoc extractors that parse generated code and populate the contract
registry with what was *actually* produced by each agent.

These run AFTER an agent completes, scanning the output directory for
TypeScript / TSX files and extracting structural information via regex.
No TypeScript compiler or external dependencies required.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Entity extraction from Drizzle ORM schema files
# ---------------------------------------------------------------------------

# Matches the start of a pgTable call up to the opening brace of the columns
# object.  We then manually balance braces to extract the full column block
# (which may contain nested braces like { length: 255 }).
_TABLE_START_RE = re.compile(
    r'export\s+const\s+(\w+)\s*=\s*pgTable\s*\(\s*["\'](\w+)["\']\s*,\s*\{',
)

# Matches a column definition line.  We capture the field name, column type
# function, and everything else on the line (the "tail") so we can inspect
# chained method calls like .primaryKey().notNull().
_COLUMN_RE = re.compile(
    r'^\s*(\w+)\s*:\s*(\w+)\s*\(\s*["\'](\w+)["\'](.*)$',
    re.MULTILINE,
)

# Start of a column definition (name: drizzleType(...). Used to parse each
# column's FULL definition, which may span multiple lines (the `.notNull()` /
# `.references()` chain is often wrapped). The old per-line regex only saw the
# first line, so a multi-line `guestId` lost its `.notNull()` → wrong nullable.
_COLUMN_START_RE = re.compile(r'(\w+)\s*:\s*(\w+)\s*\(')


def _iter_columns(block: str):
    """Yield (field_name, type_fn, full_chain) for each column in a Drizzle columns
    block, splitting on TOP-LEVEL commas so a definition that wraps across lines is
    captured whole (modifier detection then scans the entire chain)."""
    segments: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in block:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        segments.append("".join(buf))
    for seg in segments:
        m = _COLUMN_START_RE.search(seg)
        if not m:
            continue
        yield m.group(1), m.group(2), seg

# Drizzle column type to simplified type mapping
_DRIZZLE_TYPES = {
    "serial": "serial",
    "bigserial": "bigserial",
    "integer": "integer",
    "bigint": "bigint",
    "smallint": "smallint",
    "varchar": "varchar",
    "text": "text",
    "boolean": "boolean",
    "timestamp": "timestamp",
    "date": "date",
    "time": "time",
    "json": "json",
    "jsonb": "jsonb",
    "uuid": "uuid",
    "numeric": "numeric",
    "decimal": "decimal",
    "real": "real",
    "doublePrecision": "doublePrecision",
}


def _pascal_case(name: str) -> str:
    """Convert a snake_case or plain table name to PascalCase for the entity key."""
    return "".join(word.capitalize() for word in re.split(r"[_\s]+", name))


def _extract_brace_block(text: str, start: int) -> str:
    """Extract content between balanced braces starting at position *start*.

    *start* should point to the character right after the opening ``{``.
    Returns the content between the outermost ``{`` and its matching ``}``.
    """
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch in ('"', "'", "`"):
            # Skip string literals to avoid counting braces inside them
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\" and i + 1 < len(text):
                    i += 1  # skip escaped char
                i += 1
        i += 1
    return text[start:i - 1]


def extract_entities_from_schema(output_dir: str) -> dict:
    """Scan Drizzle ORM schema files and return entities in registry format.

    Looks at ``{output_dir}/src/db/schema/*.ts``.
    Returns an empty dict if the directory does not exist.
    """
    schema_dir = Path(output_dir) / "src" / "db" / "schema"
    if not schema_dir.is_dir():
        log.debug("Schema directory not found: %s", schema_dir)
        return {}

    entities: dict = {}

    for ts_file in sorted(schema_dir.glob("*.ts")):
        content = ts_file.read_text(encoding="utf-8", errors="replace")
        log.debug("Scanning schema file: %s", ts_file)

        for match in _TABLE_START_RE.finditer(content):
            var_name = match.group(1)
            table_name = match.group(2)
            # Balance braces to extract the full columns object
            columns_block = _extract_brace_block(content, match.end())

            entity_key = _pascal_case(table_name)
            fields: dict = {}

            for field_name, col_type_fn, chain in _iter_columns(columns_block):
                # `chain` is the column's FULL (possibly multi-line) definition, so
                # modifiers on wrapped lines (.notNull()/.references()) are seen.
                col_type = _DRIZZLE_TYPES.get(col_type_fn, col_type_fn)

                is_pk = ".primaryKey()" in chain
                is_not_null = ".notNull()" in chain
                is_unique = ".unique()" in chain
                # Any Drizzle default: .default(), .defaultNow(), .defaultRandom(),
                # .$defaultFn(), .$default(). A column with a default is NOT required
                # on a create form even when NOT NULL (the DB fills it in).
                has_default = bool(re.search(r"\.\$?default", chain))

                field_info: dict = {
                    "type": col_type,
                    "primaryKey": is_pk,
                    "nullable": not (is_not_null or is_pk),
                }
                if is_unique:
                    field_info["unique"] = True
                if has_default:
                    field_info["hasDefault"] = True

                # Extract enum/union type hints from .$type<"a" | "b">()
                type_hint = re.search(r'\.\$type<([^>]+)>', chain)
                if type_hint:
                    raw = type_hint.group(1)
                    values = [v.strip().strip("\"'") for v in raw.split("|")]
                    field_info["enum_values"] = values

                fields[field_name] = field_info

            if fields:
                entities[entity_key] = {"fields": fields, "indexes": []}
                log.debug(
                    "Extracted entity %s (%s) with %d fields from %s",
                    entity_key, table_name, len(fields), ts_file.name,
                )

    log.info("Extracted %d entities from schema files in %s", len(entities), schema_dir)
    return entities


# ---------------------------------------------------------------------------
# 2. Route extraction from Next.js API route files
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Matches: export async function GET(  or  export function POST(
# Also matches: export const GET =
_EXPORT_METHOD_RE = re.compile(
    r'export\s+(?:async\s+)?(?:function\s+|const\s+)(' + "|".join(_HTTP_METHODS) + r')\b'
)


def _route_path_from_filepath(file_path: Path, output_dir: Path) -> str:
    """Derive the API route string from a route.ts file path.

    Example: src/app/api/orders/[id]/route.ts -> /api/orders/[id]
    """
    rel = file_path.relative_to(output_dir)
    # Remove the trailing route.ts
    parts = list(rel.parts)
    if parts and parts[-1] == "route.ts":
        parts = parts[:-1]
    # Remove leading 'src/app' if present
    if len(parts) >= 2 and parts[0] == "src" and parts[1] == "app":
        parts = parts[2:]
    return "/" + "/".join(parts) if parts else "/"


def _entity_from_route(route_path: str) -> str:
    """Infer entity name from the first path segment after /api/.

    /api/orders/[id] -> orders
    /api/users -> users
    """
    segments = [s for s in route_path.split("/") if s]
    if len(segments) >= 2 and segments[0] == "api":
        return segments[1]
    return segments[-1] if segments else "unknown"


def extract_routes_from_files(output_dir: str) -> dict:
    """Scan Next.js API route files and return routes in registry format.

    Looks at ``{output_dir}/src/app/api/**/route.ts``.
    """
    api_dir = Path(output_dir) / "src" / "app" / "api"
    if not api_dir.is_dir():
        log.debug("API directory not found: %s", api_dir)
        return {}

    routes: dict = {}
    out = Path(output_dir)

    for route_file in sorted(api_dir.rglob("route.ts")):
        content = route_file.read_text(encoding="utf-8", errors="replace")
        route_path = _route_path_from_filepath(route_file, out)
        entity = _entity_from_route(route_path)

        methods_found = set(_EXPORT_METHOD_RE.findall(content))
        log.debug("Route file %s -> %s, methods: %s", route_file, route_path, methods_found)

        for method in sorted(methods_found):
            key = f"{method} {route_path}"
            routes[key] = {
                "entity": entity,
                "request_fields": [],
                "response_entity": entity,
            }

    log.info("Extracted %d API routes from %s", len(routes), api_dir)
    return routes


# ---------------------------------------------------------------------------
# 3. Component extraction from TSX files
# ---------------------------------------------------------------------------

# Matches: export function ComponentName  /  export default function ComponentName
#          export const ComponentName
_COMPONENT_NAME_RE = re.compile(
    r'export\s+(?:default\s+)?(?:function|const)\s+([A-Z]\w*)'
)

# Matches fetch("/api/...", or fetch(`/api/...`
_FETCH_CALL_RE = re.compile(
    r'fetch\s*\(\s*[`"\']([^`"\']+)[`"\']'
)

# Matches imported api-client helpers: import { getOrders, createUser } from
_API_CLIENT_IMPORT_RE = re.compile(
    r'import\s*\{([^}]+)\}\s*from\s*["\'](?:@/|\.\.?/)(?:lib|utils|services)/api[^"\']*["\']'
)

# Also match direct named imports from api paths
_API_FUNC_RE = re.compile(
    r'\b(get|create|update|delete|fetch|post|put|patch|remove|list|search)\w*'
    r'\s*\(',
    re.IGNORECASE,
)


def _extract_api_calls(content: str) -> list[str]:
    """Extract API call references from component/page source."""
    calls: list[str] = []

    # Fetch calls
    for m in _FETCH_CALL_RE.finditer(content):
        calls.append(m.group(1))

    # Imported API helpers
    for m in _API_CLIENT_IMPORT_RE.finditer(content):
        imports = [name.strip() for name in m.group(1).split(",") if name.strip()]
        calls.extend(imports)

    return sorted(set(calls))


def extract_components_from_files(output_dir: str) -> dict:
    """Scan TSX component files and return components in registry format.

    Looks at ``{output_dir}/src/components/**/*.tsx``.
    """
    comp_dir = Path(output_dir) / "src" / "components"
    if not comp_dir.is_dir():
        log.debug("Components directory not found: %s", comp_dir)
        return {}

    components: dict = {}
    out = Path(output_dir)

    for tsx_file in sorted(comp_dir.rglob("*.tsx")):
        content = tsx_file.read_text(encoding="utf-8", errors="replace")
        rel_path = str(tsx_file.relative_to(out))

        names = _COMPONENT_NAME_RE.findall(content)
        if not names:
            log.debug("No exported component found in %s", tsx_file)
            continue

        api_calls = _extract_api_calls(content)

        for name in names:
            components[name] = {
                "file": rel_path,
                "props": {},
                "api_calls": api_calls,
                "field_refs": [],
            }
            log.debug("Extracted component %s from %s", name, rel_path)

    log.info("Extracted %d components from %s", len(components), comp_dir)
    return components


# ---------------------------------------------------------------------------
# 4. Page extraction from Next.js page files
# ---------------------------------------------------------------------------

# Matches: import { Foo, Bar } from "@/components/..."
_COMPONENT_IMPORT_RE = re.compile(
    r'import\s*\{([^}]+)\}\s*from\s*["\']@/components/[^"\']*["\']'
)

# Matches: import Foo from "@/components/..."
_DEFAULT_COMPONENT_IMPORT_RE = re.compile(
    r'import\s+([A-Z]\w*)\s+from\s*["\']@/components/[^"\']*["\']'
)


def _route_from_page_path(file_path: Path, output_dir: Path) -> str:
    """Derive the page route from a page.tsx file path.

    Example: src/app/orders/page.tsx -> /orders
             src/app/orders/[id]/page.tsx -> /orders/[id]
             src/app/page.tsx -> /
    """
    rel = file_path.relative_to(output_dir)
    parts = list(rel.parts)
    # Remove page.tsx
    if parts and parts[-1] == "page.tsx":
        parts = parts[:-1]
    # Remove leading src/app
    if len(parts) >= 2 and parts[0] == "src" and parts[1] == "app":
        parts = parts[2:]
    return "/" + "/".join(parts) if parts else "/"


def extract_pages_from_files(output_dir: str) -> dict:
    """Scan Next.js page files and return pages in registry format.

    Looks at ``{output_dir}/src/app/**/page.tsx``.
    """
    app_dir = Path(output_dir) / "src" / "app"
    if not app_dir.is_dir():
        log.debug("App directory not found: %s", app_dir)
        return {}

    pages: dict = {}
    out = Path(output_dir)

    for page_file in sorted(app_dir.rglob("page.tsx")):
        content = page_file.read_text(encoding="utf-8", errors="replace")
        route = _route_from_page_path(page_file, out)
        rel_path = str(page_file.relative_to(out))

        # Collect component imports
        imported_components: list[str] = []
        for m in _COMPONENT_IMPORT_RE.finditer(content):
            names = [n.strip() for n in m.group(1).split(",") if n.strip()]
            # Handle aliased imports: "Foo as Bar" -> take "Bar"
            names = [n.split(" as ")[-1].strip() for n in names]
            imported_components.extend(names)
        for m in _DEFAULT_COMPONENT_IMPORT_RE.finditer(content):
            imported_components.append(m.group(1))

        api_calls = _extract_api_calls(content)

        pages[route] = {
            "file": rel_path,
            "components": sorted(set(imported_components)),
            "api_calls": api_calls,
        }
        log.debug("Extracted page %s from %s with %d components", route, rel_path, len(imported_components))

    log.info("Extracted %d pages from %s", len(pages), app_dir)
    return pages


# ---------------------------------------------------------------------------
# 5. Page extraction from JSON schema files (page-driven layout)
# ---------------------------------------------------------------------------

def _api_calls_from_data_sources(data_sources: list) -> list[str]:
    """Derive synthetic API-call keys from a schema's dataSources list.

    Each data source like ``{"entity": "Note", "op": "list"}`` maps to a
    canonical key ``/api/notes`` so that registry cross-reference checks can
    match against the routes section.  The entity name is lower-cased and
    pluralised naively (append 's' if not already ending in 's').
    """
    calls: list[str] = []
    for ds in data_sources:
        entity = ds.get("entity", "")
        if not entity:
            continue
        slug = entity.lower()
        if not slug.endswith("s"):
            slug += "s"
        calls.append(f"/api/{slug}")
    return sorted(set(calls))


def extract_schema_pages_from_json(output_dir: str) -> dict:
    """Scan JSON schema files and return pages in registry format.

    Looks at ``{output_dir}/src/schemas/**/*.json``.  Both the flat layout
    (``schemas/notes.json``) and the legacy entity-trio layout
    (``schemas/notes/list.json``) are handled via ``rglob``.

    The registry key for each page is:

    1. The schema's own ``route`` field if present (e.g. ``/notes``).
    2. Otherwise ``"/" + rel`` where *rel* is the path stem relative to
       ``schemas_dir`` (e.g. ``notes/list`` → ``/notes/list``).

    Auto-generated helper files (``registry.json``, ``load.json``) are
    skipped.
    """
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.is_dir():
        log.debug("Schemas directory not found: %s", schemas_dir)
        return {}

    pages: dict = {}
    out = Path(output_dir)

    for path in sorted(schemas_dir.rglob("*.json")):
        if path.name in ("registry.json", "load.json"):
            continue
        try:
            page = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError) as exc:
            log.debug("Skipping unreadable schema file %s: %s", path, exc)
            continue

        rel = path.relative_to(schemas_dir).with_suffix("")
        # `.as_posix()`: `route_key` is the registry's page key, matched by
        # every route-keyed consumer (route_tree, nav_guard, the singleton
        # reconciler). `str()` registered a schema without an explicit
        # `route` under `/notes\list`, which nothing can ever match.
        route_key = page.get("route") or ("/" + rel.as_posix())
        rel_path = str(path.relative_to(out))

        api_calls = _api_calls_from_data_sources(page.get("dataSources", []))

        pages[route_key] = {
            "file": rel_path,
            "components": [],   # not yet rendered; populated later by extract_pages_from_files
            "api_calls": api_calls,
        }
        log.debug(
            "Extracted JSON schema page %s from %s with %d data sources",
            route_key, rel_path, len(page.get("dataSources", [])),
        )

    log.info("Extracted %d pages from JSON schemas in %s", len(pages), schemas_dir)
    return pages
