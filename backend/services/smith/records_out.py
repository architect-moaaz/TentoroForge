"""The owner's own records, out — and an honest answer to "back it up".

Two asks sat under "Can I trust this?" in the phrasebook with nothing behind
them. "Can I get all this out as a spreadsheet?" reached an `export` that
hands over a Dockerfile, a compose file and the source: the DEFINITION of the
application and none of what it holds. "Back it up somewhere" reached nothing
at all — there was no sentence an owner could type that meant it.

Both are the same question asked twice, and it is not a feature request. It is
what somebody asks the moment they realise their business now runs on this: if
you go away, do I still have my customers? The only answer worth giving is one
they can hold — a file on their own machine.

WHAT THEY GET
-------------
`export_records` writes one CSV per kind of record, because "a spreadsheet" to
a business owner means something that opens in Excel, not a JSON dump. One
entity named gives one `.csv`; the whole application gives a `.zip` of them.
Headers are the field names the Blueprint uses, which are the words the
application shows them.

`back_up` writes one archive holding those same CSVs AND the definition the
application is built from, plus a README that says what it is. Records without
the definition are columns nobody can interpret; the definition without the
records is what `export` already did.

WHAT THEY DO NOT GET, SAID OUT LOUD
-----------------------------------
There is no scheduled backup, and this deliberately does not pretend to be
one. Nothing here runs on a timer, nothing is kept on the platform's side, and
there is no restore button — putting records back means loading the CSVs into
a database, which is work a person does. Saying "backed up" and meaning "a zip
you downloaded once in September" is the kind of promise that is discovered to
be false on the worst day, so `summary_of` says all of that in the reply, and
`README_TEXT` says it again inside the archive where it will still be legible
a year later next to the file it describes.

WHY THE COLUMNS ARE READ OFF THE APPLICATION
--------------------------------------------
The table and its columns come from the app's own `src/db/schema/*.ts` — the
declaration `drizzle-kit push` turned into the database — and not from a
second walk over the Blueprint's entities. A second derivation of "which
column is this field" is a second derivation that drifts, and the one that
drifts is the one that SELECTs a column that is not there. An entity whose
module is not on disk is reported as not exported, with the reason. It is
never guessed at.

THREE THINGS THIS MUST NOT DO
-----------------------------
1. **Cross a project.** The database url is read from the application's own
   `.env.local` (`assembly.app_database_url`) — the database the application
   itself opens — and the app tree is reached from the project's `output_dir`,
   which the router takes off an authorised project row. No id in a request
   names a database, so no request can name somebody else's.

2. **Become a new way in.** The generated application gains NOTHING here: no
   route, no endpoint, no column of access. This path exists only on the
   platform side, for the person who owns the project, so no application user's
   reach changes by one row. The app's access rules are not bypassed because
   the app is not asked.

3. **Carry credentials out.** The scaffold stores a bcrypt hash in
   `users.password`; a CSV of those in an owner's inbox is a harm the owner did
   not ask for and cannot undo. Those columns are omitted and the omission is
   stated, in the reply and in the README.

WHOSE ROWS THESE ARE. An entity can be scoped in the application so each of
its users reaches only their own rows (§100, `security.ownershipRules`). The
owner is not one of those users — they hold the database — so the export is
taken whole, and every entity that is scoped that way is NAMED as scoped in
the reply and in the README. Silently flattening a per-user table into one
spreadsheet without saying so is how somebody emails a competitor's records to
a customer. Saying it is the difference.
"""

from __future__ import annotations

import csv
import datetime as _dt
import decimal
import json
import logging
import re
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterator

from services.llm_client import tell
from services.smith.section_change import SectionChangeError

logger = logging.getLogger(__name__)

#: Columns the PLATFORM writes a secret into, never the owner's own data.
#: `templates/app-foundation/src/db/schema/user.ts` declares `password` and the
#: signup route writes a bcrypt hash there. Nothing in a Drizzle declaration
#: marks a column secret, so this one fact is declared here, once, with its
#: reason — and it is matched by column name across every table, because a
#: column called `password` anywhere holds a credential by any reading.
SECRET_COLUMNS: frozenset[str] = frozenset({"password"})

#: Where the projections write the table declarations.
SCHEMA_DIR = ("src", "db", "schema")


# --------------------------------------------------------------------------- #
# what there is to take out
# --------------------------------------------------------------------------- #

