"""SV-STRICT-2a — every FaultClassification carries its W-slot tag.

The W-slot names WHICH promise the fault falsifies. Slice 3's narrator
groups by it; Slice 5's fault log records it. The mapping is intrinsic
to the signature (not the evidence) so it stays deterministic.

Slot vocabulary matches component_contract.SlotName exactly:
  what | who | where | when | how | why
"""
from __future__ import annotations

import pytest

from services.fault_classifier import (
    Evidence,
    FaultSignature,
    LogEntry,
    NetworkEntry,
    classify,
    w_slot_for_signature,
)
from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    FormInteraction,
    FormSubmit,
    ListInteraction,
    RouteInteraction,
)


# ── Mapping surface ──────────────────────────────────────────────────────


class TestMappingCompleteness:
    def test_every_signature_has_a_w_slot(self):
        # w_slot_for_signature MUST return a valid slot for every known
        # signature. UNCLASSIFIED gets 'what' as the safe default (we
        # know a promise was broken, we just don't know which one).
        allowed = {"what", "who", "where", "when", "how", "why"}
        for name, sig in vars(FaultSignature).items():
            if not isinstance(sig, str) or not name.isupper():
                continue
            slot = w_slot_for_signature(sig)
            assert slot in allowed, f"{sig} → {slot!r} not in slot vocabulary"

    def test_unknown_signature_falls_back_to_what(self):
        assert w_slot_for_signature("TOTALLY_MADE_UP") == "what"


class TestSignatureSemantics:
    """Each signature's W-slot must match what it actually falsifies."""

    def test_route_404_is_a_where_failure(self):
        # The route "isn't there" — the WHERE promise is broken.
        assert w_slot_for_signature(FaultSignature.ROUTE_404_MISSING_SCHEMA) == "where"

    def test_route_401_is_a_who_failure(self):
        # The route rejects who the runner claims to be.
        assert w_slot_for_signature(FaultSignature.ROUTE_401_UNEXPECTED) == "who"

    def test_button_dead_click_is_a_when_failure(self):
        # BUTTON_NO_ACTION_DECLARED: the click WHEN didn't do anything.
        assert w_slot_for_signature(FaultSignature.BUTTON_NO_ACTION_DECLARED) == "when"

    def test_button_workflow_missing_is_a_how_failure(self):
        # The MECHANISM (workflow dispatch) is broken — the button knew
        # when to fire, but the how failed.
        assert w_slot_for_signature(FaultSignature.BUTTON_WORKFLOW_MISSING) == "how"

    def test_button_nav_target_missing_is_a_where_failure(self):
        # Navigated to a route that doesn't exist — WHERE the click
        # tried to go is broken.
        assert w_slot_for_signature(FaultSignature.BUTTON_NAV_TARGET_MISSING) == "where"

    def test_form_submit_500_is_a_how_failure(self):
        # Form knew when to submit, submit target existed, the submit
        # MECHANISM crashed.
        assert w_slot_for_signature(FaultSignature.FORM_SUBMIT_500_GENERIC) == "how"
        assert w_slot_for_signature(FaultSignature.FORM_SUBMIT_500_FK) == "how"

    def test_form_submit_400_is_a_how_failure(self):
        # Input shape mismatch — the how (payload contract) is wrong.
        assert w_slot_for_signature(FaultSignature.FORM_SUBMIT_400) == "how"

    def test_list_empty_is_a_what_failure(self):
        # The Table WHAT (rows of data) isn't delivered.
        assert w_slot_for_signature(FaultSignature.LIST_EMPTY) == "what"

    def test_dashboard_blank_is_a_what_failure(self):
        assert w_slot_for_signature(FaultSignature.DASHBOARD_BLANK) == "what"

    def test_detail_binding_unresolved_is_a_how_failure(self):
        # The MECHANISM that resolves :id → record is broken.
        assert w_slot_for_signature(FaultSignature.DETAIL_BINDING_UNRESOLVED) == "how"

    def test_ssr_500_is_a_what_failure(self):
        # Route promised to render — it didn't. WHAT.
        for sig in (FaultSignature.SSR_500_ENOENT_JSON,
                    FaultSignature.SSR_500_UNKNOWN_TABLE,
                    FaultSignature.SSR_500_MODULE_NOT_FOUND,
                    FaultSignature.SSR_500_GENERIC):
            assert w_slot_for_signature(sig) == "what"


# ── Classification carries w_slot end-to-end ─────────────────────────────


class TestClassificationCarriesWSlot:
    def test_classify_output_has_w_slot(self):
        # Any classify() call must produce a FaultClassification whose
        # w_slot field matches the signature's mapping.
        route = RouteInteraction(
            id="route:/candidates", kind="route",
            route="/candidates", requires_auth=True,
        )
        # A 401 on an auth-gated route → ROUTE_401_UNEXPECTED
        ev = Evidence(status=401, body_excerpt="unauthorized")
        result = classify(route, ev)
        assert hasattr(result, "w_slot")
        assert result.w_slot == w_slot_for_signature(result.signature)

    def test_button_dead_click_is_when(self):
        btn = ButtonInteraction(
            id="button:/candidates:new", kind="button",
            route="/candidates", selector="[data-testid='button-new']",
            label="New Candidate",
            action=ButtonAction(kind="none"),
        )
        ev = Evidence(dom_snapshot="<button>New Candidate</button>",
                      network_log=[], url_after_click="/candidates")
        result = classify(btn, ev)
        assert result.signature == FaultSignature.BUTTON_NO_ACTION_DECLARED
        assert result.w_slot == "when"

    def test_form_submit_500_is_how(self):
        form = FormInteraction(
            id="form:/candidates/new:form", kind="form",
            route="/candidates/new", selector="[data-testid='form-form']",
            fields=(),
            submit=FormSubmit(kind="workflow", workflow_target="CreateCandidate"),
        )
        ev = Evidence(
            # Classifier top-level status is the primary-action status
            # for a Form, which is the POST response.
            status=500,
            network_log=[NetworkEntry(method="POST",
                                       url="/api/workflows/CreateCandidate/start",
                                       status=500)],
            body_excerpt="Internal Server Error",
        )
        result = classify(form, ev)
        assert result.signature == FaultSignature.FORM_SUBMIT_500_GENERIC
        assert result.w_slot == "how"
