# backend/services/crud_workflow_generator.py
"""Deterministic CRUD workflow generation.

For each entity, emit Create/Update/Delete<Entity> workflow definitions whose
single action node runs db_insert/db_update/db_delete. Shape matches the runtime
workflow contract (node.data.config.actionType + table + where/values maps of
column -> process-variable). Mechanical — no LLM, so no hallucinated names.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.entity_names import EntityNameError, derive_names, entity_key
from services.schema_tables import schema_files

logger = logging.getLogger(__name__)

# Columns the platform manages itself — never user-supplied on create/update.
# deletedAt is a soft-delete timestamp: including it as a "" string insert value
# crashes Drizzle's timestamp mapper (value.toISOString is not a function).
_MANAGED = {
    "id", "createdat", "updatedat", "deletedat",
    "created_at", "updated_at", "deleted_at",
}


def _writable(fields: list[dict]) -> list[str]:
    out = []
    for f in fields or []:
        name = f.get("name") if isinstance(f, dict) else None
        if name and name.lower() not in _MANAGED:
            out.append(name)
    return out


def _node(node_id: str, ntype: str, x: int, config: dict, label: str) -> dict:
    return {"id": node_id, "type": ntype, "position": {"x": x, "y": 0},
            "data": {"config": config, "label": label}}


def build_crud_workflow(
    entity: str,
    table: str,
    fields: list[dict],
    op: str,
    pk: str | None = None,
    children: list[dict] | None = None,
) -> dict:
    """Build one CRUD workflow dict. op in {create, update, delete}.

    ``pk`` is the table's real primary-key column, read from the parsed
    Drizzle schema by :func:`generate_crud_workflows`. Update/Delete used
    to hardcode ``where {"id": "id"}`` even when the schema said otherwise,
    so every Update/Delete workflow for a table keyed on ``uuid`` /
    ``candidate_id`` / ``code`` referenced a column that does not exist.
    At runtime ``_buildWhere`` drops the unmatched field and then refuses
    with "WHERE resolved to zero conditions" — the button does nothing.

    Passing ``None`` keeps the ``id`` default for callers with no schema
    at hand, but a table whose real key is known and is NOT ``id`` must
    supply it.
    """
    writable = _writable(fields)
    op_cap = op.capitalize()
    name = f"{op_cap}{entity}"
    slug = f"{op}-{entity.lower()}"

    key = (pk or "id").strip() or "id"
    # Canonical `{{name}}` refs, not bare identifiers. Bare names only resolve
    # when the variable is BOTH declared and supplied; an unsupplied bare name
    # in `values` silently writes the literal string into the column.
    key_ref = "{{" + key + "}}"

    cascade_nodes: list[dict] = []
    if op == "create":
        config = {"actionType": "db_insert", "table": table,
                  "values": {f: "{{" + f + "}}" for f in writable}}
        pvars = writable
        action_type = "db_insert"
    elif op == "update":
        config = {"actionType": "db_update", "table": table,
                  "where": {key: key_ref},
                  "values": {f: "{{" + f + "}}" for f in writable}}
        pvars = [key, *writable]
        action_type = "db_update"
    elif op == "delete":
        config = {"actionType": "db_delete", "table": table, "where": {key: key_ref}}
        pvars = [key]
        action_type = "db_delete"
        # Dependent rows first: a child table with an FK into this one makes
        # the bare DELETE fail with a foreign-key violation, so every Delete
        # button silently did nothing (register: dxlc5m31 Discard Scan).
        # One level deep covers the overwhelmingly common case; the nodes are
        # continueOnError so a child table with no matching rows (or its own
        # grandchildren) degrades to the old behaviour instead of a dead stop.
        for i, child in enumerate(children or []):
            ct, cf = child.get("table"), child.get("fk")
            if not ct or not cf or (ct == table and cf == key):
                continue
            cascade_nodes.append(_node(
                f"cascade_{i}_{ct}", "action", 100 + i * 40,
                {"actionType": "db_delete", "table": ct,
                 "where": {cf: key_ref}, "continueOnError": True},
                f"Delete dependent {ct}",
            ))
    else:
        raise ValueError(f"unknown crud op: {op}")

    nodes = [
        _node("trigger", "trigger", 0, {"type": "manual"}, "Start"),
        *cascade_nodes,
        _node(action_type, "action", 200, config, f"{op_cap} {entity}"),
        _node("end", "end", 400, {}, "End"),
    ]
    chain = ["trigger", *(n["id"] for n in cascade_nodes), action_type, "end"]
    edges = [
        {"id": f"e{i}", "source": a, "target": b}
        for i, (a, b) in enumerate(zip(chain, chain[1:]))
    ]
    # Carry the REAL column type through (register CRUD-11).
    #
    # Every process variable was declared `"string"`, discarding the type the
    # schema parser had already resolved — so an integer / boolean / date
    # column was announced to the editor and the form builder as free text, and
    # the user got a text box for a number.
    _types = {
        f.get("name"): f.get("type")
        for f in (fields or [])
        if isinstance(f, dict) and f.get("name")
    }
    # `required` reflects the COLUMN, not a blanket True (register WFW-1).
    #
    # Every process variable was emitted `required: True`, so wire_form_workflow
    # treated an unmatched OPTIONAL input as a hard failure and refused to wire
    # the form at all — one nullable column with no matching field blocked the
    # entire wiring. The key is genuinely required (the WHERE needs it); a data
    # column is required only when the schema says NOT NULL with no default.
    _req = {
        f.get("name"): bool(f.get("not_null")) and not f.get("has_default")
        for f in (fields or [])
        if isinstance(f, dict) and f.get("name")
    }
    process_vars = [
        {
            "name": p,
            "type": _process_var_type(_types.get(p), p, key),
            "required": True if p == key else _req.get(p, True),
        }
        for p in pvars
    ]
    return {
        "id": slug,
        "name": name,
        "description": f"{op_cap} a {entity} record.",
        "processVariables": process_vars,
        # `definition.trigger` is required by the runtime engine (it reads
        # `workflow.definition.trigger.inputMapping`). With no inputMapping the
        # engine copies all input fields into process variables — exactly what
        # these CRUD workflows want (input keys == process-var names == fields).
        "definition": {"trigger": {"type": "manual"}, "nodes": nodes, "edges": edges},
    }


class UnsafeWorkflowNameError(ValueError):
    """Raised when a workflow name cannot be turned into a safe filename."""


# Anything that can leave the target directory, address an NTFS alternate data
# stream, or name a Windows device. Entity names come from a planner / an LLM /
# user text, so they are untrusted input on a filesystem write path.
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_workflow_path(wdir: Path, workflow_name: str) -> Path:
    """Resolve ``<wdir>/<workflow_name>.json``, refusing anything that escapes.

    The destination filename was interpolated straight from the entity name,
    which is untrusted. Three register findings share that one root cause:

    * **CRUD-3** — a ``:`` in an entity name (``"Order:Draft"``) makes Windows
      open an NTFS *alternate data stream*. The write "succeeds", nothing is
      raised, and the visible file is 0 bytes.
    * **CRUD-10** — ``../`` in an entity name writes outside the project.
    * **CRUD-12** — no sanitisation of names/ids in general.

    Sanitising alone is not enough: the result is re-resolved and checked to be
    inside ``wdir``, so any escape that survives normalisation is still caught.
    Raises :class:`UnsafeWorkflowNameError` rather than writing somewhere
    unintended — a silent write to the wrong path is exactly the failure mode.
    """
    raw = str(workflow_name or "").strip()
    if not raw:
        raise UnsafeWorkflowNameError("workflow name is empty")

    cleaned = _UNSAFE_NAME_CHARS.sub("_", raw).strip(" .")
    if not cleaned or set(cleaned) <= {"_", "."}:
        raise UnsafeWorkflowNameError(
            f"workflow name {workflow_name!r} contains nothing usable as a filename"
        )
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"{cleaned}_wf"
    if cleaned != raw:
        logger.warning(
            "crud_workflow_generator: workflow name %r is not filesystem-safe; "
            "writing as %r instead.", raw, cleaned,
        )

    dest = (wdir / f"{cleaned}.json").resolve()
    root = wdir.resolve()
    if root != dest.parent:
        raise UnsafeWorkflowNameError(
            f"workflow name {workflow_name!r} resolves to {dest} which is outside "
            f"the workflows directory {root} — refusing to write"
        )
    return dest


# Drizzle/SQL column type → the process-variable type the editor understands.
_PVAR_TYPE_BY_SQL: dict[str, str] = {
    "integer": "number", "int": "number", "int4": "number", "int8": "number",
    "bigint": "number", "smallint": "number", "serial": "number",
    "bigserial": "number", "numeric": "number", "decimal": "number",
    "real": "number", "double": "number", "float": "number", "money": "number",
    "boolean": "boolean", "bool": "boolean",
    "timestamp": "date", "timestamptz": "date", "date": "date",
    "time": "date", "datetime": "date",
    "json": "object", "jsonb": "object",
    "uuid": "string", "text": "string", "varchar": "string", "char": "string",
}


def _process_var_type(sql_type: object, var_name: str, pk: str) -> str:
    """The declared type for one process variable.

    The key column stays a string (it is an id reference, not a value the user
    types). Anything the schema typed is mapped; anything unknown falls back to
    "string", which is the old behaviour for exactly the cases where we still
    know nothing."""
    if var_name == pk:
        return "string"
    t = str(sql_type or "").strip().lower()
    if not t:
        return "string"
    return _PVAR_TYPE_BY_SQL.get(t, "string")


def _derive_table(entity: str) -> str:
    """The DB table an entity maps to, per the single naming authority.

    Delegates to :func:`services.entity_names.derive_names` — do NOT
    re-derive this locally. The private pluralizer that used to live here
    appended a bare ``'s'`` and disagreed with the authority on 15 of
    every 20 names, so ``Category`` generated CRUD against ``categorys``
    and every one of those workflows failed at runtime with `unknown
    table` (register finding CRUD-1, CRITICAL).

    Raises :class:`services.entity_names.EntityNameError` on a nameless
    entity rather than inventing a table for it."""
    return derive_names(entity).tableSnake


def _norm_entity(name: str) -> str:
    """Normalize an entity name for singular/plural dedup so 'Customer'
    and 'Customers' group together.

    Delegates to :func:`services.entity_names.entity_key`, which unwinds
    the same pluralization rules :func:`_derive_table` applies. The old
    "drop one trailing s" split irregulars apart — 'Categories' reduced
    to 'categorie' while 'Category' reduced to 'category', so the pair
    never merged and CRUD was generated twice."""
    return entity_key(name)


def _dedup_entities(entities: dict, real_tables: dict) -> list[tuple[str, dict]]:
    """Collapse singular/plural duplicate entities (e.g. Customer + Customers) that
    map to the same table — a planner/extraction artifact that otherwise doubles
    every CRUD workflow. Returns canonical (name, info) pairs.

    Two entities are merged only when they normalize to the same base AND resolve
    to the same table. Within a group the canonical pick prefers a name whose table
    exists in the real schema, then the shorter (singular) name for readable
    workflow names (CreateCustomer over CreateCustomers)."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for name, info in entities.items():
        if not isinstance(info, dict):
            logger.error(
                "crud_workflow_generator: entity %r has a %s instead of a dict — "
                "skipped; no CRUD workflows will exist for it.",
                name, type(info).__name__,
            )
            continue
        # Per-entity isolation runs HERE too, because this dedup pass touches
        # every entity BEFORE the generation loop does. Without it one
        # unnameable entity raised out of the dedup and no entity at all got
        # CRUD workflows — the whole pipeline lost its CRUD layer over a single
        # malformed record.
        try:
            table = info.get("table") or _derive_table(name)
            key = _norm_entity(name)
        except EntityNameError as e:
            logger.error(
                "crud_workflow_generator: entity %r cannot be named (%s) — skipped; "
                "every OTHER entity is unaffected.", name, e,
            )
            continue
        groups.setdefault((key, table), []).append((name, info))

    canonical: list[tuple[str, dict]] = []
    for (_, table), members in groups.items():
        if len(members) == 1:
            canonical.append(members[0])
            continue
        winner = max(members, key=lambda m: (table in real_tables, -len(m[0])))
        # MERGE the losers' fields into the winner (register CRUD-6).
        #
        # The winner was returned as-is and every other member discarded whole,
        # so a column declared on only one spelling — `Customer.name` and
        # `Customers.email` are one table — simply vanished from the generated
        # form. The two entries describe the SAME table; the union is the only
        # reading that does not lose data. The winner's own definition of a
        # field always wins a conflict.
        merged = _merge_member_fields(winner, [m for m in members if m is not winner])
        canonical.append(merged)
    return canonical


