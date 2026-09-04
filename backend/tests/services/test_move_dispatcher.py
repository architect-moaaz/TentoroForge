"""The move — Blueprint first, and honest when it finds nothing."""

from services.smith.move_dispatcher import _retitle, _route_matches


def _tree():
    return {
        "type": "Stack",
        "children": [
            {"type": "Button", "props": {"label": "Add plant",
                                         "navigate": "/plants/new"}},
            {"type": "Heading", "props": {"content": "Plants"}},
            {"type": "EmptyState", "props": {"message": "None yet"},
             "children": [
                 # The same label twice — a header button and its echo in the
                 # empty state. Renaming one is the bug reported next.
                 {"type": "Button", "props": {"label": "Add plant"}},
             ]},
        ],
    }


def test_every_occurrence_of_a_label_is_renamed():
    tree = _tree()
    assert _retitle(tree, "Add plant", "New plant") == 2
    labels = []

    def walk(n):
        if isinstance(n, dict):
            p = n.get("props") or {}
            if "label" in p:
                labels.append(p["label"])
            for c in n.get("children") or []:
                walk(c)

    walk(tree)
    assert labels == ["New plant", "New plant"]


def test_a_label_nobody_uses_changes_nothing():
    tree = _tree()
    assert _retitle(tree, "Export", "Download") == 0


def test_only_visible_text_props_are_matched():
    """`navigate` holds /plants/new. A prop that is not text someone can read
    is not something they would name, and matching it edits the wrong thing."""
    tree = {"type": "Button",
            "props": {"label": "Go", "navigate": "/plants/new"}}
    assert _retitle(tree, "/plants/new", "/elsewhere") == 0
    assert tree["props"]["navigate"] == "/plants/new"


def test_a_route_matches_itself_and_its_schema_path():
    """Understanding returns whichever of the two the Blueprint slice showed
    it; refusing one turns a good understanding into a no-op."""
    assert _route_matches("/plants", "/plants")
    assert _route_matches("/plants", "src/schemas/plants.json")
    assert _route_matches("/plants/[id]", "src/schemas/plants/[id].json")


def test_an_unrelated_route_does_not_match():
    assert not _route_matches("/settings", "src/schemas/plants.json")
    assert not _route_matches("", "src/schemas/plants.json")
    assert not _route_matches("/plants", "")


def test_a_request_with_nothing_to_write_is_not_a_move():
    """A removal has no replacement and this function does not know how to do
    one — None, so run_iteration reports no_op rather than inventing an edit."""
    from services.smith.move_dispatcher import move_dispatcher

    assert move_dispatcher({"element_label": "Export", "new_value": ""},
                           "/tmp/nope") is None
    assert move_dispatcher({"element_label": "", "new_value": "x"},
                           "/tmp/nope") is None


def test_a_missing_blueprint_is_not_a_crash():
    from services.smith.move_dispatcher import move_dispatcher

    assert move_dispatcher(
        {"element_label": "Add plant", "new_value": "New plant",
         "target_file": "/plants"},
        "/tmp/definitely-not-a-project",
    ) is None
