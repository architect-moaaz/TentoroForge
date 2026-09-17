"""“Here's our customer spreadsheet, load it in.”

The first dead end an owner reaches, and they reach it within the hour,
because every owner arrives with an existing business and existing data.
There was no import of any kind, so the first real use of an application
Forge built was typing everything in again.

WHAT AN IMPORT IS, HERE
-----------------------
Three steps, and the middle one is the point:

1. The file lands in the project's own **inbox** — `.forge/imports/<id>/` —
   put there by the turn it was attached to. Not a slot on the verb: like
   `revert`, the file is always the one just attached, and asking a person for
   an attachment id they have never seen is asking them to know what Smith
   recorded.

2. **A dry run that writes nothing.** Columns are bound to the entity's
   DECLARED fields, every row is coerced to the declared types, and the answer
   says how many rows would land, how many would not and why, which column
   became which field, and which columns have no field at all. Then it waits.
   An import is the one change whose subject is data the owner cannot
   regenerate; finding out what it did by looking at the result is not good
   enough.

3. On a yes, the rows are written where records belong — the generated app's
   own database, through the app's own seeder — and the Blueprint records that
   the import HAPPENED, never the rows themselves.

A COLUMN WITH NO FIELD IS A REFUSAL
-----------------------------------
Not a silent drop, and not an invented field. `Credit Limit` against a
Customer that has no such field is answered with the two things that do work:
add the field first, or say to import without that column. Guessing that
`Credit Limit` means `creditLimitAmount` is how a mapping layer starts
growing a synonym table, and the synonym table is always wrong about somebody's
spreadsheet.

WHAT THE MODEL IS FOR, AND WHAT IT IS NOT
-----------------------------------------
Columns whose normalised name equals a declared field's are bound without a
model. The REMAINDER — `Phone No.` against `phoneNumber` — is one model call,
handed the unmatched columns and the unused declared fields and asked to pair
them. The reply is checked against the declared list, so a field that does not
exist, or is already taken, is dropped. The model picks from a list; it cannot
widen the schema, and it never sees a row.

Rows do not pass through a model at any point. They are read, coerced and
written by this file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from services.llm_client import tell
from services.smith.section_change import SectionChangeError, find_named

logger = logging.getLogger(__name__)

#: Where an attached spreadsheet waits for the turn that names an entity for
#: it. Inside the project, so the one argument every caller has — `output_dir`
#: — is enough to reach it: the tool loop, `SmithSession` and the CLI all have
#: it, and none of them has a project id or an attachment id.
INBOX = Path(".forge") / "imports"

#: The planned import, between the dry run that describes it and the yes that
#: applies it. Kept whole so what lands is EXACTLY what was shown — re-deciding
#: the mapping on the second turn could show one thing and do another.
PENDING = Path(".forge") / "pending-import.json"

#: What the chips say. The first is the yes the gate looks for.
GO_LABEL = "Load them in"
NO_LABEL = "No, leave it"

#: Extensions this reads. `.xlsx` is what an owner's spreadsheet usually is;
#: `.csv`/`.tsv` are what a careful one exports.
SHEET_EXT = frozenset({".csv", ".tsv", ".xlsx"})

#: Delimiters the sniffer is allowed to find. A European CSV is
#: semicolon-separated and reading it as one column would produce a refusal
#: about a column named `Name;Email;Phone`, which tells the owner nothing.
_DELIMITERS = ",;\t|"

#: Enough to see what the file is without reading anybody's records into a
#: prompt. Shown in the turn's note and in the dry run.
PREVIEW_ROWS = 3

#: A whole spreadsheet does not belong in memory twice. 50k rows is far past
#: any owner's first import and still bounded.
MAX_ROWS = 50_000


class ImportRefused(SectionChangeError):
    """The import cannot be made, with the reason the owner can act on."""


# --------------------------------------------------------------------------- #
# the inbox
# --------------------------------------------------------------------------- #

def inbox_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / INBOX


def import_id_for(data: bytes) -> str:
    """The import's id IS the file's content.

    So the same spreadsheet attached twice is the same import rather than a
    second copy of every row — the check that keeps 412 customers from
    becoming 824 lives in the id, not in a comparison nobody remembers to
    write.
    """
    return "IMP-" + hashlib.sha1(data).hexdigest()[:10]


def is_spreadsheet(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in SHEET_EXT


def accept(output_dir: str | Path, filename: str, data: bytes) -> dict:
    """Put one attached spreadsheet in the inbox; return its record."""
    if not is_spreadsheet(filename):
        raise ImportRefused(
            f"{filename} is not a spreadsheet I can read. Export it as CSV "
            f"(or attach the .xlsx) and I will load it.")
    imp = import_id_for(data)
    d = inbox_dir(output_dir) / imp
    d.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    (d / f"source{suffix}").write_bytes(data)
    rec = {"id": imp, "filename": filename, "bytes": len(data),
           "acceptedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (d / "meta.json").write_text(json.dumps(rec, indent=2), "utf-8")
    return rec


def _source_of(d: Path) -> Path | None:
    for path in sorted(d.glob("source.*")):
        if path.suffix.lower() in SHEET_EXT:
            return path
    return None


def in_inbox(output_dir: str | Path) -> list[dict]:
    """Every accepted spreadsheet, newest first."""
    root = inbox_dir(output_dir)
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            rec = json.loads((d / "meta.json").read_text("utf-8"))
        except (OSError, ValueError):
            continue
        src = _source_of(d)
        if src is None:
            continue
        rec["path"] = str(src)
        out.append(rec)
    return sorted(out, key=lambda r: str(r.get("acceptedAt") or ""), reverse=True)


def newest(output_dir: str | Path) -> dict | None:
    recs = in_inbox(output_dir)
    return recs[0] if recs else None


# --------------------------------------------------------------------------- #
# reading a sheet
# --------------------------------------------------------------------------- #

def _decode(raw: bytes) -> str:
    """The text of a CSV, by the two encodings a spreadsheet export uses.

    UTF-8 (with or without the BOM Excel writes) first; Windows-1252 second,
    which is what "Save as CSV" produces on a machine that has never heard of
    Unicode. Two named encodings, not a detector.
    """
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=_DELIMITERS).delimiter
    except (csv.Error, IndexError):
        return ","


def read_sheet(path: str | Path) -> tuple[list[str], list[dict], str]:
    """`(columns, rows, how)` — the file as headings and dictionaries.

    `how` says how it was read, so an owner whose file came out wrong can see
    why rather than guess.
    """
    p = Path(path)
    if p.suffix.lower() == ".xlsx":
        return _read_xlsx(p)

    text = _decode(p.read_bytes())
    delim = _delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        return [], [], "the file is empty"
    columns = [str(c).strip() for c in header]
    rows = []
    for values in reader:
        if not any(str(v).strip() for v in values):
            continue                      # a trailing blank line is not a row
        rows.append({columns[i]: (values[i] if i < len(values) else "")
                     for i in range(len(columns))})
        if len(rows) >= MAX_ROWS:
            break
    named = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
    return columns, rows, f"{named.get(delim, delim)}-separated"


def _read_xlsx(path: Path) -> tuple[list[str], list[dict], str]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:       # pragma: no cover - declared in requirements
        raise ImportRefused(
            "I cannot read .xlsx files on this server. Export the sheet as "
            "CSV and attach that instead.") from exc
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    try:
        header = next(it)
    except StopIteration:
        return [], [], "the sheet is empty"
    columns = [str(c).strip() if c is not None else "" for c in header]
    rows = []
    for values in it:
        if not any(v not in (None, "") for v in values):
            continue
        row = {}
        for i, col in enumerate(columns):
            if not col:
                continue
            v = values[i] if i < len(values) else None
            row[col] = "" if v is None else v
        rows.append(row)
        if len(rows) >= MAX_ROWS:
            break
    wb.close()
    return [c for c in columns if c], rows, f"the “{ws.title}” sheet"


# --------------------------------------------------------------------------- #
# columns → declared fields
# --------------------------------------------------------------------------- #

def norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def loadable_fields(entity: dict) -> list[dict]:
    """The fields a spreadsheet column may be loaded into.

    Three kinds are excluded, and none of them is a judgement about the data:

    * the primary key — the database mints it, and a spreadsheet's own id
      column is not this application's id;
    * a foreign key (`references`) — its value names another record, and
      matching a name to a record already in the app is a different problem
      from loading a file, so it is refused rather than guessed;
    * a `sensitive` field — §42. A password or a token pasted into a
      spreadsheet column must not be loaded into a database column by a
      mapping nobody looked at.
    """
    out = []
    for f in (entity.get("fields") or []):
        if not isinstance(f, dict) or not str(f.get("name") or "").strip():
            continue
        if f.get("primaryKey") or f.get("references") or f.get("sensitive"):
            continue
        out.append(f)
    return out


def _db_owned(entity: dict) -> set[str]:
    """Normalised names of the columns the DATABASE owns, not the owner: the
    primary key and every declared foreign key."""
    return {norm(f.get("name")) for f in (entity.get("fields") or [])
            if isinstance(f, dict) and (f.get("primaryKey") or f.get("references"))
            and f.get("name")}


def match_exact(columns: list[str], fields: list[dict]) -> dict[str, str]:
    """Columns whose normalised heading IS a declared field's name."""
    by_norm = {norm(f.get("name")): str(f.get("name")) for f in fields}
    pairs = {}
    taken: set[str] = set()
    for col in columns:
        field = by_norm.get(norm(col))
        if field and field not in taken:
            pairs[col] = field
            taken.add(field)
    return pairs


