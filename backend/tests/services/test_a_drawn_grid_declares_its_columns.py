"""A Grid the transform emits must satisfy the contract it is emitted under.

`Grid` declares `columns` REQUIRED in the component catalog. The Figma
transform promoted any node whose className carried `grid-cols-` to a Grid and
never set it, so the Blueprint refused the page:

    props.(root): 'columns' is a required property

On a real 15-screen design that was the single largest cause of failure — 15 of
15 pages — and it survived three rounds of other fixes because the count was
never missing, only unread. Dev Mode had written it into the class:

    grid-cols-[___355.66px_355.66px_355.66px]

THE UNDERSCORES ARE SEPARATORS, NOT TRACKS. Tailwind encodes spaces in an
arbitrary value as underscores, so a leading run of them is the gap between
`[` and the first track. Counting raw splits gives six columns for three.

WHEN IT CANNOT BE READ, IT IS NOT A GRID. `grid-cols-none` and a bare `grid`
declare no count, and inventing one would place children in columns the design
never had. `Container` keeps the same children and the same className — the CSS
still lays them out — where an under-specified Grid costs the whole page.
"""
import pytest

from services.jsx_to_schema import _grid_columns, transform_jsx_to_schema
from services.blueprint.page_planner import load_catalog, validate_props


# ------------------------------------------------------------ reading the count

@pytest.mark.parametrize("cn,expected", [
    ("grid grid-cols-3 gap-4", 3),
    ("grid-cols-1", 1),
    ("grid grid-cols-12", 12),
    # The real spelling, from a live export.
    ("grid-cols-[___355.66px_355.66px_355.66px]", 3),
    ("grid grid-cols-[1fr_2fr]", 2),
    ("grid grid-cols-[minmax(0,1fr)]", 1),
])
def test_the_column_count_is_read_from_the_class(cn, expected):
    assert _grid_columns(cn) == expected


@pytest.mark.parametrize("cn", ["grid", "grid-cols-none", "grid-cols-", "", "flex gap-2"])
def test_an_unreadable_count_is_not_invented(cn):
    """A guessed column count rearranges a design that was never drawn that
    way — worse than not calling it a Grid."""
    assert _grid_columns(cn) is None


def test_a_zero_count_is_not_a_grid():
    assert _grid_columns("grid-cols-0") is None


# ------------------------------------------------- what the transform emits

GRID_JSX = '''
export default function F() {
  return (
    <div className="bg-white relative size-full" data-node-id="1:1">
      <div className="grid grid-cols-[___355.66px_355.66px_355.66px] gap-x-[16px]" data-node-id="1:2">
        <p className="text-[14px]">One</p>
        <p className="text-[14px]">Two</p>
        <p className="text-[14px]">Three</p>
      </div>
    </div>
  );
}
'''

BARE_GRID_JSX = GRID_JSX.replace(
    "grid grid-cols-[___355.66px_355.66px_355.66px] gap-x-[16px]", "grid gap-x-[16px]")


def _root(jsx):
    return transform_jsx_to_schema(jsx, {}, canvas=(1200.0, 800.0))["children"][0]


def _find(node, kind, node_id="1:2"):
    """The node the JSX marked `1:2` — the grid itself.

    Searching by type alone finds the canvas root, which is also a Container:
    the fallback assertions then check the wrong node and pass or fail for the
    wrong reason.
    """
    if isinstance(node, dict):
        if node.get("type") == kind and \
                (node.get("props") or {}).get("_figmaNodeId") == node_id:
            return node
        for child in node.get("children") or []:
            hit = _find(child, kind, node_id)
            if hit:
                return hit
    return None


def test_a_drawn_grid_carries_its_columns():
    grid = _find(_root(GRID_JSX), "Grid")
    assert grid is not None, "the grid node disappeared"
    assert grid["props"]["columns"] == 3


def test_a_grid_with_no_readable_count_becomes_a_container():
    assert _find(_root(BARE_GRID_JSX), "Grid") is None
    assert _find(_root(BARE_GRID_JSX), "Container") is not None


def test_the_container_keeps_the_class_that_lays_it_out():
    """Falling back must not also throw away the CSS — the browser still
    renders the columns from `grid`, it is only the declaration that is gone."""
    node = _find(_root(BARE_GRID_JSX), "Container")
    assert "grid" in (node["props"].get("className") or "")


def test_the_children_survive_either_way():
    for jsx, kind in ((GRID_JSX, "Grid"), (BARE_GRID_JSX, "Container")):
        node = _find(_root(jsx), kind)
        assert len(node.get("children") or []) == 3


# ------------------------------------------- the property that actually failed

def test_the_composed_tree_passes_the_validator():
    """The end of it: this exact shape is what the Blueprint rejected."""
    errors = validate_props({"root": _root(GRID_JSX)}, load_catalog())
    assert not [e for e in errors if "columns" in e], errors
