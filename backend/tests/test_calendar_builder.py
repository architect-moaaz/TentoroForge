"""Tests for the deterministic Calendar page builder (Task A-4).

Event mode reads `events` (a {{dataSource}} binding), NOT `bind` and NOT a bare
name. The builder binds `events` to the entity's list dataSource, sets `dateField`
to the entity's primary date column, `titleField` to the label field, and
`colorField` to the status column when present. Only Calendar.schema.ts event-mode
props are emitted.

Run: cd backend && /usr/local/bin/python3 -m pytest tests/test_calendar_builder.py -v
"""
from __future__ import annotations

from services.deterministic_pages import (
    build_calendar_page, build_crud_page, effective_archetype,
)


def _assessment_cols() -> dict:
    return {
        "id": {"type": "uuid", "primaryKey": True},
        "title": {"type": "varchar"},
        "scheduledAt": {"type": "timestamp"},
        "status": {"type": "varchar", "enum_values": ["scheduled", "completed", "cancelled"]},
        "candidateId": {"type": "uuid"},
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


# ── 1. root Stack{ Heading, Calendar } with correct EVENT-mode binding ────────
def test_build_calendar_page_basic():
    page = build_calendar_page("Assessment", _assessment_cols(), "/schedule")
    assert page["schemaVersion"] == "2"
    assert page["route"] == "/schedule"

    root = page["root"]
    assert root["type"] == "Stack"
    kinds = [c["type"] for c in root["children"]]
    assert kinds == ["Heading", "Calendar"]

    nodes = _nodes(page)
    assert not any(n["type"] in ("Table", "MetricTile") for n in nodes)

    cal = next(n for n in nodes if n["type"] == "Calendar")
    props = cal["props"]
    # EVENT mode: events is the {{listDataSource}} binding — not `bind`, not bare
    assert props["events"] == "{{assessments}}"
    assert "bind" not in props
    assert props["dateField"] == "scheduledAt"
    assert props["titleField"] == "title"
    assert props["colorField"] == "status"

    src = next(d for d in page["dataSources"] if d["op"] == "list")
    assert src["name"] == "assessments"
    assert src["entity"] == "Assessment"


# ── 2. date-field detection skips audit timestamps, prefers scheduling names ──
def test_date_field_detection():
    cols = {
        "id": {"type": "uuid", "primaryKey": True},
        "name": {"type": "varchar"},
        "createdAt": {"type": "timestamp"},   # system — never the event date
        "dueAt": {"type": "timestamp"},
        "updatedAt": {"type": "timestamp"},
    }
    page = build_calendar_page("Task", cols, "/calendar")
    cal = next(n for n in _nodes(page) if n["type"] == "Calendar")
    assert cal["props"]["dateField"] == "dueAt"


# ── 3. only valid Calendar.schema.ts props are emitted ───────────────────────
def test_only_valid_calendar_props():
    page = build_calendar_page("Assessment", _assessment_cols(), "/schedule")
    cal = next(n for n in _nodes(page) if n["type"] == "Calendar")
    allowed = {"events", "dateField", "endDateField", "titleField", "colorField",
               "eventHref", "emptyText", "view", "detailFields", "name", "value",
               "bind", "className", "style"}
    assert set(cal["props"]).issubset(allowed), set(cal["props"]) - allowed


# ── 4. effective_archetype + build_crud_page dispatch ─────────────────────────
def test_effective_archetype_calendar():
    assert effective_archetype("/schedule", "calendar", "calendar") == "calendar"


def test_build_crud_page_dispatches_calendar():
    page = build_crud_page("calendar", "Assessment", _assessment_cols(), "/schedule")
    assert page is not None
    cal = next(n for n in _nodes(page) if n["type"] == "Calendar")
    assert cal["props"]["events"] == "{{assessments}}"


# ── 5. schema_pipeline dispatch: a calendar page goes deterministic (no LLM) ───
def test_dispatch_calendar_is_deterministic(tmp_path):
    import json
    import os
    from services.schema_pipeline import _emit_deterministic_page

    output_dir = str(tmp_path)
    os.makedirs(os.path.join(output_dir, "src", "schemas"), exist_ok=True)
    registry = {"entities": {"Assessment": {"fields": _assessment_cols()}}}
    with open(os.path.join(output_dir, "registry.json"), "w", encoding="utf-8") as fh:
        json.dump(registry, fh)

    plan = {"entities": registry["entities"]}
    page = {"name": "Schedule", "route": "/assessments",
            "type": "calendar", "archetype": "calendar", "entity": "Assessment"}
    assert _emit_deterministic_page(output_dir, plan, page) is True

    written = os.path.join(output_dir, "src", "schemas", "assessments.json")
    assert os.path.exists(written)
    with open(written, encoding="utf-8") as fh:
        schema = json.load(fh)
    cal = next(n for n in _nodes(schema) if n["type"] == "Calendar")
    assert cal["props"]["events"] == "{{assessments}}"
    assert cal["props"]["dateField"] == "scheduledAt"
