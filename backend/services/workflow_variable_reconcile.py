"""Final workflow-variable reconciliation — kills the undefined-ref class.

Runs LAST among workflow mutators (post_generate_fixes, immediately before
workflow_validator) so it reconciles the FINAL on-disk definitions. Three
deterministic repairs, applied in this order:

C) **Self-referential enum literals** — ``values.status = "{{status}}"``
   writes a column to itself, which is never meaningful. When the target
   table's column has plan-declared enum values, pick the literal by
   token-matching the step id + workflow name against the enum
   (``expire_entries`` → ``expired``, ``CancelBooking`` → ``cancelled``);
   fall back to the plan field default when it is a member of the enum.
   No confident match → left alone for the later repairs/validator.

B) **Query-output pairing** — schedule workflows read rows
   (``find_expiring``) but the query declares no ``outputVar``, so later
   ``{{expiringSubscriptions}}`` refs dangle. A result-ish undeclared root
   (NOT named after a column the workflow itself writes/filters) is paired
   with the LAST preceding ``db_query`` that has no outputVar.

A) **Final free-ref declaration** — any remaining ``{{ref}}`` root with no
   provider is declared as a launcher-supplied processVariable — for
   non-schedule triggers only (same rule as
   :mod:`services.workflow_process_variables` Source 4). This closes the
   ORDERING hazard where passes like workflow_graph_gate rewrite literals
   into bindings AFTER sync already derived processVariables.

All repairs are additive + idempotent; existing outputVars, literals and
processVariables entries are never overwritten. Repairs are applied to BOTH
``definition.steps`` (editor) and ``definition.nodes`` (runtime/validator)
so the two views can't drift.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.plan_field_lookup import get_enum_values, load_plan
from services.workflow_process_variables import (
    derive_process_variables,
    strip_source,
)

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*$")
_REF_ROOT_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)")
_OUTPUT_KEYS = ("variableName", "outputVariable", "outputVar", "resultVar",
                "resultVariable", "assignTo")
_BUILTIN_ROOTS = {"trigger", "input", "event", "context", "process",
                  "processVariables", "id"}


def _fold(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _trigger_type(wf: dict) -> str:
    t = ((wf.get("definition") or {}).get("trigger") or {})
    return str(t.get("type") or "").strip().lower()


def _step_lists(wf: dict) -> list[list[dict]]:
    """Both config-bearing views (steps for the editor, nodes for the
    runtime + validator). Repairs must hit every view they appear in."""
    d = wf.get("definition") or {}
    out = []
    for key in ("steps", "nodes"):
        lst = d.get(key)
        if isinstance(lst, list) and lst:
            out.append([s for s in lst if isinstance(s, dict)])
    return out


def _config(node: dict) -> dict:
    data = node.get("data")
    if isinstance(data, dict) and isinstance(data.get("config"), dict):
        return data["config"]
    if isinstance(node.get("config"), dict):
        return node["config"]
    return {}


def _tokens(*names: str) -> list[str]:
    toks: list[str] = []
    for n in names:
        toks.extend(t.lower() for t in re.findall(r"[A-Za-z]+", str(n) or ""))
    return [t for t in toks if len(t) >= 4]


def _match_enum(tokens: list[str], enum_values: list[str]) -> str | None:
    """Longest-common-prefix (>=4) match between a name token and an enum
    value: expire↔expired, cancel↔cancelled, renew↔renewed."""
    best: tuple[int, str] | None = None
    for value in enum_values:
        fv = _fold(value)
        for t in tokens:
            n = 0
            for a, b in zip(fv, t):
                if a != b:
                    break
                n += 1
            if n >= 4 and (best is None or n > best[0]):
                best = (n, value)
    return best[1] if best else None


def _enum_for(plan: dict | None, table: str, column: str) -> list[str] | None:
    """Plan enum values for a snake/plural table name — tries the raw name
    plus naive singulars, since plan entities are singular PascalCase."""
    if not plan or not table:
        return None
    cands = [table, table.rstrip("s")]
    if table.endswith("ies"):
        cands.append(table[:-3] + "y")
    if table.endswith("es"):
        cands.append(table[:-2])
    folds = {_fold(c) for c in cands}
    # plan_field_lookup folds by lowercase only — snake table names never
    # match PascalCase entity names there, so resolve the REAL entity name
    # ourselves by alnum-fold and query with it.
    names = [m.get("name") for m in plan.get("data_models") or []
             if isinstance(m, dict) and m.get("name")]
    ents = plan.get("entities")
    if isinstance(ents, dict):
        names.extend(ents.keys())
    for name in names:
        if _fold(name) in folds:
            vals = get_enum_values(plan, str(name), column)
            if vals:
                return vals
    return None


def _field_default(plan: dict | None, table: str, column: str) -> Any:
    from services.plan_field_lookup import get_field
    if not plan:
        return None
    for c in (table, table.rstrip("s")):
        f = get_field(plan, c, column)
        if isinstance(f, dict) and f.get("default") is not None:
            return f["default"]
    return None


# ── C: self-referential enum literals ──────────────────────────────────

def _repair_self_refs(wf: dict, plan: dict | None) -> list[dict]:
    repaired: list[dict] = []
    wf_name = str(wf.get("name") or "")
    # Decide replacements once (from whichever view we see first), then
    # apply the same literal to every view so steps/nodes stay in sync.
    decided: dict[tuple[str, str], Any] = {}
    for view in _step_lists(wf):
        for step in view:
            cfg = _config(step)
            if cfg.get("actionType") not in ("db_insert", "db_update"):
                continue
            values = cfg.get("values")
            if not isinstance(values, dict):
                continue
            table = str(cfg.get("table") or "")
            sid = str(step.get("id") or "")
            for col, v in list(values.items()):
                m = _REF_RE.match(v) if isinstance(v, str) else None
                if not m or m.group(1) != col:
                    continue  # only the self-referential shape
                key = (table, col)
                if key not in decided:
                    enum_vals = _enum_for(plan, table, col)
                    if not enum_vals:
                        continue
                    literal = _match_enum(_tokens(sid, wf_name), enum_vals)
                    if literal is None:
                        dflt = _field_default(plan, table, col)
                        if dflt in enum_vals:
                            literal = dflt
                    if literal is None:
                        continue
                    decided[key] = literal
                    repaired.append({"step": sid, "column": col,
                                     "literal": decided[key]})
                values[col] = decided[key]
    return repaired


# ── B: query-output pairing ────────────────────────────────────────────

def _declared_roots(wf: dict) -> set[str]:
    names = set(_BUILTIN_ROOTS)
    for p in wf.get("processVariables") or []:
        if isinstance(p, dict) and p.get("name"):
            names.add(str(p["name"]))
    for view in _step_lists(wf):
        for step in view:
            if step.get("id"):
                names.add(str(step["id"]))
            cfg = _config(step)
            for key in _OUTPUT_KEYS:
                v = cfg.get(key)
                if isinstance(v, str) and v:
                    names.add(v)
    return names


def _column_names(wf: dict) -> set[str]:
    """Column-ish names this workflow writes/filters — a root with one of
    these names is a value, never a query result."""
    cols: set[str] = set()
    for view in _step_lists(wf):
        for step in view:
            cfg = _config(step)
            for key in ("values", "where"):
                d = cfg.get(key)
                if isinstance(d, dict):
                    for k in d:
                        cols.add(re.sub(r"_(in|lt|gt|lte|gte|ne)$", "", str(k)))
    return cols


def _pair_query_outputs(wf: dict) -> list[dict]:
    paired: list[dict] = []
    declared = _declared_roots(wf)
    cols = {_fold(c) for c in _column_names(wf)}
    views = _step_lists(wf)
    if not views:
        return paired
    primary = views[0]

    # Ordered scan: remember outputVar-less db_query steps; when an
    # undeclared result-ish root first appears, pair it with the LAST
    # such query seen so far.
    open_queries: list[dict] = []
    assigned: dict[str, str] = {}  # root -> query step id
    for step in primary:
        cfg = _config(step)
        if cfg.get("actionType") == "db_query" and not any(
                cfg.get(k) for k in _OUTPUT_KEYS):
            open_queries.append(step)
            continue
        for root in _REF_ROOT_RE.findall(json.dumps(cfg)):
            if root in declared or root in assigned or _fold(root) in cols:
                continue
            if not open_queries:
                continue
            q = open_queries.pop()  # last preceding unpaired query
            assigned[root] = str(q.get("id") or "")
            _config(q)["outputVar"] = root
            declared.add(root)
            paired.append({"query": assigned[root], "outputVar": root})
    # Mirror assignments into every other view (nodes) by step id.
    for view in views[1:]:
        by_id = {str(s.get("id")): s for s in view if s.get("id")}
        for item in paired:
            s = by_id.get(item["query"])
            if s is not None:
                _config(s).setdefault("outputVar", item["outputVar"])
    return paired


# ── A: final free-ref declaration ──────────────────────────────────────

def _declare_remaining(wf: dict) -> list[str]:
    d = wf.get("definition") or {}
    nodes = d.get("nodes") or d.get("steps") or []
    pseudo = {
        "trigger": _trigger_type(wf),
        "processVariables": wf.get("processVariables") or [],
    }
    merged = strip_source(derive_process_variables(pseudo, nodes))
    before = {str(p.get("name")) for p in wf.get("processVariables") or []
              if isinstance(p, dict)}
    added = [p["name"] for p in merged if p["name"] not in before]
    if added:
        wf["processVariables"] = merged
    return added


# ── entry point ────────────────────────────────────────────────────────

def reconcile_workflow_variables(output_dir: str | Path) -> dict:
    """Reconcile every workflows/*.json. Returns a per-file report; never
    raises (unreadable files are skipped)."""
    root = Path(output_dir)
    wf_dir = root / "workflows"
    plan = load_plan(root)
    report: list[dict] = []
    if not wf_dir.is_dir():
        return {"files": report}
    for path in sorted(wf_dir.glob("*.json")):
        try:
            wf = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(wf, dict):
            continue
        literals = _repair_self_refs(wf, plan)
        outputs = _pair_query_outputs(wf)
        declared = _declare_remaining(wf)
        if literals or outputs or declared:
            path.write_text(json.dumps(wf, indent=2), encoding="utf-8")
            report.append({"file": path.name, "literals": literals,
                           "output_vars": outputs, "declared": declared})
            logger.info(
                "[wf-var-reconcile] %s: %d literal(s), %d outputVar(s), "
                "%d declared", path.name, len(literals), len(outputs),
                len(declared))
    return {"files": report}


__all__ = ["reconcile_workflow_variables"]
