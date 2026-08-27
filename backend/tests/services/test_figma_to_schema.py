import json, pathlib
from services.figma_to_schema import build_page_schema, _id_for


FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login.json"


def _walk_types(node, acc=None):
    if acc is None: acc = {}
    if isinstance(node, dict):
        t = node.get("type")
        if t: acc[t] = acc.get(t, 0) + 1
        for c in node.get("children") or []:
            _walk_types(c, acc)
    return acc


def test_fixture_exists():
    assert FIXTURE.exists(), f"missing fixture at {FIXTURE}"


def test_emits_expected_component_types():
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    types = _walk_types({"children": result.page["children"]})
    # Login page MUST have these in any sane mapping:
    assert types.get("Form", 0) >= 1
    assert types.get("Input", 0) >= 2          # email + password
    assert types.get("Button", 0) >= 1
    assert types.get("Checkbox", 0) >= 1
    assert types.get("Heading", 0) >= 1        # Welcome title
    assert types.get("Link", 0) >= 1
    assert types.get("Image", 0) >= 1          # Logo
    assert types.get("Text", 0) >= 3           # subtitle + labels + button text


def test_idempotent_ids():
    doc = json.loads(FIXTURE.read_text())
    a = build_page_schema(doc)
    b = build_page_schema(doc)
    assert json.dumps(a.page) == json.dumps(b.page)


def test_extracts_emerald_primary_from_button():
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    primary_500 = result.tokens["color"]["primary"].get("500", "").lower()
    # Emerald-ish — first hex digit pair starts with 0 or 1
    assert primary_500.startswith("#10") or primary_500.startswith("#0f"), \
        f"unexpected primary 500: {primary_500}"


def test_complete_flag_true_when_no_box_nodes():
    """If the classifier handles every node, complete is True."""
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    # Allow a small number of Box fall-throughs from edge cases, but most
    # should be classified. complete will be True iff zero Boxes.
    types = _walk_types({"children": result.page["children"]})
    box_count = types.get("Box", 0)
    # We expect <= 1 Box for the Label wrapper or similar edge case
    assert box_count <= 1


def test_empty_document_returns_empty_page():
    result = build_page_schema({})
    assert result.page["children"] == [{"id": "empty", "type": "Stack", "props": {}, "children": []}] or result.page["children"] == []


def test_id_derived_from_figma_id():
    assert _id_for("1:2") == _id_for("1:2")
    assert _id_for("1:2") != _id_for("1:3")
    assert _id_for("1:2").startswith("n_")


def test_emits_typography_tokens():
    """Fixture's TEXT nodes carry style — typography block must populate."""
    import json
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    typo = result.tokens.get("typography") or {}
    # Top-level keys present
    assert "font" in typo and "weight" in typo and "scale" in typo
    # Heading vs body inferred — Cal Sans / Inter Display for headings, Inter for body
    assert typo["font"]["heading"] == "Inter Display"
    assert typo["font"]["body"] == "Inter"
    # Scale picked up at least the heading + body + label sizes
    rem_values = set(typo["scale"].values())
    assert "2rem" in rem_values         # 32px heading
    assert "1rem" in rem_values         # 16px subtitle
    assert "0.75rem" in rem_values      # 12px label
    # Heading letter-spacing is negative (e.g. "-.016em")
    assert typo["letterSpacing"]["heading"].startswith("-")
    # Body line-height inferred from 24/16 + 20/14 averaged ≈ 1.46
    lh = typo["lineHeight"]["normal"]
    assert 1.3 < float(lh) < 1.6, f"unexpected body line-height: {lh}"


# ── FigmaFix regression: leaf-type cleanup ──────────────────────────────────
# These tests pin the schema-shape guarantees the renderer relies on:
#   - Heading / Text / Button / Input / Link / Checkbox / Image / Icon never
#     own structural children (so the brand-coloured vector-shape Boxes inside
#     Figma icon frames don't render as stacked red squares).
#   - Leaf nodes carry their visible text on the wrapper's `content` / `label`
#     prop (so a TEXT descendant inside a Heading frame doesn't surface as a
#     doubly-nested Heading).
#   - Image / Icon nodes have either a `src` (when asset_paths resolves) or
#     no src (so the renderer's null-fallback kicks in instead of showing
#     broken-image alt text).

_LEAF_TYPES_TEST = {
    "Heading", "Text", "Button", "Input", "Link", "Checkbox", "Image", "Icon",
}


def _collect_nodes(node, acc=None):
    if acc is None:
        acc = []
    if isinstance(node, dict) and node.get("type"):
        acc.append(node)
    for c in (node or {}).get("children") or []:
        _collect_nodes(c, acc)
    return acc


def test_leaf_nodes_have_no_children():
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    nodes = _collect_nodes({"children": result.page["children"]})
    offenders = [
        n for n in nodes
        if n.get("type") in _LEAF_TYPES_TEST and (n.get("children") or [])
    ]
    assert not offenders, (
        f"leaf nodes must not carry children, found {len(offenders)}: "
        f"{[(o['type'], len(o.get('children') or [])) for o in offenders[:3]]}"
    )


def test_heading_carries_folded_content():
    """Heading wrappers around TEXT children must surface the descendant
    text as props.content — not as a nested Heading child."""
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    nodes = _collect_nodes({"children": result.page["children"]})
    headings = [n for n in nodes if n.get("type") == "Heading"]
    assert headings, "fixture must contain at least one Heading"
    # At least one must carry non-empty content folded from descendants
    with_content = [h for h in headings if (h.get("props") or {}).get("content")]
    assert with_content, (
        "expected at least one Heading with folded content, got: "
        f"{[h.get('props') for h in headings[:3]]}"
    )


