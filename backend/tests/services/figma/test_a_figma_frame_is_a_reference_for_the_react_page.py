"""A Figma frame as the reference the React page writer adapts.

`figma_connect` stores the frames of a connected design. The React path asks `reference_for` for the
page's frame and the writer ADAPTS it — the same seam UX Pilot's drawing uses. A page with no frame,
or whose frame cannot be read, is written as before, and never fails because of a design."""
from __future__ import annotations

from services.blueprint.ui_engineer import compose_page, reference_block
from services.figma import react_reference as fr
from services.figma import store
from services.figma.reference import DesignReference, DesignTokens, ScreenRef
from services.figma.url import FigmaTarget

REST = {
    "type": "FRAME", "name": "Dashboard", "absoluteBoundingBox": {"width": 1440, "height": 900},
    "layoutMode": "VERTICAL", "itemSpacing": 16, "paddingTop": 24, "paddingRight": 24,
    "paddingBottom": 24, "paddingLeft": 24,
    "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}],
    "children": [
        {"type": "TEXT", "name": "h", "characters": "Welcome back", "style": {"fontSize": 24, "fontWeight": 700},
         "fills": [{"type": "SOLID", "color": {"r": 0.07, "g": 0.09, "b": 0.15}}]},
        {"type": "FRAME", "name": "Stats", "layoutMode": "HORIZONTAL", "itemSpacing": 12,
         "absoluteBoundingBox": {"width": 600, "height": 120}, "cornerRadius": 8,
         "children": [{"type": "TEXT", "name": "n", "characters": "128 open", "style": {"fontSize": 14}}]},
        {"type": "RECTANGLE", "name": "hidden", "visible": False},
    ],
}

TSX = ('export default function Frame() { return <div className="absolute w-[1440px]">'
       '<img src="https://www.figma.com/api/mcp/asset/abc123" /><h1>Welcome back</h1></div>; }')


def _doc(frame="1:2", pattern="dashboard"):
    return {
        "application": {"id": "t", "name": "Desk"},
        "designSources": [{"id": "FIGMA-001", "provider": "figma"}],
        "pages": [{"id": "PAGE-001", "name": "Dashboard", "route": "/", "pattern": pattern,
                   **({"figmaFrame": frame} if frame else {})}],
    }


def _store(tmp_path, structure, *, tokens=None):
    screen = ScreenRef(node_id="1:2", name="Dashboard", width=1440, height=900, structure=structure)
    ref = DesignReference(target=FigmaTarget(file_key="abc", node_id="1:2"), screens=[screen],
                          tokens=tokens or DesignTokens())
    store.save(ref, tmp_path)


def test_a_rest_tree_becomes_an_outline_of_what_the_designer_decided():
    out = fr.outline(REST)
    assert 'FRAME "Dashboard" 1440x900 col gap16 pad24 bg#ffffff' in out
    assert 'TEXT "Welcome back" 24/700 #121726' in out
    assert 'FRAME "Stats" 600x120 row gap12 r8' in out
    assert "  TEXT \"128 open\" 14" in out, "children are indented under their parent"
    assert "hidden" not in out, "an invisible layer is not part of the drawing"


def test_an_outline_is_cut_on_a_line_and_says_so():
    wide = {"type": "FRAME", "name": "root", "children": [
        {"type": "TEXT", "characters": f"row {i}" * 4} for i in range(400)]}
    out = fr.outline(wide, limit=500)
    assert len(out) < 650 and out.endswith("kind of content)")


def test_generated_code_loses_its_image_urls_and_is_cut_on_a_tag():
    out = fr.code_digest(TSX)
    assert "figma.com" not in out and "<asset>" in out and "<h1>Welcome back</h1>" in out
    cut = fr.code_digest("<div>" + "<p>row</p>" * 5000 + "</div>", limit=800)
    assert len(cut) < 1000 and cut.split(" {/*")[0].endswith(">")