def _live(items: Any) -> list[dict]:
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def schema_tables(app_root: str | Path) -> dict[str, tuple[tuple[str, str], ...]]:
    """``table -> ((field, column), …)``, read off the application itself.

    Every module in `src/db/schema/` except the barrel. Includes the platform
    and `_forge_*` tables that share the directory — :func:`tables_for` picks
    out the ones the Blueprint declares, so what is exported stays the owner's
    records rather than the runtime's bookkeeping.
    """
    from services.blueprint.projection import parse_table_columns

    root = Path(app_root, *SCHEMA_DIR)
    out: dict[str, tuple[tuple[str, str], ...]] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.ts")):
        if path.name == "index.ts":
            continue
        try:
            table, columns = parse_table_columns(path.read_text("utf-8"))
        except OSError:
            continue
        if table and columns:
            out[table] = columns
    return out


def scope_note(doc: dict, entity: dict) -> str:
    """How this entity is scoped in the application, in the owner's words.

    Empty when the Blueprint declares no enforceable rule for it — which means
    every signed-in user of the application already reaches every row, so
    there is nothing about the export that is wider than the application.
    """
    from services.blueprint.projection import _canonical_key, ownership_rules

    manifest = ownership_rules(doc)
    for key in (_canonical_key(entity.get("name") or ""),
                _canonical_key(entity.get("table") or "")):
        for rule in manifest.get(key) or []:
            if rule.get("kind") != "scope":
                continue
            whose = ("one user" if rule.get("scope") == "user"
                     else "one workspace")
            exempt = [str(r) for r in (rule.get("unscopedRoles") or [])]
            said = (f"in the application each row belongs to {whose} "
                    f"(`{rule.get('column')}`)")
            if exempt:
                said += f", and only {', '.join(exempt)} sees all of them"
            return said
    return ""


class Table:
    """One kind of record, ready to be written out."""

    def __init__(self, entity: dict, table: str,
                 columns: tuple[tuple[str, str], ...], scope: str) -> None:
        self.name = str(entity.get("name") or table)
        self.table = table
        #: (header, column) — the header is the owner's word for the box.
        self.columns = columns
        self.scope = scope

    @property
    def headers(self) -> list[str]:
        return [field for field, _col in self.columns]

    @property
    def sql_columns(self) -> list[str]:
        return [col for _field, col in self.columns]

    @property
    def filename(self) -> str:
        return f"{self.table}.csv"


def tables_for(doc: dict, app_root: str | Path,
               entity_named: str = "") -> tuple[list[Table], list[str]]:
    """The tables to export, and one line per entity that cannot be.

    `entity_named` empty means the whole application. Named, it is matched the
    way every other verb matches an entity — by canonical spelling, so
    "rent payments", `RentPayment` and `rent_payments` all land on the same
    one.
    """
    from services.blueprint.projection import _canonical_key, to_snake

    on_disk = schema_tables(app_root)
    wanted = _canonical_key(entity_named)
    tables: list[Table] = []
    skipped: list[str] = []
    matched = False
    for entity in _live((doc.get("data") or {}).get("entities")):
        name = str(entity.get("name") or "")
        table = str(entity.get("table") or to_snake(name))
        if wanted and wanted not in {_canonical_key(name), _canonical_key(table)}:
            continue
        matched = True
        columns = on_disk.get(table)
        if not columns:
            skipped.append(
                f"**{name}** — the application has no `{table}` table on disk, "
                "so there is nothing to read")
            continue
        kept = tuple((field, col) for field, col in columns
                     if col.lower() not in SECRET_COLUMNS)
        dropped = [col for _f, col in columns if col.lower() in SECRET_COLUMNS]
        if dropped:
            logger.info("records_out: omitting %s from %s", dropped, table)
        tables.append(Table(entity, table, kept, scope_note(doc, entity)))

    if wanted and not matched:
        raise SectionChangeError(
            f"There is no kind of record called “{entity_named}” in this "
            "application. Ask me for all of them and I will send everything.")
    return tables, skipped


def omitted_credentials(doc: dict, app_root: str | Path) -> list[str]:
    """Tables a credential column was left out of — named, never silent."""
    out = []
    for table, columns in schema_tables(app_root).items():
        if any(col.lower() in SECRET_COLUMNS for _f, col in columns):
            out.append(table)
    return sorted(out)


# --------------------------------------------------------------------------- #
# reading the rows
# --------------------------------------------------------------------------- #