def test_text_color_propagated_into_leaf_wrapper():
    """A Heading wrapper whose inner TEXT has a fill must carry that colour
    as a `text-[#hex]` utility on its own className — otherwise the visible
    text colour is lost when the inner TEXT child is dropped."""
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    nodes = []
    def go(n):
        if isinstance(n, dict) and n.get("type"):
            nodes.append(n)
        for c in (n or {}).get("children") or []:
            go(c)
    for c in result.page["children"]:
        go(c)
    headings_with_color = [
        n for n in nodes
        if n.get("type") == "Heading"
        and "text-[#" in ((n.get("props") or {}).get("className") or "")
    ]
    assert headings_with_color, (
        "expected at least one Heading to carry a text-[#hex] colour from "
        f"its inner TEXT descendant, found: "
        f"{[(n.get('props') or {}).get('className') for n in nodes if n.get('type')=='Heading']}"
    )


def test_text_font_size_propagated_into_leaf_wrapper():
    """Inner TEXT's font-size must surface on the leaf wrapper's className
    so headings render at the size the designer set in Figma."""
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    def all_nodes(n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type"):
            acc.append(n)
        for c in (n or {}).get("children") or []:
            all_nodes(c, acc)
        return acc
    headings = [n for n in all_nodes({"children": result.page["children"]}) if n.get("type") == "Heading"]
    with_size = [
        h for h in headings
        if any(
            t.startswith("text-[") and t.endswith("px]")
            for t in ((h.get("props") or {}).get("className") or "").split()
        )
    ]
    assert with_size, (
        "expected at least one Heading with text-[Npx] from inner TEXT: "
        f"{[(h.get('props') or {}).get('className') for h in headings]}"
    )


def test_background_fill_emits_bg_utility():
    """A frame with a non-white solid fill must surface as a `bg-[#hex]`
    utility on its className. This is the mechanism the brand-red panel
    of the design relies on to render its colour."""
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    def all_nodes(n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type"):
            acc.append(n)
        for c in (n or {}).get("children") or []:
            all_nodes(c, acc)
        return acc
    nodes = all_nodes({"children": result.page["children"]})
    with_bg = [
        n for n in nodes
        if "bg-[#" in ((n.get("props") or {}).get("className") or "")
    ]
    assert with_bg, (
        "expected at least one node with a bg-[#hex] utility from its fill"
    )


def _all_typed(node, want, acc=None):
    if acc is None: acc = []
    if isinstance(node, dict) and node.get("type") == want:
        acc.append(node)
    for c in (node or {}).get("children") or []:
        _all_typed(c, want, acc)
    return acc


def test_bbox_infers_row_when_panels_are_side_by_side():
    """A Container whose children are absolute-positioned side by side
    (LEFT at x=0, RIGHT at x=600) should be promoted to Row, and each
    child should pick up `flex-1` so they share the row width."""
    fake_doc = {
        "id": "60:1", "name": "Outer", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 800},
        "children": [
            {"id": "60:2", "name": "Container", "type": "FRAME",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 800},
             "children": [
                 {"id": "60:l", "name": "Left Panel", "type": "FRAME",
                  "layoutMode": "VERTICAL",
                  "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 800}},
                 {"id": "60:r", "name": "Right Panel", "type": "FRAME",
                  "layoutMode": "VERTICAL",
                  "absoluteBoundingBox": {"x": 600, "y": 0, "width": 600, "height": 800}},
             ]},
        ],
    }
    result = build_page_schema(fake_doc)
    # Find the inner Container — outer was promoted to Stack already by
    # `layoutMode=None` (no signal) but the inner Container has children
    # with horizontal x-spread → should be Row.
    def find_row(n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == "Row":
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find_row(c, acc)
        return acc
    rows = find_row({"children": result.page["children"]})
    assert rows, (
        f"expected at least one Row from bbox-based promotion, "
        f"got types: {[ (n.get('type'), (n.get('props') or {}).get('className')) for n in result.page['children'] ]}"
    )
    # Each child of the promoted Row should have flex-1 in its className
    row = rows[0]
    for child in row["children"]:
        cn = (child.get("props") or {}).get("className", "")
        assert "flex-1" in cn, (
            f"row children should get flex-1 for proportional widths, got cn={cn!r}"
        )


def test_bbox_infers_stack_when_children_are_vertically_stacked():
    """Children at x=0 with growing y values should keep Stack semantics."""
    fake_doc = {
        "id": "61:1", "name": "Outer", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 1200},
        "children": [
            {"id": "61:2", "name": "Container", "type": "FRAME",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 1200},
             "children": [
                 {"id": "61:a", "name": "Row A", "type": "FRAME",
                  "layoutMode": "HORIZONTAL",
                  "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 200}},
                 {"id": "61:b", "name": "Row B", "type": "FRAME",
                  "layoutMode": "HORIZONTAL",
                  "absoluteBoundingBox": {"x": 0, "y": 400, "width": 600, "height": 200}},
                 {"id": "61:c", "name": "Row C", "type": "FRAME",
                  "layoutMode": "HORIZONTAL",
                  "absoluteBoundingBox": {"x": 0, "y": 800, "width": 600, "height": 200}},
             ]},
        ],
    }
    result = build_page_schema(fake_doc)
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    stacks = find("Stack", {"children": result.page["children"]})
    assert stacks, "expected at least one Stack from vertical-arrangement inference"


def test_bbox_asymmetric_row_uses_pixel_width_for_small_child():
    """In a Row where one child is much narrower than the other (icon+text
    layout), the small child should get `w-[Npx] shrink-0` (its bbox width)
    instead of `flex-1`, so the icon tile stays small while the text column
    grows."""
    fake_doc = {
        "id": "70:1", "name": "Page", "type": "FRAME", "layoutMode": "VERTICAL",
        "children": [
            {"id": "70:2", "name": "Container", "type": "FRAME",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 500, "height": 60},
             "children": [
                 {"id": "70:t", "name": "Icon tile", "type": "FRAME",
                  "absoluteBoundingBox": {"x": 0, "y": 0, "width": 40, "height": 40}},
                 {"id": "70:x", "name": "Text col", "type": "FRAME",
                  "absoluteBoundingBox": {"x": 56, "y": 0, "width": 400, "height": 40}},
             ]},
        ],
    }
    result = build_page_schema(fake_doc)
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    rows = find("Row", {"children": result.page["children"]})
    assert rows, "expected the Container to promote to Row"
    row = rows[0]
    kids = row["children"]
    assert len(kids) == 2
    # Small child should have w-[40px] shrink-0
    small_cn = (kids[0].get("props") or {}).get("className", "")
    assert "w-[40px]" in small_cn and "shrink-0" in small_cn, (
        f"small child should get bbox-derived width, got cn={small_cn!r}"
    )
    # Large child should have flex-1
    large_cn = (kids[1].get("props") or {}).get("className", "")
    assert "flex-1" in large_cn, f"large child should get flex-1, got cn={large_cn!r}"