def _merge_member_fields(
    winner: tuple[str, dict], losers: list[tuple[str, dict]],
) -> tuple[str, dict]:
    """Union the losers' field definitions into a copy of the winner."""
    name, info = winner
    if not losers:
        return winner

    def _as_map(fields: object) -> dict:
        if isinstance(fields, dict):
            return dict(fields)
        if isinstance(fields, list):
            return {f["name"]: {k: v for k, v in f.items() if k != "name"}
                    for f in fields if isinstance(f, dict) and f.get("name")}
        return {}

    combined = _as_map(info.get("fields"))
    added: list[str] = []
    for lname, linfo in losers:
        for fname, fmeta in _as_map(linfo.get("fields")).items():
            if fname not in combined:
                combined[fname] = fmeta
                added.append(f"{lname}.{fname}")
    if added:
        logger.info(
            "crud_workflow_generator: merged %d field(s) from duplicate entity "
            "spelling(s) into %r: %s",
            len(added), name, ", ".join(sorted(added)),
        )
    out = dict(info)
    out["fields"] = combined
    return (name, out)


# Match the START of a pgTable definition; the body is then extracted by
# brace-balancing (NOT a non-greedy regex, which truncates at the first inner
# `}` — e.g. the `}` of `varchar("x", { length: 255 })`).
_PGTABLE_OPEN_RE = re.compile(r'pgTable\(\s*["\']([^"\']+)["\']\s*,\s*\{')
_COL_RE = re.compile(r"(\w+)\s*:\s*(\w+)\(")