#: A reader takes (database url, table, columns) and yields rows in that
#: column order. Injected so the shaping of a spreadsheet can be tested
#: without a Postgres, and so nothing else in here knows about a driver.
Reader = Callable[[str, str, list[str]], Iterator[tuple]]


def _quote(identifier: str) -> str:
    """A Postgres identifier, quoted. Rejects anything that is not one.

    The table and column names come off the application's own schema modules,
    not off a request — but this is the one place a name becomes SQL, so it
    refuses rather than interpolates anything it did not expect.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", identifier or ""):
        raise SectionChangeError(
            f"“{identifier}” is not a column name I can read safely, so I have "
            "exported nothing.")
    return '"' + identifier + '"'


def postgres_reader(url: str, table: str, columns: list[str]) -> Iterator[tuple]:
    """Stream one table out of the application's database.

    A named cursor, so a table with a million rows is read a page at a time
    rather than assembled in the platform's memory before the first line of
    CSV is written.
    """
    import psycopg2

    sql = (f"SELECT {', '.join(_quote(c) for c in columns)} "
           f"FROM {_quote(table)} ORDER BY 1")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor(name=f"forge_export_{uuid.uuid4().hex}") as cur:
            cur.itersize = 1000
            cur.execute(sql)
            for row in cur:
                yield tuple(row)
    finally:
        conn.close()


def cell(value: Any) -> str:
    """One database value as a spreadsheet writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def write_csv(path: Path, table: Table, rows: Iterator[tuple]) -> int:
    """One table to one CSV. Returns the number of rows written.

    A table with nothing in it still gets its file, with its headers: "there
    are no orders yet" and "orders were left out of your backup" are very
    different facts, and an absent file says the wrong one.
    """
    written = 0
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(table.headers)
        for row in rows:
            out.writerow([cell(v) for v in row])
            written += 1
    return written


# --------------------------------------------------------------------------- #
# the two things an owner asks for
# --------------------------------------------------------------------------- #

def _app_root(output_dir: str | Path) -> Path:
    return Path(output_dir) / "app"


def _database_url(output_dir: str | Path) -> str:
    from services.blueprint.assembly import app_database_url

    url = app_database_url(_app_root(output_dir))
    if not url:
        raise SectionChangeError(
            "I cannot find the database this application opens — its "
            "`.env.local` names none — so I have nothing to read the records "
            "out of. Build the application and I will try again.")
    return url


def _gather(doc: dict, output_dir: str | Path, tables: list[Table],
            into: Path, reader: Reader, reasoning: Any = None) -> dict[str, int]:
    """Write one CSV per table into `into`; return the row count of each."""
    url = _database_url(output_dir)
    counts: dict[str, int] = {}
    for table in tables:
        tell(reasoning, f"Reading {table.name} out of the application.", "step")
        try:
            rows = reader(url, table.table, table.sql_columns)
            counts[table.name] = write_csv(into / table.filename, table, rows)
        except SectionChangeError:
            raise
        except Exception as exc:         # noqa: BLE001 — a driver error is an answer
            raise SectionChangeError(
                f"I could not read **{table.name}** out of the application's "
                f"database ({type(exc).__name__}: {exc}), so I have sent you "
                "nothing rather than a partial copy.") from exc
    return counts


def _doc(output_dir: str | Path) -> dict:
    from services.smith.engine_blueprint_adapter import load_engine_doc

    doc = load_engine_doc(str(output_dir))
    if not doc:
        raise SectionChangeError(
            "This project has no built application yet, so it holds no records "
            "to take out. Approve the definition and build it first.")
    return doc


