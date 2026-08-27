"""Drop workflow-values keys the dispatching form doesn't actually provide.

Why this exists
---------------
The CRUD generator emits plain-string values like `{"isVerified": "isVerified"}`
for every writable column. If the dispatching form doesn't collect a specific
column (system-managed fields like `isVerified` / `verifiedAt` / `totalSessions`
on the Carer create form), the runtime dispatch has NO value under that name.
The db_insert writes `undefined` to a typed column and Postgres rejects — the
row never lands and the user sees no confirmation. Same symptom class as the
mustache-values bug fixed by `workflow_values_clean_guard`, but a different
mechanism: this pass handles the plain-string-mode leg.

What this pass does
-------------------
For every `form_submit` action-contract entry with a resolved workflow_id:

  1. Load the workflow file. Collect its declared processVariable names.
  2. Union the `input_map` keys+values across EVERY dispatching form.
  3. Walk the first mutation node's `values` map.
  4. For each key whose RHS is a plain string equal to a process-var name
     (the CRUD-generator convention), verify that same name is in the
     form-provided union. If not, drop the key.

Skips mustache (`{{name}}`) values — those belong to workflow_values_clean_guard.
Skips literal strings (RHS not a process-var name) — those are intentional
static writes. Deterministic. Idempotent. Silent on error.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_MUTATION_ACTION_TYPES = ("db_insert", "db_update")
_MUSTACHE_RE = re.compile(r"^\s*\{\{.*\}\}\s*$")


def prune_workflow_form_fields(output_dir: str) -> dict[str, Any]:
    """For each workflow dispatched by at least one form, drop mutation-values
    entries the form doesn't provide. Returns summary. Never raises."""
    summary: dict[str, Any] = {
        "workflows_scanned": 0,
        "workflows_touched": [],
        "values_removed": 0,
    }
    root = Path(output_dir)
    contract_path = root / "contracts" / "action-contract.json"
    wf_dir = root / "workflows"
    if not contract_path.exists() or not wf_dir.exists():
        return summary

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("[wf-form-prune] contract read failed")
        return summary

    actions = contract.get("actions")
    if not isinstance(actions, list):
        return summary

    # Union input_maps by workflow_id (normalized). Keys AND values are added
    # since CRUD input_maps use the same name on both sides and we want the
    # column-level set of "form-provided" names.
    form_fields_by_wf: dict[str, set[str]] = {}
    for a in actions:
        if not isinstance(a, dict):
            continue
        if a.get("kind") != "form_submit":
            continue
        if not a.get("resolved"):
            continue
        wf_id = a.get("workflow_id")
        if not isinstance(wf_id, str) or not wf_id.strip():
            continue
        input_map = a.get("input_map") or {}
        if not isinstance(input_map, dict):
            continue
        provided: set[str] = set()
        for k, v in input_map.items():
            if isinstance(k, str) and k.strip():
                provided.add(k)
            if isinstance(v, str) and v.strip():
                provided.add(v)
        if not provided:
            continue
        form_fields_by_wf.setdefault(_norm_wf_id(wf_id), set()).update(provided)

    if not form_fields_by_wf:
        return summary

    touched: list[str] = []

    for wf_path in sorted(wf_dir.glob("*.json")):
        summary["workflows_scanned"] += 1
        norm = _norm_wf_id(wf_path.stem)
        provided = form_fields_by_wf.get(norm)
        if not provided:
            continue

        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("[wf-form-prune] read failed: %s", wf_path.name)
            continue

        removed = _prune_workflow(wf, provided)
        if removed <= 0:
            continue

        try:
            wf_path.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("[wf-form-prune] write failed: %s", wf_path.name)
            continue

        summary["values_removed"] += removed
        touched.append(wf_path.stem)

    summary["workflows_touched"] = sorted(touched)
    if summary["values_removed"]:
        logger.info(
            "[wf-form-prune] dropped %d unmapped column(s) across %d workflow(s)",
            summary["values_removed"],
            len(touched),
        )
    return summary


def _prune_workflow(wf: dict, form_provided: set[str]) -> int:
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
            if _MUSTACHE_RE.match(rhs):
                # workflow_values_clean_guard handles this shape.
                continue
            # RHS is a plain string. If it matches a process-var name AND
            # that name is NOT in the form-provided union, drop it.
            if rhs in known_vars and rhs not in form_provided:
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


def _norm_wf_id(s: str) -> str:
    return (s or "").lower().replace("-", "").replace("_", "")
