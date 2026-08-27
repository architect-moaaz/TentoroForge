"""Tests for services.plan_canonicalizer — one spelling at ingestion.

The pipeline's tolerance code (plan_field_lookup's dual-shape readers,
guards that re-derive names) exists because plan.json is written in
whatever shape the planner/LLM produced. The canonicalizer normalizes
ONCE at the persist seam so every downstream reader sees one shape.
"""
from __future__ import annotations

import copy

from services.plan_canonicalizer import canonicalize_plan


def _plan(**over) -> dict:
    base = {
        "name": "Doc Intel",
        "data_models": [
            {
                "name": "Document",
                "table": "documents",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "status", "type": "text",
                     "semantic": {"enum_values": ["queued", "done"]}},
                ],
            },
        ],
    }
    base.update(over)
    return base


# ── semantic.enum_values hoist ──────────────────────────────────────

def test_hoists_semantic_enum_values_to_top_level():
    plan, report = canonicalize_plan(_plan())
    f = plan["data_models"][0]["fields"][1]
    assert f["enum_values"] == ["queued", "done"]
    assert report["summary"]["enum_hoisted"] == 1


def test_top_level_enum_values_win_over_semantic():
    p = _plan()
    p["data_models"][0]["fields"][1]["enum_values"] = ["a", "b"]
    plan, report = canonicalize_plan(p)
    assert plan["data_models"][0]["fields"][1]["enum_values"] == ["a", "b"]
    assert report["summary"]["enum_hoisted"] == 0


# ── container-spelling normalization ────────────────────────────────

def test_data_models_camel_spelling_folded_in():
    p = {"dataModels": [{"name": "Invoice", "fields": []}]}
    plan, _ = canonicalize_plan(p)
    assert "dataModels" not in plan
    assert plan["data_models"][0]["name"] == "Invoice"


def test_columns_renamed_to_fields():
    p = {"data_models": [{"name": "Invoice",
                          "columns": [{"name": "total", "type": "numeric"}]}]}
    plan, report = canonicalize_plan(p)
    ent = plan["data_models"][0]
    assert ent["fields"][0]["name"] == "total"
    assert "columns" not in ent
    assert report["summary"]["containers_renamed"] == 1


def test_field_column_key_gets_name():
    p = {"data_models": [{"name": "Invoice",
                          "fields": [{"column": "due_date", "type": "date"}]}]}
    plan, _ = canonicalize_plan(p)
    assert plan["data_models"][0]["fields"][0]["name"] == "due_date"


# ── entity dedup + cross-container consistency ──────────────────────

def test_duplicate_data_models_merged():
    p = {"data_models": [
        {"name": "Document", "fields": [{"name": "id", "type": "uuid"}]},
        {"name": "document", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "status", "type": "text", "enum_values": ["a"]},
        ]},
    ]}
    plan, report = canonicalize_plan(p)
    assert len(plan["data_models"]) == 1
    names = {f["name"] for f in plan["data_models"][0]["fields"]}
    assert names == {"id", "status"}
    assert report["summary"]["entities_deduped"] == 1


def test_entities_dict_and_data_models_agree():
    """Metadata declared on only ONE copy becomes visible on both —
    the _unique_enum_entity double-hit class."""
    p = _plan(entities={
        "Document": {"table": "documents", "fields": [
            {"name": "status", "type": "text"},
        ]},
    })
    plan, _ = canonicalize_plan(p)
    dict_side = plan["entities"]["Document"]["fields"]
    status = next(f for f in dict_side if f["name"] == "status")
    assert status["enum_values"] == ["queued", "done"]


def test_entities_only_field_backfilled_into_data_models():
    p = _plan(entities={
        "Document": {"table": "documents", "fields": [
            {"name": "ownerId", "type": "uuid", "fk": {"table": "users"}},
        ]},
    })
    plan, _ = canonicalize_plan(p)
    dm_fields = {f["name"]: f for f in plan["data_models"][0]["fields"]}
    assert dm_fields["ownerId"]["fk"] == {"table": "users"}


# ── safety ──────────────────────────────────────────────────────────

def test_idempotent():
    once, _ = canonicalize_plan(_plan(entities={
        "Document": {"table": "documents", "fields": [
            {"name": "status", "type": "text"}]},
    }))
    twice, report2 = canonicalize_plan(copy.deepcopy(once))
    assert twice == once
    assert report2["summary"]["enum_hoisted"] == 0
    assert report2["summary"]["entities_deduped"] == 0


def test_input_not_mutated():
    p = _plan()
    snapshot = copy.deepcopy(p)
    canonicalize_plan(p)
    assert p == snapshot


def test_garbage_shapes_no_crash():
    for junk in (None, [], "x", {"data_models": "nope"},
                 {"entities": [1, 2]}, {"data_models": [None, "x"]}):
        plan, _ = canonicalize_plan(junk)  # type: ignore[arg-type]
        assert isinstance(plan, dict) or plan == junk
