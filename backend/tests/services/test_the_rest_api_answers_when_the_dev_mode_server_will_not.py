"""The Dev Mode server needs the desktop app with the file loaded, and on a
real morning it let every metadata read time out. For the node tree and a
rendered crop the REST API has always served the same token; the gateway
falls back to it for those two tools only, in the block shapes the
extraction and the crop renderer already read."""
import asyncio
import base64
from unittest.mock import patch

import pytest

from services.figma.credentials import FigmaCredential
from services.figma.gateway import FigmaGateway, FigmaGatewayError


class _Resolver:
    def resolve(self, ref):
        return "figd_test"


def _gateway():
    return FigmaGateway(credential=FigmaCredential(ref="FIGMA_TOKEN"), resolver=_Resolver(),
                        endpoint="http://127.0.0.1:3845/mcp")


async def _timeout(self, tool, args):
    raise FigmaGatewayError("timeout", f"{tool} exceeded 60s")


def test_metadata_comes_back_as_the_node_tree():
    tree = {"id": "1:2", "name": "Platform", "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1031, "height": 764},
            "children": [{"id": "1:70", "name": "Card", "type": "FRAME",
                          "absoluteBoundingBox": {"x": 280, "y": 90, "width": 172, "height": 110}}]}

    async def fake_node(file_key, node_id, token):
        assert (file_key, node_id, token) == ("KEY", "1:2", "figd_test")
        return tree

    gw = _gateway(); gw.max_attempts = 1
    with patch.object(FigmaGateway, "_invoke", _timeout), \
         patch("services.figma_client.fetch_figma_node", fake_node):
        blocks = asyncio.run(gw.call("get_metadata", file_key="KEY", node_id="1:2"))
    assert blocks == [{"type": "structured", "data": tree}]
    from services.figma.reference import _screens_from_metadata
    (screen,) = _screens_from_metadata(blocks, limit=5)
    assert screen.node_id == "1:2" and screen.structure["boxes"][0]["id"] == "1:70"


def test_a_screenshot_comes_back_as_an_image_block():
    png = b"\\x89PNG fake"

    async def fake_urls(file_key, node_ids, token, format="svg", scale=1.0, batch_size=60):
        assert format == "png" and node_ids == ["1:70"]
        return {"1:70": "https://cdn.example/crop.png"}

    class _Resp:
        status_code = 200
        content = png

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp()

    gw = _gateway(); gw.max_attempts = 1
    with patch.object(FigmaGateway, "_invoke", _timeout), \
         patch("services.figma_client.fetch_figma_image_urls", fake_urls), \
         patch("httpx.AsyncClient", _Client):
        blocks = asyncio.run(gw.call("get_screenshot", file_key="KEY", node_id="1:70"))
    assert blocks[0]["type"] == "image" and base64.b64decode(blocks[0]["data"]) == png


def test_the_design_context_has_no_rest_equivalent():
    gw = _gateway(); gw.max_attempts = 1
    with patch.object(FigmaGateway, "_invoke", _timeout), pytest.raises(FigmaGatewayError) as err:
        asyncio.run(gw.call("get_design_context", file_key="KEY", node_id="1:2"))
    assert err.value.kind == "timeout"
