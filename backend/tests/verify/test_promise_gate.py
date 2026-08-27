"""SV-STRICT-4 — promise gate.

Deterministic gen-time verifier: given the contracts + Promises, does
every persona job have SOME reachable component (page or workflow)
that plausibly fulfills it? If not, emit a PROMISE_NOT_DELIVERED
synthetic fault.

Pure function — no browser, no runner. Runs at pipeline-end and
supplements the runtime interaction-driven faults with promise-level
gaps that no click-through would surface.
"""
from __future__ import annotations

import pytest

from services.blueprint_promises import PersonaJob, Promises
from services.component_contract import ComponentContract, WSlot
from services.fault_classifier import FaultSignature
from services.promise_gate import check_promises


def _slots():
    return {n: WSlot(slot=n) for n in
            ("what", "who", "where", "when", "how", "why")}


def _page(route: str, label: str = "") -> ComponentContract:
    return ComponentContract(
        id=f"page:{route}", component_type="page",
        label=label or route, slots=_slots(), route=route,
    )


def _workflow(name: str) -> ComponentContract:
    return ComponentContract(
        id=f"workflow:{name}", component_type="workflow",
        label=name, slots=_slots(),
    )


def _entity(name: str) -> ComponentContract:
    return ComponentContract(
        id=f"entity:{name}", component_type="entity",
        label=name, slots=_slots(),
    )


def _job(persona: str, label: str,
         entities: tuple[str, ...] = ()) -> PersonaJob:
    return PersonaJob(
        persona_id=persona.lower(), persona_name=persona,
        job_id=label.lower().replace(" ", "-"), job_label=label,
        primary_entities=entities,
    )


# ── Fulfilled jobs return no faults ──────────────────────────────────────


class TestFulfilled:
    def test_no_jobs_returns_no_faults(self):
        promises = Promises(persona_jobs=[])
        assert check_promises([], promises) == []

    def test_job_with_matching_entity_page_is_fulfilled(self):
        # A page whose route mentions the primary entity slug counts as
        # a plausible fulfillment.
        contracts = [
            _page("/sessions"),
            _entity("Session"),
        ]
        promises = Promises(persona_jobs=[
            _job("Member", "Book a class", entities=("Session",)),
        ])
        assert check_promises(contracts, promises) == []

    def test_job_with_matching_workflow_is_fulfilled(self):
        contracts = [_workflow("BookClass")]
        promises = Promises(persona_jobs=[
            _job("Member", "Book a class"),
        ])
        assert check_promises(contracts, promises) == []

    def test_job_matched_by_page_title_words(self):
        contracts = [_page("/booking", label="Class Booking")]
        promises = Promises(persona_jobs=[
            _job("Member", "Book a class"),
        ])
        # "book" appears in the page label — plausible.
        assert check_promises(contracts, promises) == []


# ── Unfulfilled jobs emit PROMISE_NOT_DELIVERED ──────────────────────────


class TestUnfulfilled:
    def test_job_with_no_matching_component(self):
        contracts = [_page("/settings"), _entity("User")]
        promises = Promises(persona_jobs=[
            _job("Member", "Book a class", entities=("Session",)),
        ])
        faults = check_promises(contracts, promises)
        assert len(faults) == 1
        f = faults[0]
        assert f["signature"] == FaultSignature.PROMISE_NOT_DELIVERED

    def test_fault_carries_persona_job_context(self):
        contracts = [_page("/settings")]
        promises = Promises(persona_jobs=[
            _job("Member", "Book a class", entities=("Session",)),
        ])
        f = check_promises(contracts, promises)[0]
        # Enough context for the narrator to render a useful sentence.
        assert "Book a class" in f["interaction"]["label"]
        assert f["interaction"]["kind"] == "route"
        # The synthetic interaction_id should be stable.
        assert f["interaction_id"] == f["interaction"]["id"]

    def test_multiple_unfulfilled_jobs_produce_one_fault_each(self):
        contracts = [_page("/x")]
        promises = Promises(persona_jobs=[
            _job("A", "Do X", entities=("Foo",)),
            _job("B", "Do Y", entities=("Bar",)),
        ])
        assert len(check_promises(contracts, promises)) == 2


# ── Robustness ───────────────────────────────────────────────────────────


class TestRobustness:
    def test_deterministic_across_calls(self):
        contracts = [_page("/x")]
        promises = Promises(persona_jobs=[
            _job("A", "Do something", entities=("Baz",)),
        ])
        a = check_promises(contracts, promises)
        b = check_promises(contracts, promises)
        assert a == b

    def test_no_promises_no_faults(self):
        assert check_promises([_page("/x")], Promises()) == []