def _split_top_level(body: str) -> list[str]:
    """Split a pgTable body on commas that are NOT inside (), {} or [] or a
    string. One element per column definition, however it is line-wrapped."""
    out: list[str] = []
    depth = 0
    quote: str | None = None
    cur: list[str] = []
    prev = ""
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote and prev != "\\":
                quote = None
            prev = ch
            continue
        if ch in "\"'`":
            quote = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        prev = ch
    if cur:
        out.append("".join(cur))
    return out


def _balanced_body(src: str, open_brace_idx: int) -> str:
    """Return the text inside the {...} starting at `open_brace_idx` (the `{`),
    matching nested braces. Empty string if unbalanced."""
    depth = 0
    i = open_brace_idx
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[open_brace_idx + 1:i]
        i += 1
    return ""


def _parse_schema_columns(output_dir: str) -> dict[str, list[dict]]:
    """Parse the generated Drizzle schema for real column definitions.

    Reads every ``*.ts`` under ``output_dir/src/db/schema/`` and
    ``output_dir/src/db/`` and parses each
    ``export const <var> = pgTable("<sqlname>", { ... })`` block.

    Returns ``{ "<sqlname>": [ {name, type, not_null, has_default,
    primary_key} ] }`` keyed by the SQL table name (the string literal),
    not the JS variable. Column detection mirrors
    ``services.seed_backstop.parse_pg_tables``.
    """
    # Schema location comes from services.schema_tables — the single
    # authority — so this parser and workflow_table_guard can never again
    # disagree about which layouts exist (register finding TG-2).
    # required=False: a plan-only run legitimately has no schema yet and
    # falls back to the plan's own field list below.
    files = schema_files(output_dir, required=False)

    tables: dict[str, list[dict]] = {}
    for f in files:
        try:
            src = f.read_text()
        except Exception:
            continue
        for m in _PGTABLE_OPEN_RE.finditer(src):
            sqlname = m.group(1)
            body = _balanced_body(src, m.end() - 1)  # m.end()-1 is the `{`
            cols: list[dict] = []
            # Split on TOP-LEVEL commas, not on newlines.
            #
            # Parsing line by line meant a column definition wrapped across
            # lines — which is exactly what prettier produces for anything
            # long — was read wrong in two ways:
            #
            #     email: varchar("email", { length: 255 })
            #       .notNull()            <- invisible: modifiers on their own line
            #       .unique(),
            #
            #     fullName:
            #       varchar("full_name", …)   <- invisible: no match at all,
            #                                    the column simply disappeared
            #
            # So a NOT NULL column looked nullable and a defaulted column
            # looked plain, which is what decides the writable-column set and
            # therefore what the generated form asks the user for.
            for entry in _split_top_level(body):
                entry = entry.strip().rstrip(",")
                if not entry:
                    continue
                # Collapse the whole entry to one line before matching, so the
                # name/type pair and every chained modifier are all visible.
                flat = " ".join(entry.split())
                cm = _COL_RE.match(flat)
                if not cm:
                    continue
                cols.append({
                    "name": cm.group(1),
                    "type": cm.group(2),
                    "not_null": ".notNull()" in flat,
                    "has_default": (".default" in flat or ".defaultNow()" in flat
                                    or ".defaultRandom()" in flat or ".$default" in flat),
                    "primary_key": ".primaryKey()" in flat,
                })
            # When the same SQL table is defined in more than one file, keep the
            # fuller definition (most columns) rather than last-wins.
            if cols and len(cols) >= len(tables.get(sqlname, [])):
                tables[sqlname] = cols
    return tables


