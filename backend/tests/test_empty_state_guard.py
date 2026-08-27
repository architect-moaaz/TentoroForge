"""strip_redundant_empty_states: an EmptyState sibling of a data Table stacks below
it (and shows even with data), because the Table renders its own in-frame empty
state. The guard drops those siblings; unrelated empty-states are left alone."""
from services.schema_binding import strip_redundant_empty_states


def _tree(children):
    return {"root": {"type": "Stack", "children": children}}


def test_removes_empty_state_sibling_of_data_table():
    schema = _tree([
        {"type": "Table", "props": {"columns": [], "rows": "{{folios}}"}},
        {"type": "EmptyStateRich", "props": {"title": "No folios found"}},
    ])
    out, info = strip_redundant_empty_states(schema)
    kids = out["root"]["children"]
    assert info["empty_states_removed"] == 1
    assert [c["type"] for c in kids] == ["Table"]


def test_keeps_empty_state_without_a_data_table():
    schema = _tree([
        {"type": "Heading", "props": {"content": "Reports"}},
        {"type": "EmptyState", "props": {"title": "Nothing here"}},
    ])
    out, info = strip_redundant_empty_states(schema)
    assert info["empty_states_removed"] == 0
    assert any(c["type"] == "EmptyState" for c in out["root"]["children"])


def test_gates_empty_state_next_to_a_repeat_list():
    # Repeat has no built-in empty state → gate the sibling with count()==0,
    # even when the Repeat is nested inside a sibling (Section → Grid → Repeat).
    schema = _tree([
        {"type": "Section", "children": [
            {"type": "Grid", "children": [
                {"type": "Repeat", "bind": "tasks", "children": [{"type": "Stack"}]},
            ]},
        ]},
        {"type": "EmptyStateRich", "props": {"title": "No tasks"}},
    ])
    out, info = strip_redundant_empty_states(schema)
    es = [c for c in out["root"]["children"] if c["type"] == "EmptyStateRich"][0]
    assert info["empty_states_gated"] == 1
    assert es["visibleIf"] == "count(tasks) = 0"
    assert info["empty_states_removed"] == 0  # not removed — Repeat has no built-in


def test_ignores_static_table_without_binding():
    # A Table with no rows/data binding isn't a live list → leave the empty-state.
    schema = _tree([
        {"type": "Table", "props": {"columns": []}},
        {"type": "EmptyState", "props": {}},
    ])
    out, info = strip_redundant_empty_states(schema)
    assert info["empty_states_removed"] == 0


def test_idempotent():
    schema = _tree([
        {"type": "Table", "props": {"rows": "{{x}}"}},
        {"type": "EmptyState", "props": {}},
    ])
    strip_redundant_empty_states(schema)
    _, info = strip_redundant_empty_states(schema)
    assert info["empty_states_removed"] == 0
