"""Deterministic value↔column TYPE check for workflow db_insert/db_update nodes.

A workflow action node maps ``config.values[col] = expr``. An LLM-authored domain
workflow can drop the WRONG KIND of value into a column — e.g. a timestamp literal
(``CURRENT_TIMESTAMP``) into a ``uuid`` FK column, or the node's own LABEL string
into an enum/status column. Postgres then rejects the insert at runtime
("column candidate_id is of type uuid but expression is of type timestamp").

This module is the SOURCE-side type checker (the corrector lives alongside it):

- ``analyze_workflow_values(defn, columns_by_table)`` — pure detector; returns a
  list of findings, never raises. Unknown table/column → skipped (no false
  positive). Also a standalone tool the fix-assistant's verify step calls.

The value↔column compatibility matrix (a finding is emitted only on a MISMATCH):

    value kind \\ column category
                        date  uuid  enum/status  text  numeric  boolean
    template ({{..}})    ok    ok      ok         ok     ok       ok      (always ok)
    null                 ok    ok      ok         ok     ok       ok      (skip)
    timestamp_literal    ok   MISS    MISS       MISS   MISS     MISS
    iso_date             ok   MISS    MISS       MISS   MISS     MISS
    number              MISS  MISS    (skip)     (ok)    ok      MISS
    bool                MISS  MISS    (skip)     (ok)   MISS      ok
    bare_string         (ok) MISS*   MISS**     (ok)   (skip)   (skip)

    *  bare_string→uuid: mismatch only when the string is NOT a plausible
       variable identifier (has spaces / non-identifier chars) — an identifier
       equal to a process variable is a valid binding (e.g. "candidateId").
    ** bare_string→enum/status: mismatch when the string equals the node's
       ``data.label`` (a leaked label) or, when enum values are known, is not one
       of them.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

_MUTATION_ACTIONS = {"db_insert", "db_update"}

# Column-type category buckets (lowercased type string → category).
_DATE_TYPES = {"timestamp", "timestamptz", "date", "time", "datetime", "timestamp with time zone"}
_UUID_TYPES = {"uuid"}
_NUMERIC_TYPES = {
    "integer", "int", "int4", "int8", "bigint", "smallint", "serial", "bigserial",
    "numeric", "decimal", "real", "double", "double precision", "float", "money",
}
_BOOL_TYPES = {"boolean", "bool"}
_TEXT_TYPES = {"text", "varchar", "char", "character varying", "string", "citext"}

# Column NAMES that are enum/status-like even when stored as varchar/text.
_STATUS_NAMES = {"status", "state", "stage"}
_STATUS_SUFFIXES = ("status", "state", "stage")

_TIMESTAMP_LITERALS = {"current_timestamp", "now()", "current_date", "current_time", "now"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?(z|[+-]\d{2}:?\d{2})?)?$", re.I)
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_real_date(s: str) -> bool:
    """Is this ISO-SHAPED string an actual calendar date?

    The regex checked only the SHAPE, so "2026-13-45" and "2026-02-31" were
    classified as dates and then compared against date columns as if valid
    (register VT-3). A shape is not a value: parse it.
    """
    from datetime import datetime
    text = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
            return True
        except ValueError:
            continue
    # Offsets / fractional seconds — let the stdlib decide.
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _column_is_omittable(columns_by_table: dict, table: str, column: str) -> bool:
    """Can this column be left out of a write without the statement failing?

    True when it is nullable or has a default. Used to decide how loudly to
    report a dropped value (register VT-4): dropping a NOT NULL column with no
    default turns a bad write into a FAILED write, which the author must know.
    Unknown metadata is treated as omittable — we do not invent a failure.
    """
    cols = _col_type_map(columns_by_table, table) or {}
    meta = cols.get(column)
    if not isinstance(meta, dict):
        return True
    if meta.get("nullable") is False and not meta.get("has_default"):
        return False
    if meta.get("not_null") and not meta.get("has_default"):
        return False
    return True


def _category(column_type: str) -> str:
    """Bucket a raw column type string into a compatibility category."""
    t = (column_type or "").strip().lower()
    # Strip a PARAMETER list before bucketing (register VT-5).
    #
    # `varchar(255)`, `numeric(10,2)` and `timestamp(3) with time zone` never
    # matched the exact-membership sets below, so every parameterised column
    # fell through to "other" and was exempt from type checking entirely —
    # silently, and those are the commonest real declarations.
    base = re.sub(r"\s*\(.*?\)", "", t).strip()
    # e.g. "enum('a','b')" or "pgEnum" style
    if t.startswith("enum") or "enum" in t:
        return "enum"
    t = base or t
    if t in _DATE_TYPES:
        return "date"
    if t in _UUID_TYPES:
        return "uuid"
    if t in _NUMERIC_TYPES:
        return "numeric"
    if t in _BOOL_TYPES:
        return "boolean"
    if t in _TEXT_TYPES:
        return "text"
    return "other"


def _is_status_like(column_name: str, category: str) -> bool:
    if category == "enum":
        return True
    n = (column_name or "").strip().lower()
    if n in _STATUS_NAMES:
        return True
    return n.endswith(_STATUS_SUFFIXES)


def classify_value_kind(value: object) -> str:
    """Classify the KIND of a value expression: template / timestamp_literal /
    iso_date / number / bool / null / bare_string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if not isinstance(value, str):
        # dict/list — treat as a structured literal; not a simple mismatch case.
        return "bare_string"
    s = value.strip()
    if not s:
        return "bare_string"
    if _TEMPLATE_RE.search(s):
        return "template"
    low = s.lower()
    if low in {"null", "none"}:
        return "null"
    if low in {"true", "false"}:
        return "bool"
    if low in _TIMESTAMP_LITERALS or re.fullmatch(r"now\s*\(\s*\)", low):
        return "timestamp_literal"
    if _ISO_DATE_RE.match(s) and _is_real_date(s):
        return "iso_date"
    if _NUMBER_RE.match(s):
        return "number"
    return "bare_string"


