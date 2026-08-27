"""Responsive-layout post-processing for Figma-mapped schemas.

A Figma frame locks content to a fixed pixel width (e.g. w-[1271px]); on any
narrower viewport that overflows and never reflows. _fluidize_fixed_width_shells
converts large fixed-width containers to `w-full max-w-[Npx] mx-auto` so the page
fills the viewport up to the design width and centers — matching the Figma at the
design width while shrinking gracefully below it.
"""
from services.figma_to_schema import _fluidize_fixed_width_shells


def _cn(node):
    return (node.get("props") or {}).get("className", "")


def test_large_fixed_width_becomes_fluid_capped_and_centered():
    nodes = [{"type": "Stack", "props": {"className": "w-[1271px] min-h-[121px] bg-[#fff]"},
              "children": []}]
    _fluidize_fixed_width_shells(nodes)
    cn = _cn(nodes[0]).split()
    assert "w-full" in cn, cn
    assert "max-w-[1271px]" in cn, cn
    assert "mx-auto" in cn, cn
    assert "w-[1271px]" not in cn, cn
    # unrelated utilities preserved
    assert "min-h-[121px]" in cn and "bg-[#fff]" in cn, cn


def test_recurses_into_children():
    nodes = [{"type": "Stack", "props": {"className": "w-[1271px]"}, "children": [
        {"type": "Card", "props": {"className": "w-[1144px] p-6"}, "children": []},
    ]}]
    _fluidize_fixed_width_shells(nodes)
    assert "max-w-[1144px]" in _cn(nodes[0]["children"][0]).split()
    assert "w-full" in _cn(nodes[0]["children"][0]).split()


def test_small_fixed_widths_left_untouched():
    # Sidebars (~247) and chips/columns (< 600) must stay fixed so the
    # asymmetric-row + sidebar heuristics keep working.
    nodes = [
        {"type": "Stack", "props": {"className": "w-[247px] shrink-0"}, "children": []},
        {"type": "Box", "props": {"className": "w-[96px] shrink-0"}, "children": []},
    ]
    _fluidize_fixed_width_shells(nodes)
    assert _cn(nodes[0]) == "w-[247px] shrink-0"
    assert _cn(nodes[1]) == "w-[96px] shrink-0"


def test_idempotent():
    nodes = [{"type": "Stack", "props": {"className": "w-[1271px]"}, "children": []}]
    _fluidize_fixed_width_shells(nodes)
    once = _cn(nodes[0])
    _fluidize_fixed_width_shells(nodes)
    twice = _cn(nodes[0])
    assert once == twice, (once, twice)
    # exactly one w-full, max-w not re-fluidized
    assert twice.split().count("w-full") == 1, twice
    assert "max-w-[1271px]" in twice.split() and twice.split().count("max-w-[1271px]") == 1, twice


def test_does_not_touch_max_w_token():
    # `max-w-[800px]` contains the substring `w-[800px]` — must NOT be matched.
    nodes = [{"type": "Stack", "props": {"className": "w-full max-w-[800px] mx-auto"}, "children": []}]
    _fluidize_fixed_width_shells(nodes)
    assert _cn(nodes[0]) == "w-full max-w-[800px] mx-auto"
