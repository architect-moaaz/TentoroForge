"""When the hosted MCP's get_design_context is unavailable, extraction fetches
the frame's REST node tree instead, and the screen still composes.

The hosted Figma MCP that yields design-context *code* is gated to partners, so
`get_design_context` raises for us. Extraction now falls back to the REST node
document (`gateway.rest_node`), stores it as `structure.source ==
"rest_node_document"`, and `figma_layout.compose` routes it through
`build_page_schema` — so a gated MCP degrades to the REST path instead of
losing the screen.
"""
import asyncio

from services.blueprint import figma_layout as F
from services.figma import store
from services.figma.gateway import FigmaGatewayError
from services.figma.reference import extract
from services.figma.url import FigmaTarget

TARGET = FigmaTarget(file_key="aBcD1234EfGh",
                     source_url="https://figma.com/design/aBcD1234EfGh/X")

# What get_metadata returns: a canvas with one screen-sized frame.
METADATA = {
    "document": {
        "id": "0:0", "type": "DOCUMENT", "name": "Doc",
        "children": [{
            "id": "0:1", "type": "CANVAS", "name": "Screens",
            "children": [{
                "id": "1:2", "type": "FRAME", "name": "Dashboard",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 900},
            }],
        }],
    }
}

# What the REST node fetch returns for frame 1:2: the full native node tree.
def _document() -> dict:
    def bb(x, y, w, h):
        return {"x": x, "y": y, "width": w, "height": h}
    return {
        "id": "1:2", "type": "FRAME", "name": "Dashboard",
        "layoutMode": "VERTICAL", "itemSpacing": 16,
        "absoluteBoundingBox": bb(0, 0, 1440, 900),
        "children": [
            {"id": "1:3", "type": "TEXT", "name": "h", "characters": "Operations Dashboard",
             "absoluteBoundingBox": bb(24, 24, 400, 32),
             "style": {"fontSize": 24, "fontWeight": 600}},
            {"id": "1:4", "type": "TEXT", "name": "k", "characters": "Open Cases",
             "absoluteBoundingBox": bb(24, 72, 200, 20), "style": {"fontSize": 14}},
        ],
    }


class _GatedGateway:
    """MCP answers metadata, but get_design_context is gated; rest_node works."""

    def __init__(self, document: dict):
        self.document = document
        self.rest_calls: list[str] = []

    async def call(self, tool, *, file_key, node_id=None, **kw):
        if tool == "get_metadata":
            return [{"type": "structured", "data": METADATA}]
        if tool == "get_design_context":
            raise FigmaGatewayError("not_allowed", "hosted MCP gated to partners")
        raise FigmaGatewayError("tool_error", f"{tool} unavailable")

    async def rest_node(self, *, file_key, node_id):
        self.rest_calls.append(node_id)
        return self.document


class _Svc:
    def __init__(self, doc, output_dir):
        self.doc = doc
        self.output_dir = str(output_dir)


def test_gated_design_context_stores_a_rest_document(tmp_path):
    gw = _GatedGateway(_document())
    ref = asyncio.run(extract(gw, TARGET, with_images=False))

    assert gw.rest_calls == ["1:2"], "the REST node tree was fetched for the frame"
    screen = next(s for s in ref.screens if s.node_id == "1:2")
    assert screen.structure.get("source") == "rest_node_document"
    assert screen.structure.get("document", {}).get("id") == "1:2"


def test_the_rest_backed_screen_then_composes(tmp_path):
    gw = _GatedGateway(_document())
    ref = asyncio.run(extract(gw, TARGET, with_images=False))
    store.save(ref, tmp_path)

    svc = _Svc({"application": {"name": "X"},
                "designSources": [{"id": "FIGMA-001",
                                   "frames": [{"nodeId": "1:2", "name": "Dashboard"}]}]},
               tmp_path)
    out = F.compose(svc, {"id": "PAGE-001", "route": "/dashboard",
                          "name": "Dashboard", "figmaFrame": "1:2"},
                    app_root=tmp_path / "app")

    assert out is not None, "a gated MCP must degrade to the REST path, not lose the page"
    texts = _texts(out["root"])
    assert any("Operations Dashboard" in t for t in texts), texts[:8]


def _texts(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        p = node.get("props") or {}
        for k in ("content", "label"):
            v = p.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        for c in node.get("children") or []:
            _texts(c, out)
    return out