def _incompatible(kind: str, category: str, *, value: str, column_name: str,
                  node_label: str, enum_values: list[str] | None,
                  known_vars: set[str] | None = None) -> str | None:
    """Return a reason string when (kind, category) is a mismatch, else None."""
    # Compatible-with-everything kinds.
    if kind in ("template", "null"):
        return None

    if kind in ("timestamp_literal", "iso_date"):
        if category == "date":
            return None
        return f"{kind.replace('_', '-')}-into-{category}"

    if kind == "number":
        if category in ("date", "uuid", "boolean"):
            return f"number-into-{category}"
        return None

    if kind == "bool":
        if category in ("date", "uuid", "numeric"):
            return f"bool-into-{category}"
        return None

    if kind == "bare_string":
        s = (value or "").strip()
        if category == "uuid":
            # An identifier is only OK when it names a KNOWN process variable.
            #
            # The docstring promises "an identifier equal to a process
            # variable is a valid binding", but the check was merely "looks
            # like an identifier" — so ANY single word passed into a uuid
            # column, including a typo'd variable name or a stray label.
            # Postgres then rejects it at runtime with `invalid input syntax
            # for type uuid` (register VT-2). When the caller supplies the
            # known-variable set we hold it to the documented rule; with no
            # set to check against we keep the permissive behaviour rather
            # than inventing false positives.
            if _IDENT_RE.match(s):
                if known_vars is None or s in known_vars:
                    return None
                return "unknown-variable-into-uuid"
            return "bare-string-into-uuid"
        if _is_status_like(column_name, category):
            # A known-enum column with a value outside the enum set is invalid.
            if enum_values:
                if s in enum_values:
                    return None
                # Value equal to the node label is a clearly leaked label.
                if node_label and s.strip().lower() == node_label.strip().lower():
                    return "label-string-into-enum"
                return "invalid-enum-value"
            # No enum values known: only flag when it equals the node label
            # (a leaked node title), which is the observed LLM failure mode.
            if node_label and s.strip().lower() == node_label.strip().lower():
                return "label-string-into-enum"
            return None
        return None

    return None