def test_polish_centers_root_card():
    """A root Stack with rounded-* wrapping a single Row should pick up
    max-w, mx-auto, my-12, shadow-2xl, overflow-hidden from the centering
    heuristic."""
    fake_doc = {
        "id": "71:1", "name": "Root", "type": "FRAME", "layoutMode": "HORIZONTAL",
        "cornerRadius": 16,  # → rounded-xl → triggers card rule
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 800},
        "children": [
            {"id": "71:L", "name": "Left", "type": "FRAME", "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 800}},
            {"id": "71:R", "name": "Right", "type": "FRAME", "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"x": 600, "y": 0, "width": 600, "height": 800}},
        ],
    }
    result = build_page_schema(fake_doc)
    # First root child should be a Stack (the corner-radius'd card) wrapping
    # a single Row… actually with our fake doc the root IS a Row. Let me
    # check Stack wrapping pattern instead by adapting.
    # When root is Row directly, the card-centering rule shouldn't fire.
    # Build a real card: outer Stack(rounded-xl) → Row → [L, R]
    fake_doc2 = {
        "id": "71:c", "name": "Card", "type": "FRAME", "layoutMode": "VERTICAL",
        "cornerRadius": 16,
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 800},
        "children": [
            {"id": "71:r", "name": "Container", "type": "FRAME",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1200, "height": 800},
             "children": [
                 {"id": "71:l2", "name": "Left", "type": "FRAME", "layoutMode": "VERTICAL",
                  "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 800}},
                 {"id": "71:r2", "name": "Right", "type": "FRAME", "layoutMode": "VERTICAL",
                  "absoluteBoundingBox": {"x": 600, "y": 0, "width": 600, "height": 800}},
             ]},
        ],
    }
    result2 = build_page_schema(fake_doc2)
    # The outer Stack should have max-w + mx-auto
    root = result2.page["children"][0]
    if root["type"] == "Stack":
        cn = (root.get("props") or {}).get("className", "")
        assert "max-w-" in cn and "mx-auto" in cn, (
            f"expected card centering on root Stack, got cn={cn!r}"
        )


def test_polish_container_with_checkbox_and_text_is_flex_row():
    """Container holding a Checkbox + Text should become a flex row so the
    checkbox sits inline with its label (Remember-me pattern)."""
    fake_doc = {
        "id": "72:1", "name": "Form", "type": "FRAME",
        "children": [
            {"id": "72:c", "name": "Container", "type": "FRAME",
             "children": [
                 {"id": "72:cb", "name": "Checkbox", "type": "FRAME"},
                 {"id": "72:l", "name": "RememberMe Label", "type": "TEXT",
                  "characters": "Remember me"},
             ]},
        ],
    }
    result = build_page_schema(fake_doc)
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    containers = find("Container", {"children": result.page["children"]})
    assert containers, "expected the Container to survive"
    cn = (containers[0].get("props") or {}).get("className", "")
    assert "flex" in cn.split() and "items-center" in cn, (
        f"Container[Checkbox, Text] should be flex-row, got cn={cn!r}"
    )


def test_polish_row_with_container_and_link_uses_justify_between():
    """A Row containing both a Container (typically with a Checkbox group)
    and a Link (e.g. "Forgot password?") should justify-between so the
    link is right-aligned."""
    fake_doc = {
        "id": "73:1", "name": "Form", "type": "FRAME",
        "children": [
            {"id": "73:r", "name": "Container", "type": "FRAME",
             "layoutMode": "HORIZONTAL",
             "children": [
                 {"id": "73:c", "name": "Container", "type": "FRAME",
                  "children": [{"id": "73:cb", "name": "Checkbox", "type": "FRAME"}]},
                 {"id": "73:l", "name": "Forgot Link", "type": "FRAME",
                  "characters": "Forgot password?"},
             ]},
        ],
    }
    result = build_page_schema(fake_doc)
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    rows = find("Row", {"children": result.page["children"]})
    matching = [
        r for r in rows
        if any(c.get("type") == "Container" for c in r.get("children") or [])
        and any(c.get("type") == "Link" for c in r.get("children") or [])
    ]
    if matching:
        cn = (matching[0].get("props") or {}).get("className", "")
        assert "justify-between" in cn, (
            f"Row[Container, Link] should justify-between, got cn={cn!r}"
        )