_MAP_PROMPT = """A business owner has attached a spreadsheet to load into one \
kind of record in their application. Some column headings did not match a \
field by name. Pair up what you can.

The record is "{entity}". Its fields still free, with their types:
{fields}

The columns still unpaired, with an example value from the file:
{columns}

Return ONLY a JSON object mapping column heading -> field name, using the \
exact spellings above. Pair a column only when the two plainly mean the same \
thing ("Phone No." and phoneNumber, "E-mail" and email). Leave a column OUT \
when you are not sure, when it means something the record has no field for, \
or when the field's type could not hold it — a column left out is reported to \
the owner, and a wrong pairing writes the wrong data into their business \
records. Do not invent a field name. Do not explain.
"""


def _propose(entity_name: str, columns: list[str], fields: list[dict],
             sample: dict, provider: Callable[[str], str] | None = None,
             reasoning: Any = None) -> dict[str, str]:
    """One model call for the columns that did not match by name.

    CONSTRAIN, DON'T CORRECT: the reply is filtered against the declared field
    list and the columns actually offered, so an invented field, a field
    already taken, or a column that is not in the file is dropped rather than
    repaired into something the model did not say.
    """
    if not columns or not fields:
        return {}
    lines_f = "\n".join(f"- {f.get('name')} ({f.get('type') or 'text'})"
                        + (f" one of: {', '.join(str(v) for v in f.get('enumValues') or [])}"
                           if f.get("enumValues") else "")
                        for f in fields)
    lines_c = "\n".join(f"- {c}: {str(sample.get(c, ''))[:60]!r}" for c in columns)
    prompt = _MAP_PROMPT.format(entity=entity_name, fields=lines_f, columns=lines_c)

    call = provider or (lambda p: _default_provider(p, reasoning))
    try:
        raw = call(prompt)
    except Exception as exc:  # noqa: BLE001 — an unreachable model refuses, it does not crash
        logger.warning("[import] mapping call failed: %s", exc)
        return {}
    data = _parse_object(raw)
    if not data:
        return {}
    allowed = {str(f.get("name")) for f in fields}
    offered = set(columns)
    out: dict[str, str] = {}
    for col, field in data.items():
        col, field = str(col), str(field)
        if col in offered and field in allowed and field not in out.values():
            out[col] = field
    return out


