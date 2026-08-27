"""SV-STRICT-3b — from persisted row.report → narrated payload.

The runner writes ``row.report["faults"]`` as raw dicts (unclassified).
This module classifies them, joins them to :class:`ComponentContract`s
if an ``output_dir`` is available, and renders the plain-English
narration payload that the chat UI shows instead of raw evidence.

Public surface: :func:`narrate_from_row_report`.

Never raises — the verify pipeline calls this best-effort during
summary construction and cannot afford a bad fault dict to break the
whole run.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def narrate_from_row_report(
    row_report: dict,
    *,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Return the narrated payload for a persisted row.report.

    Result shape::

        {
          "narratives": [
            {"text": "...", "priority": "BROKEN",
             "signature": "...", "w_slot": "when",
             "component_id": "button:/x:root.children[0]",
             "contract_id": "button:/x:new-candidate" | None,
             "route": "/x"},
            ...
          ],
          "by_w_slot": {"when": [<narrative>...], "how": [...], ...},
        }
    """
    faults_json = (row_report or {}).get("faults") or []
    if not faults_json:
        return {"narratives": [], "by_w_slot": {}}

    try:
        from services.fault_classifier import (
            FaultClassification, classify, w_slot_for_signature,
        )
        from services.fault_narrator import narrate_report
        from services.fault_report import _hydrate_evidence, _hydrate_interaction

        pairs = []
        for raw in faults_json:
            try:
                interaction = _hydrate_interaction(raw.get("interaction") or {})
                # Honor pre-classified faults (e.g. promise_gate synthetic
                # PROMISE_NOT_DELIVERED). Re-classifying would drop the
                # signature since the synthetic interaction has no real
                # error signal — classify() returns UNCLASSIFIED.
                if raw.get("signature"):
                    cls = _cls_from_raw(raw, FaultClassification,
                                        w_slot_for_signature)
                else:
                    evidence = _hydrate_evidence(raw.get("evidence") or {})
                    cls = classify(interaction, evidence)
                pairs.append((cls, interaction))
            except Exception as exc:  # noqa: BLE001
                logger.debug("[verify_narration] skipped bad fault: %s", exc)
                continue

        narrated = narrate_report(pairs)

        if output_dir:
            _attach_contract_ids(narrated, pairs, output_dir)

        return narrated
    except Exception as exc:  # noqa: BLE001 — never crash the summary
        logger.warning("[verify_narration] failed: %s", exc)
        return {"narratives": [], "by_w_slot": {}}


def _cls_from_raw(raw: dict, FaultClassification, w_slot_for_signature):
    """Rebuild a FaultClassification from an already-classified raw dict.

    Used for synthetic gate faults (e.g. promise_gate emits
    signature=PROMISE_NOT_DELIVERED with priority/layer/w_slot already set).
    Priority/Layer are Literal string aliases at runtime, so the dict's
    strings are already in the right shape — no coercion needed.
    Falls back to the signature-derived w_slot when the raw dict omits it.
    """
    sig = raw.get("signature") or ""
    return FaultClassification(
        signature=sig,
        priority=raw.get("priority") or "BROKEN",
        layer=raw.get("layer") or "value",
        hypothesis=raw.get("hypothesis") or "",
        suggested_tools=tuple(raw.get("suggested_tools") or ()),
        w_slot=raw.get("w_slot") or w_slot_for_signature(sig),
    )


def _attach_contract_ids(narrated: dict[str, Any],
                          pairs: list, output_dir: str) -> None:
    """Populate ``contract_id`` on every narrative entry (best-effort)."""
    try:
        from dataclasses import dataclass
        from services.component_contract import extract_component_contracts
        from services.contract_fault_join import join_faults_to_contracts
        from services.fault_report import Fault

        # Build minimal Fault stubs for the join API — only id + interaction
        # are actually used by the join.
        faults_for_join = [
            Fault(
                id=cls_.signature and (interaction.id if hasattr(interaction, "id") else "") or "",
                interaction=interaction,
                signature=cls_.signature, priority=cls_.priority,
                layer=cls_.layer, hypothesis=cls_.hypothesis,
                suggested_tools=cls_.suggested_tools,
                evidence=None,  # not used by join
                w_slot=cls_.w_slot,
            )
            for cls_, interaction in pairs
        ]
        # Fix up ids: use the interaction's own id (join keys on this).
        faults_for_join = [
            Fault(**{**f.__dict__, "id": f.interaction.id}) for f in faults_for_join
        ]
        contracts = extract_component_contracts(output_dir)
        joined = join_faults_to_contracts(faults_for_join, contracts)

        # Narratives are ordered the same as pairs, so we can index-match.
        for narrative, (_cls, interaction) in zip(
            narrated.get("narratives") or [], pairs,
        ):
            narrative["contract_id"] = joined.get(getattr(interaction, "id", ""))
        # The by_w_slot dict points at the same items — no separate pass needed.
    except Exception as exc:  # noqa: BLE001
        logger.debug("[verify_narration] contract join failed: %s", exc)
