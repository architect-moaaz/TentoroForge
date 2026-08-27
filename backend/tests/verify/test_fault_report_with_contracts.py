"""SV-STRICT-2b integration — build_report_from_runner + output_dir.

Legacy callers (no output_dir) still get the pre-existing shape. New
callers get contracts + contract_id on every fault.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.fault_report import build_report_from_runner


def _write(root: Path, rel: str, data: dict | list) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _mk_runner_report_with_button_fault() -> dict:
    """Minimal RunReport shape matching what forge-verify emits."""
    return {
        "run_id": "test-run",
        "project_id": "test-proj",
        "target": "preview",
        "base_url": "http://x",
        "started_at": "",
        "finished_at": "",
        "interactions_run": 1,
        "interactions_passed": 0,
        "interactions_flaky": 0,
        "faults": [{
            "interaction_id": "button:/candidates:root.children[0]",
            "interaction": {
                "kind": "button",
                "id": "button:/candidates:root.children[0]",
                "route": "/candidates",
                "selector": "[data-testid='button-new-candidate']",
                "label": "New Candidate",
                "action": {"kind": "none"},
            },
            "evidence": {
                "status": 200,
                "dom_snapshot": "<button>New Candidate</button>",
            },
        }],
    }


@pytest.fixture
def app_tree(tmp_path: Path) -> Path:
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "version": "1.0",
        "initialPage": "candidates",
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
        "id": "candidates", "route": "/candidates",
        "dataSources": [],
        "root": {"type": "Section", "props": {}, "children": [
            {"type": "Button", "props": {"label": "New Candidate",
                                          "navigate": "/candidates/new"}},
        ]},
    })
    return tmp_path


# ── Back-compat: legacy call site sees unchanged behavior ────────────────


class TestLegacyCallSite:
    def test_no_output_dir_leaves_contracts_empty(self):
        r = build_report_from_runner(_mk_runner_report_with_button_fault())
        assert r.contracts == []

    def test_no_output_dir_leaves_contract_id_none(self):
        r = build_report_from_runner(_mk_runner_report_with_button_fault())
        assert r.faults[0].contract_id is None

    def test_no_output_dir_still_carries_w_slot(self):
        # w_slot annotation is unconditional — no output_dir needed.
        r = build_report_from_runner(_mk_runner_report_with_button_fault())
        assert r.faults[0].w_slot == "when"


# ── With output_dir: contracts + join land ───────────────────────────────


class TestWithOutputDir:
    def test_contracts_list_populated(self, app_tree: Path):
        r = build_report_from_runner(
            _mk_runner_report_with_button_fault(),
            output_dir=str(app_tree),
        )
        assert r.contracts, "contracts list should not be empty"
        # sanity: every entry looks contract-shaped
        for c in r.contracts:
            assert "id" in c and "component_type" in c and "slots" in c

    def test_button_fault_joins_to_button_contract(self, app_tree: Path):
        r = build_report_from_runner(
            _mk_runner_report_with_button_fault(),
            output_dir=str(app_tree),
        )
        button = r.faults[0]
        assert button.contract_id is not None
        assert button.contract_id.startswith("button:/candidates:")

    def test_page_contract_also_emitted(self, app_tree: Path):
        r = build_report_from_runner(
            _mk_runner_report_with_button_fault(),
            output_dir=str(app_tree),
        )
        types = {c["component_type"] for c in r.contracts}
        assert "page" in types
        assert "button" in types


# ── Fail-open: unreadable output_dir does not crash ─────────────────────


class TestRobustness:
    def test_bad_output_dir_does_not_raise(self, tmp_path: Path):
        # non-existent output dir → contracts remain empty, faults still built
        r = build_report_from_runner(
            _mk_runner_report_with_button_fault(),
            output_dir=str(tmp_path / "does-not-exist"),
        )
        assert r.contracts == []
        assert r.faults[0].w_slot == "when"
        assert r.faults[0].contract_id is None
