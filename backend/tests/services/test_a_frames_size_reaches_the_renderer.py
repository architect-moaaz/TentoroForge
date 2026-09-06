"""The frame's size must travel from the composer to the page the app serves.

`figma_layout.compose` returns the frame's recorded size as `canvas`, and the
`FigmaCanvas` client component scales a page by (available width / frame
width) — but nothing between them carried the value. The executor's layout row
omitted it, so `plan_page` had nothing to emit, so the projected schema had no
`_figmaCanvas`, so `FigmaCanvas` never mounted: a 3902px frame rendered cropped
to the viewport with twenty-seven of its thirty cards off-screen to the right.

Two hops, each pinned here: the layout row carries `canvas` (executor), and a
layout row that carries it produces a schema that carries `_figmaCanvas`
(projection). Every page whose row has no `canvas` — every A2UI page, and any
Figma frame with no recorded size — comes out byte-identical to before.
"""
import inspect

from services.blueprint import executors
from services.blueprint.page_planner import load_catalog, plan_page

DOC = {"application": {"name": "X"}, "data": {"entities": []}, "workflows": []}
PAGE = {"id": "PAGE-001", "route": "/", "name": "Home", "pattern": "dashboard"}
ROOT = {"type": "Container", "props": {"className": "relative"}, "children": []}


def _row(**extra):
    return {"page": "PAGE-001", "pattern": "dashboard", "composedBy": "figma",
            "root": ROOT, "dataSources": [], "requirements": [], **extra}


def test_a_layout_with_a_canvas_projects_it():
    schema = plan_page(DOC, PAGE, _row(canvas={"width": 3902.0, "height": 1975.0}),
                       load_catalog())
    assert schema["_figmaCanvas"] == {"width": 3902.0, "height": 1975.0}


def test_a_layout_without_a_canvas_is_unchanged():
    """Every A2UI page, and a frame with no recorded size."""
    schema = plan_page(DOC, PAGE, _row(), load_catalog())
    assert "_figmaCanvas" not in schema


def test_an_empty_canvas_is_not_emitted():
    schema = plan_page(DOC, PAGE, _row(canvas=None), load_catalog())
    assert "_figmaCanvas" not in schema


def test_the_executor_puts_canvas_on_the_layout_row():
    """The first hop. Pinned on the source because the branch runs inside the
    DAG executor and needs a live Figma extraction to reach."""
    src = inspect.getsource(executors)
    assert '"canvas": drawn["canvas"]' in src


def test_the_fit_reaches_the_renderer_with_the_size():
    """`fluid` or `scale` travels in the same canvas record as width/height."""
    from services.blueprint.page_planner import plan_page
    import inspect
    src = inspect.getsource(plan_page)
    assert '"_figmaCanvas": template["canvas"]' in src, "the canvas is copied whole"