def _iter_mutation_nodes(defn: dict) -> Iterable[dict]:
    """Yield the graph nodes whose config is a db_insert/db_update mutation."""
    if not isinstance(defn, dict):
        return
    nodes = defn.get("nodes")
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        if config.get("actionType") in _MUTATION_ACTIONS and isinstance(config.get("values"), dict):
            yield node


def _col_type_map(columns_by_table: dict, table: str) -> dict | None:
    if not isinstance(columns_by_table, dict) or not table:
        return None
    cols = columns_by_table.get(table)
    if isinstance(cols, dict):
        return cols
    return None


def _enum_values_for(columns_by_table: dict, table: str, column: str) -> list[str] | None:
    """Optional enum-value lookup: columns_by_table may map col→a dict carrying
    ``{"type":.., "enum":[..]}`` instead of a bare type string. Returns None when
    no enum info is available (the common case — plain type strings)."""
    cols = _col_type_map(columns_by_table, table)
    if not cols:
        return None
    entry = cols.get(column)
    if isinstance(entry, dict):
        ev = entry.get("enum")
        if isinstance(ev, list) and ev:
            return [str(v) for v in ev]
    return None


def _type_of(entry: object) -> str:
    """A columns_by_table entry is either a bare type string or a dict with type."""
    if isinstance(entry, dict):
        return str(entry.get("type") or "")
    return str(entry or "")


def analyze_workflow_values(defn: dict, columns_by_table: dict) -> list[dict]:
    """Detect value↔column type mismatches in a workflow definition.

    ``defn`` is a workflow ``definition`` dict (has ``nodes``). ``columns_by_table``
    maps ``table -> {column -> type}`` (type may be a bare string OR a dict with a
    ``type``/``enum``). Returns a list of findings; never raises. Unknown
    table/column is skipped (no false positive).

    Finding shape: ``{node, table, column, value, valueKind, columnType, reason}``.
    """
    findings: list[dict] = []
    try:
        for node in _iter_mutation_nodes(defn):
            data = node.get("data") or {}
            config = data.get("config") or {}
            table = config.get("table")
            values = config.get("values") or {}
            cols = _col_type_map(columns_by_table, table)
            if cols is None:
                continue  # unknown table → skip
            node_label = str(data.get("label") or "")
            node_id = node.get("id")
            for column, expr in values.items():
                if column not in cols:
                    continue  # unknown column → skip
                column_type = _type_of(cols[column])
                category = _category(column_type)
                kind = classify_value_kind(expr)
                enum_values = _enum_values_for(columns_by_table, table, column)
                reason = _incompatible(
                    kind, category,
                    value=expr if isinstance(expr, str) else str(expr),
                    column_name=column,
                    node_label=node_label,
                    enum_values=enum_values,
                )
                if reason:
                    findings.append({
                        "node": node_id,
                        "table": table,
                        "column": column,
                        "value": expr,
                        "valueKind": kind,
                        "columnType": column_type,
                        "reason": reason,
                    })
    except Exception:
        # Defensive: a checker must never crash the build.
        return findings
    return findings


