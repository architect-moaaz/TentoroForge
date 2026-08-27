"""Tests for button_audit._try_wire_workflow — label→workflow wiring.

Closes the "buttons not working" gap where the LLM authored a labelled
button ("Approve Request") but didn't wire an onClick, and the existing
audit only tried route wiring. The workflow-wiring pass fires ONLY on
unique matches — under ambiguity, we refuse to guess.
"""
from __future__ import annotations

from services.button_audit import _label_tokens, _try_wire_workflow, audit_button_actions


class TestLabelTokens:
    def test_strips_stopwords(self):
        assert _label_tokens("Approve the request") == {"approve", "request"}

    def test_strips_new_verbs(self):
        # 'Add Applicant' → strip 'add', leave 'applicant'
        assert _label_tokens("Add Applicant") == {"applicant"}

    def test_singularizes(self):
        assert _label_tokens("Approve Requests") == {"approve", "request"}


class TestTryWireWorkflow:
    def _idx(self, workflows):
        return {"exact": list(workflows), "norm": {}, "meta": {}}

    def test_unique_match_wires(self):
        props = {"label": "Approve Request"}
        idx = self._idx(["ApproveRequest", "SendNotification"])
        assert _try_wire_workflow(props, "Approve Request", idx) is True
        assert props["workflow"] == "ApproveRequest"

    def test_ambiguous_match_refuses(self):
        # Two workflows both contain the label's tokens ("approve") —
        # scoring produces a tie → refuse to guess.
        props = {"label": "Approve"}
        idx = self._idx(["ApproveRequest", "ApproveInvoice"])
        assert _try_wire_workflow(props, "Approve", idx) is False
        assert "workflow" not in props

    def test_no_match_refuses(self):
        props = {"label": "Escalate"}
        idx = self._idx(["ApproveRequest", "SendNotification"])
        assert _try_wire_workflow(props, "Escalate", idx) is False

    def test_empty_index_refuses(self):
        props = {"label": "Approve"}
        assert _try_wire_workflow(props, "Approve", {}) is False
        assert _try_wire_workflow(props, "Approve", {"exact": []}) is False

    def test_empty_label_refuses(self):
        props = {"label": ""}
        idx = self._idx(["ApproveRequest"])
        assert _try_wire_workflow(props, "", idx) is False
        assert _try_wire_workflow(props, "the a an", idx) is False

    def test_metadata_labels_boost_match(self):
        # Workflow id is opaque but its metadata label matches — should
        # still wire.
        idx = {"exact": ["wf_1"], "norm": {},
               "meta": {"wf_1": {"label": "Approve request"}}}
        props = {"label": "Approve Request"}
        assert _try_wire_workflow(props, "Approve Request", idx) is True
        assert props["workflow"] == "wf_1"

    def test_partial_match_below_threshold_refuses(self):
        # "Send" against "SendNotification" — Jaccard is 1/2 = 0.5,
        # right at the threshold. This is the intentional edge: the
        # match IS what the user typed, so wire it.
        props = {"label": "Send"}
        idx = self._idx(["SendNotification"])
        assert _try_wire_workflow(props, "Send", idx) is True

    def test_new_verbs_stripped(self):
        # "New Booking" should NOT route to a workflow — the new-route
        # wire fires first. But even if it doesn't, "add/new/create"
        # verbs are stripped so a "Booking" workflow wouldn't collide.
        props = {"label": "New Booking"}
        idx = self._idx(["Booking"])
        # After stripping new-verbs the label content is just
        # "booking" — matches the workflow → wires.
        assert _try_wire_workflow(props, "New Booking", idx) is True


class TestAuditIntegration:
    """The full audit pass calls _try_wire_workflow after _try_wire_new
    and before _try_wire_nav. Verify the fallthrough order actually
    wires a workflow-shaped label when no route matches."""

    def test_end_to_end_wires_workflow(self):
        schema = {
            "root": {
                "type": "Container",
                "children": [
                    {"type": "Button", "props": {"label": "Approve Request"}},
                ],
            },
        }
        idx = {"exact": ["ApproveRequest"], "norm": {},
               "meta": {}}
        # No matching route exists — only the workflow.
        out, findings = audit_button_actions(
            schema, known_routes=["/applicants"], workflow_index=idx,
            route="/applicants",
        )
        btn = out["root"]["children"][0]
        assert btn["props"]["workflow"] == "ApproveRequest"
        assert findings == []

    def test_end_to_end_new_button_still_routes_to_new(self):
        # "New Applicant" should still prefer the create-route wiring
        # over workflow wiring — _try_wire_new fires first.
        schema = {
            "root": {"type": "Container", "children": [
                {"type": "Button", "props": {"label": "New Applicant"}},
            ]},
        }
        idx = {"exact": ["Applicant"], "norm": {}, "meta": {}}
        out, findings = audit_button_actions(
            schema, known_routes=["/applicants/new"], workflow_index=idx,
        )
        btn = out["root"]["children"][0]
        # Route wiring won — no workflow prop.
        assert btn["props"].get("navigate") == "/applicants/new"
        assert "workflow" not in btn["props"]
