"""Fix CHECK constraints written with a plain string instead of a `sql` template.

drizzle's `check(name, condition)` requires `condition` to be an SQL object built
with the `sql` tagged template. The LLM often writes it as a raw string:

    check("status_check", "status IN ('confirmed', 'cancelled')")   // WRONG

A plain string has no `.toQuery()`, so `drizzle-kit push` aborts the ENTIRE
migration with `TypeError: sql2.toQuery is not a function` during snapshot
generation — no tables get created, and seeding then fails on `relation "users"
does not exist`. One bad check silently breaks the whole database.

This guard rewrites the string condition into a `sql` template and ensures the
file imports `sql` from "drizzle-orm". Deterministic + idempotent; a condition
already written as sql`...` (backticks) is left untouched.
"""
from __future__ import annotations

import glob
import os
import re

# check( "name" , "CONDITION" )  — condition as a DOUBLE-quoted string (SQL
# conditions use single quotes internally, so the outer quotes are ~always double).
# Spans newlines. Groups: (1) `check("name",` prefix, (2) condition text, (3) `)`.
_CHECK_STR_RE = re.compile(
    r'(check\(\s*"[^"]*"\s*,\s*)"([^"]*)"(\s*\))',
    re.DOTALL,
)

_SQL_IMPORT = 'import { sql } from "drizzle-orm";\n'


def _has_sql_import(text: str) -> bool:
    # `import { sql } from "drizzle-orm"` or `import { sql, ... } from "drizzle-orm"`
    return bool(re.search(r'import\s*\{[^}]*\bsql\b[^}]*\}\s*from\s*["\']drizzle-orm["\']', text))


def _fix_file(text: str) -> tuple[str, int]:
    def repl(m: re.Match) -> str:
        cond = m.group(2)
        # Don't touch conditions that would break a backtick template.
        if "`" in cond or "${" in cond:
            return m.group(0)
        return f"{m.group(1)}sql`{cond}`{m.group(3)}"

    new, n = _CHECK_STR_RE.subn(repl, text)
    if n and not _has_sql_import(new):
        new = _SQL_IMPORT + new
    return new, n


def guard_check_constraints(output_dir: str) -> dict:
    """Rewrite string CHECK conditions to sql`` across schema files.
    Returns {fixed, files}."""
    sdir = os.path.join(output_dir, "src", "db", "schema")
    if not os.path.isdir(sdir):
        return {"fixed": 0, "files": 0}
    fixed = touched = 0
    for fp in glob.glob(os.path.join(sdir, "**", "*.ts"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        new, n = _fix_file(text)
        if n and new != text:
            with open(fp, "w", encoding="utf-8") as fh:
                fh.write(new)
            fixed += n
            touched += 1
    return {"fixed": fixed, "files": touched}