def _default_provider(prompt: str, reasoning: Any = None) -> str:
    from services.llm_client import complete
    return complete(content=prompt, max_tokens=900, reasoning_callback=reasoning)


def _parse_object(raw: str) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# values → declared types
# --------------------------------------------------------------------------- #

_TRUE = frozenset({"true", "yes", "y", "1", "t"})
_FALSE = frozenset({"false", "no", "n", "0", "f"})


class Rejected(ValueError):
    """One value the declared type cannot hold, with the reason."""


def coerce(value: Any, field: dict) -> Any:
    """One spreadsheet cell as the declared type, or `Rejected` saying why.

    ONE TABLE, NO EXCEPTIONS LIST. A declared type this does not name is
    text — which is what an undeclared type already is everywhere else in the
    projection — and that is a rule, not a fallback for a special case.
    """
    kind = str(field.get("type") or "text").lower()
    name = str(field.get("name") or "field")
    raw = value
    if isinstance(raw, str):
        raw = raw.strip()
    empty = raw is None or raw == ""

    if empty:
        if field.get("required"):
            raise Rejected(f"{name} is required and the column is empty")
        return None

    options = [str(v) for v in (field.get("enumValues") or [])]
    if options:
        for opt in options:
            if str(raw).strip().lower() == opt.strip().lower():
                return opt
        raise Rejected(f"{name} must be one of {', '.join(options)} — the file says "
                       f"“{raw}”")

    if kind in ("int", "integer", "number", "serial", "bigint", "smallint"):
        try:
            return int(str(raw).replace(",", "").strip())
        except ValueError:
            raise Rejected(f"{name} is a whole number and the file says “{raw}”") from None
    if kind in ("decimal", "numeric", "float", "double", "money", "currency", "real"):
        cleaned = re.sub(r"[,\s]", "", str(raw))
        cleaned = re.sub(r"^[^\d.\-+]+", "", cleaned)     # a currency symbol is not a digit
        try:
            return float(cleaned)
        except ValueError:
            raise Rejected(f"{name} is a number and the file says “{raw}”") from None
    if kind in ("bool", "boolean"):
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise Rejected(f"{name} is yes or no and the file says “{raw}”")
    if kind in ("date", "datetime", "timestamp", "timestamptz"):
        return _as_date(raw, name, time_too=kind != "date")
    if kind == "json":
        try:
            return json.loads(str(raw))
        except ValueError:
            raise Rejected(f"{name} holds structured data and “{raw}” is not") from None
    return str(raw)


