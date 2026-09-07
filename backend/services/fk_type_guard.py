"""fk_type_guard — make every foreign-key column's SQL type match the primary
key it references.

The schema agent sometimes emits an FK column as ``integer("landlord_id")`` while
the referenced table's PK is ``uuid("id")`` (or the reverse). Drizzle then cannot
create the constraint — Postgres rejects it with *"key columns are of incompatible
types: integer and uuid"* — the migration half-applies, and seeding inserts 0 rows
into every table that has such an FK.

This deterministic pass parses ``src/db/schema/*.ts``, builds a registry of each
table's PK type, resolves every FK (both the ``foreignKey({columns, foreignColumns})``
block form and the inline ``.references(() => t.id)`` form), and rewrites any FK
column whose type doesn't match its target PK — fixing the ``drizzle-orm/pg-core``
imports to match. Idempotent: a schema that's already consistent is left untouched.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Drizzle column-type helpers we understand. Anything else is left alone.
_COL_TYPES = ("uuid", "bigserial", "serial", "bigint", "integer", "varchar", "text", "char")

# What SQL type an FK column must be to reference a PK of the given type. A PK
# declared serial/bigserial is stored as int/bigint, and an FK to it is a plain
# (non-auto-incrementing) integer/bigint.
_PK_TO_FK = {
    "uuid": "uuid",
    "serial": "integer",
    "bigserial": "bigint",
    "integer": "integer",
    "bigint": "bigint",
    "text": "text",
    "varchar": "varchar",
    "char": "varchar",
}

_IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*["\']drizzle-orm/pg-core["\'];?'
)
# `import { landlords } from "./landlord";` — one or more names.
_TABLE_IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*["\']\.\/[\w./-]+["\'];?'
)
_EXPORT_RE = re.compile(r'export\s+const\s+(\w+)\s*=\s*pgTable\(')
# A column definition: `propName: type("col_name"...`  (type is a known helper).
_COL_RE = re.compile(r'(\w+)\s*:\s*(' + "|".join(_COL_TYPES) + r')\s*\(')
# PK: a column line carrying .primaryKey()
_PK_LINE_RE = re.compile(
    r'(\w+)\s*:\s*(' + "|".join(_COL_TYPES) + r')\s*\([^\n]*\.primaryKey\(\)'
)
# foreignKey({ columns: [t.localCol], foreignColumns: [Foreign.id] })  — order-independent.
_FK_LOCAL_RE = re.compile(r'columns\s*:\s*\[\s*\w+\.(\w+)\s*\]')
_FK_FOREIGN_RE = re.compile(r'foreignColumns\s*:\s*\[\s*(\w+)\.(\w+)\s*\]')
# Inline: `localCol: type("...")....references(() => Foreign.id)`
_REF_RE = re.compile(
    r'(\w+)\s*:\s*(?:' + "|".join(_COL_TYPES) +
    r')\s*\([^\n]*?\.references\(\s*\(\)\s*=>\s*(\w+)\.(\w+)'
)


def pk_type_to_fk_type(pk_type: str) -> str:
    """The column type an FK must use to reference a PK of ``pk_type``."""
    return _PK_TO_FK.get(pk_type, pk_type)


def _parse_file(text: str) -> dict[str, Any]:
    """Extract tables, their PK types, columns, FK edges and imports from one file."""
    exports = _EXPORT_RE.findall(text)  # table export names defined here
    columns: dict[str, str] = {}
    for prop, typ in _COL_RE.findall(text):
        columns.setdefault(prop, typ)

    pk_prop = pk_type = None
    m = _PK_LINE_RE.search(text)
    if m:
        pk_prop, pk_type = m.group(1), m.group(2)

    # FK edges: (local_prop, foreign_export, foreign_prop)
    fks: list[tuple[str, str, str]] = []
    # Inline .references()
    for local, fexport, fprop in _REF_RE.findall(text):
        fks.append((local, fexport, fprop))
    # Block foreignKey({...}) — pair each foreignColumns with the nearest columns.
    for block in re.findall(r'foreignKey\(\s*\{(.*?)\}\s*\)', text, re.DOTALL):
        lm = _FK_LOCAL_RE.search(block)
        fm = _FK_FOREIGN_RE.search(block)
        if lm and fm:
            fks.append((lm.group(1), fm.group(1), fm.group(2)))

    return {
        "exports": exports,
        "columns": columns,
        "pk_prop": pk_prop,
        "pk_type": pk_type,
        "fks": fks,
    }


def _ensure_import(text: str, name: str) -> str:
    """Ensure ``name`` is imported from drizzle-orm/pg-core in this file."""
    m = _IMPORT_RE.search(text)
    if not m:
        return text  # unusual — leave it; tsc will surface the missing import
    names = [n.strip() for n in m.group(1).split(",") if n.strip()]
    if name in names:
        return text
    names.append(name)
    new_import = "import {\n  " + ",\n  ".join(sorted(set(names))) + ",\n} from \"drizzle-orm/pg-core\";"
    return text[: m.start()] + new_import + text[m.end():]


def _prune_import(text: str, name: str) -> str:
    """Drop ``name`` from the pg-core import if it's no longer used as a helper."""
    # Used as a column helper anywhere else? `name(` still present outside imports.
    body = _IMPORT_RE.sub("", text)
    if re.search(r'\b' + re.escape(name) + r'\s*\(', body):
        return text  # still used — keep the import
    m = _IMPORT_RE.search(text)
    if not m:
        return text
    names = [n.strip() for n in m.group(1).split(",") if n.strip() and n.strip() != name]
    new_import = "import {\n  " + ",\n  ".join(sorted(set(names))) + ",\n} from \"drizzle-orm/pg-core\";"
    return text[: m.start()] + new_import + text[m.end():]


