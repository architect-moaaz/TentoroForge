"""Strip stale `{{binding}}` values from workflow mutation nodes.

Why this exists
---------------
`workflow_input_map_backfill` adds `values[field] = "{{field}}"` for every
column in `action-contract.unmapped_fields`. When a column NEVER appears as
a form input AND never as a workflow processVariable (e.g. `isActive` on a
users table — has a DB default, no form field), the mustache binding cannot
resolve at runtime. The FEEL-lite interpolator returns `""` or `undefined`
and Postgres rejects the cast to the column type (booleans/dates crash
loudly, text columns silently store the literal `""`). The generated app
looks like it accepted the create but the row never lands.

What this pass does
-------------------
For every workflow file, for every mutation node (`db_insert` / `db_update`),
walk `data.config.values`. Drop any key whose right-hand side is a
`{{name}}` binding where `name` is not one of the workflow's declared
`processVariables`. Leave plain-string mappings and hard-coded literals
alone — those are intentional shapes (CRUD-generator plain form; literal
defaults from the LLM).

This closes the "new user created but doesn't appear in the list" symptom
whenever the cause is a stale mustache binding on a mutation values map.
Deterministic, idempotent, silent on error.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MUTATION_ACTION_TYPES = ("db_insert", "db_update")

# Match `{{name}}` (optionally surrounded by whitespace). Dot-paths like
# `{{ctx.foo.bar}}` are NOT covered here — those bind to runtime state we
# don't inspect, and are always intentional. We only touch the flat form.
_FLAT_MUSTACHE_RE = re.compile(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*$")


def clean_workflow_values(output_dir: str) -> dict[str, Any]:
    """Walk every workflow file under `<output_dir>/workflows/` and drop stale
    mustache bindings from mutation nodes. Returns a summary dict.

    Never raises. On IO/parse failure returns the counts collected so far.
    """
    summary: dict[str, Any] = {
        "workflows_scanned": 0,
        "workflows_touched": [],
        "values_removed": 0,
    }
    wdir = Path(output_dir) / "workflows"
    if not wdir.exists():
        return summary

    touched: list[str] = []

    for wf_path in sorted(wdir.glob("*.json")):
        summary["workflows_scanned"] += 1
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("[wf-values-clean] read failed: %s", wf_path.name)
            continue

        removed = _clean_one(wf)
        if removed <= 0:
            continue

        try:
            wf_path.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("[wf-values-clean] write failed: %s", wf_path.name)
            continue

        summary["values_removed"] += removed
        touched.append(wf_path.stem)

    summary["workflows_touched"] = sorted(touched)
    if summary["values_removed"]:
        logger.info(
            "[wf-values-clean] removed %d stale binding(s) across %d workflow(s)",
            summary["values_removed"],
            len(touched),
        )
    return summary


def _clean_one(wf: dict) -> int:
    known_vars = _process_var_names(wf)
    defn = wf.get("definition")
    if not isinstance(defn, dict):
        return 0
    nodes = defn.get("nodes")
    if not isinstance(nodes, list):
        return 0

    removed = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        config = data.get("config")
        if not isinstance(config, dict):
            continue
        if config.get("actionType") not in _MUTATION_ACTION_TYPES:
            continue
        values = config.get("values")
        if not isinstance(values, dict):
            continue
        for key in list(values.keys()):
            rhs = values[key]
            if not isinstance(rhs, str):
                continue
            m = _FLAT_MUSTACHE_RE.match(rhs)
            if not m:
                continue
            name = m.group(1)
            if name not in known_vars:
                del values[key]
                removed += 1
    return removed


def _process_var_names(wf: dict) -> set[str]:
    out: set[str] = set()
    vars_ = wf.get("processVariables")
    if isinstance(vars_, list):
        for v in vars_:
            if isinstance(v, dict):
                n = v.get("name")
                if isinstance(n, str) and n.strip():
                    out.add(n.strip())
    return out
