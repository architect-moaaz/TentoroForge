"""Tests for the build-time binding validator (Slice 1 resource-binding gate)."""
from __future__ import annotations

import json
import os
import shutil

import pytest

from services.binding_validator import validate_bindings


# ── fixtures / builders ──────────────────────────────────────────────────────

_SCHEMA_TS = """\
import { pgTable, uuid, varchar, integer, boolean, timestamp } from "drizzle-orm/pg-core";

export const knowledgeArticles = pgTable("knowledgeArticles", {
  id: uuid("id").primaryKey().defaultRandom(),
  authorId: uuid("author_id"),
  viewCount: integer("view_count"),
  title: varchar("title", { length: 255 }),
  published: boolean("published"),
  createdAt: timestamp("created_at"),
});
"""

_WORKFLOW = {
    "id": "create-knowledge-article",
    "name": "CreateKnowledgeArticle",
    "definition": {
        "trigger": {"type": "manual"},
        "nodes": [
            {
                "id": "db_insert",
                "type": "action",
                "data": {
                    "config": {
                        "actionType": "db_insert",
                        "table": "knowledgeArticles",
                        "values": {
                            "title": "title",
                            "authorId": "authorId",
                            "viewCount": "viewCount",
                        },
                    }
                },
            }
        ],
    },
}


def _mkapp(tmp_path, *, pages: dict, workflows: dict | None = None,
           schema_ts: str = _SCHEMA_TS) -> str:
    """Materialize a minimal generated-app tree under tmp_path and return its dir."""
    out = os.path.join(str(tmp_path), "app")
    os.makedirs(os.path.join(out, "src", "db", "schema"), exist_ok=True)
    os.makedirs(os.path.join(out, "src", "schemas"), exist_ok=True)
    os.makedirs(os.path.join(out, "workflows"), exist_ok=True)
    with open(os.path.join(out, "src", "db", "schema", "knowledgeArticles.ts"), "w") as fh:
        fh.write(schema_ts)
    for name, doc in (workflows or {"CreateKnowledgeArticle.json": _WORKFLOW}).items():
        with open(os.path.join(out, "workflows", name), "w") as fh:
            json.dump(doc, fh)
    for name, doc in pages.items():
        fp = os.path.join(out, "src", "schemas", name)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w") as fh:
            json.dump(doc, fh)
    return out


def _kinds(res: dict) -> set:
    return {e["kind"] for e in res["errors"]}


# ── individual checks ────────────────────────────────────────────────────────

