"""“Can I get all this out as a spreadsheet?” — and “back it up somewhere”.

Two dead ends on the same phrasebook page as the import, and the same
sentence underneath both: the owner's data is theirs, and an application that
will not hand it back is one they cannot leave, cannot audit, cannot send to
their accountant and cannot sleep over.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
It is Smith producing the file on the turn they ask for it. They asked a
question in a conversation, so the answer is a file and a link to it, not the
promise of a button — a button is what `add_widgets` is for, and they did not
ask for one.

An export CHANGES NOTHING. Nothing is written to the application, nothing is
declared in the Blueprint, nothing is added to the change history, and there
is no undo for one. That asymmetry with `data_import` is the whole difference
between reading and writing, and it is why this file is a third of the size.

WHAT COMES OUT
--------------
The DECLARED fields, in the words the application declares them in — not
`SELECT *`. Three reasons, and none of them is taste:

* `SELECT *` carries `users.password`. §42 names exports, specifically, as a
  place sensitive values must not surface.
* raw columns are not what the owner sees on their screens, so the file would
  not be recognisable as their business.
* the declared field names are exactly what `data_import` reads, so what goes
  out is the shape that can come back.

The primary key goes first, so a row can be pointed at, and `data_import`
knows to leave that column alone when the file returns.

WHERE THE ROWS COME FROM
------------------------
The application's own database, read with psycopg2 over
`data_import.database_url` — one spelling of that URL for the import and the
export both. When no database is reachable this says so and names the
in-app URL instead. It never invents a file: an export of rows nobody read is
worse than no export, because it looks like an answer.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.data_import import (
    database_url, entities_of, table_of,
)
from services.smith.section_change import SectionChangeError, find_named

logger = logging.getLogger(__name__)

#: Where a produced file waits for the owner to click the link. In the
#: project, beside the import inbox, for the same reason: `output_dir` is the
#: one argument every caller of a Smith seam has.
EXPORTS = Path(".forge") / "exports"

#: Enough for any owner's first export and bounded, so one turn cannot read a
#: million rows into memory. A table past it exports the first `MAX_ROWS` and
#: SAYS SO — a truncated export that claims to be whole is a lie about their
#: business.
MAX_ROWS = 100_000

#: A produced name is ours, never theirs: it reaches a URL.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class ExportRefused(SectionChangeError):
    """The export cannot be produced, with the reason the owner can act on."""


# --------------------------------------------------------------------------- #
# what an export holds
# --------------------------------------------------------------------------- #

def exported_fields(entity: dict) -> list[dict]:
    """The columns an export carries: the key first, then every declared
    field that is not sensitive.

    A `sensitive` field is left out rather than masked. A masked column in a
    spreadsheet is a column of `****` that cannot be read, cannot be imported
    and cannot be explained — and the mask exists for the screen, where the
    row it belongs to is in front of somebody who has a reason to see it.
    """
    fields = [f for f in (entity.get("fields") or [])
              if isinstance(f, dict) and str(f.get("name") or "").strip()]
    key = [f for f in fields if f.get("primaryKey")]
    rest = [f for f in fields if not f.get("primaryKey") and not f.get("sensitive")]
    return key + rest


def withheld(entity: dict) -> list[str]:
    """Fields an export deliberately does not carry, by name. Said out loud:
    a file quietly missing a column is one somebody makes a decision on."""
    return [str(f.get("name")) for f in (entity.get("fields") or [])
            if isinstance(f, dict) and f.get("sensitive") and f.get("name")]


def _cell(value: Any) -> str:
    """One database value as a spreadsheet cell.

    Dates go out ISO, which is the one format `data_import` reads back, and
    the one that does not mean two different days in two countries.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value)
    return str(value)