def test_a_stored_rest_frame_is_the_pages_reference(tmp_path):
    _store(tmp_path, {"source": "rest_node_document", "document": REST},
           tokens=DesignTokens(colors={"brand/primary": "#4f46e5"}))
    ref, said = fr.reference_for(_doc(), _doc()["pages"][0], tmp_path)
    assert ref["format"] == "figma-outline" and "Welcome back" in ref["html"]
    assert ref["size"] == [1440, 900] and ref["frame"] == "Dashboard"
    assert "brand/primary: #4f46e5" in ref["tokens"]
    assert "Adapting Figma frame Dashboard for /" in said


def test_stored_code_is_used_when_the_hosted_mcp_answered(tmp_path):
    _store(tmp_path, {"source": "design_context_code", "code": TSX})
    ref, _ = fr.reference_for(_doc(), _doc()["pages"][0], tmp_path)
    assert ref["format"] == "figma-tsx" and "<asset>" in ref["html"]


def test_a_page_with_no_frame_or_an_auth_page_gets_no_reference_and_no_noise(tmp_path):
    assert fr.reference_for(_doc(frame=""), _doc(frame="")["pages"][0], tmp_path) == (None, "")
    auth = _doc(pattern="auth")
    assert fr.reference_for(auth, auth["pages"][0], tmp_path) == (None, "")


def test_a_frame_that_cannot_be_read_says_why_and_never_raises(tmp_path):
    ref, said = fr.reference_for(_doc(), _doc()["pages"][0], tmp_path)          # nothing stored
    assert ref is None and "no stored extraction holds" in said
    _store(tmp_path, {"source": "rest_node_document"})                           # nothing to read in it
    ref, said = fr.reference_for(_doc(), _doc()["pages"][0], tmp_path)
    assert ref is None and "no structure to read" in said


def test_a_ux_pilot_frame_is_left_to_its_own_reference(tmp_path):
    _store(tmp_path, {"source": "uxpilot_html", "html": "<h1>x</h1>"})
    assert fr.reference_for(_doc(), _doc()["pages"][0], tmp_path) == (None, "")


def test_the_writer_is_told_the_frame_is_the_decision_and_its_pixels_are_not(tmp_path):
    _store(tmp_path, {"source": "rest_node_document", "document": REST},
           tokens=DesignTokens(colors={"brand/primary": "#4f46e5"}))
    ref, _ = fr.reference_for(_doc(), _doc()["pages"][0], tmp_path)
    block = reference_block(ref)
    assert "A Figma frame drawn for this page" in block and "“Dashboard”, 1440x900" in block
    assert "```text" in block and "brand/primary: #4f46e5" in block
    assert "THE FRAME IS THE DECISION" in block and "never copy a fixed width" in block
    assert "read the real thing in `load.ts`".lower() in block.lower()
    # UX Pilot's wording is untouched for its own drawings
    assert "THE DESIGN IS THE DECISION" in reference_block({"html": "<h1>x</h1>", "designId": "d"})


def test_a_frame_reference_seeds_the_writer_like_any_drawing():
    """`compose_page` treats a reference with markup as a drawing to adapt (no planning call)."""
    import inspect

    src = inspect.getsource(compose_page)
    assert 'reference.get("html")' in src, "the seeded rule reads `html`, which a Figma reference fills"


def test_a_translucent_fill_is_shown_as_a_wash_not_as_a_solid():
    wash = {"type": "FRAME", "name": "Active borrow", "absoluteBoundingBox": {"width": 215, "height": 88},
            "fills": [{"type": "SOLID", "color": {"r": 0.85, "g": 0.44, "b": 0.2}, "opacity": 0.1}], "children": []}
    solid = dict(wash, name="Avatar", fills=[{"type": "SOLID", "color": {"r": 0.85, "g": 0.44, "b": 0.2}}])
    out = fr.outline({"type": "FRAME", "name": "root", "children": [wash, solid]})
    assert 'FRAME "Active borrow" 215x88 bg#d97033/10%' in out
    assert 'FRAME "Avatar" 215x88 bg#d97033' in out and 'bg#d97033/' not in out.split("Avatar")[1]