def repair_workflow_values(
    defn: dict,
    columns_by_table: dict,
    trigger_inputs: set[str] | None = None,
) -> tuple[dict, list[dict]]:
    """Deterministically correct the mismatches ``analyze_workflow_values`` finds.

    Strategy per finding (never leave the bad literal, never invent a uuid):
      1. A same-named ``trigger_inputs`` entry exists → REBIND ``values[col]``
         to ``"{{col}}"``.
      2. A label-into-enum with a derivable valid enum value → replace with it.
      3. Otherwise DROP the key (column takes its DB default/NULL).

    Returns ``(repaired_defn, changes)`` where changes is a list of
    ``{node, column, from, to}`` (``to`` is ``None`` when the key was dropped),
    suitable for narration. Does not mutate the input; idempotent.
    """
    trigger_inputs = trigger_inputs or set()
    repaired = copy.deepcopy(defn) if isinstance(defn, dict) else defn
    findings = analyze_workflow_values(repaired, columns_by_table)
    if not findings:
        return repaired, []

    # Index the mutation nodes by id for in-place correction.
    nodes_by_id = {}
    for node in _iter_mutation_nodes(repaired):
        nodes_by_id[node.get("id")] = node

    changes: list[dict] = []
    for finding in findings:
        node = nodes_by_id.get(finding["node"])
        if node is None:
            continue
        config = (node.get("data") or {}).get("config") or {}
        values = config.get("values")
        if not isinstance(values, dict):
            continue
        col = finding["column"]
        if col not in values:
            continue
        original = values[col]

        # 1. Rebind to a same-named trigger input.
        if col in trigger_inputs:
            new_val = "{{" + col + "}}"
            values[col] = new_val
            changes.append({"node": finding["node"], "column": col, "from": original, "to": new_val})
            continue

        # 2. Label-into-enum with a derivable valid enum value.
        if finding["reason"] in ("label-string-into-enum", "invalid-enum-value"):
            enum_values = _enum_values_for(columns_by_table, finding["table"], col)
            if enum_values:
                new_val = enum_values[0]
                values[col] = new_val
                changes.append({"node": finding["node"], "column": col, "from": original, "to": new_val})
                continue

        # 3. Last resort — drop the key so the column takes its DB default.
        #
        # Deletion is a LOSS, not a repair: the workflow no longer writes a
        # column its author asked it to write, and the run still reports
        # success (register VT-4). It stays as the final fallback because an
        # invalid value is worse than an absent one, but it is now recorded as
        # a drop rather than an ordinary change, and logged — so a workflow
        # that has been quietly hollowed out is visible instead of silent.
        if not _column_is_omittable(columns_by_table, finding["table"], col):
            logger.error(
                "workflow_value_types: dropping %r from the %s write in node %r "
                "(value %r, %s). The column is NOT NULL and has no default, so "
                "this write will now FAIL at runtime rather than write a bad "
                "value — the workflow needs a real value for it.",
                col, finding["table"], finding["node"], original, finding["reason"],
            )
        else:
            logger.warning(
                "workflow_value_types: dropping %r from the %s write in node %r "
                "(value %r, %s) — the column will take its DB default.",
                col, finding["table"], finding["node"], original, finding["reason"],
            )
        del values[col]
        changes.append({"node": finding["node"], "column": col,
                        "from": original, "to": None, "dropped": True})

    return repaired, changes


# --------------------------------------------------------------------------- #
# Registry / workflow adapters — build the inputs the two core functions need.
# --------------------------------------------------------------------------- #

def columns_by_table_from_registry(registry: dict) -> dict[str, dict]:
    """Build ``{table -> {column -> {"type":.., "enum":..}}}`` from the canonical
    resource registry (``contracts/resource-registry.json``)."""
    out: dict[str, dict] = {}
    if not isinstance(registry, dict):
        return out
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return out
    skipped: list[str] = []
    for ent_name, ent in entities.items():
        if not isinstance(ent, dict):
            continue
        table = ent.get("table")
        col_map: dict[str, dict] = {}

        # Accept BOTH registry shapes.
        #
        # Only the canonical `columns: [ {name, type, enum}, … ]` list was
        # recognised. The fallback / plan-built registry stores the same
        # information as `fields: { name: {type, …} }` — a dict — so `cols` was
        # not a list, the entity was skipped, and the map came back EMPTY. An
        # empty map means the value↔column type checker has nothing to compare
        # against, so it passed everything: on any app whose registry took the
        # fallback shape the guard was a silent no-op, which is indistinguishable
        # from "no type problems found".
        cols = ent.get("columns")
        if isinstance(cols, list):
            for c in cols:
                if isinstance(c, dict) and c.get("name"):
                    col_map[c["name"]] = {"type": c.get("type") or "",
                                          "enum": c.get("enum")}
        else:
            fields = ent.get("fields")
            if isinstance(fields, dict):
                for fname, meta in fields.items():
                    if not fname:
                        continue
                    meta = meta if isinstance(meta, dict) else {}
                    col_map[str(fname)] = {
                        "type": meta.get("type") or "",
                        "enum": meta.get("enum") or meta.get("enum_values"),
                    }
            elif isinstance(fields, list):
                for f in fields:
                    if isinstance(f, dict) and f.get("name"):
                        col_map[f["name"]] = {"type": f.get("type") or "",
                                              "enum": f.get("enum")}

        if not table or not col_map:
            skipped.append(str(ent_name))
            continue
        out[str(table)] = col_map

    if skipped:
        # Say so. An empty result silently disables every downstream type check.
        logger.warning(
            "workflow_value_types: %d registry entit%s yielded no columns (%s) — "
            "value/column type checking is INACTIVE for %s.",
            len(skipped), "y" if len(skipped) == 1 else "ies",
            ", ".join(sorted(skipped)[:10]),
            "them" if out else "EVERY table (the map is empty)",
        )
    return out


