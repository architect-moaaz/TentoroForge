"""Drift guard: the editor's workflow node catalog must cover the RUNTIME authority.

The runtime `types.ts` unions (parsed by `workflow_node_contracts`) are the single
source of truth for what the engine executes. The planner + backend translator already
read it; the EDITOR (`frontend/src/types/workflow.ts`) is a separate hand-authored
catalog that historically drifted — it lacked `exclusive_gateway`, `db_update`,
`set_variable`, etc., so generated workflows rendered as "undefined"/"Custom Task".

This test fails the build if the editor is MISSING any runtime node type or action type
(the editor may have MORE — legacy `task_pool`/`escalation` are fine; missing is not).
"""
from pathlib import Path

import pytest

from services.workflow_node_contracts import node_contracts, parse_editor_catalog

_EDITOR_CATALOG = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend" / "src" / "types" / "workflow.ts"
)

# Runtime node types that are NOT distinct user-placeable palette items:
# structural/implicit (trigger/end/action) or surfaced under an editor alias
# (`user_task` is offered as "Assignment"/"Approval"/"Task Pool").
_NON_PALETTE_NODE_TYPES = {"trigger", "end", "end_event", "action", "user_task"}

# AI capabilities appear in BOTH the runtime NodeType and ActionType unions, but the
# editor (and, since A1, the backend translator) represents them as TOP-LEVEL node
# types — so they are covered by the node-type checks, not the ActionType union.
_AI_ACTION_TYPES = {"ai_generate", "ai_classify", "ai_extract", "ai_decide"}


@pytest.fixture(scope="module")
def catalogs():
    if not _EDITOR_CATALOG.exists():
        pytest.skip(f"editor catalog not found at {_EDITOR_CATALOG}")
    return node_contracts(), parse_editor_catalog(str(_EDITOR_CATALOG))


def test_editor_union_covers_every_runtime_node_type(catalogs):
    runtime, editor = catalogs
    missing = sorted(set(runtime["node_types"]) - editor["nodeTypes"])
    assert not missing, (
        f"Editor WorkflowNodeType union is MISSING runtime node types {missing} — "
        f"generated workflows using them render as 'undefined'. Add them to "
        f"frontend/src/types/workflow.ts."
    )


def test_editor_union_covers_every_runtime_action_type(catalogs):
    runtime, editor = catalogs
    # AI action-types are covered as top-level node types, not ActionType members.
    missing = sorted(set(runtime["action_types"]) - _AI_ACTION_TYPES - editor["actionTypes"])
    assert not missing, (
        f"Editor ActionType union is MISSING runtime action types {missing} — "
        f"those action nodes render as 'Custom Task'. Add them to "
        f"frontend/src/types/workflow.ts."
    )


def test_editor_palette_offers_placeable_node_types(catalogs):
    """Every runtime node type a user can drop must be in NODE_CATEGORIES (palette),
    except structural types (trigger/end/action) that aren't hand-placed as bare nodes.
    AI node types are palette items in their own right."""
    runtime, editor = catalogs
    placeable = set(runtime["node_types"]) - _NON_PALETTE_NODE_TYPES
    missing = sorted(placeable - editor["paletteTypes"] - editor["paletteActions"])
    assert not missing, (
        f"Editor palette (NODE_CATEGORIES) is MISSING placeable node types {missing}."
    )


def test_editor_palette_offers_real_action_subtypes(catalogs):
    """The concrete `action` subtypes (db_update, set_variable, …) must be offered as
    palette actions so a user can build what the generator emits. `custom`/`transform`
    are allowed to be absent from the palette (advanced/rare)."""
    runtime, editor = catalogs
    # AI action-types are surfaced as top-level AI palette nodes, not action subtypes.
    ai = {"ai_generate", "ai_classify", "ai_extract", "ai_decide"}
    optional = {"custom", "transform"}
    required = set(runtime["action_types"]) - ai - optional
    missing = sorted(required - editor["paletteActions"])
    assert not missing, (
        f"Editor palette is MISSING action subtypes {missing} (defaultConfig.actionType)."
    )
