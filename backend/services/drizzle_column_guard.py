"""drizzle_column_guard — rewrite malformed ``sql`…`` column definitions into
real Drizzle column builders.

The schema agent sometimes emits a column as a raw SQL template with chained
builder methods, e.g.

    status: sql`varchar(50) default 'Confirmed'`.notNull(),

which throws at *import* time — ``sql`…`` returns an SQL fragment that has no
``.notNull()`` (or ``.default()`` / ``.unique()`` / …) method — so BOTH
``drizzle-kit push`` and the seed script crash before a single row is written.

This deterministic pass parses ``src/db/schema/*.ts``, finds every
``<prop>: sql`<sqltype> [default <val>]`<trailing>`` column and rewrites it to the
real builder — ``varchar("status", { length: 50 }).default("Confirmed").notNull()``
— adding the helper to the ``drizzle-orm/pg-core`` import. Idempotent; a SQL type
it doesn't understand is left untouched (tsc will surface it) rather than guessed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from services.fk_type_guard import _ensure_import

# `<prop>: sql`<body>`<.method()...>` — trailing is any chain of builder calls.
_SQL_COL_RE = re.compile(
    r'(?P<prop>\w+)\s*:\s*sql`(?P<body>[^`]*)`(?P<trailing>(?:\s*\.\s*\w+\s*\([^)]*\))*)'
)
# Leading SQL type in the body: one word (+ optional "precision"/"varying") and
# optional (args). Everything after is the "rest" (default clauses etc).
_BODY_RE = re.compile(
    r'^\s*(?P<type>[a-z_]+(?:\s+(?:precision|varying))?)\s*(?:\(\s*(?P<args>[^)]*)\))?\s*(?P<rest>.*)$',
    re.I | re.S,
)
_DEFAULT_RE = re.compile(
    r"""\bdefault\s+(?P<val>'[^']*'|"[^"]*"|[A-Za-z0-9_.\-]+(?:\([^)]*\))?)""",
    re.I,
)
_NOT_NULL_RE = re.compile(r'\bnot\s+null\b', re.I)


def _snake(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def _builder(sqltype: str, args: str, col: str) -> tuple[str, str] | None:
    """(helper_name, builder_expr) for a SQL type, or None if we don't handle it."""
    t = " ".join(sqltype.lower().split())
    a = (args or "").strip()
    if t in ("varchar", "character varying"):
        return "varchar", f'varchar("{col}", {{ length: {a or "255"} }})'
    if t in ("char", "bpchar", "character"):
        return "char", f'char("{col}", {{ length: {a or "1"} }})'
    if t == "text":
        return "text", f'text("{col}")'
    if t in ("integer", "int", "int4"):
        return "integer", f'integer("{col}")'
    if t in ("smallint", "int2"):
        return "smallint", f'smallint("{col}")'
    if t in ("bigint", "int8"):
        return "bigint", f'bigint("{col}", {{ mode: "number" }})'
    if t in ("boolean", "bool"):
        return "boolean", f'boolean("{col}")'
    if t in ("numeric", "decimal"):
        parts = [p.strip() for p in a.split(",") if p.strip()] if a else []
        if len(parts) == 2:
            return "numeric", f'numeric("{col}", {{ precision: {parts[0]}, scale: {parts[1]} }})'
        if len(parts) == 1:
            return "numeric", f'numeric("{col}", {{ precision: {parts[0]} }})'
        return "numeric", f'numeric("{col}")'
    if t in ("real", "float4"):
        return "real", f'real("{col}")'
    if t in ("double precision", "float8", "double"):
        return "doublePrecision", f'doublePrecision("{col}")'
    if t in ("timestamp", "timestamptz", "timestamp with time zone"):
        return "timestamp", f'timestamp("{col}")'
    if t == "date":
        return "date", f'date("{col}")'
    if t == "time":
        return "time", f'time("{col}")'
    if t == "uuid":
        return "uuid", f'uuid("{col}")'
    if t == "json":
        return "json", f'json("{col}")'
    if t == "jsonb":
        return "jsonb", f'jsonb("{col}")'
    return None


def _default_call(val: str) -> tuple[str, str | None]:
    """(.default(...) call, extra_import_or_None) for a raw SQL default literal."""
    v = val.strip()
    low = v.lower()
    if low in ("now()", "current_timestamp"):
        return ".defaultNow()", None
    if low in ("true", "false"):
        return f".default({low})", None
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        inner = v[1:-1].replace('"', '\\"')
        return f'.default("{inner}")', None
    if re.fullmatch(r'-?\d+(\.\d+)?', v):
        return f".default({v})", None
    # An expression / function call (gen_random_uuid(), etc.) — valid as sql arg.
    return f".default(sql`{v}`)", "sql"


def _convert(prop: str, body: str, trailing: str) -> tuple[str, str] | None:
    """Return (helper_name, full_replacement_text) or None to leave it unchanged."""
    bm = _BODY_RE.match(body or "")
    if not bm:
        return None
    built = _builder(bm.group("type"), bm.group("args") or "", _snake(prop))
    if built is None:
        return None
    helper, expr = built
    rest = bm.group("rest") or ""

    chain = expr
    dm = _DEFAULT_RE.search(rest)
    if dm:
        call, _extra = _default_call(dm.group("val"))
        chain += call
    trail = "".join((trailing or "").split())     # collapse whitespace/newlines
    if _NOT_NULL_RE.search(rest) and ".notNull(" not in trail:
        chain += ".notNull()"
    chain += trail                                 # preserve .notNull()/.unique()/…
    return helper, f"{prop}: {chain}"


def guard_drizzle_columns(output_dir: str | Path) -> dict[str, Any]:
    """Rewrite ``sql`…``-as-column definitions to real builders across the schema.

    Returns {fixed, changes:[{file, column, type}]}."""
    base = Path(output_dir)
    schema_dir = base / "src" / "db" / "schema"
    if not schema_dir.exists():
        return {"fixed": 0, "changes": []}

    changes: list[dict] = []
    for p in sorted(schema_dir.glob("*.ts")):
        if p.name in ("index.ts", "relations.ts"):
            continue
        text = p.read_text()
        helpers: set[str] = set()
        file_changes: list[dict] = []

        def _sub(m: re.Match) -> str:
            res = _convert(m.group("prop"), m.group("body"), m.group("trailing"))
            if res is None:
                return m.group(0)
            helper, replacement = res
            helpers.add(helper)
            file_changes.append({"file": p.name, "column": m.group("prop"), "type": helper})
            return replacement

        new_text = _SQL_COL_RE.sub(_sub, text)
        if new_text != text:
            for h in sorted(helpers):
                new_text = _ensure_import(new_text, h)
            p.write_text(new_text)
            changes.extend(file_changes)

    return {"fixed": len(changes), "changes": changes}
