"""Tests for widget_data_source_guard.bind_static_widgets.

A stat/progress widget with a hardcoded numeric value that maps to a real entity
count gets an op:"aggregate" dataSource binding; a static header/text widget is
left untouched; the pass is idempotent. Also covers list widgets and the
conservative skips (qualifier stats, shape-specialized widgets).
"""
import json
import os

from services.widget_data_source_guard import bind_static_widgets


def _write_registry(root: str, entities: dict) -> None:
    reg = {
        "entities": {
            name: {"fields": {c: {"type": t} for c, t in cols.items()}}
            for name, cols in entities.items()
        }
    }
    with open(os.path.join(root, "registry.json"), "w", encoding="utf-8") as fh:
        json.dump(reg, fh)


def _write_schema(root: str, name: str, schema: dict) -> str:
    sdir = os.path.join(root, "src", "schemas")
    os.makedirs(sdir, exist_ok=True)
    fp = os.path.join(sdir, name)
    with open(fp, "w", encoding="utf-8") as fh:
        json.dump(schema, fh)
    return fp


def _load(fp: str) -> dict:
    with open(fp, encoding="utf-8") as fh:
        return json.load(fh)


def _make_app(tmp_path, root_node: dict, data_sources=None) -> str:
    root = str(tmp_path)
    _write_registry(root, {
        "Drive": {"id": "uuid", "title": "varchar", "status": "varchar"},
        "Candidate": {"id": "uuid", "firstName": "varchar"},
    })
    _write_schema(root, "dashboard.json", {
        "id": "dashboard",
        "route": "/dashboard",
        "dataSources": data_sources or [],
        "root": root_node,
    })
    return root


def test_stat_widget_with_hardcoded_count_gets_aggregate_binding(tmp_path):
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile",
             "props": {"label": "Total Drives", "value": 128, "format": "number"}},
        ],
    })
    res = bind_static_widgets(root)
    assert res["bound"] == 1

    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    tile = schema["root"]["children"][0]
    # Literal number replaced with an aggregate binding.
    assert tile["props"]["value"] == "{{driveTotal.value}}"
    agg = [d for d in schema["dataSources"] if d["name"] == "driveTotal"]
    assert len(agg) == 1
    assert agg[0]["op"] == "aggregate"
    assert agg[0]["entity"] == "Drive"
    assert agg[0]["metrics"] == {"value": {"fn": "count"}}


def test_static_header_text_untouched(tmp_path):
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "h", "type": "Heading", "props": {"content": "Recruitment Drives", "level": 1}},
            {"id": "t", "type": "Text", "props": {"content": "Manage all drives"}},
        ],
    })
    res = bind_static_widgets(root)
    assert res["bound"] == 0

    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    kids = schema["root"]["children"]
    assert kids[0]["props"]["content"] == "Recruitment Drives"
    assert kids[1]["props"]["content"] == "Manage all drives"
    assert schema["dataSources"] == []


def test_idempotent(tmp_path):
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "StatCard", "props": {"label": "Drives", "value": 42}},
        ],
    })
    first = bind_static_widgets(root)
    assert first["bound"] == 1
    after_first = _load(os.path.join(root, "src", "schemas", "dashboard.json"))

    second = bind_static_widgets(root)
    assert second["bound"] == 0  # already bound -> no-op
    after_second = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    assert after_first == after_second


def test_qualified_stat_is_skipped(tmp_path):
    # "Active Drives" carries a qualifier we can't express as a plain count.
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile", "props": {"label": "Active Drives", "value": 7}},
        ],
    })
    res = bind_static_widgets(root)
    assert res["bound"] == 0
    assert res["skipped"] == 1
    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    assert schema["root"]["children"][0]["props"]["value"] == 7


def test_shape_specialized_widgets_left_alone(tmp_path):
    # ActivityFeed / ApprovalStepper are not in any allowlist -> never touched.
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "feed", "type": "ActivityFeed",
             "props": {"title": "Drive Updates", "entries": [{"action": "launched"}]}},
            {"id": "stepper", "type": "ApprovalStepper",
             "props": {"steps": [{"label": "Planning", "status": "approved"}]}},
        ],
    })
    res = bind_static_widgets(root)
    assert res["bound"] == 0
    assert res["skipped"] == 0  # not even candidates
    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    kids = schema["root"]["children"]
    assert kids[0]["props"]["entries"] == [{"action": "launched"}]
    assert kids[1]["props"]["steps"] == [{"label": "Planning", "status": "approved"}]
    assert schema["dataSources"] == []


