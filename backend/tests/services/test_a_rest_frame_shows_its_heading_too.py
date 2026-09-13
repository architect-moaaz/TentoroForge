"""A frame captured over the REST API records what it shows, like one captured
as code.

`store.connect` read `shows` from `structure.code` only. Production
extraction is the REST fallback (the hosted MCP's code is gated to partners),
so every real file recorded no `shows`, and the planner routed fifteen
identically named frames by position — the failure `shows` was added to end.
Two things had to be true of the REST read: the tree must not fold into one
text node (a frame named "Body" is structure), and the rail's destinations —
typed as buttons in the REST tree — must count as the names a screen can be.
"""
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget

SAME = "Refund & Case Management Platform"


def _bb(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _text(nid, chars, x, y, w, h, size=12):
    return {"id": nid, "type": "TEXT", "name": chars, "characters": chars,
            "absoluteBoundingBox": _bb(x, y, w, h),
            "style": {"fontSize": size, "fontWeight": 500}}


def _rail(prefix):
    def item(i, label):
        return {"id": f"{prefix}:r{i}", "type": "FRAME", "name": "Button",
                "absoluteBoundingBox": _bb(16, 60 + 32 * i, 200, 28),
                "children": [_text(f"{prefix}:t{i}", label, 24, 64 + 32 * i, 180, 20)]}
    return {"id": f"{prefix}:rail", "type": "FRAME", "name": "Sidebar", "layoutMode": "VERTICAL",
            "absoluteBoundingBox": _bb(0, 0, 240, 900),
            "fills": [{"type": "SOLID", "color": {"r": 0.07, "g": 0.06, "b": 0.05}}],
            "children": [_text(f"{prefix}:brand", "Criterion", 16, 16, 120, 20, size=14),
                         item(0, "Dashboard"), item(1, "Front Desk"), item(2, "Ticket Queue")]}


def _screen(nid, crumb, heading):
    p = nid.replace(":", "")
    return {
        "id": nid, "type": "FRAME", "name": SAME, "layoutMode": "VERTICAL",
        "absoluteBoundingBox": _bb(0, 0, 1387, 982),
        "children": [{
            "id": f"{p}:body", "type": "FRAME", "name": "Body", "layoutMode": "VERTICAL",
            "absoluteBoundingBox": _bb(0, 0, 1387, 982),
            "children": [{
                "id": f"{p}:shell", "type": "FRAME", "name": "Shell", "layoutMode": "HORIZONTAL",
                "absoluteBoundingBox": _bb(0, 0, 1387, 982),
                "children": [
                    _rail(p),
                    {"id": f"{p}:main", "type": "FRAME", "name": "Main", "layoutMode": "VERTICAL",
                     "absoluteBoundingBox": _bb(240, 0, 1147, 982),
                     "children": [
                         _text(f"{p}:c1", "Criterion", 264, 16, 60, 16),
                         _text(f"{p}:c2", "/", 330, 16, 10, 16),
                         _text(f"{p}:c3", crumb, 344, 16, 120, 16),
                         _text(f"{p}:h1", heading, 264, 48, 400, 32, size=24),
                         _text(f"{p}:b1", "Some body copy here", 264, 96, 400, 20, size=14),
                     ]},
                ]}]}],
    }


def _ref():
    screens = [("1:2", "Ticket Queue", "Ticket Queue"),
               ("1:3", "Dashboard", "Operations Dashboard"),
               ("1:4", "Front Desk", "Front Desk")]
    return DesignReference(
        target=FigmaTarget(file_key="aBcD1234EfGh"), source_id="FIGMA-001",
        screens=[ScreenRef(node_id=n, name=SAME, canvas="P", width=1387, height=982,
                           structure={"source": "rest_node_document",
                                      "document": _screen(n, crumb, heading), "boxes": []})
                 for n, crumb, heading in screens])


class _Svc:
    def __init__(self, d): self.doc, self.output_dir = d, "/tmp/x"
    def save(self): pass


def test_a_rest_screen_reads_as_a_tree_not_one_text():
    trees = store._screen_trees(_ref())
    assert set(trees) == {"1:2", "1:3", "1:4"}

    def count(n):
        return 1 + sum(count(c) for c in (n.get("children") or []) if isinstance(c, dict))
    assert all(count(t) > 10 for t in trees.values())


def test_connect_records_what_each_rest_frame_shows(tmp_path):
    svc = _Svc({}); svc.output_dir = str(tmp_path)
    record = store.connect(svc, _ref(), treat_as="evidence")
    shows = {f["nodeId"]: f.get("shows") for f in record["frames"]}
    assert shows["1:2"] == "Ticket Queue"
    assert shows["1:4"] == "Front Desk"
    # The rail names "Dashboard"; the screen's own title says more, and the
    # breadcrumb is the rail's word for it — either is its identity, and
    # neither is the brand.
    assert shows["1:3"] in ("Dashboard", "Operations Dashboard")
    assert all(v != "Criterion" for v in shows.values())


def test_the_rail_is_recorded_from_the_rest_capture(tmp_path):
    svc = _Svc({}); svc.output_dir = str(tmp_path)
    record = store.connect(svc, _ref(), treat_as="evidence")
    assert record.get("chrome", {}).get("sharedBy") == 3
