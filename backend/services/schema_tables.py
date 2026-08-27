"""Single authority for WHERE the generated Drizzle schema lives and WHAT
tables it declares.

Two modules in the same pipeline used to answer "where is the schema?"
differently:

* ``crud_workflow_generator._parse_schema_columns`` read ``src/db/schema/**``
  recursively AND ``src/db/**``.
* ``workflow_table_guard._real_tables`` globbed ``src/db/schema/*.ts`` only —
  non-recursive, directory-only.

Both layouts are real: ``schema_barrel.py`` documents the single-file
``src/db/schema.ts`` layout, and ``seed_backstop.py`` reads it explicitly.
So on a single-file schema the table guard saw ZERO tables and then reported
every perfectly valid workflow table as an unresolved schema gap — register
finding TG-2. That is the same "two implementations of one lookup" shape as
the pluralizers; the fix is the same shape too. Read the schema through this
module or not at all.

Failure policy
--------------
:func:`real_tables` and :func:`schema_files` raise :class:`SchemaNotFoundError`
by default when the output dir declares no schema at all. A caller that
genuinely tolerates a schema-less tree must say so with ``required=False``
and handle the empty result — silence is not available. The whole point of
TG-2 is that "I found nothing" and "there is nothing" were indistinguishable.
"""
from __future__ import annotations

import re
from pathlib import Path

# pgTable("name", ...  /  pgTable('name', ...  — captures the real SQL table
# name (the string literal), not the JS variable it is assigned to.
_PGTABLE_RE = re.compile(r"""pgTable\(\s*["']([^"']+)["']""")


class SchemaNotFoundError(RuntimeError):
    """Raised when an output dir carries no Drizzle schema to read.

    Names every location that was searched, so the reader does not have to
    guess which of the two historical layouts was expected."""

    def __init__(self, output_dir: str | Path, searched: list[Path]) -> None:
        self.output_dir = str(output_dir)
        self.searched = searched
        locations = ", ".join(str(p) for p in searched) or "(none)"
        super().__init__(
            f"no Drizzle schema found under {output_dir!r}; searched: {locations}"
        )


def schema_roots(output_dir: str | Path) -> list[Path]:
    """The directories a schema may live in, most specific first.

    ``src/db/schema/`` is the multi-file layout; ``src/db/`` covers the
    single-file ``schema.ts`` layout and anything nested beneath it."""
    base = Path(output_dir)
    return [base / "src" / "db" / "schema", base / "src" / "db"]


def schema_files(output_dir: str | Path, *, required: bool = True) -> list[Path]:
    """Every ``.ts`` file that may declare tables, de-duplicated and ordered.

    Recursive under both roots, so all three real layouts are covered:
    ``src/db/schema/*.ts``, ``src/db/schema/sub/*.ts``, ``src/db/schema.ts``.

    Raises :class:`SchemaNotFoundError` when nothing is found and
    ``required`` is True (the default)."""
    roots = schema_roots(output_dir)
    seen: set[Path] = set()
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*.ts")):
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(f)
    if not files and required:
        raise SchemaNotFoundError(output_dir, roots)
    return files


def real_tables(output_dir: str | Path, *, required: bool = True) -> list[str]:
    """Every ``pgTable("X")`` name declared anywhere in the schema.

    De-duplicated, first-seen order preserved. Unreadable files raise
    rather than being skipped — a schema file that cannot be read is a
    broken tree, and swallowing it produces exactly the phantom
    "unresolved table" reports TG-2 is about.

    Raises :class:`SchemaNotFoundError` when the tree declares no schema
    files at all and ``required`` is True."""
    names: list[str] = []
    for fp in schema_files(output_dir, required=required):
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError as e:
            raise SchemaNotFoundError(output_dir, [fp]) from e
        names.extend(_PGTABLE_RE.findall(text))

    seen: set[str] = set()
    uniq: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq
