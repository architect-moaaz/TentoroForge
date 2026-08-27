"""Tests for the detail-page polish pass."""
import json

from services.detail_polish import polish_detail_schema, polish_detail_schemas


def _kv_row(label, value):
    return {"type": "Row", "children": [
        {"type": "Text", "props": {"content": label, "color": "muted"}},
        {"type": "Text", "props": {"content": value, "weight": "medium"}},
    ]}


def _detail_schema():
    return {"root": {"type": "Stack", "children": [
        {"type": "Row", "children": [
            {"type": "Heading", "props": {"content": "Amanda Davis"}},
            {"type": "Row", "children": [
                {"type": "Button", "props": {"label": "Back"}},
                {"type": "Button", "props": {"label": "Delete"}},
            ]},
        ]},
        {"type": "Card", "children": [
            {"type": "Stack", "children": [
                _kv_row("Name", "{{tech.name}}"),
                _kv_row("Email", "{{tech.email}}"),
                _kv_row("Phone", "{{tech.phone}}"),
            ]},
        ]},
    ]}}


def test_converts_kv_rows_to_description_list():
    s = _detail_schema()
    n = polish_detail_schema(s)
    assert n == 1
    stack = s["root"]["children"][1]["children"][0]  # Card > Stack
    kids = stack["children"]
    assert len(kids) == 1
    dl = kids[0]
    assert dl["type"] == "DescriptionList"
    assert dl["props"]["orientation"] == "horizontal"
    items = dl["props"]["items"]
    assert items[0] == {"term": "Name", "description": "{{tech.name}}"}
    assert [i["term"] for i in items] == ["Name", "Email", "Phone"]


def test_leaves_header_row_alone():
    s = _detail_schema()
    polish_detail_schema(s)
    header = s["root"]["children"][0]
    # Heading + button-row is not a 2-Text row → untouched
    assert header["children"][0]["type"] == "Heading"
    assert header["children"][1]["children"][0]["props"]["label"] == "Back"


def test_swaps_when_value_comes_first():
    s = {"root": {"type": "Card", "children": [
        {"type": "Row", "children": [
            {"type": "Text", "props": {"content": "{{x.a}}"}},
            {"type": "Text", "props": {"content": "Label A"}},
        ]},
        {"type": "Row", "children": [
            {"type": "Text", "props": {"content": "{{x.b}}"}},
            {"type": "Text", "props": {"content": "Label B"}},
        ]},
    ]}}
    polish_detail_schema(s)
    items = s["root"]["children"][0]["props"]["items"]
    assert items[0] == {"term": "Label A", "description": "{{x.a}}"}


def test_idempotent():
    s = _detail_schema()
    assert polish_detail_schema(s) == 1
    assert polish_detail_schema(s) == 0  # already converted


def test_ignores_non_kv_rows():
    # A single kv row (not >=2) is left alone — too little to restyle.
    s = {"root": {"type": "Card", "children": [_kv_row("Only", "{{x}}")]}}
    assert polish_detail_schema(s) == 0


def test_walks_detail_files(tmp_path):
    d = tmp_path / "src" / "schemas" / "technicians"
    d.mkdir(parents=True)
    (d / "[id].json").write_text(json.dumps(_detail_schema()))
    (tmp_path / "src/schemas/technicians.json").write_text(json.dumps({"root": {"type": "Text"}}))
    res = polish_detail_schemas(tmp_path)
    assert res["files"] == 1
    assert res["converted"] == 1
    out = json.loads((d / "[id].json").read_text())
    dl = out["root"]["children"][1]["children"][0]["children"][0]
    assert dl["type"] == "DescriptionList"


def test_no_schema_dir(tmp_path):
    assert polish_detail_schemas(tmp_path) == {"files": 0, "converted": 0, "changed_files": []}
