"""Tests for the deterministic Kanban page builder (Task A-2).

A kanban archetype page is built from the registry — never LLM-authored — so a
pipeline page can't silently become a Table. The Kanban node binds to the entity's
list dataSource, groups by the entity's status/stage column, and titles cards with
the entity's label field. Only props the Kanban.schema.ts contract accepts are emitted.

Run: cd backend && /usr/local/bin/python3 -m pytest tests/test_kanban_builder.py -v
"""
from __future__ import annotations

from services.deterministic_pages import (
    build_kanban_page, build_crud_page, effective_archetype,
)


def _application_cols() -> dict:
    return {
        "id": {"type": "uuid", "primaryKey": True},
        "candidateName": {"type": "varchar"},
        "status": {"type": "varchar", "enum_values": ["applied", "screening", "interview", "offer", "hired", "rejected"]},
        "jobOpeningId": {"type": "uuid"},
        "createdAt": {"type": "timestamp"},
    }


def _nodes(page: dict) -> list[dict]:
    out: list[dict] = []

    def walk(n):
        if isinstance(n, dict):
            if "type" in n:
                out.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(page.get("root"))
    return out


# ── 1. root has a Kanban bound to {{applications}} grouped by status, no Table ──
def test_build_kanban_page_basic():
    page = build_kanban_page("Application", _application_cols(), "/pipeline")
    assert page["schemaVersion"] == "2"
    assert page["route"] == "/pipeline"

    nodes = _nodes(page)
    assert not any(n["type"] == "Table" for n in nodes), "kanban page must not contain a Table"

    kanbans = [n for n in nodes if n["type"] == "Kanban"]
    assert len(kanbans) == 1
    props = kanbans[0]["props"]
    assert props["data"] == "{{applications}}"
    assert props["groupBy"] == "status"
    # card title is the entity's label field (best display column)
    assert props["cardTitle"] == "candidateName"

    # list dataSource emitted, named after the entity slug, op:list
    ds = page["dataSources"]
    src = next(d for d in ds if d["op"] == "list")
    assert src["name"] == "applications"
    assert src["entity"] == "Application"

    # enum values → columnOrder (nice-to-have, valid Kanban prop)
    assert props.get("columnOrder") == ["applied", "screening", "interview", "offer", "hired", "rejected"]


# ── 2. groupBy detection prefers an ENUM status over a plain named one ─────────
def test_groupby_prefers_enum_column():
    cols = {
        "id": {"type": "uuid", "primaryKey": True},
        "title": {"type": "varchar"},
        # a plain-text "state" AND an enum "stage" — the enum wins
        "state": {"type": "varchar"},
        "stage": {"type": "varchar", "enum_values": ["todo", "doing", "done"]},
    }
    page = build_kanban_page("Task", cols, "/board")
    kb = next(n for n in _nodes(page) if n["type"] == "Kanban")
    assert kb["props"]["groupBy"] == "stage"


# ── 3. only valid Kanban.schema.ts props are emitted ─────────────────────────
def test_only_valid_kanban_props():
    page = build_kanban_page("Application", _application_cols(), "/pipeline")
    kb = next(n for n in _nodes(page) if n["type"] == "Kanban")
    allowed = {"data", "groupBy", "columnOrder", "cardTitle", "cardDescription",
               "cardBadge", "cardFields", "cardHref", "emptyText", "columns",
               "bind", "className", "style"}
    assert set(kb["props"]).issubset(allowed), set(kb["props"]) - allowed


# ── 4. effective_archetype + build_crud_page dispatch ─────────────────────────
def test_effective_archetype_kanban():
    assert effective_archetype("/pipeline", "kanban", "kanban") == "kanban"


def test_build_crud_page_dispatches_kanban():
    page = build_crud_page("kanban", "Application", _application_cols(), "/pipeline")
    assert page is not None
    assert any(n["type"] == "Kanban" for n in _nodes(page))
    assert not any(n["type"] == "Table" for n in _nodes(page))


# ── 5. schema_pipeline dispatch: a kanban page goes deterministic (no LLM) ─────
def test_dispatch_kanban_is_deterministic(tmp_path):
    import json
    import os
    from services.schema_pipeline import _emit_deterministic_page

    output_dir = str(tmp_path)
    os.makedirs(os.path.join(output_dir, "src", "schemas"), exist_ok=True)
    registry = {"entities": {"Application": {"fields": _application_cols()}}}
    with open(os.path.join(output_dir, "registry.json"), "w", encoding="utf-8") as fh:
        json.dump(registry, fh)

    plan = {"entities": registry["entities"]}
    page = {"name": "Pipeline", "route": "/applications",
            "type": "kanban", "archetype": "kanban", "entity": "Application"}
    assert _emit_deterministic_page(output_dir, plan, page) is True

    written = os.path.join(output_dir, "src", "schemas", "applications.json")
    assert os.path.exists(written)
    with open(written, encoding="utf-8") as fh:
        schema = json.load(fh)
    nodes = _nodes(schema)
    kb = next(n for n in nodes if n["type"] == "Kanban")
    assert kb["props"]["data"] == "{{applications}}"
    assert kb["props"]["groupBy"] == "status"
    assert not any(n["type"] == "Table" for n in nodes)