def _rewrite_column_type(text: str, prop: str, new_type: str) -> tuple[str, str | None]:
    """Rewrite the FK column ``prop``'s type helper to ``new_type``.

    Returns (new_text, old_type) — old_type is None if nothing changed."""
    pat = re.compile(r'(\b' + re.escape(prop) + r'\s*:\s*)(' + "|".join(_COL_TYPES) + r')(\s*\()')
    old: list[str] = []

    def _sub(m: re.Match) -> str:
        if m.group(2) == new_type:
            return m.group(0)
        old.append(m.group(2))
        return m.group(1) + new_type + m.group(3)

    new_text = pat.sub(_sub, text, count=1)
    return new_text, (old[0] if old else None)


def guard_fk_types(output_dir: str | Path) -> dict[str, Any]:
    """Fix every FK column whose type doesn't match its referenced PK.

    Returns {checked, fixed, changes:[{file, column, from, to, references}]}."""
    base = Path(output_dir)
    schema_dir = base / "src" / "db" / "schema"
    if not schema_dir.exists():
        return {"checked": 0, "fixed": 0, "changes": []}

    files = {p: p.read_text(encoding="utf-8") for p in sorted(schema_dir.glob("*.ts"))
             if p.name not in ("index.ts", "relations.ts")}

    parsed = {p: _parse_file(t) for p, t in files.items()}

    # Registry: table export name → its PK type (across all files).
    pk_by_export: dict[str, str] = {}
    for info in parsed.values():
        if info["pk_type"]:
            for exp in info["exports"]:
                pk_by_export[exp] = info["pk_type"]

    changes: list[dict] = []
    checked = 0
    for path, info in parsed.items():
        text = files[path]
        dirty = False
        for local_prop, foreign_export, _foreign_prop in info["fks"]:
            target_pk = pk_by_export.get(foreign_export)
            if not target_pk:
                continue  # references a table we couldn't resolve — skip
            checked += 1
            want = pk_type_to_fk_type(target_pk)
            have = info["columns"].get(local_prop)
            if not have or have == want:
                continue
            new_text, old = _rewrite_column_type(text, local_prop, want)
            if old is None:
                continue
            text = _ensure_import(new_text, want)
            text = _prune_import(text, old)
            info["columns"][local_prop] = want  # keep local view consistent
            dirty = True
            changes.append({
                "file": path.name, "column": local_prop,
                "from": old, "to": want, "references": foreign_export,
            })
        if dirty:
            path.write_text(text, encoding="utf-8")

    return {"checked": checked, "fixed": len(changes), "changes": changes}