def _as_date(raw: Any, name: str, *, time_too: bool) -> str:
    """A date, ISO-8601 only.

    `03/04/2026` IS NOT READ. It is the third of April to the owner who typed
    it and the fourth of March to half the world, and an import that guesses
    puts wrong dates on real records silently. So it is refused, with the
    format that works — which the owner can produce from the same spreadsheet
    in one step.
    """
    if isinstance(raw, datetime):
        return raw.isoformat(timespec="seconds") if time_too else raw.date().isoformat()
    text = str(raw).strip().replace(" ", "T", 1) if time_too else str(raw).strip()[:10]
    try:
        parsed = datetime.fromisoformat(text.rstrip("Z"))
    except ValueError:
        raise Rejected(
            f"{name} is a date and “{raw}” is not one I can read without "
            f"guessing — dates must be written 2026-09-18 (year-month-day)"
        ) from None
    return parsed.isoformat(timespec="seconds") if time_too else parsed.date().isoformat()


# --------------------------------------------------------------------------- #
# the dry run
# --------------------------------------------------------------------------- #

def entities_of(doc: dict) -> list[dict]:
    return [e for e in ((doc.get("data") or {}).get("entities") or [])
            if isinstance(e, dict) and e.get("status") != "DEPRECATED"]


def imports_of(doc: dict) -> list[dict]:
    return [i for i in ((doc.get("data") or {}).get("imports") or []) if isinstance(i, dict)]


def table_of(entity: dict) -> str:
    from services.blueprint.projection import to_snake
    return str(entity.get("table") or to_snake(str(entity.get("name") or "entity")))


def plan(doc: dict, output_dir: str | Path, entity_ref: str, *,
         ignore_columns: list[str] | None = None,
         source: dict | None = None,
         provider: Callable[[str], str] | None = None,
         reasoning: Any = None) -> dict:
    """What the import WOULD do. Writes nothing.

    Every refusal in an import happens here, before a row exists anywhere:
    no file, no such record, a column with no field, a required field no
    column supplies, a file already loaded, nothing that survives coercion.
    """
    rec = source or newest(output_dir)
    if not rec:
        raise ImportRefused(
            "I do not have a spreadsheet to load. Attach it to your message — "
            "a .csv or .xlsx export — and say which records it holds.")

    entity = find_named(entities_of(doc), entity_ref)
    if entity is None:
        known = ", ".join(str(e.get("name")) for e in entities_of(doc)) or "(none)"
        raise ImportRefused(
            f"I could not tell which kind of record “{entity_ref}” means. This "
            f"application keeps: {known}. Name one of those and I will load "
            f"the file into it.")

    already = [i for i in imports_of(doc) if str(i.get("id")) == rec["id"]]
    if already:
        prior = already[0]
        raise ImportRefused(
            f"That exact file is already loaded — {prior.get('rowCount')} "
            f"row(s) went into {prior.get('table')} on "
            f"{str(prior.get('importedAt') or '')[:10]}. Loading it again "
            f"would give you every record twice. Attach a file with only the "
            f"new rows in it, or add them on the screen.")

    columns, rows, how = read_sheet(rec["path"])
    if not columns:
        raise ImportRefused(f"{rec['filename']} has no column headings in its "
                            f"first row, so I cannot tell what anything is.")
    if not rows:
        raise ImportRefused(f"{rec['filename']} has headings but no rows.")

    ignored = [c for c in columns if c in set(ignore_columns or [])]
    # THE DATABASE'S OWN COLUMNS ARE NOT THE OWNER'S DATA. A file that came
    # out of `export` leads with the primary key and carries the foreign keys,
    # and neither can be loaded from a spreadsheet: the key is minted by the
    # database, and a reference names a record this cannot match by name. They
    # are IGNORED WITH THE REASON PRINTED rather than refused — refusing would
    # make the app's own export the one file it will not read, and dropping
    # them in silence is what every other column here is protected from.
    owned = [c for c in columns if c not in set(ignored)
             and norm(c) in _db_owned(entity)]
    ignored += owned
    live = [c for c in columns if c not in set(ignored)]
    fields = loadable_fields(entity)

    pairs = match_exact(live, fields)
    unmatched = [c for c in live if c not in pairs]
    free = [f for f in fields if str(f.get("name")) not in set(pairs.values())]
    if unmatched and free:
        tell(reasoning, f"{len(unmatched)} column(s) did not match a field by name — "
                        f"pairing what I can.", "step")
        pairs.update(_propose(str(entity.get("name")), unmatched, free,
                              rows[0], provider=provider, reasoning=reasoning))

    unmapped = [c for c in live if c not in pairs]
    by_name = {str(f.get("name")): f for f in fields}
    required_missing = [str(f.get("name")) for f in fields
                        if f.get("required") and str(f.get("name")) not in set(pairs.values())]

    accepted: list[dict] = []
    rejects: list[dict] = []
    for i, row in enumerate(rows, start=2):        # row 1 is the headings
        out: dict[str, Any] = {}
        why = ""
        for col, field_name in pairs.items():
            try:
                value = coerce(row.get(col), by_name[field_name])
            except Rejected as exc:
                why = f"row {i}: {exc}"
                break
            if value is not None:
                out[field_name] = value
        if why:
            rejects.append({"row": i, "why": why})
            continue
        if not out:
            rejects.append({"row": i, "why": f"row {i}: every column was empty"})
            continue
        accepted.append(out)

    return {
        "import_id": rec["id"], "source": rec["filename"], "path": rec["path"],
        "entity": str(entity.get("id") or ""), "entity_name": str(entity.get("name") or ""),
        "table": table_of(entity), "how": how,
        "columns": [{"column": c, "field": f} for c, f in pairs.items()],
        "unmapped": unmapped, "ignored": ignored, "db_owned": owned,
        "required_missing": required_missing,
        "rows": accepted, "rejects": rejects,
        "total": len(rows), "preview": rows[:PREVIEW_ROWS],
    }