def to_csv(columns: list[str], rows: list[dict]) -> str:
    """The sheet. Headers are written even for no rows — an empty file and an
    empty table are different things, and only one of them is a bug."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return out.getvalue()


# --------------------------------------------------------------------------- #
# reading the application's database
# --------------------------------------------------------------------------- #

def read_rows(url: str, table: str, columns: list[str],
              limit: int = MAX_ROWS) -> list[dict]:
    """`limit` rows of `table`, restricted to `columns`.

    The column list is built from the Blueprint's declared field names and
    every identifier is quoted, so nothing from the conversation reaches SQL.
    A column the database does not have is dropped by the caller, which asks
    the database what it has first — a spelling drift between the document and
    the schema must not fail the whole export.
    """
    import psycopg2
    from psycopg2 import sql as _sql

    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _sql.SQL("SELECT {cols} FROM {table} LIMIT %s").format(
                    cols=_sql.SQL(", ").join(_sql.Identifier(c) for c in columns),
                    table=_sql.Identifier(table)),
                (limit,))
            got = cur.fetchall()
    return [dict(zip(columns, row)) for row in got]


def existing_columns(url: str, table: str) -> set[str]:
    """What the table actually has. Asked, never assumed: a field renamed in
    the document and not yet pushed would otherwise fail the whole export
    with a Postgres error instead of exporting the other nine columns."""
    import psycopg2

    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s", (table,))
            return {str(r[0]) for r in cur.fetchall()}


# --------------------------------------------------------------------------- #
# producing the files
# --------------------------------------------------------------------------- #

def exports_dir(output_dir: str | Path) -> Path:
    d = Path(output_dir) / EXPORTS
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def one_sheet(doc: dict, url: str, entity: dict) -> dict:
    """One entity's rows as a sheet, plus what it left out and why."""
    table = table_of(entity)
    fields = exported_fields(entity)
    wanted = [str(f.get("name")) for f in fields]

    have = existing_columns(url, table)
    if not have:
        raise ExportRefused(
            f"The application's database has no {table} table yet — it is "
            f"created the first time the app starts. Start it once and ask me "
            f"again.")
    # SNAKE OR CAMEL, WHICHEVER THE SCHEMA USED. The document declares
    # `fullName`; drizzle may have created `full_name`. The mapping is
    # recorded so the sheet's headers stay the DECLARED names, which is what
    # makes the file importable.
    by_norm = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in have}
    use: list[tuple[str, str]] = []
    for name in wanted:
        actual = name if name in have else by_norm.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if actual:
            use.append((name, actual))
    if not use:
        raise ExportRefused(
            f"None of the declared fields of {entity.get('name')} exist as "
            f"columns on {table}, so there is nothing I could honestly put in "
            f"a sheet. The database is older than the definition — start the "
            f"app once so its tables catch up.")

    rows = read_rows(url, table, [a for _, a in use])
    renamed = [{declared: row.get(actual) for declared, actual in use} for row in rows]
    return {
        "entity": str(entity.get("name") or ""), "table": table,
        "columns": [d for d, _ in use], "rows": renamed,
        "csv": to_csv([d for d, _ in use], renamed),
        "withheld": withheld(entity),
        "missing": [n for n in wanted if n not in {d for d, _ in use}],
        "truncated": len(rows) >= MAX_ROWS,
    }


def write_sheet(output_dir: str | Path, sheet: dict) -> str:
    name = f"{sheet['table']}-{_stamp()}.csv"
    if not _SAFE_NAME.match(name):                      # a table name is ours, but
        name = f"export-{_stamp()}.csv"                 # never trust it into a URL
    (exports_dir(output_dir) / name).write_text(sheet["csv"], "utf-8")
    return name


def write_backup(output_dir: str | Path, sheets: list[dict], app: str) -> str:
    """Every sheet in one file. THAT is what "back it up somewhere" means —
    one thing to put somewhere, not eleven downloads."""
    slug = re.sub(r"[^a-z0-9]+", "-", (app or "app").lower()).strip("-") or "app"
    name = f"{slug}-backup-{_stamp()}.zip"
    path = exports_dir(output_dir) / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for sheet in sheets:
            zf.writestr(f"{sheet['table']}.csv", sheet["csv"])
    return name


def produced(output_dir: str | Path) -> list[dict]:
    """What has been produced, newest first — for the route that serves them."""
    d = Path(output_dir) / EXPORTS
    if not d.is_dir():
        return []
    out = [{"name": p.name, "bytes": p.stat().st_size,
            "producedAt": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            .isoformat(timespec="seconds")}
           for p in d.iterdir() if p.is_file() and _SAFE_NAME.match(p.name)]
    return sorted(out, key=lambda r: r["producedAt"], reverse=True)


def path_of(output_dir: str | Path, name: str) -> Path | None:
    """The file behind a name from the URL, or None.

    The name is matched against a produced file rather than joined onto a
    path: `../../.env` is a legal thing for a browser to ask for.
    """
    if not _SAFE_NAME.match(str(name or "")):
        return None
    path = Path(output_dir) / EXPORTS / name
    return path if path.is_file() else None


# --------------------------------------------------------------------------- #
# the turn
# --------------------------------------------------------------------------- #

def link_for(project_id: str, name: str) -> str:
    return f"/api/projects/{project_id}/exports/{name}"