_PGTABLE_VAR_RE = re.compile(
    r'const\s+(\w+)\s*=\s*pgTable\(\s*["\']([^"\']+)["\']\s*,\s*\{'
)
_REF_RE = re.compile(r'\.references\(\s*\(\)\s*=>\s*(\w+)\.(\w+)')


def parse_child_references(output_dir: str) -> dict[str, list[dict]]:
    """Inbound FK map: SQL table -> children referencing it.

    Returns ``{parent_sql_table: [{"table": child_sql_table, "fk":
    child_js_column_name}, ...]}`` parsed from ``.references(() =>
    parentVar.col)`` chains in the Drizzle schema. Delete workflows use it
    to clear dependent rows before the parent DELETE — without that, any
    entity with children fails the delete on the FK constraint.
    """
    files = schema_files(output_dir, required=False)
    var_to_sql: dict[str, str] = {}
    bodies: list[tuple[str, str]] = []  # (sql_table, body)
    for f in files:
        try:
            src = f.read_text()
        except Exception:
            continue
        for m in _PGTABLE_VAR_RE.finditer(src):
            var_to_sql[m.group(1)] = m.group(2)
        for m in _PGTABLE_OPEN_RE.finditer(src):
            bodies.append((m.group(1), _balanced_body(src, m.end() - 1)))

    children: dict[str, list[dict]] = {}
    for child_sql, body in bodies:
        for entry in _split_top_level(body):
            flat = " ".join(entry.split())
            cm = _COL_RE.match(flat)
            if not cm:
                continue
            rm = _REF_RE.search(flat)
            if not rm:
                continue
            parent_sql = var_to_sql.get(rm.group(1))
            if not parent_sql:
                continue
            entry_list = children.setdefault(parent_sql, [])
            rec = {"table": child_sql, "fk": cm.group(1)}
            if rec not in entry_list:
                entry_list.append(rec)
    return children