def blocked(report: dict) -> str:
    """Why this import cannot go ahead as it stands, or "".

    A refusal, with the two things that do work — the shape §42's own
    refusals take. Never a partial import: a spreadsheet half-loaded is worse
    than one not loaded, because nobody knows which half.
    """
    entity = report.get("entity_name") or "that record"
    if report.get("required_missing"):
        missing = ", ".join(f"**{m}**" for m in report["required_missing"])
        return (f"Every {entity} must have {missing}, and no column in "
                f"{report['source']} holds it — so every row would be turned "
                f"away. Add the column to the file and attach it again.")
    if report.get("unmapped"):
        cols = ", ".join(f"**{c}**" for c in report["unmapped"])
        one = len(report["unmapped"]) == 1
        return (f"{report['source']} has {'a column' if one else 'columns'} "
                f"{cols} and {entity} has no field for "
                f"{'it' if one else 'them'}.\n\n"
                f"Either add the field first — say "
                f"`add a {report['unmapped'][0].lower()} field to "
                f"{str(report.get('table') or entity).lower()}` — and attach "
                f"the file again, or say `{ignore_label(report)}` and I will "
                f"leave {'that column' if one else 'those columns'} out.")
    if not report.get("rows"):
        first = (report.get("rejects") or [{}])[0].get("why") or "no row could be read"
        return (f"Not one of the {report.get('total')} rows in "
                f"{report['source']} could be loaded. The first says: {first}. "
                f"Nothing has been changed.")
    return ""


def ignore_label(report: dict) -> str:
    cols = report.get("unmapped") or []
    return "Import without " + ", ".join(cols)


def rows_account(report: dict) -> list[str]:
    """What would become of each row, and of each column. Never omitted.

    A refusal about one column used to be the WHOLE answer, so an owner
    agreeing to leave that column out then found that two of their three rows
    had also been turned away — for reasons they were never shown, on a turn
    that was their last chance to fix the file. Both halves are always said.
    """
    lines = [f"- add **{len(report['rows'])} {report['table']}** record(s)"]
    if report["rejects"]:
        lines.append(f"- turn away **{len(report['rejects'])}** row(s):")
        lines += [f"  - {r['why']}" for r in report["rejects"][:5]]
        if len(report["rejects"]) > 5:
            lines.append(f"  - …and {len(report['rejects']) - 5} more like these")
    if report["ignored"]:
        lines.append("- leave out the column(s): " + ", ".join(report["ignored"]))
    if report.get("db_owned"):
        lines.append("  (" + ", ".join(report["db_owned"]) + " because the "
                     "database writes " + ("that column" if len(report["db_owned"]) == 1
                                           else "those columns") + " itself)")
    if report["columns"]:
        lines += ["", "Each column goes here:", ""]
        lines += [f"- {c['column']} → `{c['field']}`" for c in report["columns"]]
    return lines


