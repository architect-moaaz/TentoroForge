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

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]

TYPES_TS = REPO / "frontend" / "src" / "types" / "workflow.ts"
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


def _palette_action_types() -> set[str]:
    """actionType strings that show up as defaultConfig on action nodes."""
    txt = TYPES_TS.read_text()
    return set(re.findall(r'actionType:\s*"([^"]+)"', txt))


def _palette_node_types() -> set[str]:
    """`type: "..."` strings on NODE_CATEGORIES entries — top-level only.

    Node entries look like:
        { id: "…", type: "action", …, defaultConfig: { type: "manual" } }
    We want the outer `type` (kind of node), NOT the nested one inside
    defaultConfig (which is a trigger sub-type like manual / webhook).
    Strip defaultConfig blocks before matching.
    """
    txt = TYPES_TS.read_text()
    start = txt.find("NODE_CATEGORIES")
    if start < 0:
        return set()
    end = txt.find("];", start)
    body = txt[start : end + 2]
    # Remove `defaultConfig: {...}` fragments so their inner `type: "…"`
    # doesn't leak into the match set.
    body = re.sub(r"defaultConfig:\s*\{[^{}]*\}", "", body)
    return set(re.findall(r'\btype:\s*"([^"]+)"', body))


def _contract_keys() -> set[str]:
    """Top-level keys in the ACTION_CONTRACTS object literal."""
    txt = CONTRACTS_TS.read_text()
    start = txt.find("ACTION_CONTRACTS")
    if start < 0:
        return set()
    return set(re.findall(r"^\s{2}(\w+):\s*\{", txt[start:], flags=re.M))


def _engine_switch_cases() -> set[str]:
    """`case "foo":` strings inside the executeNode switch."""
    txt = ENGINE_TS.read_text()
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
