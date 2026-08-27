"""SV-STRICT-3 — fault narrator: signature → plain English for chat.

Every FaultSignature gets a template. Templates reference the component
using its label / route so the user sees "The 'New Candidate' button on
/candidates does nothing when clicked" — not "BUTTON_NO_ACTION_DECLARED".

The narrator is pure: (fault, interaction) → str. No I/O.
"""
from __future__ import annotations

import pytest

from services.fault_classifier import (
    Evidence,
    FaultClassification,
    FaultSignature,
)
from services.fault_narrator import (
    narrate,
    narrate_report,
)
from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    FormInteraction,
    FormSubmit,
    ListInteraction,
    RouteInteraction,
)


def _fault(sig: str, hypothesis: str = "test") -> FaultClassification:
    from services.fault_classifier import _make  # type: ignore
    return _make(sig)


def _button(label: str = "New Candidate",
            route: str = "/candidates",
            action: ButtonAction | None = None) -> ButtonInteraction:
    return ButtonInteraction(
        id=f"button:{route}:{label}", kind="button",
        route=route,
        selector=f"[data-testid='button-{label.lower()}']",
        label=label,
        action=action or ButtonAction(kind="none"),
    )


def _form(label: str = "Create Candidate",
          route: str = "/candidates/new",
          target: str = "CreateCandidate") -> FormInteraction:
    return FormInteraction(
        id=f"form:{route}:{label}", kind="form",
        route=route,
        selector=f"[data-testid='form-{label.lower()}']",
        fields=(),
        submit=FormSubmit(kind="workflow", workflow_target=target),
    )


def _route(route: str = "/candidates", auth: bool = True) -> RouteInteraction:
    return RouteInteraction(id=f"route:{route}", kind="route",
                            route=route, requires_auth=auth)


# ── Per-signature narration ──────────────────────────────────────────────


class TestPerSignatureText:
    def test_button_dead_click_names_the_button(self):
        text = narrate(_fault(FaultSignature.BUTTON_NO_ACTION_DECLARED),
                       _button("New Candidate", "/candidates"))
        # Must name the label + the route + say what's broken in plain English.
        assert "New Candidate" in text
        assert "/candidates" in text
        # No jargon leakage — signature name never appears verbatim.
        assert "BUTTON_NO_ACTION_DECLARED" not in text
        # Sanity check for readability — non-empty, ends with a period.
        assert text.strip().endswith(".")
        assert len(text.split()) >= 6

    def test_button_workflow_missing_names_target(self):
        btn = _button("Book Class", "/schedule",
                      action=ButtonAction(kind="workflow",
                                            workflow_target="ScheduleClass"))
        text = narrate(_fault(FaultSignature.BUTTON_WORKFLOW_MISSING), btn)
        assert "Book Class" in text
        assert "ScheduleClass" in text

    def test_form_submit_500_says_the_form_crashed(self):
        text = narrate(_fault(FaultSignature.FORM_SUBMIT_500_GENERIC),
                       _form("Create Candidate", "/candidates/new"))
        assert "Create Candidate" in text
        assert "form" in text.lower()
        # Some indication of server-side failure
        assert "server" in text.lower() or "crash" in text.lower() \
            or "5" in text or "error" in text.lower()

    def test_route_404_says_page_missing(self):
        text = narrate(_fault(FaultSignature.ROUTE_404_MISSING_SCHEMA),
                       _route("/candidates"))
        assert "/candidates" in text
        assert "missing" in text.lower() or "not found" in text.lower() \
            or "doesn't exist" in text.lower()

    def test_route_401_says_auth_issue(self):
        text = narrate(_fault(FaultSignature.ROUTE_401_UNEXPECTED),
                       _route("/candidates", auth=True))
        assert "sign" in text.lower() or "auth" in text.lower() \
            or "log" in text.lower()

    def test_unknown_signature_still_narrates(self):
        # Fallback template — should never throw, always produce SOMETHING.
        text = narrate(_fault(FaultSignature.UNCLASSIFIED),
                       _button("Some Button", "/somewhere"))
        assert isinstance(text, str)
        assert text.strip() != ""


# ── Report grouping ──────────────────────────────────────────────────────


class TestReportGrouping:
    def test_empty_report_has_zero_narratives(self):
        report = narrate_report([])
        assert report["narratives"] == []
        assert report["by_w_slot"] == {}

    def test_report_groups_by_w_slot(self):
        # A button dead-click and a form 500 — different W-slots, so the
        # report should surface them separately.
        pairs = [
            (_fault(FaultSignature.BUTTON_NO_ACTION_DECLARED),
             _button("New Candidate")),
            (_fault(FaultSignature.FORM_SUBMIT_500_GENERIC),
             _form("Create Candidate")),
        ]
        report = narrate_report(pairs)
        assert set(report["by_w_slot"].keys()) == {"when", "how"}
        assert len(report["by_w_slot"]["when"]) == 1
        assert len(report["by_w_slot"]["how"]) == 1

    def test_narratives_include_priority(self):
        # For chat rendering, each narrative carries its severity so the
        # UI can decorate (BLOCKER = red chip, CONTENT = amber).
        pair = (_fault(FaultSignature.BUTTON_NO_ACTION_DECLARED),
                _button("New Candidate"))
        report = narrate_report([pair])
        assert report["narratives"][0]["priority"] == "BROKEN"

    def test_narrative_carries_component_id(self):
        # Downstream (fault log, applied-fix tracking) needs to join to
        # the component. Text is not enough.
        btn = _button("New Candidate")
        pair = (_fault(FaultSignature.BUTTON_NO_ACTION_DECLARED), btn)
        report = narrate_report([pair])
        assert report["narratives"][0]["component_id"] == btn.id
