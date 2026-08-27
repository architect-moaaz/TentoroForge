"""SV-STRICT-2b — pure join: (fault, interaction) → contract_id.

The two extractors emit slightly different ids for widgets (interaction
extractor keys by JSON path in the schema tree; contract extractor
keys by label/dataSource slug). This module bridges them by joining
on the invariant they share: (kind, route, disambiguating signal).

Pure function. Deterministic. Missing matches return None — never
raises, never fabricates.
"""
from __future__ import annotations

import pytest

from services.component_contract import ComponentContract, WSlot
from services.contract_fault_join import join_faults_to_contracts
from services.fault_classifier import Evidence, FaultSignature
from services.fault_report import Fault
from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    DetailInteraction,
    FormInteraction,
    FormSubmit,
    ListInteraction,
    RouteInteraction,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


def _empty_slots():
    return {n: WSlot(slot=n) for n in
            ("what", "who", "where", "when", "how", "why")}


def _mk_contract(id_: str, ctype: str, label: str,
                 route: str | None = None) -> ComponentContract:
    return ComponentContract(id=id_, component_type=ctype, label=label,
                              slots=_empty_slots(), route=route)


def _mk_fault(fault_id: str, interaction, sig: str = FaultSignature.UNCLASSIFIED) -> Fault:
    return Fault(
        id=fault_id,
        interaction=interaction,
        signature=sig,
        priority="BROKEN",
        layer="dom",
        hypothesis="",
        suggested_tools=(),
        evidence=Evidence(),
    )


# ── Route + detail joins (id already matches) ────────────────────────────


class TestRouteJoin:
    def test_route_joins_to_page_contract(self):
        contracts = [_mk_contract("page:/candidates", "page",
                                    "Candidates", "/candidates")]
        interaction = RouteInteraction(id="route:/candidates", kind="route",
                                        route="/candidates", requires_auth=True)
        faults = [_mk_fault("route:/candidates", interaction)]

        joined = join_faults_to_contracts(faults, contracts)
        assert joined["route:/candidates"] == "page:/candidates"

    def test_detail_route_prefers_detail_contract(self):
        # A [id] route has BOTH a page contract and a detail contract
        # emitted for it. A RouteInteraction should match page; a
        # DetailInteraction should match detail.
        contracts = [
            _mk_contract("page:/candidates/[id]", "page",
                          "Candidate Detail", "/candidates/[id]"),
            _mk_contract("detail:/candidates/[id]", "detail",
                          "Candidate Detail", "/candidates/[id]"),
        ]
        detail_int = DetailInteraction(id="detail:/candidates/[id]",
                                        kind="detail",
                                        route="/candidates/[id]",
                                        entity="Candidate",
                                        param_name="id")
        faults = [_mk_fault("detail:/candidates/[id]", detail_int)]
        joined = join_faults_to_contracts(faults, contracts)
        assert joined["detail:/candidates/[id]"] == "detail:/candidates/[id]"

    def test_route_join_falls_back_to_page_when_no_detail(self):
        # A RouteInteraction on a bracket-param route should still match
        # the page contract (the detail contract might not exist).
        contracts = [_mk_contract("page:/x", "page", "X", "/x")]
        interaction = RouteInteraction(id="route:/x", kind="route",
                                        route="/x", requires_auth=False)
        faults = [_mk_fault("route:/x", interaction)]
        assert join_faults_to_contracts(faults, contracts)["route:/x"] == "page:/x"


# ── Button joins (id schemes differ) ─────────────────────────────────────


