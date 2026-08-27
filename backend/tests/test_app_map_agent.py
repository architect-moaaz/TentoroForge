"""App-map skeleton planner — injectable LLM boundary, plan-shaped output."""

import json

import pytest

from agents.app_map_agent import (
    AppMapError,
    normalize_skeleton,
    run_app_map_planner,
)
from services.resource_registry import build_canonical_registry


_CANNED_SKELETON = {
    "app_name": "Field Ops",
    "domain": "logistics",
    "entities": {
        "WorkOrder": {
            "description": "A unit of field work",
            "fields": {"id": "uuid", "status": "varchar", "technicianId": "uuid"},
        },
        "Technician": {
            "description": "A field technician",
            "fields": {"id": "uuid", "fullName": "varchar"},
        },
    },
    "pages": [
        {
            "route": "/work-orders",
            "name": "Work Orders",
            "entity": "WorkOrder",
            "archetype": "list",
            "description": "All work orders",
        },
        {
            "route": "/work-orders/new",
            "name": "New Work Order",
            "entity": "WorkOrder",
            "archetype": "form",
            "description": "Create a work order",
        },
    ],
    "workflows": [
        {"id": "assign-work-order", "trigger": "button", "entity": "WorkOrder"},
    ],
    "roles": ["admin", "technician"],
}


def _fake_query(system_prompt, user_prompt):
    """Canned skeleton as a JSON string (no network)."""
    return json.dumps(_CANNED_SKELETON)


def _fake_query_fenced(system_prompt, user_prompt):
    return "```json\n" + json.dumps(_CANNED_SKELETON) + "\n```"


async def _fake_query_async(system_prompt, user_prompt):
    return json.dumps(_CANNED_SKELETON)


def test_returns_plan_shaped_skeleton():
    result = run_app_map_planner("Field operations app", _query=_fake_query)

    # entities dict -> data_models list (plan-shaped, registry-consumable).
    assert isinstance(result.get("data_models"), list)
    assert len(result["data_models"]) == 2
    names = {m["name"] for m in result["data_models"]}
    assert names == {"WorkOrder", "Technician"}

    # pages carry route/entity/archetype.
    page = next(p for p in result["pages"] if p["route"] == "/work-orders")
    assert page["entity"] == "WorkOrder"
    assert page["archetype"] == "list"

    # workflows carry id/target entity.
    wf = result["workflows"][0]
    assert wf["id"] == "assign-work-order"
    assert wf["entity"] == "WorkOrder"


def test_skeleton_builds_nonempty_registry():
    result = run_app_map_planner("Field operations app", _query=_fake_query)
    registry = build_canonical_registry(result)
    assert registry.get("entities")
    assert len(registry["entities"]) == 2


def test_tolerates_json_fences():
    result = run_app_map_planner("x", _query=_fake_query_fenced)
    assert len(result["data_models"]) == 2


def test_async_query_supported():
    result = run_app_map_planner("x", _query=_fake_query_async)
    assert len(result["data_models"]) == 2


def test_malformed_response_raises_app_map_error():
    with pytest.raises(AppMapError):
        run_app_map_planner("x", _query=lambda s, u: "sorry, no JSON here")


def test_empty_response_raises_app_map_error():
    with pytest.raises(AppMapError):
        run_app_map_planner("x", _query=lambda s, u: "")


def test_query_exception_wrapped_in_app_map_error():
    def boom(s, u):
        raise RuntimeError("transport down")

    with pytest.raises(AppMapError):
        run_app_map_planner("x", _query=boom)


def test_normalize_skeleton_rejects_non_dict():
    with pytest.raises(AppMapError):
        normalize_skeleton(["not", "a", "dict"])  # type: ignore[arg-type]
