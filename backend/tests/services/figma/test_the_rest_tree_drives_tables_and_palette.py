"""The REST-composed tree drives the helpers that used to read the MCP code.

Task D: `tables.drawn_tables_from_tree` finds a table by structure (the tree has
no Figma `data-name` markers), the transformer stamps `_figmaNodeId` so a bound
region swaps in, and `palette.from_screens` reads a REST screen's colours from
its node document.
"""
from services.figma import palette, tables
from services.figma_to_schema import build_page_schema


def _bb(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _cases_document() -> dict:
    """A frame with a header and a 3-row, 3-column table drawn as plain nodes."""
    def cell(fid, text, x):
        return {"id": fid, "type": "TEXT", "name": text, "characters": text,
                "absoluteBoundingBox": _bb(x, 0, 300, 20), "style": {"fontSize": 14}}

    def row(fid, a, b, c):
        return {"id": fid, "type": "FRAME", "name": "Row", "layoutMode": "HORIZONTAL",
                "absoluteBoundingBox": _bb(0, 0, 900, 40), "children": [
                    cell(f"{fid}-1", a, 0), cell(f"{fid}-2", b, 300), cell(f"{fid}-3", c, 600)]}
    return {
        "id": "1:2", "type": "FRAME", "name": "Cases", "layoutMode": "VERTICAL",
        "absoluteBoundingBox": _bb(0, 0, 960, 600),
        "fills": [{"type": "SOLID", "color": {"r": 0.98, "g": 0.98, "b": 0.98}}],
        "children": [
            {"id": "1:3", "type": "TEXT", "name": "h", "characters": "Active Cases",
             "absoluteBoundingBox": _bb(24, 16, 400, 32), "style": {"fontSize": 24, "fontWeight": 600},
             "fills": [{"type": "SOLID", "color": {"r": 0.11, "g": 0.10, "b": 0.09}}]},
            {"id": "1:4", "type": "FRAME", "name": "New Case", "absoluteBoundingBox": _bb(760, 16, 176, 40),
             "fills": [{"type": "SOLID", "color": {"r": 0.79, "g": 0.66, "b": 0.30}}], "children": [
                 {"id": "1:5", "type": "TEXT", "name": "b", "characters": "+ New Case",
                  "absoluteBoundingBox": _bb(776, 26, 120, 20),
                  "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}]}]},
            {"id": "1:10", "type": "FRAME", "name": "Table", "layoutMode": "VERTICAL",
             "absoluteBoundingBox": _bb(24, 64, 912, 200),
             "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}], "children": [
                 row("1:11", "Reference", "Status", "Severity"),
                 row("1:12", "CASE-001", "Open", "High"),
                 row("1:13", "CASE-002", "Closed", "Low"),
                 row("1:14", "CASE-003", "Open", "Moderate")]},
        ],
    }


def test_figma_node_id_is_stamped_so_regions_can_bind():
    page = build_page_schema(_cases_document()).page

    ids = []

    def walk(n):
        if isinstance(n, dict):
            fid = (n.get("props") or {}).get("_figmaNodeId")
            if fid:
                ids.append(fid)
            for c in n.get("children") or []:
                walk(c)

    for c in page["children"]:
        walk(c)
    assert "1:10" in ids and "1:3" in ids, "raw Figma ids ride on the tree for realize to match"


def test_a_table_is_found_in_the_tree_by_structure():
    page = build_page_schema(_cases_document()).page
    root = page["children"][0] if len(page["children"]) == 1 else {
        "type": "Stack", "props": {}, "children": page["children"]}

    found = tables.drawn_tables_from_tree(root)

    assert len(found) == 1, [f.headers for f in found]
    t = found[0]
    assert t.headers == ["Reference", "Status", "Severity"]
    assert ["CASE-001", "Open", "High"] in t.rows
    assert t.node_id, "the table carries its Figma node id for realize to swap"
    assert t.title == "Active Cases"


def test_palette_reads_a_rest_screen_colours_and_areas():
    """The REST document's solid fills become area-weighted surfaces — the same
    shape `from_code` reads from Dev Mode code, sourced from Figma's own
    geometry. (`from_code`'s MIN_FILLS guard needs a real multi-frame file to
    yield a full scheme; here we assert the surfaces the adapter extracts.)"""
    doc = _cases_document()
    surfaces = palette._surfaces(palette._document_to_pseudocode(doc), (960, 600))
    by_area = {s["fill"]: s["area"] for s in surfaces}

    assert "#fafafa" in by_area, "the frame's ground fill is read"
    assert "#c9a84c" in by_area, "the accent (New Case) fill is read"
    # The ground paints the largest area — the whole frame — not a small button.
    assert by_area["#fafafa"] > by_area["#c9a84c"], "surfaces are weighted by drawn area"


def test_from_screens_accepts_a_rest_screen_without_error():
    class _Screen:
        structure = {"source": "rest_node_document", "document": _cases_document()}
        width, height = 960, 600

    # Never raises; a thin single-frame fixture may not clear MIN_FILLS, and an
    # empty scheme is the honest answer there, not a crash.
    assert isinstance(palette.from_screens([_Screen()]), dict)


def test_a_frame_of_cards_is_not_mistaken_for_a_table():
    """Two cards, not three similar rows — must not read as a table."""
    doc = {"id": "2:1", "type": "FRAME", "name": "Dash", "layoutMode": "HORIZONTAL",
           "absoluteBoundingBox": _bb(0, 0, 600, 200), "children": [
               {"id": "2:2", "type": "FRAME", "name": "Card", "absoluteBoundingBox": _bb(0, 0, 280, 120),
                "children": [{"id": "2:3", "type": "TEXT", "characters": "Open", "absoluteBoundingBox": _bb(0, 0, 100, 20)},
                             {"id": "2:4", "type": "TEXT", "characters": "4", "absoluteBoundingBox": _bb(0, 20, 100, 40)}]},
               {"id": "2:5", "type": "FRAME", "name": "Card", "absoluteBoundingBox": _bb(300, 0, 280, 120),
                "children": [{"id": "2:6", "type": "TEXT", "characters": "Overdue", "absoluteBoundingBox": _bb(0, 0, 100, 20)},
                             {"id": "2:7", "type": "TEXT", "characters": "1", "absoluteBoundingBox": _bb(0, 20, 100, 40)}]}]}
    page = build_page_schema(doc).page
    root = page["children"][0] if len(page["children"]) == 1 else {
        "type": "Stack", "props": {}, "children": page["children"]}
    assert tables.drawn_tables_from_tree(root) == [], "two cards are not three rows"