def resolve_primary_key(output_dir: str, table: str) -> str | None:
    """The key column for ``table``, read from the app's own Drizzle schema.

    Convenience wrapper over :func:`primary_key_of` for callers that hold
    an ``output_dir`` rather than a parsed column list — namely
    :mod:`services.add_workflow_seam`, so a Smith-added workflow keys its
    WHERE on the same column fresh generation would (register S21-3).

    Returns ``None`` when the schema is absent or the table has no usable
    key; callers must not substitute ``"id"`` themselves.
    """
    return primary_key_of(schema_columns_for(output_dir, table), table=table)


def schema_columns_for(output_dir: str, table: str) -> list[dict] | None:
    """The parsed Drizzle columns for ``table``, or ``None`` if unknown.

    ``None`` means *the schema does not tell us* (no schema files, an
    unparseable schema, or no such table) — which is NOT the same as
    "this table has no primary key". Callers that must refuse on a
    missing key need that distinction: refusing when the schema is simply
    absent would block every schema-less fixture and scaffold.
    """
    try:
        real_tables = _parse_schema_columns(str(output_dir)) or {}
    except Exception as exc:  # noqa: BLE001 — never block an edit on the parser
        logger.warning(
            "crud_workflow_generator.schema_columns_for: could not parse the "
            "schema under %r (%s); treating the schema as unknown.",
            output_dir, exc,
        )
        return None
    return real_tables.get(table) or _real_cols_by_key(real_tables, table)