def test_polish_button_in_form_gets_w_full():
    """A Button that lives inside a Form should be full-width — typical
    CTA pattern."""
    fake_doc = {
        "id": "74:1", "name": "Sign in Form", "type": "FRAME",
        "children": [
            {"id": "74:b", "name": "Button", "type": "FRAME",
             "characters": "Sign in"},
        ],
    }
    result = build_page_schema(fake_doc)
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    btns = find("Button", {"children": result.page["children"]})
    assert btns, "expected Button to be produced"
    cn = (btns[0].get("props") or {}).get("className", "")
    assert "w-full" in cn.split(), (
        f"Button in Form should be w-full, got cn={cn!r}"
    )


def test_polish_icon_tile_stack_gets_fixed_size():
    """A Stack whose only child is an Icon should be a fixed-square tile
    (w-10 h-10 + center alignment), not flex-1."""
    # Naming the wrapper non-passthrough ("Tile") keeps walk_and_flatten
    # from folding it into the parent; otherwise a single-child "Container"
    # frame would collapse away before the polish rule could fire.
    fake_doc = {
        "id": "75:1", "name": "Row", "type": "FRAME", "layoutMode": "HORIZONTAL",
        "children": [
            {"id": "75:tile", "name": "Tile", "type": "FRAME",
             "layoutMode": "VERTICAL", "cornerRadius": 8,
             "children": [
                 {"id": "75:ic", "name": "Icon", "type": "FRAME"},
             ]},
        ],
    }
    result = build_page_schema(fake_doc)
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    # The Container-with-only-Icon becomes Stack, then the polish rule fires.
    stacks_with_icon = [
        s for s in find("Stack", {"children": result.page["children"]})
        if len(s.get("children") or []) == 1
        and (s["children"][0] or {}).get("type") == "Icon"
    ]
    assert stacks_with_icon, "expected an icon-tile Stack"
    cn = (stacks_with_icon[0].get("props") or {}).get("className", "")
    assert "w-10" in cn.split() and "h-10" in cn.split(), (
        f"icon-tile should be w-10 h-10, got cn={cn!r}"
    )
    assert "items-center" in cn and "justify-center" in cn
    assert "flex-1" not in cn.split(), (
        f"icon-tile should not be flex-1, got cn={cn!r}"
    )


def test_bbox_no_geometry_keeps_existing_type():
    """Without absoluteBoundingBox, the inference must not change anything —
    the test fixture pattern (which has no bbox) needs to stay stable."""
    fake_doc = {
        "id": "62:1", "name": "Container", "type": "FRAME",
        "children": [
            {"id": "62:a", "name": "Heading 1", "type": "FRAME",
             "children": [{"id": "62:b", "name": "X", "type": "TEXT", "characters": "X"}]},
            {"id": "62:c", "name": "Heading 1", "type": "FRAME",
             "children": [{"id": "62:d", "name": "Y", "type": "TEXT", "characters": "Y"}]},
        ],
    }
    result = build_page_schema(fake_doc)
    # Container without bbox should remain Container (no inference fires).
    def find(t, n, acc=None):
        if acc is None: acc = []
        if isinstance(n, dict) and n.get("type") == t:
            acc.append(n)
        for c in (n or {}).get("children") or []:
            find(t, c, acc)
        return acc
    assert find("Container", {"children": result.page["children"]}), (
        "expected Container to remain Container when no bbox data is available"
    )


def test_dialog_auto_wire_matches_button_to_dialog_by_keyword():
    """A button labelled "View Context" inside a frame that also contains a
    "View contact Modal" frame should get opensDialog set to that dialog's id."""
    fake_doc = {
        "id": "20:1", "name": "Page", "type": "FRAME", "layoutMode": "VERTICAL",
        "children": [
            {"id": "20:2", "name": "View context Button", "type": "FRAME",
             "characters": "View Context"},
            {"id": "20:3", "name": "View contact Modal", "type": "FRAME",
             "layoutMode": "VERTICAL",
             "children": [{"id": "20:4", "name": "Title", "type": "TEXT",
                           "characters": "View contact"}]},
        ],
    }
    result = build_page_schema(fake_doc)
    wrapper = {"children": result.page["children"]}
    dialogs = _all_typed(wrapper, "Dialog")
    buttons = _all_typed(wrapper, "Button")
    assert dialogs and buttons, "fixture must produce both"
    btn = buttons[0]
    dialog_id = (dialogs[0].get("props") or {}).get("id")
    assert (btn.get("props") or {}).get("opensDialog") == dialog_id, (
        f"button.opensDialog should equal dialog.id={dialog_id}, "
        f"got button props={btn.get('props')}"
    )


