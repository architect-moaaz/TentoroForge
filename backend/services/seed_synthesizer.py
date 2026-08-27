"""Deterministic seed-row synthesizer — populates the domain tables.

The shipped seeder (`templates/runtime/seed.ts`) reads demo rows from
`contracts/seed-plan.json` via `t.seed_data || plan.sample_data[name] ||
plan.seed_data[name]`. NO generator ever populated that dict, and the seeder
never consumed the plan's `row_count`, so every generated app booted with the
admin user only and EMPTY domain tables (pipeline-reliability-atlas finding V1).

`synthesize_seed_rows(output_dir)` closes that hole on the Python side: it reads
the REAL Drizzle schema (`src/db/schema/*.ts`) for each planned table's columns,
types, enums, NOT-NULL flags and foreign keys, then synthesizes `row_count`
type-valid rows per table in dependency order — minting a deterministic UUID id
per row so a child's FK column can reference a real parent id. The rows are
written back into seed-plan.json under BOTH the per-table `seed_data` field and
a top-level `sample_data[name]` bag, matching every shape seed.ts reads.

Deterministic (a given output dir always yields identical bytes), idempotent
(a re-run overwrites with the same content), and never raises — a synthesizer
failure leaves the plan untouched and returns zero counts.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid

from services.entity_names import singularize

logger = logging.getLogger(__name__)

# `export const authors = pgTable("authors", ...` — const name + pgTable arg.
_EXPORT_TABLE_RE = re.compile(
    r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*pgTable\s*\("
)
# `export const statusEnum = pgEnum('status', [ 'a', 'b' ])` — const + value list.
_PGENUM_RE = re.compile(
    r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*pgEnum\(\s*['\"][^'\"]*['\"]\s*,\s*\[(.*?)\]",
    re.DOTALL,
)
_QUOTED_RE = re.compile(r"['\"]([^'\"]*)['\"]")
# Head of a column definition: `authorId: uuid("author_id")` → prop, constructor.
_COL_HEAD_RE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*)\s*\(")
# Inline FK: `.references(() => authors.id)` → target const.
_INLINE_FK_RE = re.compile(r"\.references\(\s*\(\s*\)\s*=>\s*([A-Za-z_$][\w$]*)\s*\.")
# Block FK: foreignKey({ columns: [t.bookId], foreignColumns: [books.id] }).
_BLOCK_FK_RE = re.compile(
    r"foreignKey\(\s*\{.*?columns:\s*\[\s*[A-Za-z_$][\w$]*\.([A-Za-z_$][\w$]*)\s*\]"
    r".*?foreignColumns:\s*\[\s*([A-Za-z_$][\w$]*)\s*\.",
    re.DOTALL,
)

from services.seed_values import column_role, value_for_role

_INT_CTORS = {"integer", "serial", "bigserial", "smallint", "bigint", "smallserial"}
_NUM_CTORS = {"decimal", "numeric", "real", "doubleprecision", "double"}
_STR_CTORS = {"varchar", "text", "char", "character"}


def _canon(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _singularish(c: str) -> str:
    """Fold an already-`_canon`-ed table/entity name to singular.

    Delegates to :func:`services.entity_names.singularize` — the single
    naming authority. Dropping one trailing 's' folded `categories` to
    `categorie`, which never matched the entity `category`, so the seed
    synthesizer silently failed to find the schema table for every
    irregular plural and seeded nothing for it."""
    return singularize(c)


def _paren_match(text: str, open_idx: int) -> tuple[str, int]:
    """Body between the paren at `open_idx` and its match; returns (body, close_idx)."""
    depth = 0
    for j in range(open_idx, len(text)):
        ch = text[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:j], j
    return text[open_idx + 1:], len(text)


def _first_brace_body(text: str) -> str:
    """The first `{ ... }` object body within `text` (brace-matched)."""
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    for j in range(start, len(text)):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:j]
    return text[start + 1:]


def _split_top_level(body: str) -> list[str]:
    """Split a columns-object body into top-level, comma-separated segments."""
    segs: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            segs.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        segs.append("".join(cur))
    return segs


def _parse_schema(output_dir: str) -> tuple[list[dict], dict[str, list[str]]]:
    """Parse every schema file → (tables, enum_map).

    tables: [{const, arg, columns: [{name, ctor, family, notNull, hasDefault,
             isPk, isFk, fkTargetConst, enumValues}]}]
    enum_map: enumConstName -> [values]
    """
    sdir = os.path.join(output_dir, "src", "db", "schema")
    tables: list[dict] = []
    enum_map: dict[str, list[str]] = {}
    if not os.path.isdir(sdir):
        return tables, enum_map

    files = sorted(f for f in os.listdir(sdir) if f.endswith(".ts"))
    texts: dict[str, str] = {}
    for fn in files:
        try:
            with open(os.path.join(sdir, fn), encoding="utf-8") as fh:
                texts[fn] = fh.read()
        except OSError:
            continue

    # Enums first (may be declared in any file, referenced from another).
    for text in texts.values():
        for m in _PGENUM_RE.finditer(text):
            vals = _QUOTED_RE.findall(m.group(2))
            if vals:
                enum_map[m.group(1)] = vals

    for text in texts.values():
        for m in _EXPORT_TABLE_RE.finditer(text):
            const_name = m.group(1)
            paren_idx = text.index("(", m.end() - 1)
            call_body, _ = _paren_match(text, paren_idx)
            # arg = first string literal in the call (the pgTable name).
            arg_m = re.search(r"['\"]([^'\"]+)['\"]", call_body)
            arg = arg_m.group(1) if arg_m else const_name
            cols_body = _first_brace_body(call_body)
            # Everything after the columns object holds foreignKey({...}) blocks.
            tail = call_body[call_body.find(cols_body) + len(cols_body):] if cols_body else call_body

            columns: list[dict] = []
            for seg in _split_top_level(cols_body):
                head = _COL_HEAD_RE.match(seg)
                if not head:
                    continue
                name, ctor = head.group(1), head.group(2)
                lc = ctor.lower()
                enum_values = enum_map.get(ctor)
                if enum_values:
                    family = "enum"
                elif lc == "uuid":
                    family = "uuid"
                elif lc in _INT_CTORS:
                    family = "int"
                elif lc in _NUM_CTORS:
                    family = "num"
                elif lc == "boolean":
                    family = "bool"
                elif lc in ("timestamp", "datetime"):
                    family = "timestamp"
                elif lc in ("date", "time"):
                    family = "date"
                elif lc in ("json", "jsonb"):
                    family = "json"
                else:
                    family = "str"
                inline_fk = _INLINE_FK_RE.search(seg)
                columns.append({
                    "name": name,
                    "ctor": ctor,
                    "family": family,
                    "notNull": ".notNull(" in seg,
                    "hasDefault": (".default(" in seg or ".defaultRandom(" in seg
                                   or ".defaultNow(" in seg),
                    "isPk": ".primaryKey(" in seg,
                    "isFk": bool(inline_fk),
                    "fkTargetConst": inline_fk.group(1) if inline_fk else None,
                    "enumValues": enum_values,
                })

            # Block foreignKey() declarations bind a local column to a target const.
            by_name = {c["name"]: c for c in columns}
            for fm in _BLOCK_FK_RE.finditer(tail):
                local, target = fm.group(1), fm.group(2)
                col = by_name.get(local)
                if col is not None:
                    col["isFk"] = True
                    col["fkTargetConst"] = target

            tables.append({"const": const_name, "arg": arg, "columns": columns})
    return tables, enum_map


def _humanize(token: str) -> str:
    """`author_status`/`authorStatus` → `Author Status`."""
    spaced = re.sub(r"[_\-]+", " ", token)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return " ".join(w.capitalize() for w in spaced.split())


def _label_for(table: dict) -> str:
    base = _singularish(_canon(table["arg"] or table["const"]))
    human = _humanize(table["arg"] or table["const"])
    # singular-ish human label
    parts = human.split()
    if parts and len(parts[-1]) > 3 and parts[-1].lower().endswith("s"):
        parts[-1] = parts[-1][:-1]
    return " ".join(parts) or base or "Item"


def _det_uuid(seed_key: str, const: str, i: int, salt: str = "") -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"forge-seed:{seed_key}:{const}:{salt}:{i}"))


def _value_for(col: dict, seed_key: str, const: str, label: str, i: int):
    """A deterministic, type-valid value for a no-default, non-key column."""
    fam = col["family"]
    name = col["name"]
    nlow = name.lower()
    if fam == "uuid":
        return _det_uuid(seed_key, const, i, salt=name)
    if fam == "int":
        return (i * 7 + 3) % 97 + 1
    if fam == "num":
        return f"{(i + 1) * 12}.50"
    if fam == "bool":
        return i % 2 == 0
    if fam == "date":
        return f"2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
    if fam == "timestamp":
        return f"2026-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}T09:00:00.000Z"
    if fam == "json":
        return {}
    # string family. Role-aware values first: a `recipientName` should read
    # "Priya Raman", not "Notification 10" — see services/seed_values. Seed
    # rows are declared fake and exist so the UI can be seen working, so a
    # plausible value teaches more while claiming no more.
    role = column_role(name, label)
    shaped = value_for_role(role, name, label, i)
    if shaped is not None:
        return shaped
    if "email" in nlow:
        return f"{_canon(label) or 'user'}{i + 1}@example.com"
    if "phone" in nlow:
        return f"555-01{(i + 1) % 100:02d}"
    if any(k in nlow for k in ("name", "title", "label")):
        return f"{label} {i + 1}"
    if "slug" in nlow:
        return f"{_canon(label) or 'item'}-{i + 1}"
    if any(k in nlow for k in ("description", "notes", "body", "bio", "comment")):
        return f"Sample {_humanize(name).lower()} for {label} {i + 1}."
    # generic short string, keyed by index so `.unique()` columns stay unique
    return f"{_humanize(name)} {i + 1}"


def _plan_enum_values(output_dir: str) -> dict[tuple[str, str], list[str]]:
    """(canon(entity-or-table), column_lower) -> enum_values from plan.json.

    The Drizzle schema only carries enum values for pgEnum columns; plans
    routinely type status/priority columns as plain varchar WITH declared
    enum_values. Without this map those columns fell through to the generic
    string family and seeded literals like "Status 10" — which then became
    kanban lanes, filter chips, and badge labels app-wide (cwx1stzz).
    """
    out: dict[tuple[str, str], list[str]] = {}
    plan_fp = os.path.join(output_dir, "src", "contracts", "plan.json")
    if not os.path.isfile(plan_fp):
        plan_fp = os.path.join(output_dir, "contracts", "plan.json")
    try:
        with open(plan_fp, encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, ValueError):
        return out
    ents = plan.get("entities") or {}
    items = ents.items() if isinstance(ents, dict) else [
        (e.get("name"), e) for e in ents if isinstance(e, dict)]
    for name, ent in items:
        if not isinstance(ent, dict):
            continue
        keys = {_canon(str(name))}
        if ent.get("table"):
            keys.add(_canon(str(ent["table"])))
        for f in ent.get("fields") or []:
            vals = f.get("enum_values")
            if isinstance(vals, list) and vals and f.get("name"):
                for k in keys:
                    out[(k, str(f["name"]).lower())] = [str(v) for v in vals]
    return out


def _order_tables(plan_tables: list[dict], schema_by_canon: dict[str, dict]) -> list[tuple]:
    """Return [(plan_entry, schema_table)] in dependency order (FK targets first).

    Primary order is the plan `order` field (else array index); then a stable
    topological pass moves any table that FKs to another in-set table after it.
    """
    resolved: list[tuple] = []
    for idx, pe in enumerate(plan_tables):
        if not isinstance(pe, dict):
            continue
        st = schema_by_canon.get(_canon(pe.get("name")))
        if st is None:
            st = schema_by_canon.get(_singularish(_canon(pe.get("name"))))
        if st is None:
            continue
        order = pe.get("order")
        resolved.append((order if isinstance(order, (int, float)) else idx, idx, pe, st))
    resolved.sort(key=lambda r: (r[0], r[1]))
    ordered = [(pe, st) for _, _, pe, st in resolved]

    # topological safety: ensure every FK-target table precedes its dependents.
    in_set = {t["const"] for _, t in ordered}
    result: list[tuple] = []
    placed: set[str] = set()
    remaining = list(ordered)
    # iterate until stable; bounded by len to avoid a cycle hang
    for _ in range(len(remaining) + 1):
        progressed = False
        pending = []
        for pe, st in remaining:
            deps = {
                c["fkTargetConst"] for c in st["columns"]
                if c.get("isFk") and c.get("fkTargetConst") in in_set
                and c.get("fkTargetConst") != st["const"]
            }
            if deps <= placed:
                result.append((pe, st))
                placed.add(st["const"])
                progressed = True
            else:
                pending.append((pe, st))
        remaining = pending
        if not remaining:
            break
        if not progressed:  # cycle — emit the rest in current order
            result.extend(remaining)
            break
    return result


def synthesize_seed_rows(output_dir: str) -> dict:
    """Synthesize sample rows into seed-plan.json. Returns {tables, rows_total}."""
    try:
        plan_path = os.path.join(output_dir, "contracts", "seed-plan.json")
        if not os.path.isfile(plan_path):
            return {"tables": 0, "rows_total": 0}
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        if not isinstance(plan, dict):
            return {"tables": 0, "rows_total": 0}

        schema_tables, _enum_map = _parse_schema(output_dir)
        schema_by_canon: dict[str, dict] = {}
        for st in schema_tables:
            for token in (st["const"], st["arg"]):
                schema_by_canon.setdefault(_canon(token), st)
                schema_by_canon.setdefault(_singularish(_canon(token)), st)

        plan_tables = plan.get("tables") if isinstance(plan.get("tables"), list) else []
        seed_key = os.path.basename(os.path.normpath(output_dir))

        ordered = _order_tables(plan_tables, schema_by_canon)
        plan_enums = _plan_enum_values(output_dir)

        ids_by_const: dict[str, list[str]] = {}
        rows_by_name: dict[str, list[dict]] = {}
        tables_done = 0
        rows_total = 0

        for pe, st in ordered:
            name = pe.get("name")
            const = st["const"]
            # Reserved: auth seeds the admin user separately.
            if _canon(name) == "users" or _canon(st["arg"]) == "users":
                continue
            rc = pe.get("row_count")
            row_count = int(rc) if isinstance(rc, (int, float)) and rc > 0 else 8
            label = _label_for(st)

            ids = [_det_uuid(seed_key, const, i) for i in range(row_count)]
            ids_by_const[const] = ids

            rows: list[dict] = []
            for i in range(row_count):
                row: dict = {}
                for col in st["columns"]:
                    if col["isPk"]:
                        row[col["name"]] = ids[i] if col["family"] == "uuid" else (i + 1)
                        continue
                    if col["isFk"]:
                        pool = ids_by_const.get(col.get("fkTargetConst"))
                        if pool:
                            row[col["name"]] = pool[i % len(pool)]
                        # No pool — leave the column absent. If notNull, the
                        # runtime seed's FK-fill loop backfills from the ids
                        # dict at insert time (seedAdmin pre-populates
                        # ids["users"] with the admin id; other parents are
                        # populated as their tables seed in order).
                        # PREVIOUSLY: we minted a dangling deterministic UUID
                        # here for notNull FKs, but that UUID never referenced
                        # a real row → Postgres FK-violation → every child
                        # insert silently failed → SEED MISMATCH.
                        continue
                    ev = col["enumValues"] or plan_enums.get(
                        (_canon(st["arg"]), col["name"].lower())) or plan_enums.get(
                        (_canon(name), col["name"].lower()))
                    if ev:
                        row[col["name"]] = ev[i % len(ev)]
                        continue
                    if col["hasDefault"]:
                        continue  # let the DB fill its default
                    row[col["name"]] = _value_for(col, seed_key, const, label, i)
                rows.append(row)

            rows_by_name[name] = rows
            tables_done += 1
            rows_total += len(rows)

        # Write back: per-table seed_data (read first by seed.ts) + sample_data bag.
        sample_data: dict[str, list[dict]] = {}
        for pe in plan_tables:
            if not isinstance(pe, dict):
                continue
            nm = pe.get("name")
            if nm in rows_by_name:
                pe["seed_data"] = rows_by_name[nm]
                sample_data[nm] = rows_by_name[nm]
        plan["sample_data"] = sample_data

        tmp = plan_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, plan_path)

        return {"tables": tables_done, "rows_total": rows_total}
    except Exception as e:  # noqa: BLE001 — never break the pipeline
        logger.warning("seed_synthesizer failed: %s", e)
        return {"tables": 0, "rows_total": 0}
