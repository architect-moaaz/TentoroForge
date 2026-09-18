"""The app SDK a coded page is written against, projected from the Blueprint.

A page the UI engineer writes as React (`pageCode`) may only say what the
application has: its entities' fields, its workflows' inputs, its pages'
routes. Those facts live in the Blueprint, so they are projected here as
TypeScript — and the compiler, not a heuristic validator, is what refuses a
page that names a field the entity lacks, a form that leaves a workflow input
out, or a link to a route that does not exist.

Three generated modules under ``src/sdk/``:

* ``schema.ts``    one interface per entity, with the columns exactly as the
                   data projection writes them (same reconciliation, same
                   builders), and which of them are numeric;
* ``workflows.ts`` one typed handle per workflow — its id, and its inputs as
                   an object type;
* ``pages.ts``     one typed handle per page and ``href`` to build a link.

``server.ts``, ``client.tsx`` and ``frame.tsx`` are the SDK's fixed half; they
ship with the scaffold (``templates/app-foundation/src/sdk``).

Deterministic and idempotent: the same Blueprint writes the same bytes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from services.blueprint.projection import (
    _TYPES, _DEFAULT_TYPE, _is_credential_field, _live, is_list_type,
    reconcile_platform_table,
)

SDK_DIR = "src/sdk"
HEADER = ("// Generated from the Living Blueprint — the app SDK a coded page is written\n"
          "// against. Edit the Blueprint, not this file.\n")

_RESERVED = frozenset({
    "break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete",
    "do", "else", "enum", "export", "extends", "false", "finally", "for", "function", "if",
    "import", "in", "instanceof", "new", "null", "return", "super", "switch", "this", "throw",
    "true", "try", "typeof", "var", "void", "while", "with", "yield", "let", "static",
    "implements", "interface", "package", "private", "protected", "public", "await",
})


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def pascal(text: str) -> str:
    out = "".join(w[:1].upper() + w[1:] for w in _words(text)) or "Item"
    return out if out[0].isalpha() else "T" + out


def camel(text: str) -> str:
    p = pascal(text)
    out = p[:1].lower() + p[1:]
    return out + "_" if out in _RESERVED else out


def _unique(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def _prop(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) else json.dumps(name)


def _literal_union(values: list[Any]) -> str:
    return " | ".join(json.dumps(str(v.get("value") if isinstance(v, dict) else v)) for v in values)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

def entity_columns(entity: dict, doc: dict) -> list[dict]:
    """The columns a page may read — the table's own, by the data projection's
    rules (platform reconciliation, the implicit uuid key, relationship FK
    columns), less any credential. A password hash is a column of `users`;
    it is never something a screen shows, and the SDK returns only what is
    typed here, so leaving it out keeps it off the wire as well."""
    fields, _ = reconcile_platform_table(entity)
    fields = [dict(f) for f in fields if f.get("name") and not _is_credential_field(str(f["name"]))]
    if not any(f.get("primaryKey") for f in fields):
        fields.insert(0, {"name": "id", "type": "uuid", "primaryKey": True})
    names = {f["name"] for f in fields}
    for rel in (doc.get("data") or {}).get("relationships") or []:
        col = rel.get("fromField")
        if rel.get("from") == entity.get("id") and col and col not in names:
            fields.append({"name": col, "type": "uuid"})
            names.add(col)
    return fields


def ts_type(field: dict) -> str:
    """The value a row carries for this column, as the SDK hands it over:
    numbers as numbers (numeric columns are coerced), dates as ISO strings."""
    type_name = str(field.get("type") or "").lower()
    if is_list_type(type_name):
        return "string[]"
    enum = field.get("enumValues") or field.get("enum")
    if isinstance(enum, list) and enum:
        return _literal_union(enum)
    builder = _TYPES.get(type_name, _DEFAULT_TYPE)
    return {"integer": "number", "numeric": "number", "boolean": "boolean",
            "jsonb": "unknown"}.get(builder, "string")


def _numeric(field: dict) -> bool:
    type_name = str(field.get("type") or "").lower()
    return not is_list_type(type_name) and _TYPES.get(type_name, _DEFAULT_TYPE) in ("integer", "numeric")


def entity_type_names(doc: dict) -> dict[str, str]:
    """Entity id -> its TypeScript type name (also the SDK's entity key)."""
    ents = _live((doc.get("data") or {}).get("entities"))
    names = _unique(pascal(e.get("name") or e.get("id")) for e in ents)
    return {str(e.get("id")): n for e, n in zip(ents, names)}


def emit_schema(doc: dict) -> str:
    ents = _live((doc.get("data") or {}).get("entities"))
    types = entity_type_names(doc)
    out = [HEADER]
    entries, numeric = [], []
    for e in ents:
        name = types[str(e.get("id"))]
        desc = str(e.get("description") or "").strip().replace("*/", "")
        out.append(f"/** {e.get('name')}{' — ' + desc if desc else ''} */")
        out.append(f"export interface {name} {{")
        cols = entity_columns(e, doc)
        for f in cols:
            required = bool(f.get("required") or f.get("primaryKey"))
            note = str(f.get("description") or "").strip().replace("*/", "")
            if note:
                out.append(f"  /** {note[:160]} */")
            out.append(f"  {_prop(f['name'])}: {ts_type(f)}{'' if required else ' | null'};")
        out.append("}")
        out.append("")
        # The key the data engine resolves: the entity's own name.
        entries.append(f"  {json.dumps(str(e.get('name')))}: {name};")
        numeric.append(f"  {json.dumps(str(e.get('name')))}: "
                       f"{json.dumps([f['name'] for f in cols if _numeric(f)])},")
    out.append("/** Every entity, by the name the SDK's reads take. */")
    out.append("export interface Entities {")
    out.extend(entries or ["  [name: string]: never;"])
    out.append("}")
    out.append("")
    out.append("export type EntityName = keyof Entities & string;")
    out.append("")
    out.append("/** The numeric fields of an entity — what `total` and `series` can add up. */")
    out.append("export type NumericField<E extends EntityName> = {")
    out.append("  [K in keyof Entities[E]]-?: NonNullable<Entities[E][K]> extends number ? K : never;")
    out.append("}[keyof Entities[E]] & string;")
    out.append("")
    out.append("/** The columns the SDK returns for each entity — exactly the typed ones. */")
    out.append("export const READABLE_FIELDS: Record<string, readonly string[]> = {")
    for e in ents:
        out.append(f"  {json.dumps(str(e.get('name')))}: "
                   f"{json.dumps([f['name'] for f in entity_columns(e, doc)])},")
    out.append("};")
    out.append("")
    out.append("/** Columns the driver returns as strings that the SDK hands over as numbers. */")
    out.append("export const NUMERIC_FIELDS: Record<string, readonly string[]> = {")
    out.extend(numeric)
    out.append("};")
    out.append("")
    out.append("/** The display label of each entity's records. */")
    out.append("export const LABEL_FIELD: Record<string, string> = {")
    for e in ents:
        cols = [f["name"] for f in entity_columns(e, doc)]
        label = e.get("labelField") or next((c for c in ("name", "title", "fullName", "label")
                                             if c in cols), None) \
            or next((c for c in cols if c != "id"), "id")
        out.append(f"  {json.dumps(str(e.get('name')))}: {json.dumps(label)},")
    out.append("};")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

def _step_entities(doc: dict, wf: dict) -> list[dict]:
    ents = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    by_name = {str(e.get("name")): e for e in ents.values()}
    out = []
    for step in wf.get("steps") or []:
        ref = str(step.get("entity") or "")
        e = ents.get(ref) or by_name.get(ref)
        if e and e not in out:
            out.append(e)
    return out


def input_type(doc: dict, wf: dict, inp: dict) -> str:
    """A field input takes the type of the column it writes when a step's
    entity has one of that name (so an enum keeps its values); a record input
    is the record's id."""
    if inp.get("kind") == "record":
        return "string"
    name = str(inp.get("name") or "")
    for e in _step_entities(doc, wf):
        col = next((f for f in e.get("fields") or [] if f.get("name") == name), None)
        if col:
            return ts_type(col)
    return ts_type({"type": inp.get("type") or "string", "enumValues": inp.get("enumValues")})


def workflow_keys(doc: dict) -> dict[str, str]:
    wfs = _live(doc.get("workflows"))
    keys = _unique(camel(w.get("name") or w.get("id")) for w in wfs)
    return {str(w.get("id")): k for w, k in zip(wfs, keys)}


def emit_workflows(doc: dict) -> str:
    keys = workflow_keys(doc)
    out = [HEADER,
           "/** A workflow a page can run. `I` is its input — what a form must collect",
           " *  or a button must pass. The phantom `__input` field only carries the type. */",
           "export interface Workflow<I> {",
           "  id: string;",
           "  name: string;",
           "  readonly __input?: I;",
           "}",
           "",
           "function wf<I>(id: string, name: string): Workflow<I> {",
           "  return { id, name };",
           "}",
           ""]
    body = []
    for w in _live(doc.get("workflows")):
        wid = str(w.get("id"))
        props: list[str] = []
        for inp in w.get("inputs") or []:
            if not isinstance(inp, dict) or not inp.get("name"):
                continue
            opt = "" if inp.get("required", True) else "?"
            what = str(inp.get("description") or "").strip().replace("*/", "")
            if inp.get("kind") == "record":
                target = next((e for e in _live((doc.get("data") or {}).get("entities"))
                               if str(e.get("id")) == str(inp.get("entity"))
                               or str(e.get("name")) == str(inp.get("entity"))), None)
                what = (f"id of the {target.get('name')} record" if target else "a record id") \
                    + (f" — {what}" if what else "")
            if what:
                props.append(f"    /** {what[:160]} */")
            props.append(f"    {_prop(str(inp['name']))}{opt}: {input_type(doc, w, inp)};")
        purpose = str(w.get("purpose") or "").strip().replace("*/", "")
        typ = ("{\n" + "\n".join(props) + "\n  }") if props else "Record<string, never>"
        if purpose:
            body.append(f"  /** {w.get('name')} — {purpose[:200]} */")
        body.append(f"  {keys[wid]}: wf<{typ}>({json.dumps(wid)}, {json.dumps(str(w.get('name') or wid))}),")
    out.append("export const workflows = {")
    out.extend(body)
    out.append("} as const;")
    out.append("")
    out.append("export type WorkflowKey = keyof typeof workflows;")
    out.append("/** The input type of a workflow handle. */")
    out.append("export type InputOf<W> = W extends Workflow<infer I> ? I : never;")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_keys(doc: dict) -> dict[str, str]:
    pages = _live(doc.get("pages"))
    keys = _unique(camel(p.get("name") or p.get("route") or p.get("id")) for p in pages)
    return {str(p.get("id")): k for p, k in zip(pages, keys)}


def emit_pages(doc: dict) -> str:
    keys = page_keys(doc)
    out = [HEADER,
           "/** A page of this application. `R` is its route; `[param]` segments are",
           " *  what `href` must be given. */",
           "export interface PageRef<R extends string = string> {",
           "  id: string;",
           "  name: string;",
           "  route: R;",
           "}",
           "",
           "type Params<R extends string> = R extends `${string}[${infer P}]${infer Rest}`",
           "  ? { [K in P | keyof Params<Rest>]: string } : {};",
           "",
           "/** The URL of a page: `href(pages.caseDetail, { id: row.id })`. */",
           "export function href<R extends string>(",
           "  page: PageRef<R>,",
           "  ...args: keyof Params<R> extends never",
           "    ? [params?: Record<string, never>, query?: Record<string, string | undefined>]",
           "    : [params: Params<R>, query?: Record<string, string | undefined>]",
           "): string {",
           "  const [params, query] = args as [Record<string, string> | undefined, Record<string, string | undefined> | undefined];",
           "  const path = page.route.replace(/\\[([^\\]]+)\\]/g, (_, k: string) => encodeURIComponent(params?.[k] ?? \"\"));",
           "  const q = Object.entries(query ?? {}).filter(([, v]) => v !== undefined && v !== \"\");",
           "  return q.length ? `${path}?${new URLSearchParams(q as [string, string][]).toString()}` : path;",
           "}",
           "",
           "export const pages = {"]
    for p in _live(doc.get("pages")):
        purpose = str(p.get("purpose") or "").strip().replace("*/", "")
        if purpose:
            out.append(f"  /** {purpose[:160]} */")
        route = str(p.get("route") or "/")
        out.append(f"  {keys[str(p.get('id'))]}: {{ id: {json.dumps(str(p.get('id')))}, "
                   f"name: {json.dumps(str(p.get('name') or route))}, route: {json.dumps(route)} }} "
                   f"as PageRef<{json.dumps(route)}>,")
    out.append("} as const;")
    return "\n".join(out) + "\n"


def emit_index() -> str:
    return (HEADER + "// What a view may import: the types and handles, never the server reads.\n"
            'export * from "./schema";\n'
            'export * from "./workflows";\n'
            'export * from "./pages";\n')


def sdk_files(doc: dict) -> dict[str, str]:
    """``{relative path: content}`` of the generated SDK modules."""
    return {
        f"{SDK_DIR}/schema.ts": emit_schema(doc),
        f"{SDK_DIR}/workflows.ts": emit_workflows(doc),
        f"{SDK_DIR}/pages.ts": emit_pages(doc),
        f"{SDK_DIR}/index.ts": emit_index(),
    }


def project_app_sdk(doc: dict, app_root: str | Path) -> list[str]:
    """Write the generated SDK modules; returns the paths written."""
    root = Path(app_root)
    written = []
    for rel, content in sdk_files(doc).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
        written.append(rel)
    return written


def sdk_reference(doc: dict) -> str:
    """The generated modules as one block — what the UI engineer reads."""
    return "\n".join(f"// ---- @/sdk/{Path(rel).stem} ----\n{content}"
                     for rel, content in sdk_files(doc).items() if not rel.endswith("index.ts"))


# ---------------------------------------------------------------------------
# Coded pages
# ---------------------------------------------------------------------------

CODE_PAGE_MARKER = "// forge:code-page"


def code_page_dir(page: dict) -> str:
    """Where a coded page lives, relative to the app root — where the page's
    route file would live anyway. A public page sits outside `(dashboard)`,
    as `project_public_routes` puts it (that group's layout redirects anyone
    signed out); every other page inside it, in the application's shell and
    behind its session gate. A static segment outranks the scaffold's dynamic
    routes either way."""
    from services.blueprint.projection import public_route_segments

    public = public_route_segments(page)
    if public:
        return "src/app/" + "/".join(public)
    route = str(page.get("route") or "/").strip("/")
    return "src/app/(dashboard)" + (f"/{route}" if route else "")


def _entities_read(doc: dict, code: str) -> list[str]:
    names = [str(e.get("name")) for e in _live((doc.get("data") or {}).get("entities"))]
    return [n for n in names if re.search(r"[\"'`]" + re.escape(n) + r"[\"'`]", code)]


def page_module(doc: dict, page: dict, row: dict) -> str:
    """The route's `page.tsx`: fixed, so every coded page gets the same frame,
    the same context and the same 404 — and `View`'s props are, by
    construction, what `load` returned."""
    from services.blueprint.projection import public_route_segments

    entities = _entities_read(doc, str(row.get("load") or ""))
    public = public_route_segments(page) is not None
    # A public page renders as the public route file it replaces does — in
    # the public frame, with no rail into a product the visitor cannot reach.
    frame_open = "<PublicPageFrame><PageFrame" if public else "<PageFrame"
    frame_close = "</PageFrame></PublicPageFrame>" if public else "</PageFrame>"
    frame_import = ('import { PublicPageFrame } from "@/components/PublicPageFrame";\n'
                    if public else "")
    return (
        f"{CODE_PAGE_MARKER} {page.get('id')}\n"
        f"// {page.get('name')} — generated from the Living Blueprint (pageCode). Edit the\n"
        "// Blueprint, not this file.\n"
        'import { notFound } from "next/navigation";\n'
        'import { currentUser, type PageContext } from "@/sdk/server";\n'
        'import { PageFrame } from "@/sdk/frame";\n'
        + frame_import +
        'import { load } from "./load";\n'
        'import View from "./view";\n'
        "\n"
        'export const dynamic = "force-dynamic";\n'
        "\n"
        "type Search = Record<string, string | string[] | undefined>;\n"
        "\n"
        "export default async function Page(props: { params: Promise<Record<string, string>>; searchParams: Promise<Search> }) {\n"
        "  const params = await props.params;\n"
        "  const search = await props.searchParams;\n"
        "  const ctx: PageContext = {\n"
        "    params: params ?? {},\n"
        "    searchParams: Object.fromEntries(Object.entries(search ?? {}).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v])),\n"
        "    user: await currentUser(),\n"
        "  };\n"
        "  const data = await load(ctx);\n"
        "  if (data === null) notFound();\n"
        "  return (\n"
        f"    {frame_open} entities={{{json.dumps(entities)}}}>\n"
        "      <View {...data} />\n"
        f"    {frame_close}\n"
        "  );\n"
        "}\n"
    )


def code_page_files(doc: dict, row: dict) -> dict[str, str]:
    """``{relative path: content}`` for one `pageCode` row."""
    page = next((p for p in _live(doc.get("pages")) if str(p.get("id")) == str(row.get("page"))), None)
    if page is None:
        return {}
    base = code_page_dir(page)
    return {
        f"{base}/page.tsx": page_module(doc, page, row),
        f"{base}/load.ts": str(row.get("load") or ""),
        f"{base}/view.tsx": str(row.get("view") or ""),
    }


def project_code_pages(doc: dict, app_root: str | Path) -> list[str]:
    """Write every coded page, and remove the ones the Blueprint no longer has
    (found by their marker, so a hand-shipped route is never touched)."""
    root = Path(app_root)
    written: list[str] = []
    for row in _live(doc.get("pageCode")):
        for rel, content in code_page_files(doc, row).items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text() != content:
                path.write_text(content)
            written.append(rel)
    keep = {str(Path(r).parent) for r in written}
    app = root / "src/app"
    if app.is_dir():
        for page_file in sorted(app.rglob("page.tsx")):
            rel_dir = str(page_file.parent.relative_to(root))
            if rel_dir in keep:
                continue
            try:
                head = page_file.read_text()[:64]
            except OSError:
                continue
            if head.startswith(CODE_PAGE_MARKER):
                for name in ("page.tsx", "load.ts", "view.tsx"):
                    (page_file.parent / name).unlink(missing_ok=True)
                parent = page_file.parent
                while parent != app and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
    return written


__all__ = ["project_app_sdk", "project_code_pages", "code_page_files", "code_page_dir",
           "sdk_files", "sdk_reference", "entity_type_names", "workflow_keys", "page_keys",
           "SDK_DIR", "CODE_PAGE_MARKER"]