def primary_key_of(cols: list[dict] | None, *, table: str = "?") -> str | None:
    """The key column Update/Delete must filter on — the ONE authority.

    Both write paths need this answer and they used to disagree: fresh
    generation read the ``primary_key`` flag off the parsed Drizzle
    columns, while ``add_workflow_seam`` passed no ``pk`` at all and got
    the ``id`` default (register S21-3). On a table keyed on ``uuid`` /
    ``code`` the seam therefore emitted a WHERE against a column that
    does not exist; at runtime ``_buildWhere`` drops the unmatched field
    and refuses with "WHERE resolved to zero conditions" — the button
    silently does nothing.

    Returns the declared primary key, else ``"id"`` when the table has an
    ``id`` column (logged, because it is a guess), else ``None`` — which
    the caller MUST read as "keyed operations are impossible here", not
    as "use id".
    """
    if not cols:
        return None
    pk = next((c.get("name") for c in cols
               if isinstance(c, dict) and c.get("primary_key")), None)
    if pk:
        return pk
    col_names = {c.get("name") for c in cols if isinstance(c, dict)}
    if "id" in col_names:
        logger.warning(
            "crud_workflow_generator: table %r declares no PRIMARY KEY; "
            "falling back to its 'id' column for Update/Delete WHERE.",
            table,
        )
        return "id"
    # No key and no `id` — any Update/Delete we emit could never run.
    # Skipping the whole entity would hide it, so name the problem and let
    # the caller skip only the keyed operations.
    logger.error(
        "crud_workflow_generator: table %r has no PRIMARY KEY and no "
        "'id' column — Update/Delete workflows cannot be generated for "
        "it (any WHERE would reference a column that does not exist). "
        "Columns seen: %s. Create is still generated.",
        table, sorted(n for n in col_names if n),
    )
    return None


def _real_cols_by_key(real_tables: dict[str, list[dict]], table: str) -> list[dict] | None:
    """Find declared columns for `table` by canonical entity key.

    Only used when the exact name misses. Refuses to guess when two real
    tables share a key — an ambiguous join is worse than no join, because
    it silently writes to the wrong table."""
    try:
        want = entity_key(table)
    except EntityNameError:
        return None
    hits = [cols for name, cols in real_tables.items()
            if _safe_entity_key(name) == want]
    return hits[0] if len(hits) == 1 else None


def _safe_entity_key(name: str) -> str | None:
    try:
        return entity_key(name)
    except EntityNameError:
        return None


def generate_crud_workflows(plan: dict, output_dir: str) -> list[str]:
    """Write Create/Update/Delete<Entity>.json for each entity into
    output_dir/workflows/. Idempotent: never overwrite a workflow file that
    already has nodes (a domain/bizlogic workflow). Returns names written."""
    entities = (plan or {}).get("entities") or {}
    wdir = Path(output_dir) / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    # Real columns from the generated Drizzle schema — the source of truth for
    # NOT NULL columns (e.g. auth-added `password`) the plan often omits.
    real_tables = _parse_schema_columns(output_dir)
    try:
        child_refs = parse_child_references(output_dir)
    except Exception as exc:  # noqa: BLE001 — cascade is best-effort
        logger.warning("crud_workflow_generator: FK reference parse failed (%s); "
                       "delete workflows will not cascade.", exc)
        child_refs = {}
    written: list[str] = []
    failed: list[str] = []
    _ok_entities: list[str] = []
    for name, info in _dedup_entities(entities, real_tables):
        # Per-entity isolation.
        #
        # This loop had no guard, so the FIRST entity that raised anywhere in
        # the body — an unnameable entity, an unwritable path, a malformed
        # `fields` block — aborted the whole loop and every entity after it
        # silently got no CRUD workflows at all. The pipeline reported success
        # because generate_crud_workflows simply returned a short list.
        #
        # One bad entity must cost exactly one entity. Anything that fails is
        # named at ERROR and the sweep continues.
        try:
            _generated = _generate_for_entity(
                name, info, real_tables, wdir, child_refs=child_refs,
            )
        except Exception as e:  # noqa: BLE001 — one entity must not kill the rest
            failed.append(f"{name} ({type(e).__name__}: {e})")
            logger.error(
                "crud_workflow_generator: entity %r produced no CRUD workflows: %s",
                name, e, exc_info=True,
            )
            continue
        _ok_entities.append(name)
        written.extend(_generated)
    if failed:
        logger.error(
            "crud_workflow_generator: %d of %d entities produced NO CRUD workflows: %s. "
            "The remaining entities were generated normally.",
            len(failed), len(failed) + len(_ok_entities), "; ".join(failed),
        )
    return written


