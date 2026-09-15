"""A REST frame whose screen sits inside a frame named "Body" composes as the
screen, not as one text node.

Fifteen frames of one real file were each Screen > Body > Shell > Sidebar +
Main. The name classifier gave "Body" the text role, the walker kept it as a
leaf, and the fold that fills a leaf's content concatenated every text under
it: each page composed as a single Text whose content was the whole screen.
"""
from services.figma_to_schema import build_page_schema


def _bb(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _text(nid, chars, x, y, w, h, size=14):
    return {"id": nid, "type": "TEXT", "name": chars, "characters": chars,
            "absoluteBoundingBox": _bb(x, y, w, h),
            "style": {"fontSize": size, "fontWeight": 600}}


def _screen_in_a_body():
    return {
        "id": "1:2", "type": "FRAME", "name": "Refund & Case Management Platform",
        "layoutMode": "VERTICAL", "absoluteBoundingBox": _bb(0, 0, 1387, 982),
        "children": [{
            "id": "1:3", "type": "FRAME", "name": "Body", "layoutMode": "VERTICAL",
            "absoluteBoundingBox": _bb(0, 0, 1387, 982),
            "children": [{
                "id": "1:4", "type": "FRAME", "name": "Shell", "layoutMode": "HORIZONTAL",
                "absoluteBoundingBox": _bb(0, 0, 1387, 982),
                "children": [
                    {"id": "1:5", "type": "FRAME", "name": "Sidebar", "layoutMode": "VERTICAL",
                     "absoluteBoundingBox": _bb(0, 0, 240, 982),
                     "children": [_text("1:6", "Criterion", 16, 16, 120, 20),
                                  _text("1:7", "Ticket Queue", 16, 60, 120, 20)]},
                    {"id": "1:8", "type": "FRAME", "name": "Main", "layoutMode": "VERTICAL",
                     "absoluteBoundingBox": _bb(240, 0, 1147, 982),
                     "children": [_text("1:9", "Ticket Queue", 264, 24, 400, 32, size=28),
                                  _text("1:10", "CAS-2024-0443", 264, 80, 200, 20)]},
                ]}]}],
    }


def _types(node, out=None):
    out = out if out is not None else []
    if isinstance(node, dict):
        out.append(node.get("type"))
        for c in node.get("children") or []:
            _types(c, out)
    return out


def test_the_body_frame_does_not_fold_the_screen_into_one_text():
    page = build_page_schema(_screen_in_a_body(), asset_paths={}).page
    kinds = _types(page)
    texts = [k for k in kinds if k in ("Text", "Heading")]
    assert len(texts) >= 4, kinds          # four lettered layers, four nodes
    assert len(kinds) > 6, kinds           # and the frames around them survive


def test_each_text_keeps_its_own_content():
    page = build_page_schema(_screen_in_a_body(), asset_paths={}).page
    contents = []

    def walk(n):
        if isinstance(n, dict):
            c = (n.get("props") or {}).get("content")
            if isinstance(c, str) and c.strip():
                contents.append(c.strip())
            for k in n.get("children") or []:
                walk(k)
    walk(page)
    assert "CAS-2024-0443" in contents
    assert not any("Criterion" in c and "CAS-2024-0443" in c for c in contents)
