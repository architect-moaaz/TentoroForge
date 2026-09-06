"""The Figma adapter: Dev Mode JSX first, the REST node-tree mapping when
Dev Mode has nothing, with the frame's vectors exported for the mapper."""
from __future__ import annotations

import json

import pytest

from services.design_source import DesignSourceError
from services.design_source.figma import FigmaSource

URL = "https://www.figma.com/design/FILEKEY/My-App?node-id=1-2"

_DOC = {
    "id": "1:2", "name": "Login", "type": "FRAME",
    "absoluteBoundingBox": {"x": 0, "y": 0, "width": 400, "height": 300},
    "children": [
        {"id": "1:3", "name": "Heading 1", "type": "TEXT", "characters": "Welcome",
         "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 30}},
        {"id": "1:4", "name": "Logo Icon", "type": "VECTOR",
         "absoluteBoundingBox": {"x": 0, "y": 40, "width": 24, "height": 24}},
    ],
}


@pytest.fixture
def figma(monkeypatch, tmp_path):
    """A Figma source whose network is faked: Dev Mode reachable but empty,
    REST returns one frame, image export returns one SVG URL."""
    import agents.figma_mcp_agent as mcp
    import services.figma_client as client
    import services.design_source.figma as mod

    monkeypatch.setattr(mcp, "FIGMA_MCP_URL", "https://mcp.figma.com/mcp")
    calls = {"jsx": [], "export": [], "download": []}

    async def fake_jsx(url):
        calls["jsx"].append(url)
        return None

    async def fake_batched(file_key, node_ids, token):
        assert file_key == "FILEKEY" and token == "figd_t"
        return {nid: (_DOC if nid == "1:2" else {}) for nid in node_ids}

    async def fake_images(file_key, node_ids, token, format="svg", **kw):
        calls["export"].append((tuple(node_ids), format))
        return {nid: f"https://cdn.figma/{nid}.{format}" for nid in node_ids}

    async def fake_download(urls, output_dir, project_id=None, **kw):
        calls["download"].append(list(urls))
        return {u: f"/api/asset/{project_id}/figma/{i}.svg" for i, u in enumerate(urls)}

    monkeypatch.setattr(mcp, "fetch_jsx_via_mcp", fake_jsx)
    monkeypatch.setattr(client, "fetch_figma_node_batched", fake_batched)
    monkeypatch.setattr(client, "fetch_figma_image_urls", fake_images)
    import services.figma_asset_downloader as dl
    monkeypatch.setattr(dl, "download_figma_assets", fake_download)
    src = FigmaSource(URL, "figd_t", output_dir=str(tmp_path), project_id="p1")
    src.calls = calls
    return src


def test_rejects_non_figma_urls():
    with pytest.raises(DesignSourceError):
        FigmaSource("https://example.com/x", "t")
    s = FigmaSource(URL, "t")
    assert s.container == "FILEKEY" and s.node_id == "1:2"
    assert s.frame_url("12:34").endswith("node-id=12-34")


@pytest.mark.asyncio
async def test_markup_falls_back_to_the_node_tree_when_dev_mode_is_empty(figma):
    m = await figma.markup("1:2")
    assert figma.calls["jsx"] == [figma.frame_url("1:2")]
    assert m.kind == "schema"
    schema = json.loads(m.source)
    assert schema.get("schemaVersion") and "children" in schema
    assert m.preview_url == "https://cdn.figma/1:2.png"
    # The vector layer was exported and cached before the mapping ran.
    assert ("1:4",) in {c[0] for c in figma.calls["export"] if c[1] == "svg"}
    assert figma.calls["download"] == [["https://cdn.figma/1:4.svg"]]


@pytest.mark.asyncio
async def test_markup_uses_dev_mode_jsx_when_it_answers(figma, monkeypatch):
    import agents.figma_mcp_agent as mcp

    async def jsx(url):
        return '<div className="flex flex-col"><p>Hi</p></div>'

    monkeypatch.setattr(mcp, "fetch_jsx_via_mcp", jsx)
    m = await figma.markup("1:2")
    assert m.kind == "jsx" and figma.calls["export"] == []


@pytest.mark.asyncio
async def test_unknown_node_yields_no_markup(figma):
    assert await figma.markup("9:9") is None


@pytest.mark.asyncio
async def test_prefetch_feeds_theme_tokens_and_reachability(figma):
    assert figma.theme_tokens() == {}
    await figma.prefetch(["1:2"])
    theme = figma.theme_tokens()
    assert "typography" in theme
    assert await figma.reachable() is True
    # An unbound source (no output dir) maps without exporting assets.
    unbound = FigmaSource(URL, "figd_t")
    unbound._docs = {"1:2": _DOC}
    m = await unbound.markup("1:2")
    assert m.kind == "schema"
