# backend/tests/services/test_app_design_catalog.py
import json
from pathlib import Path

from services.app_design_catalog import (
    ARCHETYPES, FEATURES, APP_ARCHETYPES, archetype_names, feature_names,
    is_renderable_archetype, is_renderable_feature, catalog_for_prompt,
    app_archetype_names, app_archetype_spec, classify_app_archetype,
)


def test_archetypes_cover_new_set_and_are_renderable():
    for a in ["kanban", "calendar", "inbox", "report", "wizard", "audit-log", "settings", "timeline"]:
        assert a in ARCHETYPES, a
        assert ARCHETYPES[a]["renderable"] is True


def test_archetypes_only_use_registered_components():
    registered = {"Kanban","Calendar","Timeline","ResourceTimeline","Chart","Tree","InspectorPanel",
        "ApprovalStepper","ActivityFeed","DataGrid","Table","FilterBar","Tabs",
        "Split","Stat","MetricTile","DateRangePicker","Form","Card","Grid","Row",
        "Stack","Heading","Button","KeyValueList","Input","Text"}
    for name, spec in ARCHETYPES.items():
        assert set(spec["components"]) <= registered, (name, set(spec["components"]) - registered)


def test_features_map_to_primitive_and_flag_sp2():
    assert FEATURES["status-pipeline"]["primitive"] == "workflow"
    assert FEATURES["approval"]["primitive"] == "workflow"
    # SP2-only features are catalogued but flagged
    assert FEATURES["sla-escalation"]["renderable_in"] == "SP2"


def test_helpers():
    assert "kanban" in archetype_names()
    assert is_renderable_archetype("kanban") and not is_renderable_archetype("nope")
    assert is_renderable_feature("approval") and not is_renderable_feature("sla-escalation")
    assert "status-pipeline" in feature_names()
    txt = catalog_for_prompt()
    assert "kanban" in txt and "approval" in txt
    assert "sla-escalation" not in txt   # SP2 features excluded from the prompt


# ── APP-LEVEL ARCHETYPES (Slice 3 / visual-product-search) ────────────────


def test_visual_product_search_registered():
    """The app-level archetype exists and has the spec shape the planner
    expects: label, description, signals, entities, has_agent, default_features."""
    assert "visual-product-search" in APP_ARCHETYPES
    assert "visual-product-search" in app_archetype_names()
    spec = app_archetype_spec("visual-product-search")
    assert spec is not None
    assert spec["label"] == "Visual Product Search"
    assert isinstance(spec["description"], str) and spec["description"]
    assert isinstance(spec["signals"], list) and spec["signals"]
    assert set(spec["entities"]) == {"scan_events", "retail_sources", "users"}
    assert spec["has_agent"] is True
    assert "camera_upload" in spec["default_features"]
    assert "admin_source_control" in spec["default_features"]
    assert "outbound_links" in spec["default_features"]


def test_app_archetype_spec_unknown_returns_none():
    assert app_archetype_spec(None) is None
    assert app_archetype_spec("") is None
    assert app_archetype_spec("nope") is None


def test_classify_matches_canonical_brief():
    """The exact brief the spec's Slice 3 acceptance test uses."""
    brief = "an app to scan a product and see prices"
    assert classify_app_archetype(brief) == "visual-product-search"


def test_classify_matches_signal_phrases():
    """Every registered signal should trigger classification when in a brief."""
    for signal in APP_ARCHETYPES["visual-product-search"]["signals"]:
        brief = f"I want an app that does {signal} for shoppers"
        assert classify_app_archetype(brief) == "visual-product-search", signal


def test_classify_is_case_insensitive():
    assert classify_app_archetype("SCAN a product with my CAMERA") == "visual-product-search"


def test_classify_returns_none_on_empty_or_missing():
    assert classify_app_archetype(None) is None
    assert classify_app_archetype("") is None
    assert classify_app_archetype("   ") is None


def test_classify_returns_none_on_generic_brief():
    assert classify_app_archetype("a todo list app") is None
    assert classify_app_archetype("employee leave management") is None


def test_classify_rejects_photo_gallery():
    """A photo-gallery app mentions images and gallery but is NOT a
    visual-product-search — negative signal must reject it even though
    it might otherwise brush against a positive."""
    assert classify_app_archetype("a photo gallery app to organise my images") is None
    assert classify_app_archetype("an image gallery with albums") is None


def test_classify_rejects_receipt_scanner():
    """A receipt scanner uses the word 'scan' but is a text-extraction
    app, not a product-identifier — negative signal must reject it."""
    assert classify_app_archetype("a receipt scanner app for expense tracking") is None
    assert classify_app_archetype("scan a receipt to record expenses") is None


def test_classify_rejects_document_and_barcode_scanners():
    """Adjacent 'scan' apps (documents, barcodes, QR) are not visual
    product search — they identify text/code, not products from images."""
    assert classify_app_archetype("document scanner for PDFs") is None
    assert classify_app_archetype("barcode scanner for inventory") is None
    assert classify_app_archetype("qr code scanner for events") is None


def test_visual_product_search_exemplar_fixture_present_and_valid_json():
    """The planner exemplar fixture that Slice 3 registers must load and
    include the canonical entities, an `agent_graph` block (SP4.5 shape),
    and an MCP integration ref keyed by `firecrawl`."""
    fixture = (
        Path(__file__).resolve().parents[2]
        / "services" / "schema_examples" / "visual_product_search.json"
    )
    assert fixture.exists(), fixture
    data = json.loads(fixture.read_text())
    entity_names = {e["name"] for e in data["entities"]}
    assert {"scan_events", "retail_sources", "users"} <= entity_names
    assert data["app_archetype"] == "visual-product-search"
    # SP4.5 contract: `agent_graph` is the plan-level slot the pipeline
    # reads (services.agent_from_plan.build_agent_definition_from_plan).
    graph = data["agent_graph"]
    assert graph["name"] and graph["system_prompt"]["prompt"]
    assert any(
        t.get("tool_type") == "mcp" for t in graph["tools"]
    ), "agent_graph must include an mcp tool"
    mcp_servers = data["integrations"]["mcp_servers"]
    assert any(s.get("server_key") == "firecrawl" for s in mcp_servers)
