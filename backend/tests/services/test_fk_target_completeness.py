"""Tests for services.fk_target_completeness (B-021.8 root fix)."""

from __future__ import annotations

import pytest

from services.fk_target_completeness import (
    ensure_fk_targets,
    missing_fk_targets,
)


# ---------- missing_fk_targets --------------------------------------------

class TestMissingFkTargets:
    def test_the_b021_8_case(self):
        """Plant references nurseryLocationId but NurseryLocation entity is
        never declared — the exact bug."""
        plan = {
            "entities": {
                "Plant": {"fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "nurseryLocationId", "type": "uuid"},
                ]},
            },
        }
        assert missing_fk_targets(plan) == ["NurseryLocation"]

    def test_snake_case_fk(self):
        plan = {
            "entities": {
                "Order": {"fields": [
                    {"name": "user_id", "type": "uuid"},
                ]},
            },
        }
        assert missing_fk_targets(plan) == ["User"]

    def test_nothing_missing_when_target_declared(self):
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "nurseryLocationId", "type": "uuid"}]},
                "NurseryLocation": {"fields": [{"name": "id", "type": "uuid"}]},
            },
        }
        assert missing_fk_targets(plan) == []

    def test_case_insensitive_match(self):
        """LLM emits `nurserylocation` (lowercase) as entity name — should
        still match the FK-inferred `NurseryLocation`."""
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "nurseryLocationId", "type": "uuid"}]},
                "nurserylocation": {"fields": [{"name": "id", "type": "uuid"}]},
            },
        }
        assert missing_fk_targets(plan) == []

    def test_non_fk_field_ignored(self):
        """A field named `emailId` for a message tracker isn't a real FK."""
        plan = {
            "entities": {
                "Message": {"fields": [
                    {"name": "emailId", "type": "varchar"},
                ]},
            },
        }
        # varchar → not an FK type → not treated as one.
        assert missing_fk_targets(plan) == []

    def test_scan_relations_edges_too(self):
        """`plan.relations[].to` referencing a missing entity is also a gap."""
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "id", "type": "uuid"}]},
            },
            "relations": [
                {"from": "Plant", "to": "Nursery"},
            ],
        }
        assert missing_fk_targets(plan) == ["Nursery"]

    def test_no_duplicates(self):
        """Two FKs pointing at the same missing target should only appear once."""
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "nurseryLocationId", "type": "uuid"}]},
                "Batch": {"fields": [{"name": "nursery_location_id", "type": "uuid"}]},
            },
        }
        assert missing_fk_targets(plan) == ["NurseryLocation"]


# ---------- ensure_fk_targets ---------------------------------------------

class TestEnsureFkTargets:
    def test_synthesizes_stub_for_missing_target(self):
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "nurseryLocationId", "type": "uuid"}]},
            },
        }
        r = ensure_fk_targets(plan)
        assert "NurseryLocation" in r["entities"]
        nl = r["entities"]["NurseryLocation"]
        assert nl["synthesized"] is True
        field_names = [f["name"] for f in nl["fields"]]
        assert "id" in field_names
        assert "name" in field_names

    def test_leaves_existing_entities_alone(self):
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "nurseryLocationId", "type": "uuid"}]},
                "NurseryLocation": {"fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "address", "type": "text"},
                ]},
            },
        }
        r = ensure_fk_targets(plan)
        assert r["entities"]["NurseryLocation"]["fields"] == [
            {"name": "id", "type": "uuid"},
            {"name": "address", "type": "text"},
        ]
        assert "synthesized" not in r["entities"]["NurseryLocation"]

    def test_idempotent(self):
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "nurseryLocationId", "type": "uuid"}]},
            },
        }
        r1 = ensure_fk_targets(plan)
        r2 = ensure_fk_targets(r1)
        # Only one NurseryLocation.
        assert list(r2["entities"].keys()).count("NurseryLocation") == 1

    def test_no_entities_no_op(self):
        assert ensure_fk_targets({}) == {}


# ---------- edge cases -----------------------------------------------------

class TestEdgeCases:
    def test_multi_word_fk_column(self):
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "plant_batch_id", "type": "uuid"}]},
            },
        }
        assert missing_fk_targets(plan) == ["PlantBatch"]

    def test_bare_id_column_not_treated_as_fk(self):
        """Primary key `id` shouldn't be treated as an FK to anything."""
        plan = {
            "entities": {
                "Plant": {"fields": [{"name": "id", "type": "uuid", "primaryKey": True}]},
            },
        }
        assert missing_fk_targets(plan) == []
