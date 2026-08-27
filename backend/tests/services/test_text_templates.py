"""Tests for services.text_templates (B-021.2 root fix).

The pluralizer is the crux — the B-021.2 report was "No plant batchs yet."
which comes from LLM concatenation of "batch" + "s". Test every English
plural rule that could produce that class of bug.
"""

from __future__ import annotations

import pytest

from services.text_templates import (
    button_create,
    button_delete,
    button_edit,
    column_header,
    empty_state_text,
    entity_label,
    entity_label_plural,
    humanize,
    is_mechanical_key,
    pluralize,
    section_title,
)


# ---------- pluralize ------------------------------------------------------

class TestPluralize:
    # -ch, -sh, -x, -s, -ss, -z sibilants → -es
    @pytest.mark.parametrize("singular, expected", [
        ("batch", "batches"),      # THE B-021.2 case
        ("Batch", "Batches"),
        ("Plant", "Plants"),
        ("box",   "boxes"),
        ("bus",   "buses"),
        ("class", "classes"),
        ("dish",  "dishes"),
        ("church", "churches"),
        ("brush", "brushes"),
        ("quiz",  "quizes"),  # simple -z + es (acceptable; "quizzes" is doubled)
        ("Address", "Addresses"),
    ])
    def test_sibilants_take_es(self, singular, expected):
        assert pluralize(singular) == expected

    # consonant + -y → -ies
    @pytest.mark.parametrize("singular, expected", [
        ("city",     "cities"),
        ("City",     "Cities"),
        ("company",  "companies"),
        ("category", "categories"),
        ("property", "properties"),
        ("policy",   "policies"),
    ])
    def test_consonant_y_takes_ies(self, singular, expected):
        assert pluralize(singular) == expected

    # vowel + -y → just add -s (boy, day, key)
    @pytest.mark.parametrize("singular, expected", [
        ("boy", "boys"),
        ("day", "days"),
        ("key", "keys"),
    ])
    def test_vowel_y_stays_y(self, singular, expected):
        assert pluralize(singular) == expected

    # -f / -fe → -ves for the small English irregular set
    @pytest.mark.parametrize("singular, expected", [
        ("knife", "knives"),
        ("life",  "lives"),
        ("leaf",  "leaves"),
        ("wolf",  "wolves"),
        ("shelf", "shelves"),
    ])
    def test_fe_becomes_ves(self, singular, expected):
        assert pluralize(singular) == expected

    # Irregulars from the table
    @pytest.mark.parametrize("singular, expected", [
        ("child",  "children"),
        ("Child",  "Children"),
        ("person", "people"),
        ("man",    "men"),
        ("woman",  "women"),
        ("foot",   "feet"),
        ("mouse",  "mice"),
        ("datum",  "data"),
    ])
    def test_irregulars(self, singular, expected):
        assert pluralize(singular) == expected

    # Zero-plurals stay the same
    @pytest.mark.parametrize("word", ["sheep", "deer", "fish", "series", "data"])
    def test_zero_plurals(self, word):
        assert pluralize(word) == word

    # Default rule — just add -s
    @pytest.mark.parametrize("singular, expected", [
        ("Plant",   "Plants"),
        ("dog",     "dogs"),
        ("Product", "Products"),
    ])
    def test_default_appends_s(self, singular, expected):
        assert pluralize(singular) == expected

    def test_empty_string(self):
        assert pluralize("") == ""


# ---------- humanize -------------------------------------------------------

class TestHumanize:
    @pytest.mark.parametrize("raw, expected", [
        ("photoUrl",           "Photo URL"),
        ("nurseryLocationId",  "Nursery Location"),   # trailing Id dropped
        ("nursery_location_id", "Nursery Location"),
        ("firstName",          "First Name"),
        ("SKU",                "SKU"),                # acronym preserved
        ("apiKey",             "API Key"),
        ("plant_batch",        "Plant Batch"),
        ("id",                 "ID"),                 # bare id kept as acronym
    ])
    def test_humanize(self, raw, expected):
        assert humanize(raw) == expected


# ---------- entity labels --------------------------------------------------

class TestEntityLabels:
    def test_singular_label(self):
        assert entity_label("PlantBatch") == "Plant Batch"

    def test_plural_pluralises_last_word_only(self):
        assert entity_label_plural("PlantBatch") == "Plant Batches"
        assert entity_label_plural("Plant") == "Plants"
        assert entity_label_plural("Property") == "Properties"

    def test_the_b021_2_case(self):
        # Direct regression assertion for the exact bug reported.
        assert entity_label_plural("Batch") == "Batches"
        assert entity_label_plural("PlantBatch") == "Plant Batches"


# ---------- empty state text ----------------------------------------------

class TestEmptyState:
    def test_default_no_x_yet(self):
        assert empty_state_text("Plant") == "No plants yet."
        assert empty_state_text("Batch") == "No batches yet."       # regression
        assert empty_state_text("PlantBatch") == "No plant batches yet."
        assert empty_state_text("City") == "No cities yet."

    def test_with_filter_note(self):
        assert (
            empty_state_text("Order", filter_note="matching your filters")
            == "No orders matching your filters."
        )


# ---------- CRUD button labels --------------------------------------------

class TestButtons:
    def test_create(self):
        assert button_create("Plant") == "Create Plant"
        assert button_create("PlantBatch") == "Create Plant Batch"

    def test_edit(self):
        assert button_edit("Order") == "Edit Order"

    def test_delete(self):
        assert button_delete("Category") == "Delete Category"


# ---------- column headers ------------------------------------------------

class TestColumnHeader:
    @pytest.mark.parametrize("field, expected", [
        ("firstName",          "First Name"),
        ("photoUrl",           "Photo URL"),
        ("nursery_location_id","Nursery Location"),
        ("sku",                "SKU"),
    ])
    def test_column_header(self, field, expected):
        assert column_header(field) == expected


# ---------- section titles ------------------------------------------------

class TestSectionTitle:
    def test_known_sections(self):
        assert section_title("overview") == "Overview"
        assert section_title("recent")   == "Recent activity"
        assert section_title("stats")    == "Statistics"

    def test_unknown_section_returns_none(self):
        assert section_title("bespoke") is None


# ---------- is_mechanical_key ---------------------------------------------

class TestIsMechanical:
    def test_flags_empty_state_variants(self):
        assert is_mechanical_key("emptyStateText") is True
        assert is_mechanical_key("emptyState")     is True
        assert is_mechanical_key("empty_state")    is True

    def test_not_flags_description(self):
        # Description IS LLM-authored (needs domain judgement).
        assert is_mechanical_key("description") is False
        assert is_mechanical_key("helperText")  is False