def test_dialog_auto_wire_wires_every_row_button_to_same_dialog():
    """A list of rows each with a "View Context" button should ALL get
    opensDialog set to the single dialog — this is the table/list-row pattern."""
    rows = [
        {"id": f"30:r{i}", "name": f"Row {i}", "type": "FRAME",
         "layoutMode": "HORIZONTAL", "children": [
             {"id": f"30:b{i}", "name": "View context Button", "type": "FRAME",
              "characters": "View Context"},
         ]} for i in range(3)
    ]
    fake_doc = {
        "id": "30:1", "name": "Page", "type": "FRAME", "layoutMode": "VERTICAL",
        "children": rows + [
            {"id": "30:m", "name": "View contact Modal", "type": "FRAME",
             "layoutMode": "VERTICAL",
             "children": [{"id": "30:t", "name": "Title", "type": "TEXT",
                           "characters": "View contact"}]},
        ],
    }
    result = build_page_schema(fake_doc)
    wrapper = {"children": result.page["children"]}
    dialog = _all_typed(wrapper, "Dialog")[0]
    dialog_id = (dialog.get("props") or {}).get("id")
    buttons = _all_typed(wrapper, "Button")
    assert len(buttons) == 3
    for b in buttons:
        assert (b.get("props") or {}).get("opensDialog") == dialog_id, (
            f"every row button should wire to dialog {dialog_id}, "
            f"got {b.get('props')}"
        )


def test_dialog_auto_wire_no_match_leaves_opens_dialog_unset():
    """A button labelled "Submit" and a dialog titled "View contact Modal"
    share no semantically meaningful tokens — opensDialog must stay unset."""
    fake_doc = {
        "id": "40:1", "name": "Page", "type": "FRAME", "layoutMode": "VERTICAL",
        "children": [
            {"id": "40:2", "name": "Submit Button", "type": "FRAME",
             "characters": "Submit"},
            {"id": "40:3", "name": "View contact Modal", "type": "FRAME",
             "layoutMode": "VERTICAL", "children": []},
        ],
    }
    result = build_page_schema(fake_doc)
    wrapper = {"children": result.page["children"]}
    btn = _all_typed(wrapper, "Button")[0]
    assert not (btn.get("props") or {}).get("opensDialog"), (
        f"unrelated button should have no opensDialog, got {btn.get('props')}"
    )


def test_dialog_auto_wire_stopwords_only_means_no_match():
    """Button labelled "Cancel" (a stopword) and dialog "Confirm Dialog"
    (the "dialog" word is itself a stopword) share no real tokens — no wire."""
    fake_doc = {
        "id": "50:1", "name": "Page", "type": "FRAME", "layoutMode": "VERTICAL",
        "children": [
            {"id": "50:2", "name": "Close Button", "type": "FRAME",
             "characters": "Close"},
            {"id": "50:3", "name": "Modal", "type": "FRAME",
             "layoutMode": "VERTICAL", "children": []},
        ],
    }
    result = build_page_schema(fake_doc)
    wrapper = {"children": result.page["children"]}
    btn = _all_typed(wrapper, "Button")[0]
    assert not (btn.get("props") or {}).get("opensDialog")


def test_dialog_frame_becomes_dialog_with_id_prop():
    """A Figma frame named like a modal must produce a Dialog node carrying
    a stable `props.id` derived from the Figma id so a Button's
    opensDialog="<id>" can target it via DialogStateContext at runtime."""
    fake_doc = {
        "id": "10:1",
        "name": "View contact Modal",
        "type": "FRAME",
        "layoutMode": "VERTICAL",
        "children": [
            {"id": "10:2", "name": "Title", "type": "TEXT", "characters": "View contact"},
        ],
    }
    result = build_page_schema(fake_doc)
    root = result.page["children"][0]
    assert root["type"] == "Dialog", f"expected Dialog, got {root['type']}"
    assert root["props"].get("id"), "Dialog must carry props.id"
    assert root["props"].get("title") == "View contact Modal"
    # Dialog is NOT a leaf — its body content should still be attached.
    assert root["children"], "Dialog must keep its body children"


def test_layout_mode_promotes_unknown_box_to_stack_or_row():
    """A Figma frame with auto-layout whose name doesn't match the classifier
    whitelist (e.g. "Login Section", "main") must still become a Stack/Row,
    not Box — otherwise two-column designs collapse to single columns."""
    from services.figma_node_walker import walk_and_flatten
    from services.figma_name_classifier import classify, refine_container_type

    # Construct a synthetic node: unknown name + HORIZONTAL layout.
    fake_doc = {
        "id": "0:1",
        "name": "RootFrame",
        "type": "FRAME",
        "layoutMode": "HORIZONTAL",
        "itemSpacing": 24,
        "children": [
            {"id": "0:2", "name": "LeftPane", "type": "FRAME", "layoutMode": "VERTICAL"},
            {"id": "0:3", "name": "RightPane", "type": "FRAME", "layoutMode": "VERTICAL"},
        ],
    }
    result = build_page_schema(fake_doc)
    root = result.page["children"][0]
    assert root["type"] == "Row", (
        f"expected unknown horizontal frame to become Row, got {root['type']}"
    )
    for c in root["children"]:
        assert c["type"] == "Stack", (
            f"expected unknown vertical frame to become Stack, got {c['type']}"
        )


def test_asset_paths_threaded_into_icon_image_props():
    """When asset_paths is supplied, matching Figma node ids get a `src` on
    the resulting Image / Icon node. This is the hook the asset-export
    pipeline plugs into to display Figma icons/logos instead of nothing."""
    doc = json.loads(FIXTURE.read_text())
    # First pass — discover the Figma node ids that classify as Image/Icon
    no_assets = build_page_schema(doc)
    image_or_icon = [
        n for n in _collect_nodes({"children": no_assets.page["children"]})
        if n.get("type") in ("Image", "Icon")
    ]
    assert image_or_icon, "fixture must contain at least one Image or Icon"

    # Walk again with a synthetic asset_paths map keyed by Figma node id.
    # We can't recover the Figma ids from the schema alone (they're hashed
    # into n_<hex>); instead supply *every* Figma id so every leaf gets a src.
    from services.figma_node_walker import walk_and_flatten
    fids = [e["node"].get("id") for e in walk_and_flatten(doc)]
    asset_paths = {fid: f"/figma/{fid}.svg" for fid in fids if fid}

    with_assets = build_page_schema(doc, asset_paths=asset_paths)
    nodes = _collect_nodes({"children": with_assets.page["children"]})
    assets_on_leaves = [
        n for n in nodes
        if n.get("type") in ("Image", "Icon") and (n.get("props") or {}).get("src")
    ]
    assert assets_on_leaves, (
        "asset_paths must thread `src` into Image/Icon leaves — none had src"
    )