def collect_trigger_inputs(defn: dict) -> set[str]:
    """Best-effort set of known input/variable names for a workflow: every
    ``{{name}}`` referenced anywhere in the definition, plus any ``fields`` lists
    on action steps/nodes (which enumerate a mutation's input columns)."""
    inputs: set[str] = set()
    if not isinstance(defn, dict):
        return inputs

    def _walk(v: object) -> None:
        if isinstance(v, str):
            for m in re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}", v):
                inputs.add(m.split(".")[0])
        elif isinstance(v, dict):
            fields = v.get("fields")
            if isinstance(fields, list):
                for f in fields:
                    if isinstance(f, str) and _IDENT_RE.match(f):
                        inputs.add(f)
            for val in v.values():
                _walk(val)
        elif isinstance(v, list):
            for item in v:
                _walk(item)

    _walk(defn)
    return inputs


def repair_workflow_dict(wf: dict, columns_by_table: dict) -> tuple[dict, list[dict]]:
    """Adapter for a whole workflow file (``{... "definition": {...}}``): derives
    the trigger inputs from the definition, repairs ``definition`` in place, and
    returns ``(wf, changes)``. Used by the source-side gate."""
    if not isinstance(wf, dict):
        return wf, []
    defn = wf.get("definition")
    if not isinstance(defn, dict):
        return wf, []
    trigger_inputs = collect_trigger_inputs(defn)
    repaired_defn, changes = repair_workflow_values(defn, columns_by_table, trigger_inputs)
    if changes:
        wf["definition"] = repaired_defn
    return wf, changes


def analyze_workflow_file(workflow_path: str, registry_path: str) -> list[dict]:
    """Convenience tool entry: load a workflow JSON + a resource-registry JSON
    from disk and return the value↔column findings. Never raises."""
    import json as _json

    try:
        wf = _json.loads(open(workflow_path, encoding="utf-8").read())
        reg = _json.loads(open(registry_path, encoding="utf-8").read())
    except (OSError, ValueError):
        return []
    defn = wf.get("definition") if isinstance(wf, dict) else None
    return analyze_workflow_values(defn or {}, columns_by_table_from_registry(reg))


def _main(argv: list[str]) -> int:  # pragma: no cover - thin CLI wrapper
    """CLI: ``python -m services.workflow_value_types WORKFLOW.json REGISTRY.json``.
    Prints findings; with ``--repair`` also prints the corrections."""
    import json as _json

    args = [a for a in argv if not a.startswith("--")]
    do_repair = "--repair" in argv
    if len(args) < 2:
        print("usage: workflow_value_types WORKFLOW.json REGISTRY.json [--repair]")
        return 2
    wf = _json.loads(open(args[0], encoding="utf-8").read())
    reg = _json.loads(open(args[1], encoding="utf-8").read())
    cbt = columns_by_table_from_registry(reg)
    findings = analyze_workflow_values(wf.get("definition") or {}, cbt)
    print(f"{len(findings)} finding(s):")
    for f in findings:
        print(f"  {f['node']}.{f['column']}: {f['value']!r} "
              f"({f['valueKind']} -> {f['columnType']}) — {f['reason']}")
    if do_repair:
        _, changes = repair_workflow_dict(wf, cbt)
        print(f"{len(changes)} repair(s):")
        for c in changes:
            print(f"  {c['node']}.{c['column']}: {c['from']!r} -> {c['to']!r}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(_main(sys.argv[1:]))
