"""SMITH-SEARCH-1: single-call resource graph lookup.

The assistant traverses several files to build the "recruitment drive"
graph before acting. This tool collapses that traversal to one call so
Smith can do the same reasoning in one ReAct turn.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_find_resources import find_resources


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _make_ats(tmp_path: Path) -> None:
    """Minimal aviation-ATS layout: RecruitmentDrive + DriveAssignment
    entities, drive pages, drive workflows."""
    _write(tmp_path, "contracts/resource-registry.json", {
        "entities": {
            "RecruitmentDrive": {
                "id": "e_drive",
                "name": "RecruitmentDrive",
                "table": "recruitment_drives",
                "slug": "recruitment-drives",
                "camel": "recruitmentDrive",
                "columns": [
                    {"name": "id", "type": "uuid"},
                    {"name": "title", "type": "varchar"},
                    {"name": "createdByUserId", "type": "uuid", "fk": "e_user"},
                ],
            },
            "DriveAssignment": {
                "id": "e_da",
                "name": "DriveAssignment",
                "table": "drive_assignments",
                "slug": "drive-assignments",
                "camel": "driveAssignment",
                "columns": [
                    {"name": "id", "type": "uuid"},
                    {"name": "driveId", "type": "uuid", "fk": "e_drive"},
                ],
            },
            "User": {
                "id": "e_user",
                "name": "User",
                "table": "users",
                "slug": "users",
                "columns": [{"name": "id", "type": "uuid"}],
            },
        },
    })

    # Schemas: list, new, [id], [id]/edit — the standard 4 drive pages.
    _write(tmp_path, "src/schemas/drives.json", {
        "route": "/drives",
        "dataSources": [{"name": "drives", "entity": "RecruitmentDrive", "op": "list"}],
    })
    _write(tmp_path, "src/schemas/drives/new.json", {
        "route": "/drives/new",
        "dataSources": [{"name": "drive", "entity": "RecruitmentDrive"}],
    })
    _write(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [{"name": "recruitmentDrive", "entity": "RecruitmentDrive", "op": "get"}],
    })
    _write(tmp_path, "src/schemas/drives/[id]/edit.json", {
        "route": "/drives/[id]/edit",
        "dataSources": [{"name": "recruitmentDrive", "entity": "RecruitmentDrive", "op": "get"}],
    })

    # Workflows: 2 target RecruitmentDrive, 1 targets Assignment (should NOT show).
    _write(tmp_path, "workflows/CreateRecruitmentDrive.json", {
        "name": "CreateRecruitmentDrive",
        "definition": {"nodes": [
            {"data": {"config": {"actionType": "db_insert", "entity": "RecruitmentDrive"}}},
        ]},
    })
    _write(tmp_path, "workflows/UpdateRecruitmentDrive.json", {
        "name": "UpdateRecruitmentDrive",
        "definition": {"nodes": [
            {"data": {"config": {"actionType": "db_update", "table": "recruitment_drives"}}},
        ]},
    })
    _write(tmp_path, "workflows/CreateAssignment.json", {
        "name": "CreateAssignment",
        "definition": {"nodes": [
            {"data": {"config": {"actionType": "db_insert", "entity": "DriveAssignment"}}},
        ]},
    })


# --------------------------------------------------------------------------- #
# Match strategies
# --------------------------------------------------------------------------- #

def test_exact_pascal_name(tmp_path):
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "RecruitmentDrive")
    assert r["matched_entity"] == "RecruitmentDrive"
    assert r["confidence"] == "exact"


def test_exact_slug(tmp_path):
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "recruitment-drives")
    assert r["matched_entity"] == "RecruitmentDrive"
    assert r["confidence"] == "exact"


def test_exact_table(tmp_path):
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "recruitment_drives")
    assert r["matched_entity"] == "RecruitmentDrive"


def test_route_stem_match(tmp_path):
    """The user says "drives" — the URL segment — which is neither entity
    name nor table. Match via schemas' dataSource.entity."""
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "drives")
    assert r["matched_entity"] == "RecruitmentDrive"
    assert r["confidence"] == "route-stem"


def test_fuzzy_english_phrase(tmp_path):
    """Plain-English "recruitment drive" (two words, lower case)."""
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "recruitment drive")
    assert r["matched_entity"] == "RecruitmentDrive"
    # This is exact once tokens canonicalize.
    assert r["confidence"] in ("exact", "fuzzy")


def test_unknown_returns_none(tmp_path):
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "spaceship")
    assert r["matched_entity"] is None if "matched_entity" in r else r["matched"] is None


# --------------------------------------------------------------------------- #
# Graph slice contents
# --------------------------------------------------------------------------- #

def test_pages_include_all_four_kinds(tmp_path):
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "RecruitmentDrive")
    kinds = {p["kind"] for p in r["pages"]}
    assert kinds >= {"list", "create", "detail", "edit"}
    routes = {p["route"] for p in r["pages"]}
    assert routes >= {"/drives", "/drives/new", "/drives/[id]", "/drives/[id]/edit"}


def test_workflows_only_matching_entity(tmp_path):
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "RecruitmentDrive")
    names = {w["name"] for w in r["workflows"]}
    assert names == {"CreateRecruitmentDrive", "UpdateRecruitmentDrive"}
    assert "CreateAssignment" not in names, "workflow targeting another entity leaked in"


def test_fks_out_includes_user_target(tmp_path):
    """RecruitmentDrive.createdByUserId → e_user is an OUT-fk (dependency)."""
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "RecruitmentDrive")
    cols = {f["column"] for f in r["fks_out"]}
    assert "createdByUserId" in cols


def test_fks_in_lists_dependent_entities(tmp_path):
    """DriveAssignment.driveId → RecruitmentDrive is an IN-fk (dependent).
    This is what Smith needs to know before deleting a drive."""
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "RecruitmentDrive")
    sources = {f["from"] for f in r["fks_in"]}
    assert "DriveAssignment.driveId" in sources


def test_hint_is_one_line_summary(tmp_path):
    """The hint compresses the graph into a single line Smith can inline
    in its response — enumerates counts + dependents."""
    _make_ats(tmp_path)
    r = find_resources(str(tmp_path), "RecruitmentDrive")
    hint = r["hint"]
    assert "RecruitmentDrive" in hint
    assert "page" in hint
    assert "workflow" in hint
    assert "DriveAssignment" in hint  # names the dependent


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #

def test_empty_query_returns_none(tmp_path):
    _make_ats(tmp_path)
    assert find_resources(str(tmp_path), "")["matched"] is None
    assert find_resources(str(tmp_path), "   ")["matched"] is None


def test_missing_registry_returns_none_without_raising(tmp_path):
    # No files at all — should not raise.
    r = find_resources(str(tmp_path), "anything")
    assert r["matched"] is None