def export_records(output_dir: str, project_id: str, *, entity: str = "",
                   reader: Reader | None = None, reasoning: Any = None) -> dict:
    """Every record the application holds, as CSV the owner downloads."""
    from services import project_exports

    doc = _doc(output_dir)
    app_root = _app_root(output_dir)
    tables, skipped = tables_for(doc, app_root, entity)
    if not tables:
        raise SectionChangeError(
            "There is nothing to export: this application declares no kind of "
            "record whose table exists yet."
            + ("\n\n" + "\n".join(f"- {line}" for line in skipped) if skipped else ""))

    name = _archive_name(doc, "records")
    with tempfile.TemporaryDirectory(dir=project_exports.exports_root(output_dir)) as tmp:
        staged = Path(tmp)
        counts = _gather(doc, output_dir, tables, staged,
                         reader or postgres_reader, reasoning)
        if len(tables) == 1:
            single = staged / tables[0].filename
            rec = project_exports.save_export_from(
                output_dir, f"{tables[0].table}.csv", single, "text/csv",
                describes=tables[0].name)
        else:
            bundle = staged / "bundle.zip"
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
                for table in tables:
                    zf.write(staged / table.filename, table.filename)
            rec = project_exports.save_export_from(
                output_dir, f"{name}.zip", bundle, "application/zip",
                describes="every kind of record")

    return {"applied": True, "kind": "export",
            "url": project_exports.download_path(project_id, rec["id"]),
            "filename": rec["filename"], "bytes": rec["bytes"],
            "counts": counts, "skipped": skipped,
            "scoped": {t.name: t.scope for t in tables if t.scope},
            "credentials_omitted": omitted_credentials(doc, app_root),
            "edited_paths": []}


def back_up(output_dir: str, project_id: str, *,
            reader: Reader | None = None, reasoning: Any = None) -> dict:
    """The records AND the definition, in one archive the owner keeps."""
    from services import project_exports

    doc = _doc(output_dir)
    app_root = _app_root(output_dir)
    tables, skipped = tables_for(doc, app_root)
    name = _archive_name(doc, "backup")

    with tempfile.TemporaryDirectory(dir=project_exports.exports_root(output_dir)) as tmp:
        staged = Path(tmp)
        records = staged / "records"
        records.mkdir()
        counts = _gather(doc, output_dir, tables, records,
                         reader or postgres_reader, reasoning) if tables else {}

        bundle = staged / "bundle.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            for table in tables:
                zf.write(records / table.filename, f"records/{table.filename}")
            # THE DEFINITION TRAVELS WITH THE ROWS. A CSV of uuids and dates is
            # not readable a year later without the document that says what
            # those columns are and what the application did with them — and
            # the definition is the only half of this pair that can rebuild
            # anything.
            zf.writestr("definition/blueprint.json",
                        json.dumps(doc, indent=2, sort_keys=True))
            for path in sorted(Path(app_root, *SCHEMA_DIR).glob("*.ts")):
                zf.writestr(f"definition/schema/{path.name}", path.read_text("utf-8"))
            zf.writestr("README.md", readme(doc, tables, counts, skipped,
                                            omitted_credentials(doc, app_root)))
        rec = project_exports.save_export_from(
            output_dir, f"{name}.zip", bundle, "application/zip",
            describes="records and definition")

    return {"applied": True, "kind": "backup",
            "url": project_exports.download_path(project_id, rec["id"]),
            "filename": rec["filename"], "bytes": rec["bytes"],
            "counts": counts, "skipped": skipped,
            "scoped": {t.name: t.scope for t in tables if t.scope},
            "credentials_omitted": omitted_credentials(doc, app_root),
            "edited_paths": []}


def _archive_name(doc: dict, suffix: str) -> str:
    from services.blueprint.projection import to_snake

    app = to_snake(str((doc.get("application") or {}).get("name") or "application"))
    day = _dt.date.today().isoformat()
    return f"{app or 'application'}-{suffix}-{day}"


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #

#: Said in the archive as well as in the chat, because a zip found on a hard
#: drive in two years has no chat around it.
README_TEXT = """\
# What this is

A copy of this application, taken on {taken}. It holds:

- `records/` — one CSV per kind of record, exactly what the application's
  database held at that moment. The first row of each file is the column
  names, as the application names them.
- `definition/blueprint.json` — the definition the application is built from:
  its screens, rules, workflows, roles and data model.
- `definition/schema/` — the table declarations, so a column in a CSV can be
  matched to the kind of value it holds.

# What this is not

- **It is not kept up to date.** It is a copy of one moment. Everything
  entered into the application after {taken} is not in here.
- **Nothing is scheduled.** The platform is not taking backups for you. This
  file exists because you asked for it once; there will not be another one
  until you ask again.
- **There is no restore button.** The definition here can rebuild the
  application. The CSVs do not put themselves back — loading them into a
  database is work somebody has to do, with this file in hand.
- **Sign-in credentials are not in here.** People sign in again on a restored
  application; nobody's password travels in a zip.
- **Anything the application stores outside its own database is not in here** —
  uploaded files, and anything held by a service it integrates with.

Keep it somewhere that is not the machine that runs the application.
"""