def _generate_for_entity(
    name: str,
    info: dict,
    real_tables: dict,
    wdir: Path,
    child_refs: dict[str, list[dict]] | None = None,
) -> list[str]:
    """Emit the CRUD workflows for ONE entity. Raises on anything it cannot do;
    the caller isolates the failure so the other entities still generate."""
    written: list[str] = []
    if True:
        table = info.get("table") or _derive_table(name)
        fields = info.get("fields")
        if isinstance(fields, dict):  # registry shape -> list
            fields = [{"name": k, **(v or {})} for k, v in fields.items()]
        # Prefer the real schema columns when available: writable columns are
        # those that aren't a primary key and don't have a DB default (excludes
        # id and created/updated timestamps; keeps email/password/name/etc.).
        # Exact name first, then the canonical entity key — so a plan that
        # spells the table `Categories` still joins to the declared
        # `categories` instead of silently falling back to the plan's
        # (usually thinner) field list.
        real_cols = real_tables.get(table) or _real_cols_by_key(real_tables, table)
        pk: str | None = None
        if real_cols:
            fields = [
                # Carry not_null / has_default through: build_crud_workflow
                # needs them to decide which process variables are genuinely
                # REQUIRED (register WFW-1). Dropping them here is what forced
                # the blanket `required: True`.
                {"name": c["name"], "type": c.get("type", "string"),
                 "not_null": bool(c.get("not_null")),
                 "has_default": bool(c.get("has_default"))}
                for c in real_cols
                if not c.get("primary_key") and not c.get("has_default")
            ]
            # The real key column, so Update/Delete filter on something that
            # exists. Hardcoding "id" produced a WHERE against a missing
            # column, which the runtime rejects with "WHERE resolved to zero
            # conditions" — the button silently does nothing.
            pk = primary_key_of(real_cols, table=table)
        ops = ("create", "update", "delete")
        if real_cols and pk is None:
            ops = ("create",)
        # An INSERT with no values writes a blank row (register CRUD-8).
        #
        # `values: {}` becomes `INSERT INTO t DEFAULT VALUES`, so every click of
        # the generated Create button added an empty record and the run
        # reported success. If there is nothing writable there is no create
        # form to build, so do not emit one.
        if "create" in ops and not _writable(fields or []):
            logger.warning(
                "crud_workflow_generator: entity %r has no writable columns "
                "(table %r) — skipping Create, which would have inserted an "
                "empty row on every click.", name, table,
            )
            ops = tuple(o for o in ops if o != "create")

        for op in ops:
            wf = build_crud_workflow(
                name, table, fields or [], op, pk=pk,
                children=(child_refs or {}).get(table),
            )
            dest = safe_workflow_path(wdir, wf["name"])
            if dest.exists():
                try:
                    prev = json.loads(dest.read_text())
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        "crud_workflow_generator: %s exists but is unreadable (%s) — "
                        "OVERWRITING it with the generated CRUD workflow.",
                        dest.name, e,
                    )
                else:
                    if _has_authored_content(prev):
                        continue  # real content already — never clobber it
            dest.write_text(json.dumps(wf, indent=2))
            written.append(wf["name"])
    return written


def _has_authored_content(prev: object) -> bool:
    """Does this existing workflow file contain work we must not destroy?

    The guard used to accept ONLY `definition.nodes`. A planner-shaped domain
    workflow carries `definition.steps` instead (see
    `workflow_step_translator`), so it looked empty and was OVERWRITTEN with a
    generated CRUD stub — silently destroying authored work (register CRUD-5).
    Anything that looks like real authoring counts.
    """
    if not isinstance(prev, dict):
        return False
    defn = prev.get("definition")
    if isinstance(defn, dict):
        for key in ("nodes", "steps"):
            v = defn.get(key)
            if isinstance(v, list) and v:
                return True
    # Some authored shapes keep the step list at the top level.
    for key in ("steps", "nodes"):
        v = prev.get(key)
        if isinstance(v, list) and v:
            return True
    return False
