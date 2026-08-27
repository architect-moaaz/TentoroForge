"""V&F 2.0 M3 — unit tests for the cross-round Smith dispatch ledger.

The ledger prevents Smith from being asked to fix the same
``(interaction_id, class_name)`` pair twice in one run. Kept in-memory;
the caller (self_verify_pass) instantiates one per run.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from services.journey_verifier.autofix import DispatchResult
from services.journey_verifier.dedup import FaultAttemptLedger
from services.journey_verifier.fault_classifier import ClassifiedFault
from services.journey_verifier.smith_autofix import dispatch_all


def _cf(iid: str, class_name: str = "render-error",
        seam: str = "smith:render") -> ClassifiedFault:
    return ClassifiedFault(
        interaction_id=iid, route=f"/{iid}",
        class_name=class_name, seam=seam,
        evidence_slice="test", needed_context=[],
        raw={"interaction": {"id": iid}, "evidence": {}},
    )


def test_record_and_already_tried():
    ledger = FaultAttemptLedger()
    fault = _cf("a")
    assert ledger.already_tried(fault) is False
    ledger.record_attempt(fault)
    assert ledger.already_tried(fault) is True


def test_max_attempts_respected():
    ledger = FaultAttemptLedger()
    fault = _cf("a")
    ledger.record_attempt(fault)
    # With max_attempts=2, the fault has 1 attempt so it's not exhausted.
    assert ledger.already_tried(fault, max_attempts=2) is False
    ledger.record_attempt(fault)
    assert ledger.already_tried(fault, max_attempts=2) is True


def test_ledger_scopes_by_interaction_and_class():
    """Same interaction id but different class is a fresh attempt."""
    ledger = FaultAttemptLedger()
    a_render = _cf("a", class_name="render-error", seam="smith:render")
    a_binding = _cf("a", class_name="binding-crash", seam="smith:binding")
    ledger.record_attempt(a_render)
    assert ledger.already_tried(a_render) is True
    assert ledger.already_tried(a_binding) is False


def test_dispatch_all_skips_duplicates_via_ledger(tmp_path: Path):
    """When a fault is in the ledger already, dispatch_all returns a
    residual result without calling Smith."""
    calls: list[str] = []

    async def stub_runner(**kwargs: Any) -> dict[str, Any]:
        # Extract the class from the prompt so we can count invocations.
        calls.append(str(kwargs.get("user_message", ""))[:100])
        return {"edited_paths": ["x"], "trace": [{"tool": "edit_page"}]}

    ledger = FaultAttemptLedger()
    ledger.record_attempt(_cf("a"))   # pre-record → this fault is already-tried

    faults = [_cf("a"), _cf("b")]
    results = asyncio.run(dispatch_all(
        faults, tmp_path,
        smith_runner=stub_runner, ledger=ledger,
    ))
    # Only 1 real Smith call — for "b".
    assert len(calls) == 1
    # And the ledger call for "a" produced an already-attempted DispatchResult.
    already = [r for r in results if r.error == "already-attempted-this-run"]
    assert len(already) == 1
    assert already[0].fixed is False


def test_dispatch_all_records_attempt_after_dispatch(tmp_path: Path):
    """After a successful dispatch, the fault is recorded in the ledger
    so a hypothetical second pass (same run) would skip it."""
    async def stub_runner(**kwargs: Any) -> dict[str, Any]:
        return {"edited_paths": ["x"], "trace": [{"tool": "edit_page"}]}

    ledger = FaultAttemptLedger()
    fault = _cf("a")
    asyncio.run(dispatch_all(
        [fault], tmp_path,
        smith_runner=stub_runner, ledger=ledger,
    ))
    assert ledger.already_tried(fault) is True
