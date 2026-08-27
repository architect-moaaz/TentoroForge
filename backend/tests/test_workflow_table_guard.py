"""Tests for the gen-time workflow-table reconciler."""
from __future__ import annotations

import json
import os

from services.workflow_table_guard import reconcile_workflow_tables


def _write_schema(tmp_path, body: str) -> None:
    sdir = tmp_path / "src" / "db" / "schema"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "x.ts").write_text(body, encoding="utf-8")


def _write_workflow(tmp_path, name: str, data: dict) -> str:
    wdir = tmp_path / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    fp = wdir / name
    fp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(fp)


def _wf(table: str) -> dict:
    return {
        "id": "create-ka",
        "definition": {
            "nodes": [
                {
                    "id": "db_insert",
                    "type": "action",
                    "data": {
                        "config": {
                            "actionType": "db_insert",
                            "table": table,
                            "values": {"title": "title"},
                        }
                    },
                }
            ]
        },
    }


def _read(fp: str) -> dict:
    with open(fp, encoding="utf-8") as fh:
        return json.load(fh)


def test_remaps_snake_to_real_camel(tmp_path):
    _write_schema(tmp_path, 'export const t = pgTable("knowledgeArticles", {});')
    fp = _write_workflow(tmp_path, "CreateKA.json", _wf("knowledge_articles"))

    res = reconcile_workflow_tables(str(tmp_path))

    data = _read(fp)
    table = data["definition"]["nodes"][0]["data"]["config"]["table"]
    assert table == "knowledgeArticles"
    assert ("CreateKA.json", "knowledge_articles", "knowledgeArticles") in res["remapped"]
    assert res["unresolved"] == []


def test_exact_match_untouched(tmp_path):
    _write_schema(tmp_path, 'export const t = pgTable("knowledgeArticles", {});')
    fp = _write_workflow(tmp_path, "CreateKA.json", _wf("knowledgeArticles"))
    before = os.path.getmtime(fp)
    before_bytes = open(fp, "rb").read()

    res = reconcile_workflow_tables(str(tmp_path))

    assert res["remapped"] == []
    assert res["unresolved"] == []
    # file content unchanged
    assert open(fp, "rb").read() == before_bytes
    assert os.path.getmtime(fp) == before


def test_unresolved_when_no_table(tmp_path):
    _write_schema(tmp_path, 'export const t = pgTable("knowledgeArticles", {});')
    fp = _write_workflow(tmp_path, "CreateKA.json", _wf("nonexistent"))
    before_bytes = open(fp, "rb").read()

    res = reconcile_workflow_tables(str(tmp_path))

    assert res["remapped"] == []
    assert ("CreateKA.json", "nonexistent") in res["unresolved"]
    assert open(fp, "rb").read() == before_bytes


def test_nested_config_table_found(tmp_path):
    _write_schema(tmp_path, 'export const t = pgTable("knowledgeArticles", {});')
    nested = {
        "id": "wf",
        "definition": {
            "branches": [
                {
                    "steps": [
                        {
                            "node": {
                                "data": {
                                    "config": {
                                        "actionType": "db_update",
                                        "table": "knowledge_articles",
                                    }
                                }
                            }
                        }
                    ]
                }
            ]
        },
    }
    fp = _write_workflow(tmp_path, "Deep.json", nested)

    res = reconcile_workflow_tables(str(tmp_path))

    data = _read(fp)
    table = data["definition"]["branches"][0]["steps"][0]["node"]["data"]["config"]["table"]
    assert table == "knowledgeArticles"
    assert ("Deep.json", "knowledge_articles", "knowledgeArticles") in res["remapped"]