class TestButtonJoin:
    def test_button_by_route_plus_label(self):
        # Interaction id is path-keyed; contract id is label-keyed.
        # Both name the same button on /candidates ("New Candidate").
        contracts = [
            _mk_contract("button:/candidates:new-candidate", "button",
                          "New Candidate", "/candidates"),
        ]
        interaction = ButtonInteraction(
            id="button:/candidates:root.children[0]",
            kind="button", route="/candidates",
            selector="[data-testid='button-new-candidate']",
            label="New Candidate",
            action=ButtonAction(kind="navigate", navigate_target="/candidates/new"),
        )
        faults = [_mk_fault(interaction.id, interaction)]
        joined = join_faults_to_contracts(faults, contracts)
        assert joined[interaction.id] == "button:/candidates:new-candidate"

    def test_button_with_ambiguous_label_still_joins_by_route(self):
        # No label-matching contract; still return the sole route button.
        contracts = [
            _mk_contract("button:/candidates:whatever", "button",
                          "Other", "/candidates"),
        ]
        interaction = ButtonInteraction(
            id="button:/candidates:root.children[0]",
            kind="button", route="/candidates",
            selector="", label="Different Label",
            action=ButtonAction(kind="none"),
        )
        joined = join_faults_to_contracts([_mk_fault(interaction.id, interaction)],
                                            contracts)
        # Sole route match wins even when labels disagree.
        assert joined[interaction.id] == "button:/candidates:whatever"

    def test_button_multiple_candidates_picks_label_match(self):
        contracts = [
            _mk_contract("button:/x:save", "button", "Save", "/x"),
            _mk_contract("button:/x:cancel", "button", "Cancel", "/x"),
        ]
        interaction = ButtonInteraction(
            id="button:/x:root.children[1]", kind="button", route="/x",
            selector="", label="Cancel",
            action=ButtonAction(kind="none"),
        )
        joined = join_faults_to_contracts([_mk_fault(interaction.id, interaction)],
                                            contracts)
        assert joined[interaction.id] == "button:/x:cancel"


# ── Form + Table joins ───────────────────────────────────────────────────


class TestFormAndTableJoin:
    def test_form_joins_by_route(self):
        contracts = [_mk_contract("form:/candidates/new:create", "form",
                                    "Create", "/candidates/new")]
        interaction = FormInteraction(
            id="form:/candidates/new:root", kind="form",
            route="/candidates/new", selector="", fields=(),
            submit=FormSubmit(kind="workflow", workflow_target="CreateCandidate"),
        )
        joined = join_faults_to_contracts([_mk_fault(interaction.id, interaction)],
                                            contracts)
        assert joined[interaction.id] == "form:/candidates/new:create"

    def test_list_joins_to_table_contract_by_route_and_datasource(self):
        # ListInteraction (runner-side) → table contract (authority-side).
        contracts = [
            _mk_contract("table:/candidates:candidates", "table",
                          "Table", "/candidates"),
        ]
        interaction = ListInteraction(
            id="list:/candidates:root.children[1]", kind="list",
            route="/candidates", selector="",
            dataSource="candidates", entity="Candidate",
            seed_min_rows=1,
        )
        joined = join_faults_to_contracts([_mk_fault(interaction.id, interaction)],
                                            contracts)
        assert joined[interaction.id] == "table:/candidates:candidates"


# ── Robustness ───────────────────────────────────────────────────────────


class TestRobustness:
    def test_no_contracts_returns_all_none(self):
        interaction = RouteInteraction(id="route:/x", kind="route",
                                        route="/x", requires_auth=False)
        faults = [_mk_fault("route:/x", interaction)]
        assert join_faults_to_contracts(faults, []) == {"route:/x": None}

    def test_no_faults_returns_empty(self):
        contracts = [_mk_contract("page:/x", "page", "X", "/x")]
        assert join_faults_to_contracts([], contracts) == {}

    def test_no_route_match_returns_none(self):
        contracts = [_mk_contract("page:/x", "page", "X", "/x")]
        interaction = RouteInteraction(id="route:/y", kind="route",
                                        route="/y", requires_auth=False)
        joined = join_faults_to_contracts([_mk_fault("route:/y", interaction)],
                                            contracts)
        assert joined["route:/y"] is None

    def test_deterministic_across_calls(self):
        contracts = [_mk_contract("page:/x", "page", "X", "/x")]
        interaction = RouteInteraction(id="route:/x", kind="route",
                                        route="/x", requires_auth=False)
        faults = [_mk_fault("route:/x", interaction)]
        a = join_faults_to_contracts(faults, contracts)
        b = join_faults_to_contracts(faults, contracts)
        assert a == b
