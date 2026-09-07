"""A page whose frame was captured over the Figma REST API composes, just like
one captured from the MCP's design-context code.

The hosted MCP that yields ``get_design_context`` code is gated to partners, so
production extraction falls back to the REST API, which returns Figma's native
node JSON. ``figma_to_schema.build_page_schema`` already turns that JSON into
the same element tree, and ``figma_layout.compose`` now routes a screen whose
``structure`` carries a REST node document through it — same seam, same tree
out. This proves the routing seam end to end (task C).
"""
import pathlib

from services.blueprint import figma_layout as F
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget


class _Svc:
    def __init__(self, doc, output_dir):
        self.doc = doc
        self.output_dir = str(output_dir)


# A minimal Figma REST node document: a frame with a heading and two cards, the
# shape /v1/files/:key/nodes returns (type, name, absoluteBoundingBox, children,
# characters, layoutMode).
def _rest_document(node_id: str = "1:2") -> dict:
    def _bb(x, y, w, h):
        return {"x": x, "y": y, "width": w, "height": h}

    def _text(nid, chars, x, y, w, h):
        return {"id": nid, "type": "TEXT", "name": chars, "characters": chars,
                "absoluteBoundingBox": _bb(x, y, w, h),
                "style": {"fontSize": 24, "fontWeight": 600}}

    return {
        "id": node_id, "type": "FRAME", "name": "Dashboard",
        "layoutMode": "VERTICAL", "itemSpacing": 16,
        "absoluteBoundingBox": _bb(0, 0, 1280, 800),
        "children": [
            _text("1:3", "Operations Dashboard", 24, 24, 400, 32),
            {"id": "1:4", "type": "FRAME", "name": "Cards", "layoutMode": "HORIZONTAL",
             "itemSpacing": 16, "absoluteBoundingBox": _bb(24, 72, 1232, 120),
             "children": [
                 {"id": "1:5", "type": "FRAME", "name": "Card",
                  "absoluteBoundingBox": _bb(24, 72, 600, 120),
                  "children": [_text("1:6", "Open Cases", 40, 88, 200, 20),
                               _text("1:7", "4", 40, 112, 80, 40)]},
                 {"id": "1:8", "type": "FRAME", "name": "Card",
                  "absoluteBoundingBox": _bb(640, 72, 600, 120),
                  "children": [_text("1:9", "Pending", 656, 88, 200, 20),
                               _text("1:10", "3", 656, 112, 80, 40)]},
             ]},
        ],
    }


def _stored_rest(tmp_path, node_id: str = "1:2") -> _Svc:
    ref = DesignReference(
        target=FigmaTarget(file_key="aBcD1234EfGh",
                           source_url="https://figma.com/design/aBcD1234EfGh/X"),
        source_id="FIGMA-001",
        screens=[ScreenRef(node_id=node_id, name="Dashboard", canvas="Page 1",
                           width=1280, height=800,
                           structure={"source": "rest_node_document",
                                      "document": _rest_document(node_id),
                                      "boxes": []})],
    )
    store.save(ref, tmp_path)
    doc = {"application": {"name": "X"},
           "designSources": [{"id": "FIGMA-001",
                              "frames": [{"nodeId": node_id, "name": "Dashboard"}]}]}
    return _Svc(doc, tmp_path)


def test_a_rest_captured_frame_composes_a_tree(tmp_path):
    svc = _stored_rest(tmp_path)
    page = {"id": "PAGE-001", "route": "/dashboard", "name": "Dashboard",
            "figmaFrame": "1:2"}

    out = F.compose(svc, page, app_root=tmp_path / "app")

    assert out is not None, "the REST node tree must compose, not fall through"
    assert out["provider"] == "figma"
    root = out["root"]
    assert isinstance(root, dict) and root.get("type")
    # the frame's own size travelled with the tree, so the renderer can scale it
    assert out.get("canvas", {}).get("width") == 1280
    # the heading text survived the REST → schema transform
    texts = _texts(root)
    assert any("Operations Dashboard" in t for t in texts), texts[:8]
    assert any("Open Cases" in t for t in texts)


def test_a_frame_with_no_structure_still_falls_through(tmp_path):
    """The seam is additive: a screen carrying neither code, HTML nor a REST
    document composes to nothing, exactly as before."""
    ref = DesignReference(
        target=FigmaTarget(file_key="aBcD1234EfGh"),
        source_id="FIGMA-001",
        screens=[ScreenRef(node_id="1:2", name="Empty", structure={"boxes": []})],
    )
    store.save(ref, tmp_path)
    svc = _Svc({"designSources": [{"id": "FIGMA-001",
                                   "frames": [{"nodeId": "1:2", "name": "Empty"}]}]},
               tmp_path)
    page = {"id": "PAGE-001", "route": "/x", "name": "X", "figmaFrame": "1:2"}

    assert F.compose(svc, page, app_root=tmp_path / "app") is None


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