def summary_of_plan(report: dict) -> str:
    """The dry run, as the owner reads it."""
    lines = [
        f"**{report['source']}** holds {report['total']} row(s), read as "
        f"{report['how']}. Loading it into **{report['entity_name']}** would:",
        "",
    ] + rows_account(report)
    lines += ["", "Nothing has been written yet. Say "
              f"`{GO_LABEL}` and I will load them."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# the plan, between the dry run and the yes
# --------------------------------------------------------------------------- #

def remember(output_dir: str | Path, report: dict) -> None:
    """Keep the planned import so the yes applies what was SHOWN.

    The rows are not kept — they are re-read from the file under the mapping
    that is, which is deterministic and involves no model. What must not drift
    between the two turns is the mapping, and that is what this holds.
    """
    keep = {k: v for k, v in report.items() if k not in ("rows", "preview", "rejects")}
    try:
        path = Path(output_dir) / PENDING
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keep, indent=2), "utf-8")
    except OSError as exc:
        logger.warning("[import] could not record the pending import: %s", exc)


def peek(output_dir: str | Path) -> dict:
    try:
        raw = json.loads((Path(output_dir) / PENDING).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def clear(output_dir: str | Path) -> None:
    try:
        (Path(output_dir) / PENDING).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[import] could not clear the pending import: %s", exc)


def wants(pending: dict, message: str) -> bool:
    """Whether this message is the yes Smith offered for THIS import.

    Pure, so a caller can ask before consuming: the gate in
    `SmithSession.run_iteration` has to know whether the turn is an agreement
    before it decides to act, and a check that consumed the plan would leave
    the turn that acts with nothing to act on.

    A REFUSED IMPORT HAS ONLY ONE YES, and it is the one that names the
    columns being left out. "yes" to "your file has a column Credit Limit and
    Customer has no field for it" is not agreement to drop that column — it
    is not agreement to anything in particular — and an import that reads it
    as one throws away part of the owner's data on a guess. So the plain
    yeses are accepted only when every column has a field.
    """
    from services.smith import confirm

    if not pending:
        return False
    said = " ".join(str(message or "").strip().lower().rstrip(".!").split())
    if pending.get("unmapped"):
        return said == ignore_label(pending).lower()
    return bool(said == GO_LABEL.lower() or confirm.is_yes(message))


def agreed(output_dir: str | Path, message: str) -> dict:
    """The import this message agrees to, or {}.

    Taken as it is read, like `pending_ask` and `confirm`: a yes that outlives
    its question is a yes nobody gave. A yes to something else is not a yes to
    this — the words accepted are the ones Smith offered.

    The chip that leaves columns out IS the instruction to leave them out, so
    it is applied here, where the words are read, rather than left for the
    caller to remember: the plan that comes back is the one to act on.
    """
    pending = peek(output_dir)
    if not wants(pending, message):
        return {}
    clear(output_dir)
    if pending.get("unmapped"):
        pending["ignored"] = list(pending.get("ignored") or []) + list(pending["unmapped"])
        pending["unmapped"] = []
    return pending


# --------------------------------------------------------------------------- #
# applying it
# --------------------------------------------------------------------------- #

def payload_path(app_root: str | Path, import_id: str) -> Path:
    return Path(app_root) / "src" / "db" / "imports" / f"{import_id}.json"


def reconcile(doc: dict, app_root: str | Path) -> list[str]:
    """Remove payload files the Blueprint no longer declares.

    An UNDO is why this exists. `revert` restores the document — the import's
    declaration goes — and re-runs every projection; without this the payload
    file would still be sitting in the app tree and the seeder would load it
    on the next boot, so the undo would not have undone anything. The app tree
    reflects the Blueprint, imports included.

    Rows already inserted into the owner's database are NOT touched, here or
    anywhere: deleting a business's real records as a side effect of "undo"
    is not a thing to do quietly, and the summary says so out loud.
    """
    out = Path(app_root) / "src" / "db" / "imports"
    if not out.is_dir():
        return []
    declared = {str(i.get("id")) for i in imports_of(doc)}
    removed = []
    for path in sorted(out.glob("*.json")):
        if path.stem in declared:
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("[import] could not remove %s: %s", path, exc)
            continue
        removed.append(str(path.relative_to(app_root)))
    return removed


def apply(svc: Any, report: dict, *, app_root: str | None = None,
          reasoning: Any = None) -> dict:
    """Write the rows where records belong, and record that it happened.

    The rows go into the generated application's OWN database, through its own
    seeder — the only route in this codebase that writes rows, and the one
    holding every hard-won rule about how a row reaches Postgres. The Blueprint
    records the import, never the data: an owner's customer list is not a
    design document.
    """
    refusal = blocked(report)
    if refusal:
        raise ImportRefused(refusal)

    root = Path(app_root) if app_root else None
    written: list[str] = []

    before = svc.snapshot()
    data = svc.doc.setdefault("data", {})
    entry = {
        "id": report["import_id"], "entity": report["entity"],
        "table": report["table"], "source": report["source"],
        "rowCount": len(report["rows"]), "rejectedCount": len(report["rejects"]),
        "columns": list(report["columns"]), "ignoredColumns": list(report["ignored"]),
        "importedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data["imports"] = [i for i in imports_of(svc.doc)
                       if str(i.get("id")) != entry["id"]] + [entry]
    # THE DECLARATION IS VALIDATED BEFORE THE ROWS ARE WRITTEN. A payload
    # sitting in the app tree that the Blueprint does not declare is rows the
    # seeder will load and nothing knows about — and `reconcile` would then
    # delete it on the next projection, so which of the two happened first
    # would decide whether the owner's data landed.
    svc.validate()
    if root is not None:
        path = payload_path(root, report["import_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"import": report["import_id"], "table": report["table"],
             "source": report["source"], "rows": report["rows"]},
            indent=2) + "\n", "utf-8")
        written.append(str(path.relative_to(root)))
    svc.commit(
        user_request=f"load {report['source']} into {report['entity_name']}",
        smith_interpretation=(f"import {len(report['rows'])} row(s) from "
                              f"{report['source']} into {report['table']}"),
        before=before,
        affected=[report["entity"]],
    )
    tell(reasoning, f"Recorded {len(report['rows'])} {report['table']} "
                    f"record(s) from {report['source']}.", "step")

    # THE DEMO ROWS STOP BEING WRITTEN. `project_seed` fabricates three rows
    # per entity so a preview is not an empty screen; an entity holding the
    # owner's real records does not want "Customer 1" beside them.
    if root is not None:
        from services.blueprint.projection import project_seed
        written += list((project_seed(svc.doc, root) or {}).get("files") or [])

    return {"applied": True, "import_id": report["import_id"],
            "rows": len(report["rows"]), "rejected": len(report["rejects"]),
            "rejects": [str(r.get("why") or "") for r in report["rejects"][:5]],
            "table": report["table"], "entity": report["entity_name"],
            "source": report["source"], "edited_paths": sorted(set(written))}


