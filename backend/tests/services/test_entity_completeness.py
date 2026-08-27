"""Tests for services.entity_completeness (B-021.7 root fix).

The heuristic adds a photoUrl field to entities that plainly need media.
Test the trigger conditions AND the safety rails (existing fields untouched,
irrelevant entities untouched, idempotent).
"""

from __future__ import annotations

import pytest

from services.entity_completeness import (
    MEDIA_BEARING_ENTITY_NAMES,
    ensure_media_fields,
    entity_needs_media,
)


# ---------- entity_needs_media ---------------------------------------------

class TestEntityNeedsMedia:
    def test_true_for_canonical_product_name(self):
        assert entity_needs_media("Plant", {"fields": []}) is True
        assert entity_needs_media("Product", {"fields": []}) is True
        assert entity_needs_media("Recipe", {"fields": []}) is True

    def test_true_for_commerce_entity(self):
        assert entity_needs_media("Widget", {"fields": []}, is_commerce=True) is True

    def test_true_for_brief_forces_media(self):
        assert entity_needs_media("Widget", {"fields": []}, brief_forces_media=True) is True

    def test_false_when_media_field_already_exists(self):
        spec = {"fields": [{"name": "imageUrl"}]}
        assert entity_needs_media("Plant", spec) is False

    def test_false_for_semantic_type_media(self):
        spec = {"fields": [{"name": "primary_asset", "semantic_type": "media"}]}
        assert entity_needs_media("Plant", spec) is False

    def test_false_for_admin_entities(self):
        # User isn't in the catalog by default.
        assert entity_needs_media("User", {"fields": []}) is False
        assert entity_needs_media("Role", {"fields": []}) is False


# ---------- ensure_media_fields --------------------------------------------

class TestEnsureMediaFields:
    def test_adds_photourl_to_plant(self):
        plan = {
            "entities": {"Plant": {"fields": [{"name": "name"}]}},
        }
        r = ensure_media_fields(plan)
        names = [f["name"] for f in r["entities"]["Plant"]["fields"]]
        assert "photoUrl" in names

    def test_multi_entity_only_hits_media_bearing(self):
        plan = {
            "entities": {
                "Plant":   {"fields": [{"name": "name"}]},
                "Batch":   {"fields": [{"name": "lot"}]},
                "Recipe":  {"fields": [{"name": "title"}]},
            },
        }
        r = ensure_media_fields(plan)
        plant_names = [f["name"] for f in r["entities"]["Plant"]["fields"]]
        batch_names = [f["name"] for f in r["entities"]["Batch"]["fields"]]
        recipe_names = [f["name"] for f in r["entities"]["Recipe"]["fields"]]
        assert "photoUrl" in plant_names
        assert "photoUrl" not in batch_names   # Batch isn't in the media list
        assert "photoUrl" in recipe_names

    def test_commerce_flag_triggers_media(self):
        plan = {
            "entities": {
                "Widget": {"commerce": True, "fields": [{"name": "name"}]},
            },
        }
        r = ensure_media_fields(plan)
        names = [f["name"] for f in r["entities"]["Widget"]["fields"]]
        assert "photoUrl" in names

    def test_brief_photos_forces_media_on_any_entity(self):
        plan = {
            "brief": "An app where users can upload photos of their listings",
            "entities": {
                "Listing": {"fields": [{"name": "title"}]},
            },
        }
        r = ensure_media_fields(plan)
        names = [f["name"] for f in r["entities"]["Listing"]["fields"]]
        assert "photoUrl" in names

    def test_existing_image_field_prevents_addition(self):
        plan = {
            "entities": {
                "Plant": {"fields": [
                    {"name": "name"},
                    {"name": "imageUrl"},
                ]},
            },
        }
        r = ensure_media_fields(plan)
        photo_urls = [f for f in r["entities"]["Plant"]["fields"] if f["name"] == "photoUrl"]
        assert photo_urls == []   # no duplicate media field

    def test_idempotent(self):
        plan = {"entities": {"Plant": {"fields": [{"name": "name"}]}}}
        r1 = ensure_media_fields(plan)
        r2 = ensure_media_fields(r1)
        photo_count = sum(1 for f in r2["entities"]["Plant"]["fields"] if f["name"] == "photoUrl")
        assert photo_count == 1

    def test_no_entities_no_op(self):
        assert ensure_media_fields({"brief": "sell photos"}) == {"brief": "sell photos"}

    def test_photourl_has_correct_shape(self):
        plan = {"entities": {"Plant": {"fields": []}}}
        r = ensure_media_fields(plan)
        photo = next(f for f in r["entities"]["Plant"]["fields"] if f["name"] == "photoUrl")
        assert photo["type"] == "varchar"
        assert photo.get("semantic_type") == "media"
        assert photo.get("not_null") is False   # media is optional by default


# ---------- catalog sanity -------------------------------------------------

class TestCatalog:
    def test_uat_entities_covered(self):
        assert "plant" in MEDIA_BEARING_ENTITY_NAMES

    def test_all_lowercase(self):
        for name in MEDIA_BEARING_ENTITY_NAMES:
            assert name == name.lower()
