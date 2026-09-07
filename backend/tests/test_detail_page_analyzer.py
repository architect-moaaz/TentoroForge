"""detail_page_analyzer — the missing signal that lets Smith reason about
"detail page not showing all information" asks on its own."""
from __future__ import annotations

import json
from pathlib import Path

from services.detail_page_analyzer import analyze_detail_pages, to_dict


def _write_schema(tmp_path: Path, rel: str, doc: dict) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_inbound_relation_gap_detected(tmp_path):
    """The canonical Drive-detail case: Application → Drive relation exists,
    detail page doesn't load Application, so we flag the gap."""
    entities = {
        "Drive": {"fks_out": [], "fks_in": [
            {"from_entity": "Application", "col": "driveId"},
        ]},
        "Application": {"fks_out": [
            {"col": "driveId", "target_entity": "Drive"},
        ], "fks_in": []},
    }
    _write_schema(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [{"name": "drive", "entity": "Drive", "op": "get"}],
        "root": {"type": "Text", "props": {"content": "{{drive.title}}"}},
    })
    pages = [{
        "route": "/drives/[id]",
        "path": "src/schemas/drives/[id].json",
        "archetype": "detail",
        "entity": "Drive",
    }]

    result = analyze_detail_pages(entities, pages, str(tmp_path))
    assert len(result) == 1
    dp = result[0]
    assert dp.entity == "Drive"
    kinds = [(g.kind, g.related_entity, g.related_via_column) for g in dp.gaps]
    assert ("inbound_relation", "Application", "driveId") in kinds


def test_inbound_relation_ignored_when_already_loaded(tmp_path):
    """When the schema already loads the related entity, that's not a
    gap — the LLM chose to include it, even if it renders it in a way
    we don't fully recognise."""
    entities = {
        "Drive": {"fks_out": [], "fks_in": [
            {"from_entity": "Application", "col": "driveId"},
        ]},
        "Application": {"fks_out": [], "fks_in": []},
    }
    _write_schema(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [
            {"name": "drive",        "entity": "Drive"},
            {"name": "applications", "entity": "Application", "op": "list"},
        ],
        "root": {"type": "Table", "props": {"dataSource": "applications"}},
    })
    pages = [{
        "route": "/drives/[id]", "path": "src/schemas/drives/[id].json",
        "archetype": "detail", "entity": "Drive",
    }]

    result = analyze_detail_pages(entities, pages, str(tmp_path))
    assert result[0].gaps == []


def test_fk_join_gap_detected(tmp_path):
    """`{{drive.recruiterId}}` is bound but the schema doesn't load User —
    the user sees a UUID instead of the recruiter's name."""
    entities = {
        "Drive": {"fks_out": [
            {"col": "recruiterId", "target_entity": "User"},
        ], "fks_in": []},
        "User": {"fks_out": [], "fks_in": []},
    }
    _write_schema(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [{"name": "drive", "entity": "Drive"}],
        "root": {"type": "Text", "props": {"content": "Recruiter: {{drive.recruiterId}}"}},
    })
    pages = [{
        "route": "/drives/[id]", "path": "src/schemas/drives/[id].json",
        "archetype": "detail", "entity": "Drive",
    }]

    result = analyze_detail_pages(entities, pages, str(tmp_path))
    gaps = result[0].gaps
    fk_gap = next((g for g in gaps if g.kind == "fk_join"), None)
    assert fk_gap is not None
    assert fk_gap.related_entity == "User"
    assert fk_gap.related_via_column == "recruiterId"


def test_fk_join_ignored_when_target_loaded(tmp_path):
    entities = {
        "Drive": {"fks_out": [
            {"col": "recruiterId", "target_entity": "User"},
        ], "fks_in": []},
        "User": {"fks_out": [], "fks_in": []},
    }
    _write_schema(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [
            {"name": "drive", "entity": "Drive"},
            {"name": "recruiter", "entity": "User"},
        ],
        "root": {"type": "Text", "props": {"content": "{{drive.recruiterId}}"}},
    })
    pages = [{
        "route": "/drives/[id]", "path": "src/schemas/drives/[id].json",
        "archetype": "detail", "entity": "Drive",
    }]
    result = analyze_detail_pages(entities, pages, str(tmp_path))
    assert not [g for g in result[0].gaps if g.kind == "fk_join"]


def test_non_detail_pages_not_analyzed(tmp_path):
    """Only ``archetype == 'detail'`` pages produce gaps. Lists,
    dashboards, forms are out of scope for this analysis."""
    entities = {
        "Drive": {"fks_out": [], "fks_in": [
            {"from_entity": "Application", "col": "driveId"},
        ]},
    }
    _write_schema(tmp_path, "src/schemas/drives.json", {
        "route": "/drives",
        "dataSources": [{"name": "drives", "entity": "Drive"}],
        "root": {"type": "Table"},
    })
    pages = [{
        "route": "/drives", "path": "src/schemas/drives.json",
        "archetype": "list", "entity": "Drive",
    }]
    result = analyze_detail_pages(entities, pages, str(tmp_path))
    assert result == []


def test_pages_without_entity_binding_skipped(tmp_path):
    """A detail-shaped route with no matched entity (dashboard-like page
    accidentally categorised as detail) is silently skipped, not
    flagged with confusing gaps."""
    entities = {}
    _write_schema(tmp_path, "src/schemas/[slug].json", {
        "route": "/[slug]",
        "dataSources": [],
        "root": {"type": "Text", "props": {"content": "generic"}},
    })
    pages = [{
        "route": "/[slug]", "path": "src/schemas/[slug].json",
        "archetype": "detail", "entity": None,
    }]
    assert analyze_detail_pages(entities, pages, str(tmp_path)) == []


def test_to_dict_serialization_shape():
    """The dataclasses turn into plain JSON-safe dicts, keyed for
    Smith's app-map consumption."""
    from services.detail_page_analyzer import DetailGap, DetailGaps
    payload = to_dict([DetailGaps(
        route="/drives/[id]",
        schema_path="src/schemas/drives/[id].json",
        entity="Drive",
        gaps=[DetailGap(
            kind="inbound_relation",
            related_entity="Application",
            related_via_column="driveId",
            suggested_component="Table",
            rationale="An Application table would be useful.",
        )],
    )])
    assert payload == [{
        "route": "/drives/[id]",
        "schema_path": "src/schemas/drives/[id].json",
        "entity": "Drive",
        "gaps": [{
            "kind": "inbound_relation",
            "related_entity": "Application",
            "related_via_column": "driveId",
            "suggested_component": "Table",
            "rationale": "An Application table would be useful.",
        }],
    }]
