"""
Static coverage guard: every palette entry the editor exposes MUST have
a matching contract in actionContracts.ts AND a case in the engine's
switch. When a new node type ships without both, this test fails with a
concrete list of what to add.

This closes the class of drift bug that the 2026-07-23 audit surfaced —
assignment / task_pool / escalation / decision all shipped in the
palette without an engine case and silently ran-to-completion.

Read-only, no fixtures — runs against the checked-in source files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]

CATALOG_JSON = REPO / "frontend" / "src" / "catalog" / "workflow-nodes.json"
CONTRACTS_TS = REPO / "frontend" / "src" / "components" / "workflow" / "actionContracts.ts"
ENGINE_TS = REPO / "backend" / "templates" / "runtime" / "workflows" / "engine.ts"

# Node types that legitimately have no engine case — terminal or
# handled implicitly by the walker (edges from `end` naturally halt).
_ENGINE_IMPLICIT = {"end_event"}

# Node types that legitimately have no contract — flow-control /
# terminal nodes don't declare inputs/outputs.
_CONTRACT_EXEMPT = {
    "trigger",
    "condition",
    "exclusive_gateway",
    "parallel_gateway",
    "fork",
    "join",
    "decision",  # decision has its own rule-table config, not a contract
    "wait",
    "end",
    "end_event",
    "assignment",
    "task_pool",
    "user_task",
    "approval",
    "escalation",
}


def _catalog() -> dict:
    """The workflow node catalog — the palette is derived from it, so it is
    the palette. Read the frontend's emitted copy, which is what the editor
    bundles."""
    return json.loads(CATALOG_JSON.read_text("utf-8"))


def _palette_action_types() -> set[str]:
    """actionType variants the palette offers on action nodes."""
    return {
        v["key"] for n in _catalog()["nodes"] if n["type"] == "action"
        for v in n.get("variants") or []
    }


def _palette_node_types() -> set[str]:
    """Node types the palette offers (a runtime-only alias is flagged
    `palette: false` and is not offered)."""
    return {n["type"] for n in _catalog()["nodes"] if n.get("palette", True)}


def _contract_keys() -> set[str]:
    """Top-level keys in the ACTION_CONTRACTS object literal."""
    txt = CONTRACTS_TS.read_text(encoding="utf-8")
    start = txt.find("ACTION_CONTRACTS")
    if start < 0:
        return set()
    return set(re.findall(r"^\s{2}(\w+):\s*\{", txt[start:], flags=re.M))


def _engine_switch_cases() -> set[str]:
    """`case "foo":` strings inside the executeNode switch."""
    txt = ENGINE_TS.read_text(encoding="utf-8")
    return set(re.findall(r'case\s+"(\w+)":', txt))


def test_every_palette_actiontype_has_a_contract() -> None:
    palette = _palette_action_types()
    contracts = _contract_keys()
    missing = palette - contracts
    assert not missing, (
        "Palette actionType(s) without an entry in "
        "frontend/src/components/workflow/actionContracts.ts: "
        f"{sorted(missing)}. Every action node dropped on the canvas "
        "needs a contract so the Properties panel knows what inputs "
        "and outputs to render."
    )


def test_every_palette_nodetype_has_an_engine_case() -> None:
    palette = _palette_node_types()
    engine = _engine_switch_cases()
    missing = palette - engine - _ENGINE_IMPLICIT
    assert not missing, (
        "Palette node type(s) with no case in engine.ts executeNode "
        f"switch: {sorted(missing)}. Dropping this node on the canvas "
        "would silently run-to-completion because the switch's default "
        "branch skips unknown types. Add a case in "
        "backend/templates/runtime/workflows/engine.ts."
    )


def test_no_contract_leaked_that_isnt_in_the_palette() -> None:
    """A contract without a palette entry is dead code — either wire up
    the palette or delete the contract."""
    palette = _palette_action_types() | (_palette_node_types() & {
        "ai_generate", "ai_classify", "ai_extract", "ai_decide",
    })
    contracts = _contract_keys()
    orphan = contracts - palette - _CONTRACT_EXEMPT
    assert not orphan, (
        "Contract(s) declared without a matching palette entry: "
        f"{sorted(orphan)}. Either add a palette node for them or "
        "delete the contract from actionContracts.ts."
    )


def test_ai_decide_branches_instead_of_fanning_out() -> None:
    """The editor gives ai_decide an else handle, the projection emits then/else
    edges for it and the platform engine routes on the decision. The scaffold
    engine used to follow every outgoing edge after an AI node, so a two-branch
    decision ran both branches in the generated app. Pin the routing."""
    src = ENGINE_TS.read_text("utf-8")
    assert "function branchEdges(" in src
    case = src[src.index('if (node.type === "ai_decide")'):]
    assert "branchEdges(outgoing, decision)" in case[:800]
    # condition routing goes through the same rule, so the two cannot drift
    assert src.count("branchEdges(") >= 3
