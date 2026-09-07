"""Tests for services.binding_prop_normalizer — canonical binding spelling."""
from __future__ import annotations

import json
from pathlib import Path

from services.binding_prop_normalizer import normalize_binding_props


def _mk_app(tmp_path: Path, schemas: dict[str, dict],
            plan: dict | None = None) -> Path:
    root = tmp_path / "app"
    for rel, doc in schemas.items():
        p = root / "src" / "schemas" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
    if plan is not None:
        p = root / "src" / "contracts" / "plan.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(plan), encoding="utf-8")
    return root


def _page(root: Path, rel: str) -> dict:
    return json.loads((root / "src" / "schemas" / rel).read_text(encoding="utf-8"))


def _list_doc(node: dict) -> dict:
    return {"dataSources": [{"name": "documents", "entity": "Document",
                             "op": "list"}],
            "root": {"type": "Stack", "children": [node]}}


# ── dataSource → canonical prop ──────────────────────────────────────

def test_table_datasource_normalized_to_rows(tmp_path: Path):
    """The atb0m97x case: Table with props.dataSource and no rows."""
    root = _mk_app(tmp_path, {"documents.json": _list_doc(
        {"type": "Table", "props": {"dataSource": "documents",
                                    "columns": []}})})
    rep = normalize_binding_props(root)
    node = _page(root, "documents.json")["root"]["children"][0]
    assert node["props"]["rows"] == "{{documents}}"
    assert rep["summary"]["normalized"] == 1


def test_wrapped_datasource_also_normalized(tmp_path: Path):
    """ActivityFeed with dataSource: "{{documents}}" → entries binding."""
    root = _mk_app(tmp_path, {"index.json": _list_doc(
        {"type": "ActivityFeed", "props": {"dataSource": "{{documents}}"}})})
    normalize_binding_props(root)
    node = _page(root, "index.json")["root"]["children"][0]
    assert node["props"]["entries"] == "{{documents}}"


def test_chart_datasource_normalized_to_data(tmp_path: Path):
    root = _mk_app(tmp_path, {"index.json": _list_doc(
        {"type": "Chart", "props": {"chartType": "bar",
                                    "dataSource": "documents"}})})
    normalize_binding_props(root)
    node = _page(root, "index.json")["root"]["children"][0]
    assert node["props"]["data"] == "{{documents}}"


def test_authored_rows_binding_never_clobbered(tmp_path: Path):
    root = _mk_app(tmp_path, {"documents.json": _list_doc(
        {"type": "Table", "props": {"dataSource": "documents",
                                    "rows": "{{other}}", "columns": []}})})
    rep = normalize_binding_props(root)
    node = _page(root, "documents.json")["root"]["children"][0]
    assert node["props"]["rows"] == "{{other}}"
    assert rep["summary"]["normalized"] == 0


def test_unknown_datasource_name_left_alone(tmp_path: Path):
    """dataSource naming nothing on the page → don't invent a binding."""
    root = _mk_app(tmp_path, {"documents.json": _list_doc(
        {"type": "Table", "props": {"dataSource": "ghosts", "columns": []}})})
    rep = normalize_binding_props(root)
    node = _page(root, "documents.json")["root"]["children"][0]
    assert "rows" not in node["props"]
    assert rep["summary"]["normalized"] == 0


def test_description_list_bare_name_wrapped(tmp_path: Path):
    root = _mk_app(tmp_path, {"detail.json": _list_doc(
        {"type": "DescriptionList",
         "props": {"dataSource": "doc.extractedFields"}})})
    normalize_binding_props(root)
    node = _page(root, "detail.json")["root"]["children"][0]
    assert node["props"]["dataSource"] == "{{doc.extractedFields}}"


def test_idempotent_rerun(tmp_path: Path):
    root = _mk_app(tmp_path, {"documents.json": _list_doc(
        {"type": "Table", "props": {"dataSource": "documents",
                                    "columns": []}})})
    normalize_binding_props(root)
    rep2 = normalize_binding_props(root)
    assert rep2["summary"]["normalized"] == 0


# ── bare Select enum backfill ────────────────────────────────────────

_PLAN = {"data_models": [{"name": "Document", "fields": [
    {"name": "status", "type": "text",
     "enum_values": ["pending", "processed", "failed"]}]}]}


def test_bare_select_backfilled_from_form_entity(tmp_path: Path):
    doc = {"root": {"type": "Form", "props": {"entity": "Document"},
                    "children": [{"type": "Select",
                                  "props": {"name": "status",
                                            "label": "Status"}}]}}
    root = _mk_app(tmp_path, {"upload.json": doc}, plan=_PLAN)
    rep = normalize_binding_props(root)
    node = _page(root, "upload.json")["root"]["children"][0]
    values = [o["value"] for o in node["props"]["options"]]
    assert values == ["pending", "processed", "failed"]
    assert rep["summary"]["selects_filled"] == 1


def test_bare_select_backfilled_by_unique_column_match(tmp_path: Path):
    """No Form ancestor — column name matches exactly one plan entity."""
    doc = {"root": {"type": "Stack", "children": [
        {"type": "Select", "props": {"name": "status", "label": "Status"}}]}}
    root = _mk_app(tmp_path, {"search.json": doc}, plan=_PLAN)
    normalize_binding_props(root)
    node = _page(root, "search.json")["root"]["children"][0]
    assert [o["value"] for o in node["props"]["options"]] \
        == ["pending", "processed", "failed"]


def test_select_with_options_untouched(tmp_path: Path):
    doc = {"root": {"type": "Select", "props": {
        "name": "status", "options": [{"value": "a", "label": "A"}]}}}
    root = _mk_app(tmp_path, {"f.json": doc}, plan=_PLAN)
    rep = normalize_binding_props(root)
    assert rep["summary"]["selects_filled"] == 0
    assert len(_page(root, "f.json")["root"]["props"]["options"]) == 1


def test_select_with_optionsfrom_untouched(tmp_path: Path):
    doc = {"root": {"type": "Select", "props": {
        "name": "documentId", "optionsFrom": {"dataSource": "documents",
                                              "valueKey": "id",
                                              "labelKey": "fileName"}}}}
    root = _mk_app(tmp_path, {"f.json": doc}, plan=_PLAN)
    rep = normalize_binding_props(root)
    assert rep["summary"]["selects_filled"] == 0
    assert rep["summary"]["unresolved"] == 0


def test_unfillable_select_reported_not_guessed(tmp_path: Path):
    doc = {"root": {"type": "Select", "props": {"name": "mystery"}}}
    root = _mk_app(tmp_path, {"f.json": doc}, plan=_PLAN)
    rep = normalize_binding_props(root)
    assert "options" not in _page(root, "f.json")["root"]["props"]
    assert rep["summary"]["unresolved"] == 1


# ── report + resilience ──────────────────────────────────────────────

def test_report_written_to_contracts(tmp_path: Path):
    root = _mk_app(tmp_path, {"documents.json": _list_doc(
        {"type": "Table", "props": {"dataSource": "documents",
                                    "columns": []}})})
    normalize_binding_props(root)
    rep = json.loads((root / "contracts" / "binding-normalize.json")
                     .read_text(encoding="utf-8"))
    assert rep["summary"]["normalized"] == 1


def test_missing_schemas_dir_no_crash(tmp_path: Path):
    rep = normalize_binding_props(tmp_path / "nope")
    assert rep["summary"] == {"normalized": 0, "selects_filled": 0,
                              "unresolved": 0}
