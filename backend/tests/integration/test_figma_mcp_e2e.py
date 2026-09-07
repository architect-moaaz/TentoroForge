"""End-to-end pipeline test against the Commitbiz fixture.

Mocks the asset downloader so CI doesn't hit the network. The real test:
parsing + transformation + asset-path threading all work as a unit.
"""
import pathlib
import pytest
from unittest.mock import AsyncMock, patch


FIXTURE = (
    pathlib.Path(__file__).parent.parent
    / "fixtures"
    / "figma"
    / "commitbiz_login_design_context.tsx"
)


@pytest.mark.asyncio
async def test_commitbiz_fixture_pipeline_end_to_end(tmp_path):
    """Feed the Commitbiz fixture through build_schema_from_jsx with a
    mocked downloader. Verify the schema has the expected high-level shape
    and that asset paths are wired through correctly."""
    from services import figma_mcp_pipeline

    # Mock the downloader so we don't fetch from Figma's CDN
    async def fake_download(urls, output_dir, concurrency=8, project_id=None):
        return {u: f"/figma/asset_{i}.svg" for i, u in enumerate(urls)}

    src = FIXTURE.read_text(encoding="utf-8")

    with patch.object(
        figma_mcp_pipeline, "download_figma_assets", AsyncMock(side_effect=fake_download)
    ):
        schema, asset_paths = await figma_mcp_pipeline.build_schema_from_jsx(
            src, str(tmp_path)
        )

    # PageV2 envelope
    assert schema["schemaVersion"] == "2.0"
    assert "children" in schema

    # Component-type sanity
    types: dict[str, int] = {}

    def walk(n):
        if isinstance(n, dict):
            t = n.get("type")
            if t:
                types[t] = types.get(t, 0) + 1
            for c in n.get("children") or []:
                walk(c)

    walk(schema)

    assert types.get("Heading", 0) >= 2, f"types: {types}"
    assert types.get("Input", 0) >= 2, f"types: {types}"
    assert types.get("Button", 0) >= 1, f"types: {types}"
    assert types.get("Image", 0) >= 1, f"types: {types}"

    # Assets — fixture has 13 unique MCP URLs (1 logo + 12 vectors)
    assert len(asset_paths) >= 1, f"assets: {asset_paths}"


@pytest.mark.asyncio
async def test_pipeline_rewrites_image_srcs(tmp_path):
    """An <img> in the JSX referencing a CDN URL should have its schema
    src rewritten to the local path after the downloader runs."""
    from services import figma_mcp_pipeline

    jsx = '''
    const imgX = "https://www.figma.com/api/mcp/asset/abc-123";
    function App() { return <img src={imgX} alt="" />; }
    '''

    async def fake_download(urls, output_dir, concurrency=8, project_id=None):
        return {"https://www.figma.com/api/mcp/asset/abc-123": "/figma/test.svg"}

    with patch.object(
        figma_mcp_pipeline, "download_figma_assets", AsyncMock(side_effect=fake_download)
    ):
        schema, paths = await figma_mcp_pipeline.build_schema_from_jsx(jsx, str(tmp_path))

    # Find the Image node
    def find_image(node):
        if isinstance(node, dict):
            if node.get("type") == "Image":
                return node
            for c in node.get("children") or []:
                hit = find_image(c)
                if hit:
                    return hit
        return None

    img = find_image(schema)
    assert img is not None
    assert img["props"]["src"] == "/figma/test.svg"


@pytest.mark.asyncio
async def test_pipeline_handles_no_assets(tmp_path):
    """JSX with no asset URLs — downloader not called, schema still emitted."""
    from services import figma_mcp_pipeline

    jsx = "<div><p>Hello</p></div>"
    mock = AsyncMock()
    with patch.object(figma_mcp_pipeline, "download_figma_assets", mock):
        schema, paths = await figma_mcp_pipeline.build_schema_from_jsx(
            jsx, str(tmp_path)
        )
    mock.assert_not_called()
    assert paths == {}
    assert schema["schemaVersion"] == "2.0"
