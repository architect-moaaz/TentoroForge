"""DataGrid row binding: a DataGrid's `rows` must be wired to the page's list
dataSource so the runtime renders real records.

The schema agent emits `DataGrid.props.rows = []` (literal) alongside a list
dataSource; the renderer interpolates props, so `rows: "{{tasks}}"` resolves to the
dataSource array. apply_bindings previously skipped all list binding when the page
already had dataSources/Repeats, leaving the grid empty — this guards the fix.
"""
from services.schema_binding import apply_datagrid_binding, apply_bindings


def _grid(rows):
    return {"id": "g", "type": "DataGrid",
            "props": {"rowKey": "id", "columns": [{"key": "title", "label": "Title"}], "rows": rows}}


def _page(nodes, dataSources):
    return {"schemaVersion": "2", "id": "tasks", "route": "/tasks",
            "dataSources": dataSources, "root": {"type": "Stack", "children": nodes}}


def test_binds_unbound_datagrid_to_matching_list_source():
    page = _page([_grid([])], [
        {"name": "stats", "entity": "Task", "op": "aggregate"},
        {"name": "tasks", "entity": "Task", "op": "list"},
    ])
    out, info = apply_datagrid_binding(page, {"entity": "Task"}, None)
    assert info["bound"] == 1 and info["source"] == "tasks"
    grid = out["root"]["children"][0]
    assert grid["props"]["rows"] == "{{tasks}}"


def test_idempotent_leaves_already_bound_grid():
    page = _page([_grid("{{tasks}}")], [{"name": "tasks", "entity": "Task", "op": "list"}])
    out, info = apply_datagrid_binding(page, {"entity": "Task"}, None)
    assert info["bound"] == 0
    assert out["root"]["children"][0]["props"]["rows"] == "{{tasks}}"


def test_creates_list_source_when_missing():
    page = _page([_grid([])], [{"name": "stats", "entity": "Task", "op": "aggregate"}])
    out, info = apply_datagrid_binding(page, {"entity": "Task"}, None)
    assert info["bound"] == 1
    # a list dataSource was synthesized for the entity
    assert any(d["op"] == "list" and d["entity"] == "Task" for d in out["dataSources"])
    assert out["root"]["children"][0]["props"]["rows"].startswith("{{")


def test_apply_bindings_runs_datagrid_despite_list_already():
    # page already has dataSources (list_already=True) — the OLD code skipped all
    # list binding here, leaving the grid empty. The grid must still get bound.
    page = _page([_grid([])], [{"name": "tasks", "entity": "Task", "op": "list"}])
    out, report = apply_bindings(page, {"entity": "Task", "file": "src/schemas/tasks.json"},
                                 {"data_models": [{"name": "Task", "fields": [{"name": "title"}]}]})
    assert report["list_skipped"] is True          # guard still skips repeater collapse
    assert report["datagrids_bound"] == 1          # but DataGrid got bound anyway
    grid = out["root"]["children"][0]
    assert grid["props"]["rows"] == "{{tasks}}"