def test_form_dispatching_missing_workflow_errors(tmp_path):
    page = {
        "route": "/articles/new",
        "root": {
            "type": "Form",
            "props": {"workflow": "NoSuchWorkflow"},
            "children": [{"type": "Input", "props": {"name": "title"}}],
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles/new.json": page}))
    assert not res["ok"]
    assert "workflow_ref" in _kinds(res)
    assert any(e["ref"] == "NoSuchWorkflow" for e in res["errors"])


def test_optionsfrom_source_not_a_slug_errors(tmp_path):
    page = {
        "route": "/articles/new",
        "root": {
            "type": "Select",
            "props": {
                "name": "authorId",
                "optionsFrom": {"source": "requesters", "value": "id", "label": "name"},
            },
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles/new.json": page}))
    assert not res["ok"]
    assert "options_source_unresolved" in _kinds(res)
    assert any(e["ref"] == "requesters" for e in res["errors"])


def test_table_rows_binding_with_no_datasource_errors(tmp_path):
    page = {
        "route": "/articles",
        "dataSources": [],
        "root": {"type": "Table", "props": {"rows": "{{foo}}", "columns": []}},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles.json": page}))
    assert not res["ok"]
    assert "binding_unresolved" in _kinds(res)
    assert any(e["ref"] == "foo" for e in res["errors"])


def test_freetext_input_to_uuid_column_errors(tmp_path):
    page = {
        "route": "/articles/new",
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateKnowledgeArticle"},
            "children": [
                {"type": "Input", "props": {"name": "title"}},
                {"type": "Input", "props": {"name": "authorId"}},  # uuid col via free text
            ],
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles/new.json": page}))
    assert not res["ok"]
    assert "type_incompatible" in _kinds(res)
    assert any(e["ref"] == "authorId" for e in res["errors"])


def test_select_optionsfrom_to_uuid_column_ok(tmp_path):
    page = {
        "route": "/articles/new",
        "dataSources": [{"name": "knowledgeArticles", "entity": "knowledgeArticles", "op": "list"}],
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateKnowledgeArticle"},
            "children": [
                {"type": "Input", "props": {"name": "title"}},
                {
                    "type": "Select",
                    "props": {
                        "name": "authorId",
                        "optionsFrom": {"source": "knowledgeArticles", "value": "id", "label": "title"},
                    },
                },
            ],
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles/new.json": page}))
    assert res["ok"], res["errors"]
    assert "type_incompatible" not in _kinds(res)


def test_all_valid_page_is_ok(tmp_path):
    list_page = {
        "route": "/articles",
        "dataSources": [{"name": "knowledgeArticles", "entity": "knowledgeArticles", "op": "list"}],
        "root": {
            "type": "Card",
            "children": [{"type": "Table", "props": {"rows": "{{knowledgeArticles}}", "columns": []}}],
        },
    }
    form_page = {
        "route": "/articles/new",
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateKnowledgeArticle"},
            "children": [
                {"type": "Input", "props": {"name": "title"}},
                {"type": "NumberInput", "props": {"name": "viewCount"}},
            ],
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={
        "articles.json": list_page, "articles/new.json": form_page,
    }))
    assert res["ok"], res["errors"]
    assert res["errors"] == []


def test_static_widget_is_warning_not_error(tmp_path):
    page = {
        "route": "/home",
        "root": {
            "type": "ActivityFeed",
            "props": {"items": [{"text": "Alice created a ticket"}, {"text": "Bob commented"}]},
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"home.json": page}))
    assert res["ok"], res["errors"]
    assert any(w["kind"] == "static_widget" for w in res["warnings"])


def test_event_only_workflow_button_without_record_context_errors(tmp_path):
    wf = {
        "id": "sla-breach-monitor",
        "name": "SlaBreachMonitor",
        "definition": {"trigger": {"type": "schedule"}, "nodes": []},
    }
    page = {
        "route": "/dashboard",
        "root": {
            "type": "Button",
            "props": {"label": "Run", "workflow": "SlaBreachMonitor"},
        },
    }
    out = _mkapp(tmp_path, pages={"dashboard.json": page},
                 workflows={"SlaBreachMonitor.json": wf})
    res = validate_bindings(out)
    assert not res["ok"]
    assert "event_only_button" in _kinds(res)


def test_event_only_workflow_button_in_detail_route_ok(tmp_path):
    wf = {
        "id": "escalate",
        "name": "Escalate",
        "definition": {"trigger": {"type": "db_change"}, "nodes": []},
    }
    # A `[id]` detail route supplies the record context → not flagged.
    page = {
        "route": "/tickets/[id]",
        "root": {"type": "Button", "props": {"label": "Escalate", "workflow": "Escalate"}},
    }
    out = _mkapp(tmp_path, pages={"tickets/[id].json": page},
                 workflows={"Escalate.json": wf})
    res = validate_bindings(out)
    assert "event_only_button" not in _kinds(res)


# ── broadened read-binding gate (Slice R3) ───────────────────────────────────

def test_chart_data_binding_with_no_datasource_errors(tmp_path):
    page = {
        "route": "/dashboard",
        "dataSources": [],
        "root": {
            "type": "Chart",
            "props": {"data": "{{foo}}", "series": [{"name": "x", "dataKey": "y"}]},
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"dashboard.json": page}))
    assert not res["ok"]
    assert "binding_unresolved" in _kinds(res)
    assert any(e["ref"] == "foo" for e in res["errors"])


def test_resource_timeline_resources_binding_with_no_datasource_errors(tmp_path):
    page = {
        "route": "/schedule",
        "dataSources": [],
        "root": {"type": "ResourceTimeline", "props": {"resources": "{{foo}}"}},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"schedule.json": page}))
    assert not res["ok"]
    assert "binding_unresolved" in _kinds(res)
    assert any(e["ref"] == "foo" for e in res["errors"])


def test_calendar_events_binding_with_no_datasource_errors(tmp_path):
    page = {
        "route": "/calendar",
        "dataSources": [],
        "root": {"type": "Calendar", "props": {"events": "{{foo}}"}},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"calendar.json": page}))
    assert not res["ok"]
    assert "binding_unresolved" in _kinds(res)
    assert any(e["ref"] == "foo" for e in res["errors"])


def test_timeline_entries_binding_with_no_datasource_errors(tmp_path):
    page = {
        "route": "/history",
        "dataSources": [],
        "root": {"type": "Timeline", "props": {"entries": "{{foo}}"}},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"history.json": page}))
    assert not res["ok"]
    assert "binding_unresolved" in _kinds(res)
    assert any(e["ref"] == "foo" for e in res["errors"])


def test_stat_value_dotted_binding_with_no_datasource_errors(tmp_path):
    page = {
        "route": "/dashboard",
        "dataSources": [],
        "root": {"type": "Stat", "props": {"label": "Open", "value": "{{foo.count}}"}},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"dashboard.json": page}))
    assert not res["ok"]
    assert "binding_unresolved" in _kinds(res)
    assert any(e["ref"] == "foo" for e in res["errors"])


