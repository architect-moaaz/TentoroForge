"""Close the form-to-workflow input-map gap.

Symptom
-------
User fills out a create form with 9 fields, hits Submit, nothing
comes back. Root cause: the workflow's mutation step (db_insert /
db_update) ships with a partial ``values`` map that only names one
or two columns — every other form field falls on the floor. Result:
either a NOT NULL violation (silent), or a row with only defaults
(user sees no confirmation).

Signal
------
The generation pipeline already RECORDS this gap in
``contracts/action-contract.json``::

    {
      "file": "drives/new.json",
      "kind": "form_submit",
      "workflow_id": "createdrive",
      "input_map": {"status": "status"},
      "unmapped_fields": ["title", "location", "openDate", ...]
    }

The ``unmapped_fields`` array is populated by earlier pipeline steps
that noticed the mismatch — but nothing acts on it. This pass acts.

What this pass does
-------------------
For every action-contract entry with a non-empty ``unmapped_fields``:

  1. Load the target workflow file (from ``workflow_id``).
  2. Find the FIRST mutation step in it — a node with actionType
     ``db_insert`` (preferred) or ``db_update``. That step's
     ``values`` is where the form fields need to land.
  3. For each unmapped field, add ``values[field] = "{{field}}"`` iff
     the key is not already present. The runtime's ``{{...}}``
     interpolator reads from the input variables the workflow was
     invoked with (see ``templates/runtime/workflows/engine.ts``),
     which for a form_submit dispatch IS the form payload.
  4. Update the action-contract entry so ``input_map`` reflects the
     new mappings and ``unmapped_fields`` is cleared.
  5. Write both files back.

Idempotent — a second run finds no unmapped fields and no-ops.
Silent on any error — a bug here must never break generation.

Env gate
--------
On by default (post workflow-audit slice). The pipeline was ALREADY detecting
partial ``values`` maps and recording ``unmapped_fields`` in
``contracts/action-contract.json`` — it just wasn't running the backfill that
consumed those records, so form fields were silently dropped and users got the
"filled 9 fields, nothing came back" experience. Backfill is idempotent and
additive; set ``FORGE_INPUT_MAP_BACKFILL=off`` to disable.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def is_input_map_backfill_enabled() -> bool:
    return os.getenv("FORGE_INPUT_MAP_BACKFILL", "on").lower() not in (
        "0", "false", "no", "off",
    )


def backfill_workflow_input_maps(output_dir: str | Path) -> dict[str, Any]:
    """Backfill every ``form_submit`` workflow's mutation values with
    the form fields the action-contract said were unmapped.

    Returns a summary dict::

        {
          "actions_scanned": int,
          "actions_backfilled": int,
          "fields_added": int,
          "workflows_touched": [str, ...],
        }

    Never raises. On IO/parse failure returns a summary with the counts
    that succeeded up to the failure point.
    """
    root = Path(output_dir)
    summary = {
        "actions_scanned":    0,
        "actions_backfilled": 0,
        "fields_added":       0,
        "workflows_touched":  [],
    }

    ac_path = root / "contracts" / "action-contract.json"
    if not ac_path.exists():
        return summary

    try:
        ac = json.loads(ac_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("[input-map-backfill] action-contract unreadable")
        return summary

    actions = ac.get("actions")
    if not isinstance(actions, list):
        return summary

    wf_dir = root / "workflows"
    workflows_touched: set[str] = set()

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("kind") != "form_submit":
            continue
        summary["actions_scanned"] += 1

        unmapped = action.get("unmapped_fields")
        if not isinstance(unmapped, list) or not unmapped:
            continue

        wf_id = action.get("workflow_id")
        if not isinstance(wf_id, str) or not wf_id.strip():
            continue

        wf_path = _resolve_workflow_path(wf_dir, wf_id)
        if wf_path is None:
            logger.info(
                "[input-map-backfill] workflow file not found for %r", wf_id,
            )
            continue

        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception(
                "[input-map-backfill] workflow %r unreadable", wf_id,
            )
            continue

        added = _backfill_workflow(wf, unmapped)
        if added <= 0:
            continue

        try:
            wf_path.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception(
                "[input-map-backfill] workflow %r write failed", wf_id,
            )
            continue

        # Update the action-contract entry to reflect the new mappings.
        input_map = action.get("input_map")
        if not isinstance(input_map, dict):
            input_map = {}
            action["input_map"] = input_map
        for field in unmapped:
            if isinstance(field, str) and field.strip():
                input_map.setdefault(field, field)
        action["unmapped_fields"] = []

        summary["actions_backfilled"] += 1
        summary["fields_added"]       += added
        workflows_touched.add(wf_id)

    if summary["actions_backfilled"] > 0:
        try:
            ac_path.write_text(
                json.dumps(ac, indent=2), encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[input-map-backfill] action-contract write failed",
            )

    summary["workflows_touched"] = sorted(workflows_touched)
    if summary["fields_added"] > 0:
        logger.info(
            "[input-map-backfill] +%d field(s) across %d workflow(s)",
            summary["fields_added"], len(workflows_touched),
        )
    return summary


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _resolve_workflow_path(wf_dir: Path, wf_id: str) -> Path | None:
    """Workflow ids appear in several shapes across the pipeline:
    ``update-candidateprofile`` (kebab, action-contract), ``updatecandidateprofile``
    (lowercase, older writer), ``UpdateCandidateProfile`` (PascalCase file
    name, current writer). Match by normalizing both sides — strip dashes/
    underscores, lower-case — so any of them resolves."""
    if not wf_dir.exists():
        return None
    exact = wf_dir / f"{wf_id}.json"
    if exact.exists():
        return exact
    target = _norm_wf_id(wf_id)
    for p in wf_dir.glob("*.json"):
        if _norm_wf_id(p.stem) == target:
            return p
    return None


def _norm_wf_id(s: str) -> str:
    return s.lower().replace("-", "").replace("_", "")


_INSERT_ACTION_TYPES = ("db_insert", "insert")
_UPDATE_ACTION_TYPES = ("db_update", "update")


def _backfill_workflow(wf: dict, unmapped: list) -> int:
    """Update the FIRST mutation step's ``values`` map to include every
    unmapped form field as ``{{field}}``. Returns the count of fields
    actually added (idempotent — already-present keys are skipped)."""
    defn = wf.get("definition")
    if not isinstance(defn, dict):
        return 0

    nodes = defn.get("nodes")
    if not isinstance(nodes, list):
        return 0

    step = _find_mutation_step(nodes)
    if step is None:
        return 0

    values = _values_container(step)
    if values is None:
        return 0

    added = 0
    for field in unmapped:
        if not (isinstance(field, str) and field.strip()):
            continue
        if field in values:
            continue
        # {{field}} interpolation — resolves against the workflow's input
        # dict at runtime (see engine.ts: `variables: { ...input }`).
        values[field] = "{{" + field + "}}"
        added += 1
    return added


def _find_mutation_step(nodes: list) -> dict | None:
    """Return the FIRST db_insert node if any; else the first db_update
    node; else None. Prefer inserts because they carry more form fields
    than updates on a create flow."""
    insert = None
    update = None
    for n in nodes:
        if not isinstance(n, dict):
            continue
        atype = _node_action_type(n)
        if atype in _INSERT_ACTION_TYPES and insert is None:
            insert = n
        elif atype in _UPDATE_ACTION_TYPES and update is None:
            update = n
    return insert or update


def _node_action_type(node: dict) -> str:
    """Read ``actionType`` from the node's config or data.config
    (the generator nests them one level deep). Returns lower-cased."""
    data = node.get("data")
    if isinstance(data, dict):
        cfg = data.get("config")
        if isinstance(cfg, dict):
            at = cfg.get("actionType")
            if isinstance(at, str):
                return at.strip().lower()
    cfg = node.get("config")
    if isinstance(cfg, dict):
        at = cfg.get("actionType")
        if isinstance(at, str):
            return at.strip().lower()
    return ""


def _values_container(node: dict) -> dict | None:
    """Locate (and create if absent) the ``values`` dict on a mutation
    node's config. The generator writes it under ``data.config.values``."""
    data = node.get("data")
    if isinstance(data, dict):
        cfg = data.get("config")
        if isinstance(cfg, dict):
            values = cfg.get("values")
            if not isinstance(values, dict):
                values = {}
                cfg["values"] = values
            return values
    cfg = node.get("config")
    if isinstance(cfg, dict):
        values = cfg.get("values")
        if not isinstance(values, dict):
            values = {}
            cfg["values"] = values
        return values
    return None