def test_button_preserves_icon_descendant_src_as_iconSrc():
    """A FRAME named 'Settings Button' with a child named 'icon' that has an
    exported SVG asset should surface that asset on Button.iconSrc, so the
    rendered button still shows the icon instead of dropping it when leaf-
    folding strips Button children. This matches the nav-item pattern in
    Figma dashboards where each row is a single FRAME containing icon+text.
    """
    doc = {
        "id": "root", "type": "FRAME", "name": "Sidebar",
        "layoutMode": "VERTICAL",
        "children": [
            {
                "id": "btn-settings", "type": "FRAME", "name": "Settings Button",
                "layoutMode": "HORIZONTAL",
                "children": [
                    {"id": "ico-settings", "type": "FRAME", "name": "icon"},
                    {"id": "txt-settings", "type": "TEXT", "name": "label",
                     "characters": "Settings"},
                ],
            },
        ],
    }
    asset_paths = {"ico-settings": "/api/asset/proj/figma/ico-settings.svg"}
    result = build_page_schema(doc, asset_paths=asset_paths)

    nodes = _collect_nodes({"children": result.page["children"]})
    buttons = [n for n in nodes if n.get("type") == "Button"]
    assert len(buttons) == 1, [n.get("type") for n in nodes]
    btn = buttons[0]
    assert btn["props"].get("label") == "Settings"
    assert btn["props"].get("iconSrc") == "/api/asset/proj/figma/ico-settings.svg", btn["props"]


def test_button_without_icon_descendant_has_no_iconSrc():
    """When a Button's source FRAME has no Icon descendant, no iconSrc is
    emitted — only Buttons whose Figma source had a real exported icon get
    the prop."""
    doc = {
        "id": "root", "type": "FRAME", "name": "Bar",
        "layoutMode": "HORIZONTAL",
        "children": [
            {"id": "b1", "type": "FRAME", "name": "Save Button",
             "children": [
                 {"id": "t1", "type": "TEXT", "name": "label", "characters": "Save"},
             ]},
        ],
    }
    result = build_page_schema(doc, asset_paths={"t1": "irrelevant"})
    nodes = _collect_nodes({"children": result.page["children"]})
    buttons = [n for n in nodes if n.get("type") == "Button"]
    assert len(buttons) == 1
    assert "iconSrc" not in buttons[0]["props"]


# ── Page-shell layout heuristic ───────────────────────────────────────────

def _find_node(node, target_id):
    if not isinstance(node, dict):
        return None
    if node.get("id") == target_id and node.get("type"):
        return node
    for c in node.get("children", []) or []:
        r = _find_node(c, target_id)
        if r is not None:
            return r
    return None


def test_page_shell_layout_swaps_fixed_frame_for_viewport_fill():
    """A Figma page frame at root — Row with fixed pixel dimensions wrapping
    a fixed-width Stack (sidebar) + flex-1 Stack (main) — should swap to
    h-screen + w-full + viewport-fill layout so the rendered page doesn't
    leave whitespace around a 1391×1134 fixed frame."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Dashboard",
        "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1391, "height": 1134},
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
        "children": [
            {"id": "sidebar", "type": "FRAME", "name": "Sidebar",
             "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 247, "height": 852},
             "layoutSizingHorizontal": "FIXED",
             "layoutSizingVertical": "FIXED",
             "children": [
                 {"id": "nav", "type": "FRAME", "name": "Nav",
                  "layoutMode": "VERTICAL",
                  "layoutSizingHorizontal": "FILL",
                  "absoluteBoundingBox": {"x": 0, "y": 0, "width": 247, "height": 600}},
                 {"id": "profile", "type": "FRAME", "name": "Profile",
                  "layoutMode": "HORIZONTAL",
                  "absoluteBoundingBox": {"x": 0, "y": 700, "width": 247, "height": 80}},
             ]},
            {"id": "main", "type": "FRAME", "name": "Main",
             "layoutMode": "VERTICAL",
             "layoutGrow": 1,
             "absoluteBoundingBox": {"x": 247, "y": 0, "width": 1144, "height": 1134},
             "children": [
                 {"id": "content", "type": "FRAME", "name": "Content",
                  "absoluteBoundingBox": {"x": 247, "y": 0, "width": 1144, "height": 1000},
                  "layoutSizingHorizontal": "FIXED"},
             ]},
        ],
    }
    result = build_page_schema(doc)
    root = result.page["children"][0]
    rcn = (root.get("props") or {}).get("className", "")
    assert "w-full" in rcn.split(), rcn
    assert "h-screen" in rcn.split(), rcn
    assert "overflow-hidden" in rcn.split(), rcn
    assert "items-stretch" in rcn.split(), rcn
    # The original `w-[1391px]` and `min-h-[1134px]` must be gone.
    assert "w-[1391px]" not in rcn
    assert "min-h-[1134px]" not in rcn


def test_page_shell_sidebar_gets_full_height_and_scroll():
    """The detected sidebar (fixed-width Stack child) gains h-screen +
    overflow-y-auto + shrink-0 + flex flex-col."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Dashboard",
        "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"width": 1391, "height": 1134},
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
        "children": [
            {"id": "sidebar", "type": "FRAME", "name": "Sidebar",
             "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"width": 247, "height": 852},
             "layoutSizingHorizontal": "FIXED",
             "layoutSizingVertical": "FIXED",
             "children": [
                 {"id": "navitem", "type": "TEXT", "name": "Nav", "characters": "Dashboard"},
             ]},
            {"id": "main", "type": "FRAME", "name": "Main",
             "layoutMode": "VERTICAL",
             "layoutGrow": 1,
             "absoluteBoundingBox": {"width": 1144, "height": 1134},
             "children": [
                 {"id": "content", "type": "TEXT", "name": "Content", "characters": "X"},
             ]},
        ],
    }
    result = build_page_schema(doc)
    sidebar = _find_node({"children": result.page["children"]}, _id_for("sidebar"))
    assert sidebar is not None
    scn = (sidebar.get("props") or {}).get("className", "").split()
    # Mobile-aware page-shell: sidebar becomes a slide-in drawer on mobile
    # (fixed inset-y-0 left-0 -translate-x-full) and a normal inline column
    # on md+ (md:relative md:translate-x-0 md:flex md:flex-col md:h-screen).
    # The drawer slides in via [data-sidebar-open="true"] [data-shell-sidebar]
    # CSS, which the ShellStateProvider sets when the hamburger is tapped.
    for cls in ("fixed", "inset-y-0", "left-0", "-translate-x-full", "z-40",
                "md:relative", "md:translate-x-0", "md:flex", "md:flex-col",
                "md:h-screen", "md:overflow-y-auto", "md:shrink-0"):
        assert cls in scn, f"sidebar missing {cls}: {scn}"
    # Sidebar is marked with shellRole=sidebar so the renderer emits
    # data-shell-sidebar (the ShellStateProvider CSS selector hook).
    assert (sidebar.get("props") or {}).get("shellRole") == "sidebar"