def test_list_widget_with_hardcoded_rows_gets_list_binding(tmp_path):
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "lst", "type": "DataList",
             "props": {"title": "Recent Candidates",
                       "items": [{"firstName": "Ada"}, {"firstName": "Bo"}]}},
        ],
    })
    res = bind_static_widgets(root)
    assert res["bound"] == 1
    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    lst = schema["root"]["children"][0]
    assert lst["props"]["items"] == "{{candidates}}"
    ds = [d for d in schema["dataSources"] if d["name"] == "candidates"]
    assert len(ds) == 1 and ds[0]["op"] == "list" and ds[0]["entity"] == "Candidate"


def test_table_columns_never_touched(tmp_path):
    # A Table's `columns` is config, `rows` already bound -> nothing to do.
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "tbl", "type": "Table",
             "props": {"rows": "{{drives}}",
                       "columns": [{"key": "title", "label": "Title"}]}},
        ],
    }, data_sources=[{"name": "drives", "entity": "Drive", "op": "list"}])
    res = bind_static_widgets(root)
    assert res["bound"] == 0
    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    tbl = schema["root"]["children"][0]
    assert tbl["props"]["columns"] == [{"key": "title", "label": "Title"}]
    assert tbl["props"]["rows"] == "{{drives}}"


def test_datasource_name_deduped(tmp_path):
    # An existing dataSource named `driveTotal` forces a suffix on the new one.
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile", "props": {"label": "Drives", "value": 5}},
        ],
    }, data_sources=[{"name": "driveTotal", "entity": "Drive", "op": "list"}])
    res = bind_static_widgets(root)
    assert res["bound"] == 1
    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    tile = schema["root"]["children"][0]
    assert tile["props"]["value"] == "{{driveTotal2.value}}"


# ── B12 — a binding whose root names no declared dataSource ─────────────────

def test_a_dangling_binding_counts_as_unbound(tmp_path):
    """The guard treated ANY `{{…}}` string as "already bound" and skipped it,
    which stepped over exactly the case it exists to fix: `/items` shipped
    three Stat tiles bound to `{{metrics.…}}` on a page with no `metrics`
    source. Nothing fetched, the tiles rendered blank, and the guard walked
    past all three because they carried a binding-shaped string."""
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile",
             "props": {"label": "Total Drives",
                       "value": "{{metrics.list_total_drives}}"}},
        ],
    })
    res = bind_static_widgets(root)
    assert res["bound"] == 1

    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    assert schema["root"]["children"][0]["props"]["value"] == "{{driveTotal.value}}"
    agg = [d for d in schema["dataSources"] if d["name"] == "driveTotal"]
    assert agg and agg[0]["op"] == "aggregate"


def test_a_binding_that_names_a_declared_source_is_left_alone(tmp_path):
    """The binding resolves. Rewriting it would replace a metric the page
    designed with a generic row count."""
    root = _make_app(
        tmp_path,
        {"id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile",
             "props": {"label": "Total Drives", "value": "{{stats.open}}"}},
        ]},
        data_sources=[{"name": "stats", "entity": "Drive", "op": "aggregate",
                       "metrics": {"open": {"fn": "count"}}}],
    )
    assert bind_static_widgets(root)["bound"] == 0
    schema = _load(os.path.join(root, "src", "schemas", "dashboard.json"))
    assert schema["root"]["children"][0]["props"]["value"] == "{{stats.open}}"


def test_a_scope_root_is_not_a_dangling_binding(tmp_path):
    """`{{user.…}}` is supplied by the renderer, not by a page fetch."""
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile",
             "props": {"label": "Total Drives", "value": "{{user.driveQuota}}"}},
        ],
    })
    assert bind_static_widgets(root)["bound"] == 0


def test_an_interpolated_sentence_is_not_treated_as_a_stat_binding(tmp_path):
    """Only a whole-string binding is a value binding; prose with a `{{…}}` in
    it is not something to rewrite into an aggregate."""
    root = _make_app(tmp_path, {
        "id": "root", "type": "Stack", "children": [
            {"id": "kpi", "type": "MetricTile",
             "props": {"label": "Total Drives",
                       "value": "about {{metrics.n}} drives"}},
        ],
    })
    assert bind_static_widgets(root)["bound"] == 0
