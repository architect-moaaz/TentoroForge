from services.figma_node_walker import walk_and_flatten


def test_flattens_single_child_container_chain():
    """Container > Container > Container > Text should collapse — the Text
    leaf's `parent` is the OUTERMOST surviving container's annotated node."""
    tree = {
        "id": "a", "type": "FRAME", "name": "Container",
        "children": [{
            "id": "b", "type": "FRAME", "name": "Container",
            "children": [{
                "id": "c", "type": "FRAME", "name": "Container",
                "children": [{"id": "d", "type": "TEXT", "name": "Hello", "characters": "Hi"}],
            }],
        }],
    }
    out = walk_and_flatten(tree)
    # Only one container survives, plus the text leaf
    types = [(e["node"]["type"], e["node"]["name"]) for e in out]
    # The outermost Container is also passthrough (single child) — it should be flattened too
    # so the result is just the TEXT
    assert any(t == "TEXT" for t, _ in types)
    text_entry = next(e for e in out if e["node"]["type"] == "TEXT")
    # Parent should be None or the surviving ancestor — definitely NOT id "c" or "b"
    parent = text_entry["parent"]
    assert parent is None or parent["id"] not in ("b", "c")


def test_preserves_layout_mode_metadata():
    tree = {
        "id": "row", "type": "FRAME", "name": "Some Row",  # custom name so it's NOT a passthrough
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}],  # has fill — definitely kept
        "layoutMode": "HORIZONTAL", "itemSpacing": 12,
        "children": [
            {"id": "a", "type": "TEXT", "name": "A", "characters": "A"},
            {"id": "b", "type": "TEXT", "name": "B", "characters": "B"},
        ],
    }
    out = walk_and_flatten(tree)
    parent_entry = next(e for e in out if e["node"]["id"] == "row")
    parent = parent_entry["node"]
    assert parent.get("_layoutMode") == "HORIZONTAL"
    assert parent.get("_itemSpacing") == 12


def test_keeps_multi_child_container():
    """Multi-child Container is NOT a passthrough — must survive."""
    tree = {
        "id": "root", "type": "FRAME", "name": "Container",
        "children": [
            {"id": "a", "type": "TEXT", "name": "A", "characters": "A"},
            {"id": "b", "type": "TEXT", "name": "B", "characters": "B"},
        ],
    }
    out = walk_and_flatten(tree)
    types = [e["node"]["id"] for e in out]
    assert "root" in types
    assert "a" in types
    assert "b" in types
    assert len(out) == 3


def test_container_with_fill_is_not_passthrough():
    """A Container that has its own visual (fill) should be kept even if it has only one child."""
    tree = {
        "id": "card", "type": "FRAME", "name": "Container",
        "fills": [{"type": "SOLID", "color": {"r": 0.9, "g": 0.9, "b": 0.95}}],
        "children": [{"id": "x", "type": "TEXT", "name": "Title", "characters": "T"}],
    }
    out = walk_and_flatten(tree)
    ids = [e["node"]["id"] for e in out]
    assert "card" in ids
    assert "x" in ids


def test_path_records_ancestors():
    tree = {
        "id": "root", "type": "FRAME", "name": "Some Card",
        "fills": [{"type": "SOLID", "color": {}}],
        "children": [{"id": "child", "type": "TEXT", "name": "T", "characters": "x"}],
    }
    out = walk_and_flatten(tree)
    child_entry = next(e for e in out if e["node"]["id"] == "child")
    assert "root" in child_entry["path"]


def test_empty_tree_returns_empty():
    assert walk_and_flatten({}) == []


def test_padding_fields_propagated_with_underscore():
    tree = {
        "id": "r", "type": "FRAME", "name": "Some Frame",
        "fills": [{"type": "SOLID", "color": {}}],
        "paddingTop": 16, "paddingRight": 24, "paddingBottom": 16, "paddingLeft": 24,
        "children": [{"id": "x", "type": "TEXT", "name": "y", "characters": "y"}],
    }
    out = walk_and_flatten(tree)
    parent = next(e for e in out if e["node"]["id"] == "r")["node"]
    assert parent.get("_paddingTop") == 16
    assert parent.get("_paddingRight") == 24
    assert parent.get("_paddingBottom") == 16
    assert parent.get("_paddingLeft") == 24


def test_vertical_autolayout_children_sorted_by_y():
    """Auto-layout VERTICAL children are walked in visual top-to-bottom order
    regardless of source layer-panel ordering. Without this, a sidebar nav
    whose layers were reordered manually after auto-layout was applied would
    render with the OTHERS section above the main nav items.
    """
    tree = {
        "id": "r", "type": "FRAME", "name": "Sidebar",
        "layoutMode": "VERTICAL",
        "fills": [{"type": "SOLID", "color": {}}],
        "children": [
            # Source order: OTHERS first. Visual order (by Y): main nav first.
            {"id": "others", "type": "TEXT", "name": "OTHERS",
             "characters": "OTHERS",
             "absoluteBoundingBox": {"x": 0, "y": 400, "width": 100, "height": 16}},
            {"id": "dashboard", "type": "FRAME", "name": "Dashboard",
             "absoluteBoundingBox": {"x": 0, "y": 100, "width": 200, "height": 40}},
            {"id": "settings", "type": "FRAME", "name": "Settings",
             "absoluteBoundingBox": {"x": 0, "y": 450, "width": 200, "height": 40}},
            {"id": "procurement", "type": "FRAME", "name": "Procurement",
             "absoluteBoundingBox": {"x": 0, "y": 150, "width": 200, "height": 40}},
        ],
    }
    out = walk_and_flatten(tree)
    # Filter to just the immediate children of root
    ids = [e["node"]["id"] for e in out if e["parent"] and e["parent"].get("id") == "r"]
    assert ids == ["dashboard", "procurement", "others", "settings"], ids


def test_horizontal_autolayout_children_sorted_by_x():
    """Symmetric to VERTICAL: HORIZONTAL auto-layout children sort by X."""
    tree = {
        "id": "r", "type": "FRAME", "name": "Header",
        "layoutMode": "HORIZONTAL",
        "fills": [{"type": "SOLID", "color": {}}],
        "children": [
            {"id": "search", "type": "FRAME", "name": "Search",
             "absoluteBoundingBox": {"x": 100, "y": 0, "width": 400, "height": 40}},
            {"id": "logo", "type": "FRAME", "name": "Logo",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 80, "height": 40}},
            {"id": "profile", "type": "FRAME", "name": "Profile",
             "absoluteBoundingBox": {"x": 600, "y": 0, "width": 200, "height": 40}},
        ],
    }
    out = walk_and_flatten(tree)
    ids = [e["node"]["id"] for e in out if e["parent"] and e["parent"].get("id") == "r"]
    assert ids == ["logo", "search", "profile"], ids


def test_non_autolayout_preserves_source_order():
    """Frames without auto-layout (layoutMode missing or NONE) keep the source
    list order — bbox-based row inference handles those cases downstream."""
    tree = {
        "id": "r", "type": "FRAME", "name": "Free",
        "fills": [{"type": "SOLID", "color": {}}],
        "children": [
            {"id": "b", "type": "FRAME", "name": "B",
             "absoluteBoundingBox": {"x": 0, "y": 100, "width": 200, "height": 40}},
            {"id": "a", "type": "FRAME", "name": "A",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 40}},
        ],
    }
    out = walk_and_flatten(tree)
    ids = [e["node"]["id"] for e in out if e["parent"] and e["parent"].get("id") == "r"]
    assert ids == ["b", "a"], ids