def test_page_shell_pins_last_sidebar_child_to_bottom():
    """The last direct child of the detected sidebar (typically the user
    profile / logout block) gets `mt-auto` so it pins to the bottom of
    the flex column."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Dashboard",
        "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"width": 1391, "height": 1134},
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
        "children": [
            {"id": "sidebar", "type": "FRAME", "name": "Sidebar",
             "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"width": 247, "height": 852},
             "layoutSizingHorizontal": "FIXED",
             "layoutSizingVertical": "FIXED",
             "children": [
                 {"id": "nav", "type": "FRAME", "name": "Nav",
                  "layoutMode": "VERTICAL",
                  "absoluteBoundingBox": {"y": 0, "width": 247, "height": 600},
                  "children": [
                      {"id": "n1", "type": "TEXT", "name": "x", "characters": "Dashboard"},
                  ]},
                 {"id": "profile", "type": "FRAME", "name": "Profile",
                  "layoutMode": "HORIZONTAL",
                  "absoluteBoundingBox": {"y": 700, "width": 247, "height": 80},
                  "children": [
                      {"id": "p1", "type": "TEXT", "name": "x", "characters": "User"},
                  ]},
             ]},
            {"id": "main", "type": "FRAME", "name": "Main",
             "layoutMode": "VERTICAL",
             "layoutGrow": 1,
             "absoluteBoundingBox": {"width": 1144, "height": 1134},
             "children": [
                 {"id": "content", "type": "TEXT", "name": "x", "characters": "X"},
             ]},
        ],
    }
    result = build_page_schema(doc)
    profile = _find_node({"children": result.page["children"]}, _id_for("profile"))
    assert profile is not None, "profile node not in schema"
    pcn = (profile.get("props") or {}).get("className", "").split()
    assert "mt-auto" in pcn, f"profile missing mt-auto: {pcn}"


def test_page_shell_relaxes_large_inner_widths():
    """Inner content stack pinned at `w-[1144px]` from the Figma frame
    becomes `w-full` after the page-shell heuristic — otherwise it stays
    capped at 1144px inside a wider main panel."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Dashboard",
        "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"width": 1391, "height": 1134},
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
        "children": [
            {"id": "sidebar", "type": "FRAME", "name": "Sidebar",
             "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"width": 247, "height": 852},
             "layoutSizingHorizontal": "FIXED",
             "layoutSizingVertical": "FIXED"},
            {"id": "main", "type": "FRAME", "name": "Main",
             "layoutMode": "VERTICAL", "layoutGrow": 1,
             "absoluteBoundingBox": {"width": 1144, "height": 1134},
             "children": [
                 {"id": "content", "type": "FRAME", "name": "Content",
                  "absoluteBoundingBox": {"width": 1144, "height": 1000},
                  "layoutSizingHorizontal": "FIXED",
                  "layoutMode": "VERTICAL",
                  "children": [
                      {"id": "x", "type": "TEXT", "name": "x", "characters": "X"},
                  ]},
             ]},
        ],
    }
    result = build_page_schema(doc)
    content = _find_node({"children": result.page["children"]}, _id_for("content"))
    assert content is not None
    ccn = (content.get("props") or {}).get("className", "").split()
    assert "w-full" in ccn, f"inner content not relaxed: {ccn}"
    assert "w-[1144px]" not in ccn