def test_read_bindings_all_resolved_is_ok(tmp_path):
    page = {
        "route": "/dashboard",
        "dataSources": [
            {"name": "articles", "entity": "knowledgeArticles", "op": "list"},
            {"name": "byStatus", "entity": "knowledgeArticles", "op": "series"},
            {"name": "techs", "entity": "knowledgeArticles", "op": "list"},
            {"name": "events", "entity": "knowledgeArticles", "op": "list"},
            {"name": "entries", "entity": "knowledgeArticles", "op": "list"},
            {"name": "openCount", "entity": "knowledgeArticles", "op": "aggregate"},
        ],
        "root": {
            "type": "Stack",
            "children": [
                {"type": "Table", "props": {"rows": "{{articles}}", "columns": []}},
                {"type": "Chart", "props": {"data": "{{byStatus}}",
                                            "series": [{"name": "x", "dataKey": "value"}]}},
                {"type": "ResourceTimeline", "props": {"resources": "{{techs}}"}},
                {"type": "Calendar", "props": {"events": "{{events}}"}},
                {"type": "Timeline", "props": {"entries": "{{entries}}"}},
                {"type": "Stat", "props": {"label": "Open", "value": "{{openCount.count}}"}},
            ],
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"dashboard.json": page}))
    assert res["ok"], res["errors"]
    assert not any(e["kind"] == "binding_unresolved" for e in res["errors"])


def test_chart_series_config_not_flagged(tmp_path):
    # `series` is config ([{name,dataKey}]), never a binding — only `data` is.
    page = {
        "route": "/dashboard",
        "dataSources": [{"name": "byStatus", "entity": "knowledgeArticles", "op": "series"}],
        "root": {
            "type": "Chart",
            "props": {
                "data": "{{byStatus}}",
                "series": [{"name": "Series A", "dataKey": "value"}],
            },
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"dashboard.json": page}))
    assert res["ok"], res["errors"]
    assert not any(e["kind"] == "binding_unresolved" for e in res["errors"])


# ── real-app smoke ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug", ["wj83u270", "2hprmppl"])
def test_real_app_smoke(tmp_path, slug):
    src = os.path.join(os.path.dirname(__file__), "..", "..", "output", slug)
    if not os.path.isdir(src):
        pytest.skip(f"output/{slug} not present")
    dst = os.path.join(str(tmp_path), slug)
    shutil.copytree(src, dst)
    res = validate_bindings(dst)
    # Returns a well-formed dict without raising.
    assert set(res) == {"ok", "errors", "warnings"}
    assert isinstance(res["errors"], list)
    assert isinstance(res["warnings"], list)
    for e in res["errors"]:
        assert set(("file", "kind", "ref", "detail")).issubset(e)


def test_repeat_with_synonym_prop_instead_of_source_errors(tmp_path):
    # The renderer resolves ONLY node.bind / props.source (Repeat.tsx) — an
    # LLM-authored `items` prop silently renders an empty list.
    page = {
        "route": "/articles",
        "dataSources": [{"name": "knowledgeArticles", "source": "knowledgeArticles"}],
        "root": {"type": "Repeat", "props": {"items": "knowledgeArticles"},
                 "children": []},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles.json": page}))
    assert not res["ok"]
    errs = [e for e in res["errors"] if e["kind"] == "repeat_missing_source"]
    assert errs and "items" in errs[0]["detail"]


def test_repeat_unresolvable_source_errors(tmp_path):
    page = {
        "route": "/articles",
        "dataSources": [],
        "root": {"type": "Repeat", "props": {"source": "phantoms"}, "children": []},
    }
    res = validate_bindings(_mkapp(tmp_path, pages={"articles.json": page}))
    assert not res["ok"]
    assert any(e["kind"] == "binding_unresolved" and e["ref"] == "phantoms"
               for e in res["errors"])


def test_repeat_with_valid_source_or_bind_ok(tmp_path):
    pages = {
        "a.json": {
            "route": "/a",
            "dataSources": [{"name": "knowledgeArticles", "source": "knowledgeArticles"}],
            "root": {"type": "Repeat", "props": {"source": "knowledgeArticles"},
                     "children": []},
        },
        "b.json": {
            "route": "/b",
            "dataSources": [{"name": "knowledgeArticles", "source": "knowledgeArticles"}],
            "root": {"type": "Repeat", "bind": "knowledgeArticles", "props": {},
                     "children": []},
        },
    }
    res = validate_bindings(_mkapp(tmp_path, pages=pages))
    assert not [e for e in res["errors"]
                if e["kind"] in ("repeat_missing_source",)], res["errors"]
