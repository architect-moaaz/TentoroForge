"""Backfill trigger contracts into pre-existing workflow JSONs (REM-4).

The trigger contract (top-level ``"trigger": {kind: event|schedule, …}`` on
workflow JSON) landed with the eventing layer (R1-R3): both workflow writers
now emit it at generation time. But workflow files written BEFORE that —
every already-generated app, plus files protected by the skip-if-executable
guard on regen — carry the plan's declared trigger only in the plan, so
their event/schedule automation silently never fires.

This pass closes that: read the plan's workflows, derive each one's
contract with the SAME mapper the writers use
(``workflow_generator.derive_trigger_contract`` — single source of truth),
and patch it into the matching ``workflows/*.json`` that lacks a top-level
``trigger``. Purely additive and idempotent: files that already carry a
contract are never touched, nothing else in the JSON is rewritten, and a
plan workflow without a derivable trigger (manual/button) is a no-op.

Matching is by the workflow JSON's own ``id``/``name`` against the plan
workflow's ``name``/``id`` (case-insensitive), never by filename — filename
conventions have drifted across generator generations.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _plan_workflows(output_dir: Path) -> list[dict]:
    for rel in ("src/contracts/plan.json", "contracts/plan.json"):
        p = output_dir / rel
        if p.exists():
            try:
                plan = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("[trigger-backfill] unreadable %s: %s", rel, exc)
                return []
            wfs = plan.get("workflows")
            return [w for w in wfs if isinstance(w, dict)] if isinstance(wfs, list) else []
    return []


def backfill_workflow_triggers(output_dir: str) -> int:
    """Patch derivable trigger contracts into trigger-less workflow JSONs.

    Returns the number of files patched. Never raises."""
    from services.workflow_generator import derive_trigger_contract

    root = Path(output_dir)
    wf_dir = root / "workflows"
    if not wf_dir.is_dir():
        return 0

    # name/id (normalised) → contract, for every plan workflow that has one.
    contracts: dict[str, dict] = {}
    for wf in _plan_workflows(root):
        try:
            contract = derive_trigger_contract(wf)
        except Exception as exc:  # noqa: BLE001 — one bad plan entry never blocks the rest
            logger.warning("[trigger-backfill] derive failed for %r: %s", wf.get("name"), exc)
            continue
        if not contract:
            continue
        for key in (wf.get("name"), wf.get("id")):
            if _norm(key):
                contracts[_norm(key)] = contract

    if not contracts:
        return 0

    patched = 0
    for fp in sorted(wf_dir.glob("*.json")):
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or isinstance(doc.get("trigger"), dict):
            continue  # already carries a contract (or isn't a workflow doc)
        contract = (contracts.get(_norm(doc.get("id")))
                    or contracts.get(_norm(doc.get("name"))))
        if not contract:
            continue
        doc["trigger"] = contract
        try:
            fp.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
            patched += 1
            logger.info("[trigger-backfill] %s ← %s", fp.name, contract)
        except OSError as exc:
            logger.warning("[trigger-backfill] write failed for %s: %s", fp.name, exc)
    return patched