def summary_of(out: dict, *, seeded: str = "") -> str:
    lines = [f"Loaded **{out['rows']} {out['table']}** record(s) from "
             f"**{out['source']}**."]
    if out.get("rejected"):
        # WITH THE REASONS. A count on its own tells an owner that some of
        # their business is missing and not which part or why, which is the
        # one thing they need in order to fix the file and load the rest.
        lines.append(f"{out['rejected']} row(s) were turned away and nothing "
                     f"was written for them:")
        lines += [f"- {why}" for why in (out.get("rejects") or [])]
        if out["rejected"] > len(out.get("rejects") or []):
            lines.append(f"- …and {out['rejected'] - len(out['rejects'])} more "
                         f"like these")
        # WHAT IS ACTUALLY TRUE. An import is recognised by the CONTENTS of
        # the file, so a corrected file is a different file and would load the
        # rows that already landed a second time. Row-level identity is not
        # something this can invent — a spreadsheet has no id that means
        # anything to the database — so the instruction is the one that works.
        lines.append("Fix those rows and attach a file with only them in it — "
                     "attaching the whole spreadsheet again would add the "
                     "rows that landed a second time.")
    lines += ["", seeded or
              ("They are written into the application's own data and land in "
               "the database the next time it starts or is published."),
              "",
              "Your records are yours: `undo` takes back the import and the "
              "demo data it replaced, but it does not delete rows already in "
              "your database."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# the two turns, as a tool handler needs them
# --------------------------------------------------------------------------- #

def run(output_dir: str, entity: str = "", *, confirm: bool = False,
        ignore_columns: list[str] | None = None, message: str = "",
        reasoning: Any = None, provider: Callable[[str], str] | None = None) -> dict:
    """One import turn: the dry run, or the yes that applies it.

    `confirm` — or a message that is the yes Smith offered — applies the
    import that was described last turn, under the mapping that was shown.
    Anything else describes what would happen and waits.
    """
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there is "
                          "nothing to load a spreadsheet into."}

    pending = agreed(output_dir, message) if message else {}
    if confirm and not pending:
        pending = peek(output_dir)
        if pending:
            clear(output_dir)
    if not pending and not str(entity or "").strip():
        # A yes with nothing waiting. Asking which records to load into would
        # be answering a question nobody asked; there is no import in hand.
        return {"applied": False, "edited_paths": [],
                "reason": "There is nothing waiting to be loaded. Attach the "
                          "spreadsheet and tell me which records it holds."}

    try:
        if pending:
            report = plan(svc.doc, output_dir, pending.get("entity_name") or entity,
                          ignore_columns=list(pending.get("ignored") or []),
                          source=_source_record(output_dir, str(pending.get("import_id") or "")),
                          provider=_fixed_mapping(pending), reasoning=reasoning)
            out = apply(svc, report, app_root=str(Path(output_dir) / "app"),
                        reasoning=reasoning)
            seeded = _seed_now(output_dir, reasoning=reasoning)
            return {**out, "diff_summary": summary_of(out, seeded=seeded), "reason": ""}

        report = plan(svc.doc, output_dir, entity,
                      ignore_columns=ignore_columns, reasoning=reasoning,
                      provider=provider)
    except ImportRefused as exc:
        clear(output_dir)
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("[import] failed")
        clear(output_dir)
        return {"applied": False, "edited_paths": [],
                "reason": f"{type(exc).__name__}: {exc}"}

    refusal = blocked(report)
    remember(output_dir, report)
    options = [GO_LABEL, NO_LABEL]
    answer = summary_of_plan(report)
    if refusal:
        answer = refusal
        if report["rows"] or report["rejects"]:
            answer += "\n\nThe rest of the file reads like this:\n\n" + \
                      "\n".join(rows_account(report))
    if report["unmapped"]:
        options = [ignore_label(report), NO_LABEL]
    return {"applied": False, "edited_paths": [], "asked": True,
            "reason": answer, "options": options, "report": report}


