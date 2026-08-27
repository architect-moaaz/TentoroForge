# backend/tests/services/test_figma_plan_binding.py
import asyncio
from services.figma_plan_binding import build_binding_analysis_input
from services.figma_plan_binding import merge_binding_analysis
from services.figma_plan_binding import enrich_figma_plan_with_bindings


def test_build_input_lists_pages_and_button_texts():
    plan = {"pages": [{"route": "/trucks", "name": "Trucks", "type": "list",
                       "figma_node_id": "1:2", "file": "src/schemas/trucks.json"}]}
    file_meta = {"document": {"children": [{"type": "CANVAS", "children": [
        {"type": "FRAME", "id": "1:2", "name": "Trucks", "children": [
            {"type": "TEXT", "characters": "Approve"},
            {"type": "TEXT", "characters": "Truck Name"},
        ]},
    ]}]}}
    out = build_binding_analysis_input(plan, file_meta)
    page = out["pages"][0]
    assert page["route"] == "/trucks"
    assert "Approve" in page["texts"]
    assert "Truck Name" in page["texts"]


def test_build_input_handles_missing_frame():
    plan = {"pages": [{"route": "/x", "name": "X", "figma_node_id": "9:9", "file": "f"}]}
    out = build_binding_analysis_input(plan, {"document": {"children": []}})
    assert out["pages"][0]["texts"] == []


def test_merge_adds_models_workflows_and_page_intent():
    plan = {"pages": [{"route": "/trucks", "name": "Trucks", "file": "src/schemas/trucks.json", "entity": None}]}
    analysis = {
        "data_models": [{"name": "Truck", "fields": [{"name": "name", "type": "varchar"}]}],
        "workflows": [{"name": "ApproveTruck", "description": "approve a truck"}],
        "pages": [{"route": "/trucks", "entity": "Truck",
                   "actions": [{"label": "Approve", "workflow": "ApproveTruck", "kind": "row_action"}]}],
    }
    out = merge_binding_analysis(plan, analysis)
    assert out["data_models"][0]["name"] == "Truck"
    assert out["workflows"][0]["name"] == "ApproveTruck"
    page = out["pages"][0]
    assert page["entity"] == "Truck"
    assert page["actions"][0]["workflow"] == "ApproveTruck"


def test_merge_drops_actions_with_unknown_workflow():
    plan = {"pages": [{"route": "/x", "file": "f", "entity": None}]}
    analysis = {"data_models": [], "workflows": [{"name": "Known", "description": ""}],
                "pages": [{"route": "/x", "entity": "E", "actions": [
                    {"label": "Good", "workflow": "Known", "kind": "page_action"},
                    {"label": "Bad", "workflow": "Ghost", "kind": "page_action"},
                ]}]}
    out = merge_binding_analysis(plan, analysis)
    labels = [a["label"] for a in out["pages"][0]["actions"]]
    assert labels == ["Good"]


def test_merge_is_safe_with_empty_analysis():
    plan = {"pages": [{"route": "/x", "file": "f", "entity": None}]}
    out = merge_binding_analysis(plan, {})
    assert out["pages"][0]["entity"] is None
    assert out["pages"][0]["actions"] == []
    assert out["data_models"] == []
    assert out["workflows"] == []


def test_enrich_uses_injected_llm_and_merges():
    plan = {"name": "Gate App",
            "pages": [{"route": "/trucks", "name": "Trucks", "figma_node_id": "1:2",
                       "file": "src/schemas/trucks.json", "entity": None}]}
    file_meta = {"document": {"children": []}}

    async def fake_llm(prompt: str) -> dict:
        return {"data_models": [{"name": "Truck", "fields": [{"name": "name", "type": "varchar"}]}],
                "workflows": [{"name": "ApproveTruck", "description": "x"}],
                "pages": [{"route": "/trucks", "entity": "Truck",
                           "actions": [{"label": "Approve", "workflow": "ApproveTruck", "kind": "row_action"}]}]}

    out = asyncio.run(enrich_figma_plan_with_bindings(plan, file_meta, call_llm=fake_llm))
    assert out["pages"][0]["entity"] == "Truck"
    assert out["data_models"][0]["name"] == "Truck"


def test_enrich_falls_back_to_unmodified_plan_on_llm_error():
    plan = {"pages": [{"route": "/x", "file": "f", "entity": None}]}

    async def boom(prompt: str) -> dict:
        raise RuntimeError("llm down")

    out = asyncio.run(enrich_figma_plan_with_bindings(plan, {}, call_llm=boom))
    assert out["pages"][0]["entity"] is None
    assert out.get("data_models", []) == []
