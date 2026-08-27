import json, pathlib
from unittest.mock import AsyncMock, patch
import pytest
from services.figma_plan_builder import build_plan_from_figma, _extract_frames


FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_full_file.json"


def test_extracts_top_level_frames():
    """Commitbiz fixture has 4 frames: 1 login + 3 intent_intelligence."""
    file_meta = json.loads(FIXTURE.read_text())
    frames = _extract_frames(file_meta)
    assert len(frames) == 4
    names = [f["name"] for f in frames]
    assert "Commitbiz_intentai_login" in names


def test_every_frame_has_id_route_type():
    file_meta = json.loads(FIXTURE.read_text())
    for f in _extract_frames(file_meta):
        assert f["id"]
        assert f["route"].startswith("/")
        # type may be None (not all frames have a known archetype)


def test_login_classified_as_auth():
    file_meta = json.loads(FIXTURE.read_text())
    frames = _extract_frames(file_meta)
    login = next(f for f in frames if "login" in f["name"].lower())
    assert login["route"] == "/login"
    assert login["type"] == "auth"


def test_duplicate_routes_deduped():
    """Commitbiz has TWO frames named 'Commitbiz_intentai_intent_intelligence'
    plus one 'Commitbiz_intentai_intent_intelligence2'. Routes must be unique."""
    file_meta = json.loads(FIXTURE.read_text())
    routes = [f["route"] for f in _extract_frames(file_meta)]
    assert len(routes) == len(set(routes)), f"duplicate routes: {routes}"


@pytest.mark.asyncio
async def test_build_plan_returns_full_shape():
    file_meta = json.loads(FIXTURE.read_text())
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=file_meta)):
        plan = await build_plan_from_figma(
            "https://www.figma.com/design/8O10fOsocmlxdN678zDp8r/Commitbiz-Design",
            token="tok",
        )
    assert plan["_figma_driven"] is True
    assert plan["figma_file_key"] == "8O10fOsocmlxdN678zDp8r"
    assert plan["name"] == "Commitbiz Design"
    assert len(plan["pages"]) == 4
    for p in plan["pages"]:
        assert "figma_node_id" in p
        assert "route" in p
        assert "file" in p
        assert p["file"].startswith("src/schemas/")


@pytest.mark.asyncio
async def test_login_page_in_plan():
    file_meta = json.loads(FIXTURE.read_text())
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=file_meta)):
        plan = await build_plan_from_figma("https://figma.com/design/X/Y", token="t")
    login_page = next((p for p in plan["pages"] if p["route"] == "/login"), None)
    assert login_page is not None
    assert login_page["type"] == "auth"
    assert login_page["figma_node_id"] == "1:2"
    assert login_page["file"] == "src/schemas/login.json"


@pytest.mark.asyncio
async def test_excludes_components_and_hidden():
    """Component/ComponentSet/Slice frames AND visible=False frames are skipped."""
    fake = {
        "document": {"children": [{
            "id": "0:1", "type": "CANVAS", "name": "Page 1",
            "children": [
                {"id": "1:1", "type": "FRAME", "name": "Login"},
                {"id": "1:2", "type": "COMPONENT", "name": "Button"},
                {"id": "1:3", "type": "COMPONENT_SET", "name": "Buttons"},
                {"id": "1:4", "type": "FRAME", "name": "Signup", "visible": False},
                {"id": "1:5", "type": "SLICE", "name": "Export slice"},
            ],
        }]},
        "name": "Test",
    }
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=fake)):
        plan = await build_plan_from_figma("https://figma.com/design/X/Y", token="t")
    routes = [p["route"] for p in plan["pages"]]
    assert routes == ["/login"]


def test_empty_document_returns_empty_pages():
    """No canvas children → empty pages list, doesn't crash."""
    result = _extract_frames({"document": {"children": []}})
    assert result == []


def test_missing_document_key_safe():
    result = _extract_frames({})
    assert result == []
    result = _extract_frames(None)
    assert result == []