def _source_record(output_dir: str | Path, import_id: str) -> dict | None:
    for rec in in_inbox(output_dir):
        if str(rec.get("id")) == import_id:
            return rec
    return None


def _fixed_mapping(pending: dict) -> Callable[[str], str]:
    """The mapping that was SHOWN, handed back as the proposal.

    The second turn must not re-ask a model what the columns mean: it could
    answer differently, and then the import that happened is not the import
    that was agreed to. The exact-name matches are re-derived (they are
    arithmetic); this supplies the rest.
    """
    pairs = {str(c.get("column")): str(c.get("field"))
             for c in (pending.get("columns") or []) if isinstance(c, dict)}
    return lambda _prompt: json.dumps(pairs)


def database_url(output_dir: str | Path) -> str:
    """The database this project's rows belong in, or "".

    The preview's, when one is running — reached exactly the way
    `preview_manager` builds it, because a second spelling of the same URL is
    a second thing to keep right. Otherwise whatever the operator has put in
    the environment, which is how a UAT host or a developer points at theirs.
    """
    import os

    short = Path(output_dir).name
    try:
        from services.preview_manager import get_environment_status
        running = get_environment_status(short) or {}
    except Exception:  # noqa: BLE001 — no preview manager is not an error
        running = {}
    port = running.get("db_port")
    if port:
        return f"postgresql://postgres:postgres@localhost:{port}/{short}"
    return os.environ.get("DATABASE_URL", "")


def _seed_now(output_dir: str | Path, *, reasoning: Any = None) -> str:
    """Run the app's seeder if its database is reachable; say what happened.

    Not a new script and no new switch: `src/db/seed.ts` ensures the admin,
    applies every import that has not been applied, and leaves a populated
    table alone. That is exactly the right behaviour after an import, so the
    command is the one the app already runs on boot.

    When no database is reachable this says nothing and the summary says the
    honest thing instead — the rows are in the application's own data and
    land when it next starts. An import that claimed to have reached a
    database it never found would be the one lie this feature cannot afford.
    """
    import os
    import subprocess

    app = Path(output_dir) / "app"
    seed = app / "src" / "db" / "seed.ts"
    url = database_url(output_dir)
    if not seed.is_file() or not url:
        return ""
    try:
        proc = subprocess.run(["npx", "tsx", "src/db/seed.ts"], cwd=str(app),
                              capture_output=True, text=True, timeout=300,
                              env={**os.environ, "DATABASE_URL": url})
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("[import] seeder did not run: %s", exc)
        return ""
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        return (f"They are written into the application's data, but the "
                f"database did not take them just now: {tail[0][:200]}. They "
                f"land the next time it starts.")
    tell(reasoning, "The application's database has taken the rows.", "step")
    return "They are in the application's database now."


__all__ = [
    "ImportRefused", "Rejected", "accept", "agreed", "apply", "blocked", "clear",
    "coerce", "entities_of", "ignore_label", "import_id_for", "imports_of",
    "in_inbox", "inbox_dir", "is_spreadsheet", "loadable_fields", "match_exact",
    "database_url", "newest", "norm", "payload_path", "peek", "plan",
    "read_sheet", "reconcile", "remember", "rows_account",
    "run", "summary_of", "summary_of_plan", "table_of", "wants",
    "GO_LABEL", "NO_LABEL", "INBOX", "PENDING", "SHEET_EXT",
]
