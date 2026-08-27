"""SV-STRICT-3b — verify_narration.

Bridges the persisted ``row.report`` shape (raw runner JSON, one Fault
dict per entry) to the classifier + narrator + join stack. The output
is attachable directly to ``row.report["narrated"]`` and read by
verify_summary + the chat UI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.verify_narration import narrate_from_row_report


def _button_fault() -> dict:
    return {
        "interaction_id": "button:/candidates:root.children[0]",
        "interaction": {
            "kind": "button",
            "id": "button:/candidates:root.children[0]",
            "route": "/candidates",
            "selector": "[data-testid='button-new-candidate']",
            "label": "New Candidate",
            "action": {"kind": "none"},
        },
        "evidence": {"status": 200},
    }


def _write(root: Path, rel: str, data: dict | list) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def app_tree(tmp_path: Path) -> Path:
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "version": "1.0", "initialPage": "candidates",
        "pages": [{
            "id": "candidates", "route": "/candidates", "title": "Candidates",
            "schemaFile": "src/schemas/candidates.json",
            "layout": None, "params": [], "shell": True,
        }],
        "transitions": [], "guards": {}, "auth_routes": [], "authGated": True,
    })
    _write(tmp_path, "src/contracts/plan.json", {"workflows": [], "actors": []})
    _write(tmp_path, "registry.json", {
        "entities": {}, "relations": [], "api_routes": {},
        "components": {}, "pages": {}, "workflow_bindings": {}, "rules": {},
    })
    _write(tmp_path, "src/schemas/candidates.json", {
        "id": "candidates", "route": "/candidates", "dataSources": [],
        "root": {"type": "Section", "props": {}, "children": [
            {"type": "Button", "props": {"label": "New Candidate",
                                          "navigate": "/candidates/new"}},
        ]},
    })
    return tmp_path


# ── Shape ────────────────────────────────────────────────────────────────


class TestShape:
    def test_empty_report_returns_empty_shape(self):
        out = narrate_from_row_report({})
        assert out == {"narratives": [], "by_w_slot": {}}

    def test_no_faults_returns_empty(self):
        out = narrate_from_row_report({"faults": []})
        assert out["narratives"] == []
        assert out["by_w_slot"] == {}

    def test_populated_report_returns_narrative_per_fault(self):
        report = {"faults": [_button_fault()]}
        out = narrate_from_row_report(report)
        assert len(out["narratives"]) == 1
        n = out["narratives"][0]
        # Text is user-readable and names the component
        assert "New Candidate" in n["text"]
        assert n["priority"] in {"BLOCKER", "BROKEN", "CONTENT", "FLAKY"}
        assert n["w_slot"] == "when"
        assert n["route"] == "/candidates"


# ── With output_dir → contract_id populated on narratives ────────────────


class TestWithContracts:
    def test_narrative_carries_contract_id(self, app_tree: Path):
        report = {"faults": [_button_fault()]}
        out = narrate_from_row_report(report, output_dir=str(app_tree))
        n = out["narratives"][0]
        assert n.get("contract_id") is not None
        assert n["contract_id"].startswith("button:/candidates:")


# ── Robustness ───────────────────────────────────────────────────────────


class TestRobustness:
    def test_bad_output_dir_still_narrates(self, tmp_path: Path):
        report = {"faults": [_button_fault()]}
        out = narrate_from_row_report(
            report, output_dir=str(tmp_path / "does-not-exist"),
        )
        # Narration still lands even when contracts are unavailable.
        assert len(out["narratives"]) == 1

    def test_malformed_fault_ignored(self):
        # A fault entry missing interaction shape should not break the pass.
        report = {"faults": [{"interaction_id": "x"}]}  # no interaction / evidence
        out = narrate_from_row_report(report)
        # Either narrated as UNCLASSIFIED or dropped — both are fine as
        # long as the call didn't raise.
        assert isinstance(out.get("narratives"), list)
