"""Gen-time guard against a DUPLICATE `pgTable("X")` reaching the migration.

`drizzle.config` globs `./src/db/schema`, so EVERY `*.ts` there is picked up. If
two files both declare `pgTable("users", ...)` — e.g. the template's auth `user.ts`
(with a `password` column) and a plan-derived `users.ts` (no password) — drizzle
sees two definitions of the same table and the WRONG one can win the migration.
The observed failure: seed dies with `column "password" of relation "users" does
not exist` because the plan-derived, password-less table won.

This guard scans the schema dir, finds any table name defined in MORE THAN ONE
file, keeps the canonical (auth/most-complete) definition, deletes the redundant
file(s), and cleans the matching `export ... from "./<stem>"` line out of the
barrel `index.ts`. It NEVER resolves silently — every duplicate found + the
resolution is logged loudly. A file that also defines a UNIQUE table is left
alone (recorded under `unresolved`) so we never delete real schema.
"""
from __future__ import annotations

import glob
import logging
import os
import re

logger = logging.getLogger(__name__)

# pgTable("name", ...   /  pgTable('name', ...  — captures the table name.
_PGTABLE_RE = re.compile(r"""pgTable\(\s*["']([^"']+)["']""")

# marker the template stamps on the auth-required table file.
_AUTH_MARKER = "required by auth.ts"

# a `password` column declared in the table body: `password: text("password")...`
_PASSWORD_COL_RE = re.compile(r"""\bpassword\s*:\s*\w+\(""")

# top-level column def inside a pgTable body: `name: builder(` .
_COLUMN_RE = re.compile(r"""(?m)^\s*['"]?\w+['"]?\s*:\s*\w+\(""")


def _tables_in(text: str) -> list[str]:
    """Every table name declared via pgTable(...) in a file (usually 1)."""
    return _PGTABLE_RE.findall(text)


def _column_count(text: str) -> int:
    """Approximate the number of columns declared across the file's tables.

    Counts `name: builder(` lines, which covers real column definitions and is a
    good tie-break proxy for "most complete". Good enough for a deterministic
    keeper choice; exactness is not required.
    """
    return len(_COLUMN_RE.findall(text))


def _pick_keeper(files: list[str], texts: dict[str, str]) -> str:
    """Deterministically choose the canonical file for a duplicated table.

    Priority: (1) auth marker, (2) declares a `password` column, (3) most
    columns, (4) lexicographically-first filename.
    """
    marked = [f for f in files if _AUTH_MARKER in texts[f]]
    if marked:
        return sorted(marked)[0]

    with_pw = [f for f in files if _PASSWORD_COL_RE.search(texts[f])]
    if with_pw:
        return sorted(with_pw)[0]

    # most columns wins; ties broken lexicographically (min filename).
    return max(files, key=lambda f: (_column_count(texts[f]), _neg_name(f)))


def _neg_name(path: str) -> tuple:
    """Sort key so that, among equal column counts, the lexicographically-first
    basename wins under max()."""
    # invert each char code so a SMALLER name yields a LARGER tuple under max().
    name = os.path.basename(path)
    return tuple(-ord(c) for c in name)


def _strip_barrel_exports(index_path: str, deleted_stems: set[str]) -> int:
    """Remove `export ... from "./<stem>"` lines referencing deleted files."""
    if not deleted_stems or not os.path.isfile(index_path):
        return 0
    try:
        with open(index_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return 0

    kept: list[str] = []
    removed = 0
    for line in lines:
        m = re.search(r"""from\s+["']\./([\w.\-/]+)["']""", line)
        stem = None
        if m:
            stem = m.group(1)
            # normalise a possible `.ts`/`.js` suffix on the specifier.
            stem = re.sub(r"\.(ts|js|tsx|jsx)$", "", stem)
        if stem is not None and stem in deleted_stems and re.match(r"\s*export\b", line):
            removed += 1
            continue
        kept.append(line)

    if removed:
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
    return removed


def dedup_schema_tables(output_dir: str) -> dict:
    """Delete redundant files that duplicate a `pgTable("X")` declaration.

    Returns {duplicates, kept, removed, unresolved}. Loud logging on every
    duplicate found + resolved — this must never be silent.
    """
    result: dict = {"duplicates": {}, "kept": {}, "removed": [], "unresolved": []}

    sdir = os.path.join(output_dir, "src", "db", "schema")
    if not os.path.isdir(sdir):
        return result

    texts: dict[str, str] = {}
    tables_by_file: dict[str, list[str]] = {}
    for fp in sorted(glob.glob(os.path.join(sdir, "*.ts"))):
        if os.path.basename(fp) == "index.ts":
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        tables = _tables_in(text)
        if not tables:
            continue
        texts[fp] = text
        tables_by_file[fp] = tables

    # group files by each table name they declare.
    files_by_table: dict[str, list[str]] = {}
    for fp, tables in tables_by_file.items():
        for t in set(tables):
            files_by_table.setdefault(t, []).append(fp)

    deleted_stems: set[str] = set()
    for table, files in files_by_table.items():
        if len(files) < 2:
            continue
        files = sorted(files)
        result["duplicates"][table] = files
        keeper = _pick_keeper(files, texts)
        result["kept"][table] = keeper
        logger.warning(
            "schema_dedup_guard: DUPLICATE pgTable(%r) in %d files: %s — keeping %s",
            table, len(files), ", ".join(os.path.basename(f) for f in files),
            os.path.basename(keeper),
        )

        for fp in files:
            if fp == keeper:
                continue
            # only delete if this file's ONLY table(s) are all duplicates that
            # have a keeper elsewhere — never drop a file that defines a UNIQUE table.
            file_tables = set(tables_by_file[fp])
            other_unique = [
                t2 for t2 in file_tables
                if len(files_by_table.get(t2, [])) < 2
            ]
            if other_unique:
                logger.warning(
                    "schema_dedup_guard: NOT removing %s — it also defines unique table(s): %s",
                    os.path.basename(fp), ", ".join(sorted(other_unique)),
                )
                if fp not in result["unresolved"]:
                    result["unresolved"].append(fp)
                continue

            try:
                os.remove(fp)
            except OSError as e:  # noqa: BLE001
                logger.warning("schema_dedup_guard: could not remove %s: %s", fp, e)
                if fp not in result["unresolved"]:
                    result["unresolved"].append(fp)
                continue
            result["removed"].append(fp)
            deleted_stems.add(os.path.splitext(os.path.basename(fp))[0])
            logger.warning(
                "schema_dedup_guard: removed duplicate-table file %s (kept %s for table %r)",
                os.path.basename(fp), os.path.basename(keeper), table,
            )

    removed_exports = _strip_barrel_exports(os.path.join(sdir, "index.ts"), deleted_stems)
    if removed_exports:
        logger.warning(
            "schema_dedup_guard: stripped %d barrel export(s) for removed file(s) in %s",
            removed_exports, sdir,
        )

    return result
