"""Tests for surface_wrap_guard — wrapping bare data-display nodes in a padded
Card so tables/charts/lists don't render flush against their container edges."""
import json
import os

from services.surface_wrap_guard import wrap_bare_data_displays


def _write(tmp_path, root):
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "home.json").write_text(json.dumps({"id": "home", "route": "/", "root": root}))
    return str(tmp_path)


def _home(out):
    return json.load(open(os.path.join(out, "src", "schemas", "home.json")))["root"]


def _types(node):
    """Flatten node types depth-first for assertions."""
    out = [node.get("type")]
    for c in node.get("children") or []:
        out += _types(c)
    return out


def test_bare_table_in_stack_is_wrapped(tmp_path):
    root = {"type": "Stack", "children": [
        {"id": "t1", "type": "Table", "props": {"rows": "{{items}}"}},
    ]}
    out = _write(tmp_path, root)
    res = wrap_bare_data_displays(out)
    assert res["wrapped"] == 1
    r = _home(out)
    # Stack > Card > Table
    assert r["type"] == "Stack"
    assert r["children"][0]["type"] == "Card"
    assert r["children"][0]["children"][0]["type"] == "Table"


def test_table_already_in_card_is_left_alone(tmp_path):
    root = {"type": "Stack", "children": [
        {"type": "Card", "children": [{"type": "Table", "props": {}}]},
    ]}
    out = _write(tmp_path, root)
    res = wrap_bare_data_displays(out)
    assert res["wrapped"] == 0
    assert _types(_home(out)) == ["Stack", "Card", "Table"]


def test_chart_with_card_ancestor_not_double_wrapped(tmp_path):
    # Card > Stack > Chart  → Chart has a Card ancestor, so leave it.
    root = {"type": "Stack", "children": [
        {"type": "Card", "children": [
            {"type": "Stack", "children": [{"type": "Chart", "props": {}}]},
        ]},
    ]}
    out = _write(tmp_path, root)
    res = wrap_bare_data_displays(out)
    assert res["wrapped"] == 0


def test_non_data_node_not_wrapped(tmp_path):
    root = {"type": "Stack", "children": [
        {"type": "Heading", "props": {"text": "Hi"}},
        {"type": "Text", "props": {"text": "x"}},
    ]}
    out = _write(tmp_path, root)
    res = wrap_bare_data_displays(out)
    assert res["wrapped"] == 0
    assert _types(_home(out)) == ["Stack", "Heading", "Text"]


def test_multiple_bare_displays_each_wrapped(tmp_path):
    root = {"type": "Stack", "children": [
        {"type": "Chart", "props": {}},
        {"type": "Table", "props": {}},
        {"type": "List", "props": {}},
    ]}
    out = _write(tmp_path, root)
    res = wrap_bare_data_displays(out)
    assert res["wrapped"] == 3
    r = _home(out)
    assert [c["type"] for c in r["children"]] == ["Card", "Card", "Card"]
    assert [c["children"][0]["type"] for c in r["children"]] == ["Chart", "Table", "List"]


def test_idempotent(tmp_path):
    root = {"type": "Stack", "children": [{"type": "Table", "props": {}}]}
    out = _write(tmp_path, root)
    wrap_bare_data_displays(out)
    res2 = wrap_bare_data_displays(out)
    assert res2["wrapped"] == 0
