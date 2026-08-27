"""Drift guard for the workflow-node vocabulary.

Fails the build when the workflow generator can emit an action the runtime has
no handler for, when a handler silently regresses to a stub, or when the AI
nodes lose their registration. This is what would have caught the
`send_notification`-was-a-stub class of bug automatically.
"""
import json
import re
from pathlib import Path

from services.workflow_node_contracts import (
    node_contracts,
    KNOWN_STUBS,
    emit_node_catalog_json,
    parse_editor_catalog,
)

_EDITOR_TYPES = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "types" / "workflow.ts"

_GEN = Path(__file__).resolve().parent.parent / "services" / "workflow_generator.py"


def _generator_emitted_actions() -> set[str]:
    """actionTypes the generator assigns (config["actionType"] = "...")."""
    src = _GEN.read_text(encoding="utf-8")
    return set(re.findall(r'config\["actionType"\]\s*=\s*"([a-z_]+)"', src))


def _generator_emitted_ai_nodes() -> set[str]:
    """AI node types the generator classifies steps into (return "ai_...")."""
    src = _GEN.read_text(encoding="utf-8")
    return set(re.findall(r'return "(ai_[a-z]+)"', src))


def test_every_action_type_has_a_handler():
    """Every ActionType in the union has a registered or inline handler."""
    c = node_contracts()
    handled = set(c["actions"])
    missing = [a for a in c["action_types"] if a not in handled]
    assert not missing, f"ActionType(s) declared but with NO handler: {missing}"


def test_generator_emitted_actions_are_handled():
    """Every action the workflow generator emits actually has a handler —
    otherwise generated workflows run green while doing nothing."""
    c = node_contracts()
    handled = set(c["actions"])
    missing = sorted(_generator_emitted_actions() - handled)
    assert not missing, f"workflow_generator emits actions with no runtime handler: {missing}"


def test_generator_ai_nodes_are_registered():
    c = node_contracts()
    handled = set(c["actions"])
    missing = sorted(_generator_emitted_ai_nodes() - handled)
    assert not missing, f"workflow_generator emits AI nodes with no handler: {missing}"


def test_no_unexpected_stub_handlers():
    """Any stub (no-op) handler must be explicitly known; a NEW stub is a
    silent-no-op regression that must be made real or acknowledged."""
    c = node_contracts()
    stubs = {a for a, info in c["actions"].items() if info.get("stub")}
    unexpected = sorted(stubs - KNOWN_STUBS)
    assert not unexpected, (
        f"Unexpected STUB handler(s) (silent no-ops): {unexpected}. "
        "Make them real, or add to KNOWN_STUBS in workflow_node_contracts.py."
    )


def test_catalog_is_nonempty_and_consistent():
    c = node_contracts()
    assert "ai_extract" in c["action_types"], "ActionType union not parsed"
    assert "schedule" in c["trigger_types"], "TriggerType union not parsed"
    assert "approval" in c["node_types"], "NodeType union not parsed"


# ---------------------------------------------------------------------------
# A2: machine catalog emission + editor-catalog parser
# ---------------------------------------------------------------------------


def test_emit_node_catalog_json_round_trips(tmp_path):
    out = emit_node_catalog_json(tmp_path / "workflow-node-catalog.json")
    assert Path(out).exists()
    data = json.loads(Path(out).read_text(encoding="utf-8"))
    c = node_contracts()
    assert data["nodeTypes"] == list(c["node_types"])
    assert data["actionTypes"] == list(c["action_types"])
    assert data["triggerTypes"] == list(c["trigger_types"])
    # sanity: known members present
    assert "trigger" in data["nodeTypes"]
    assert "db_query" in data["actionTypes"]
    assert "schedule" in data["triggerTypes"]


def test_parse_editor_catalog_reads_real_editor_types():
    cat = parse_editor_catalog(_EDITOR_TYPES)
    # non-empty sets
    assert cat["nodeTypes"] and cat["actionTypes"]
    assert cat["paletteTypes"] and cat["paletteActions"]
    # known members from the editor's own unions
    assert "trigger" in cat["nodeTypes"]
    assert "action" in cat["nodeTypes"]
    assert "db_query" in cat["actionTypes"]
    # palette-derived sets
    assert "action" in cat["paletteTypes"]
    assert "custom" in cat["paletteActions"]
    # everything is a set
    for k in ("nodeTypes", "actionTypes", "paletteTypes", "paletteActions"):
        assert isinstance(cat[k], set)