def readme(doc: dict, tables: list, counts: dict, skipped: list[str],
           credentials: list[str]) -> str:
    """`README.md` for the archive — the promise and its limits, in writing."""
    lines = [README_TEXT.format(taken=_dt.datetime.now().strftime("%d %B %Y, %H:%M"))]
    lines.append("# What is in it\n")
    for table in tables:
        said = f"- `records/{table.filename}` — {table.name}, {_rows(counts.get(table.name, 0))}"
        if table.scope:
            said += (f". Whose rows these are: {table.scope} — this file holds "
                     "every one of them")
        lines.append(said)
    if skipped:
        lines.append("\n# What was left out\n")
        lines += [f"- {re.sub(r'[*`]', '', line)}" for line in skipped]
    if credentials:
        lines.append("\n# Columns deliberately omitted\n")
        lines.append("- `" + "`, `".join(sorted(SECRET_COLUMNS))
                     + f"` from {', '.join(credentials)} — these hold sign-in "
                       "credentials, not your data.")
    return "\n".join(lines) + "\n"


def _rows(n: int) -> str:
    return "1 row" if n == 1 else f"{n} rows"


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(n // 1024, 1)} KB"


def summary_of(out: dict) -> str:
    """What was taken out, and — said plainly — what it does not do."""
    total = sum((out.get("counts") or {}).values())
    backup = out.get("kind") == "backup"
    lines = [
        f"[**Download {out['filename']}**]({out['url']}) — {_size(out['bytes'])}, "
        + ("your records and the definition they belong to."
           if backup else f"{_rows(total)} as a spreadsheet."),
        "",
    ]
    for name, count in sorted((out.get("counts") or {}).items()):
        said = f"- **{name}** — {_rows(count)}"
        scope = (out.get("scoped") or {}).get(name)
        if scope:
            said += (f". {scope[0].upper() + scope[1:]} — this file holds "
                     "every one of them.")
        lines.append(said)
    for line in out.get("skipped") or []:
        lines.append(f"- {line}")

    lines += ["", "**What this does not do.**"]
    lines.append("- It is a copy of this moment, not a live one — nothing "
                 "entered from now on is in it.")
    if backup:
        lines.append("- Nothing is scheduled. I am not keeping a backup for "
                     "you and there will not be another one until you ask.")
        lines.append("- There is no restore button. The definition in it can "
                     "rebuild the application; the records have to be loaded "
                     "back into a database by hand.")
    else:
        lines.append("- There is no import — nothing puts these rows back.")
        lines.append("- Say **back it up** and I will send the same records "
                     "together with the definition they belong to.")
    if out.get("credentials_omitted"):
        lines.append("- Sign-in credentials are left out of "
                     f"{', '.join(out['credentials_omitted'])}. Nobody's "
                     "password is in the file.")
    lines.append("- Files the application stores outside its own database are "
                 "not in it.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# the shape a tool handler needs
# --------------------------------------------------------------------------- #

def run(output_dir: str, project_id: str, *, kind: str = "export",
        entity: str = "", reader: Reader | None = None,
        reasoning: Any = None) -> dict:
    """One export or one backup, degraded to a reason rather than a crash.

    `project_id` is not decoration and not optional. The reply's whole point is
    a link, the link is `/api/projects/<project_id>/exports/<id>`, and that
    route authorises the caller against THAT project before it reads a byte.
    An export with no project to belong to would have to be served from
    somewhere unauthorised, which is why this takes the id rather than
    defaulting it — and why these verbs are dispatched from `smith_session`
    (which `smith_chat_v2` hands the id) rather than from the tool table in
    `smith_tools`, where a handler is given an `output_dir` and nothing else.
    """
    try:
        out = (back_up(output_dir, project_id, reader=reader, reasoning=reasoning)
               if kind == "backup" else
               export_records(output_dir, project_id, entity=entity,
                              reader=reader, reasoning=reasoning))
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:             # noqa: BLE001 — a turn degrades
        logger.exception("[smith] %s failed", kind)
        return {"applied": False, "edited_paths": [],
                "reason": f"{type(exc).__name__}: {exc}"}
    return {**out, "diff_summary": summary_of(out), "reason": ""}


__all__ = ["README_TEXT", "Reader", "SECRET_COLUMNS", "Table", "back_up",
           "cell", "export_records", "omitted_credentials", "postgres_reader",
           "readme", "run", "schema_tables", "scope_note", "summary_of",
           "tables_for", "write_csv"]