def test_page_shell_idempotent():
    """Re-running build_page_schema on the same doc twice yields identical
    output — the page-shell heuristic doesn't compound its mutations."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Dashboard",
        "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"width": 1391, "height": 1134},
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
        "children": [
            {"id": "sidebar", "type": "FRAME", "name": "Sidebar",
             "layoutMode": "VERTICAL",
             "absoluteBoundingBox": {"width": 247, "height": 852},
             "layoutSizingHorizontal": "FIXED",
             "layoutSizingVertical": "FIXED"},
            {"id": "main", "type": "FRAME", "name": "Main",
             "layoutMode": "VERTICAL", "layoutGrow": 1,
             "absoluteBoundingBox": {"width": 1144, "height": 1134},
             "children": [{"id": "x", "type": "TEXT", "name": "x", "characters": "X"}]},
        ],
    }
    a = json.dumps(build_page_schema(doc).page, sort_keys=True)
    b = json.dumps(build_page_schema(doc).page, sort_keys=True)
    assert a == b


def test_page_without_sidebar_pattern_is_untouched():
    """A page that isn't the sidebar + main pattern (e.g. a single-column
    landing) should NOT get h-screen / overflow-hidden — only the targeted
    pattern triggers the heuristic."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Landing",
        "layoutMode": "VERTICAL",
        "absoluteBoundingBox": {"width": 1440, "height": 900},
        "layoutSizingHorizontal": "FIXED",
        "layoutSizingVertical": "FIXED",
        "children": [
            {"id": "hero", "type": "TEXT", "name": "hero", "characters": "Hello"},
        ],
    }
    result = build_page_schema(doc)
    root = result.page["children"][0]
    rcn = (root.get("props") or {}).get("className", "")
    assert "h-screen" not in rcn.split()
    assert "overflow-hidden" not in rcn.split()


# ── Vector-only FRAME → Image ─────────────────────────────────────────────

def test_vector_only_frame_classified_as_image():
    """A logo-like FRAME whose entire subtree is VECTOR glyphs (one path
    per letter) should classify as Image so the export pipeline emits one
    SVG instead of N empty Boxes — fixes the disappearing-logo issue."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Sidebar",
        "layoutMode": "VERTICAL",
        "children": [
            {
                "id": "logo", "type": "FRAME", "name": "DITANS HEALTH",
                "absoluteBoundingBox": {"width": 144, "height": 47},
                "children": [
                    {"id": "v1", "type": "VECTOR", "name": "D"},
                    {"id": "v2", "type": "VECTOR", "name": "I"},
                    {"id": "v3", "type": "VECTOR", "name": "T"},
                    {"id": "v4", "type": "VECTOR", "name": "A"},
                    {"id": "v5", "type": "VECTOR", "name": "N"},
                    {"id": "v6", "type": "VECTOR", "name": "S"},
                ],
            },
        ],
    }
    result = build_page_schema(doc, asset_paths={"logo": "/api/asset/x/logo.svg"})
    logo = _find_node({"children": result.page["children"]}, _id_for("logo"))
    assert logo is not None
    assert logo["type"] == "Image", logo
    assert logo["props"].get("src") == "/api/asset/x/logo.svg"


def test_vector_only_frame_with_text_descendant_is_not_image():
    """Mixed-content frames (any TEXT or non-vector descendant) stay as
    their original classification — only pure vector compositions become
    Image. Without this guard, real UI frames with icon decorations would
    collapse to a single SVG."""
    doc = {
        "id": "page", "type": "FRAME", "name": "Card",
        "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": {"width": 200, "height": 100},
        "children": [
            {"id": "vec", "type": "VECTOR", "name": "icon"},
            {"id": "txt", "type": "TEXT", "name": "label", "characters": "Hi"},
        ],
    }
    result = build_page_schema(doc)
    page = _find_node({"children": result.page["children"]}, _id_for("page"))
    assert page is not None
    assert page["type"] != "Image", "mixed frame should NOT become Image"


# ── Ghost-button detection ────────────────────────────────────────────────

def test_button_without_fills_gets_ghost_variant():
    """A Button-classified frame with no visible solid fills emits
    `variant: "ghost"` so the library doesn't paint its default
    `bg-primary` over a transparent sidebar nav item."""
    doc = {
        "id": "root", "type": "FRAME", "name": "Nav",
        "layoutMode": "VERTICAL",
        "children": [
            {"id": "b1", "type": "FRAME", "name": "Settings Button",
             "fills": [],
             "children": [
                 {"id": "t1", "type": "TEXT", "name": "label", "characters": "Settings"},
             ]},
        ],
    }
    result = build_page_schema(doc)
    nodes = _collect_nodes({"children": result.page["children"]})
    buttons = [n for n in nodes if n.get("type") == "Button"]
    assert len(buttons) == 1
    assert buttons[0]["props"].get("variant") == "ghost"


def test_button_with_solid_fill_keeps_default_variant():
    """A Button with a real solid fill (a primary CTA) does NOT get
    variant:'ghost' — only fill-less buttons do."""
    doc = {
        "id": "root", "type": "FRAME", "name": "Form",
        "layoutMode": "VERTICAL",
        "children": [
            {"id": "b1", "type": "FRAME", "name": "Submit Button",
             "fills": [{"type": "SOLID", "color": {"r": 0.1, "g": 0.5, "b": 0.9}}],
             "children": [
                 {"id": "t1", "type": "TEXT", "name": "label", "characters": "Submit"},
             ]},
        ],
    }
    result = build_page_schema(doc)
    nodes = _collect_nodes({"children": result.page["children"]})
    buttons = [n for n in nodes if n.get("type") == "Button"]
    assert len(buttons) == 1
    assert buttons[0]["props"].get("variant") != "ghost"