def summary_of(out: dict) -> str:
    """What was produced, and what it does not contain."""
    lines: list[str] = []
    if out.get("backup"):
        lines.append(
            f"Backed up **{len(out['sheets'])}** kind(s) of record — "
            f"{sum(s['count'] for s in out['sheets'])} row(s) in total — into "
            f"[{out['file']}]({out['href']}).")
        lines += [f"- {s['entity']}: {s['count']} row(s)" for s in out["sheets"]]
    else:
        sheet = out["sheets"][0]
        lines.append(f"**{sheet['count']} {sheet['entity']}** record(s) are in "
                     f"[{out['file']}]({out['href']}).")
        if not sheet["count"]:
            lines.append("The table is empty, so the file has its column "
                         "headings and no rows — which is a file you can fill "
                         "in and load back with `import`.")
    withheld_all = sorted({w for s in out["sheets"] for w in s["withheld"]})
    if withheld_all:
        lines += ["", "Left out on purpose: " + ", ".join(f"`{w}`" for w in withheld_all)
                  + " — those hold sensitive values, and a spreadsheet is not "
                    "somewhere they should come to rest."]
    if any(s["truncated"] for s in out["sheets"]):
        lines += ["", f"Some tables hold more than {MAX_ROWS:,} rows and the "
                      f"file has the first {MAX_ROWS:,} of them. Ask me again "
                      f"for a narrower slice and I will say if I can."]
    if any(s["missing"] for s in out["sheets"]):
        missing = sorted({m for s in out["sheets"] for m in s["missing"]})
        lines += ["", "Not in the file because the database has no column for "
                      "them yet: " + ", ".join(f"`{m}`" for m in missing)
                  + ". They arrive when the app next starts."]
    lines += ["", "The columns are named exactly as the application declares "
                  "its fields, so this file is the shape `import` reads."]
    return "\n".join(lines)


def run(output_dir: str, entity: str = "", *, project_id: str = "",
        reasoning: Any = None) -> dict:
    """One export turn. Nothing about the application is changed.

    With an entity: that sheet. Without one: every entity, in one zip — which
    is what "back it up somewhere" is asking for.
    """
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there are no "
                          "records to get out."}

    live = entities_of(svc.doc)
    if not live:
        return {"applied": False, "edited_paths": [],
                "reason": "this application keeps no records yet, so there is "
                          "nothing to export."}

    wanted: list[dict]
    ref = str(entity or "").strip()
    if ref:
        found = find_named(live, ref)
        if found is None:
            known = ", ".join(str(e.get("name")) for e in live)
            return {"applied": False, "edited_paths": [],
                    "reason": f"I could not tell which records “{ref}” means. "
                              f"This application keeps: {known}. Name one of "
                              f"those, or say `back it up` and I will export "
                              f"all of them."}
        wanted = [found]
    else:
        wanted = live

    url = database_url(output_dir)
    if not url:
        routes = ", ".join(f"`/api/export/{table_of(e)}`" for e in wanted[:6])
        return {"applied": False, "edited_paths": [],
                "reason": ("I cannot reach this application's database from "
                           "here, so I would be making the file up. Start the "
                           "app and ask me again — or, signed in to the app "
                           f"itself, open {routes} and it will hand you the "
                           "same spreadsheet.")}

    sheets = []
    try:
        for ent in wanted:
            tell(reasoning, f"Reading {table_of(ent)}.", "step")
            sheets.append(one_sheet(svc.doc, url, ent))
    except ExportRefused as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("[export] failed")
        return {"applied": False, "edited_paths": [],
                "reason": (f"I could not read the records just then "
                           f"({type(exc).__name__}: {exc}). Nothing about the "
                           f"application has changed — an export only reads.")}

    backup = not ref and len(sheets) > 1
    if backup:
        app_name = str((svc.doc.get("application") or {}).get("name") or "app")
        name = write_backup(output_dir, sheets, app_name)
    else:
        name = write_sheet(output_dir, sheets[0])

    out = {
        "applied": True, "edited_paths": [], "backup": backup, "file": name,
        "href": link_for(project_id or Path(output_dir).name, name),
        "sheets": [{"entity": s["entity"], "table": s["table"],
                    "count": len(s["rows"]), "withheld": s["withheld"],
                    "missing": s["missing"], "truncated": s["truncated"]}
                   for s in sheets],
    }
    tell(reasoning, f"Wrote {name}.", "step")
    return {**out, "diff_summary": summary_of(out), "reason": ""}


__all__ = [
    "EXPORTS", "ExportRefused", "MAX_ROWS", "existing_columns",
    "exported_fields", "exports_dir", "link_for", "one_sheet", "path_of",
    "produced", "read_rows", "run", "summary_of", "to_csv", "withheld",
    "write_backup", "write_sheet",
]
