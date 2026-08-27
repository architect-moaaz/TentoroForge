"""Tests for services.section_split — SL2-4.

Pin the four contracts the collection composer relies on:

  - route → section list resolution (single-section = no split;
    2+ sections = split)
  - filter resolution drops columns the entity lacks
  - split emits N Cards + N dataSources + rebinds every ``{{ds_name}}``
    reference to the section-scoped clone
  - the shipped booking-platform vocabulary triggers a two-section
    split on /my-bookings and the section filters match the harvested
    booking-status enum values (confirmed / attended)
"""
from __future__ import annotations

import copy

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    load_vocabulary,
)
from services.section_split import (
    humanize_section_label,
    resolve_section_filter,
    resolve_sections,
    split_collection_into_sections,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _vocab(section_recipes=None, section_filters=None) -> ArchetypeVocabulary:
    return ArchetypeVocabulary(
        id="test",
        section_recipes=section_recipes or {},
        section_filters=section_filters or {},
    )


def _base_node(ds_name: str = "bookings") -> dict:
    """A minimal Repeat/Card collection node with two bindings."""
    return {
        "type": "Stack",
        "props": {"gap": "tokens.spacing.3"},
        "children": [{
            "type": "Repeat",
            "props": {"bind": "{{" + ds_name + "}}", "as": "item"},
            "children": [{
                "type": "Card",
                "props": {"href": "/bookings/{{item.id}}"},
                "children": [{
                    "type": "Heading",
                    "props": {"content": "{{item.className}}", "level": 4},
                }],
            }],
        }],
    }


def _base_ds(name: str = "bookings", entity: str = "bookings") -> dict:
    return {"name": name, "entity": entity, "op": "list"}


# ── humanize_section_label ───────────────────────────────────────────


class TestHumanizeSectionLabel:
    def test_single_word(self):
        assert humanize_section_label("upcoming") == "Upcoming"

    def test_hyphenated(self):
        assert humanize_section_label("my-bookings") == "My Bookings"

    def test_snake_case(self):
        assert humanize_section_label("top_instructors") == "Top Instructors"

    def test_mixed_separators(self):
        assert humanize_section_label("this-week_2") == "This Week 2"

    def test_empty_input(self):
        assert humanize_section_label("") == ""
        assert humanize_section_label(None) == ""  # type: ignore
        assert humanize_section_label("   ") == ""


# ── resolve_sections ─────────────────────────────────────────────────


class TestResolveSections:
    def test_none_vocab_returns_empty(self):
        assert resolve_sections(None, "/my-bookings") == []

    def test_vocab_without_recipes_returns_empty(self):
        v = ArchetypeVocabulary(id="test")  # section_recipes={}
        assert resolve_sections(v, "/my-bookings") == []

    def test_route_match_returns_ordered_sections(self):
        v = _vocab(section_recipes={"my-bookings": ["upcoming", "past"]})
        assert resolve_sections(v, "/my-bookings") == ["upcoming", "past"]

    def test_missing_route_returns_empty(self):
        v = _vocab(section_recipes={"my-bookings": ["upcoming", "past"]})
        assert resolve_sections(v, "/random-route") == []

    def test_bare_slug_lookup(self):
        v = _vocab(section_recipes={"my-bookings": ["upcoming", "past"]})
        assert resolve_sections(v, "my-bookings") == ["upcoming", "past"]

    def test_nested_route_matches_parent_slug(self):
        v = _vocab(section_recipes={"admin": ["current", "history"]})
        assert resolve_sections(v, "/admin/settings") == ["current", "history"]

    def test_blank_or_none_route_returns_empty(self):
        v = _vocab(section_recipes={"my-bookings": ["upcoming", "past"]})
        assert resolve_sections(v, None) == []
        assert resolve_sections(v, "") == []
        assert resolve_sections(v, "   ") == []

    def test_result_is_a_copy_not_the_recipe_list(self):
        # Mutating the returned list must not mutate the vocabulary.
        recipes = {"my-bookings": ["upcoming", "past"]}
        v = _vocab(section_recipes=recipes)
        out = resolve_sections(v, "/my-bookings")
        out.append("mutated")
        assert recipes["my-bookings"] == ["upcoming", "past"]

    def test_non_string_entries_dropped(self):
        v = _vocab(section_recipes={"x": ["a", "", None, 42, "b"]})  # type: ignore
        assert resolve_sections(v, "/x") == ["a", "b"]


# ── resolve_section_filter ───────────────────────────────────────────


class TestResolveSectionFilter:
    def test_none_vocab_returns_empty(self):
        assert resolve_section_filter(None, "upcoming", {"status": "text"}) == {}

    def test_empty_filter_dict_passes_through_as_empty(self):
        # Some vocabulary sections declare no filter (today, this-week
        # for now). Must return empty, not raise.
        v = _vocab(section_filters={"today": {}})
        assert resolve_section_filter(v, "today", {"status": "text"}) == {}

    def test_matching_column_returned(self):
        v = _vocab(section_filters={"upcoming": {"status": "confirmed"}})
        out = resolve_section_filter(v, "upcoming", {"status": "text"})
        assert out == {"status": "confirmed"}

    def test_missing_column_dropped(self):
        # Vocab names a column the entity doesn't carry — drop it.
        v = _vocab(section_filters={"upcoming": {"status": "confirmed"}})
        out = resolve_section_filter(v, "upcoming", {"otherCol": "text"})
        assert out == {}

    def test_column_match_is_case_insensitive(self):
        # Entity carries the column in a different case — still matches.
        v = _vocab(section_filters={"upcoming": {"status": "confirmed"}})
        out = resolve_section_filter(v, "upcoming", {"Status": "text"})
        assert out == {"status": "confirmed"}

    def test_unknown_section_returns_empty(self):
        v = _vocab(section_filters={"upcoming": {"status": "confirmed"}})
        assert resolve_section_filter(v, "past", {"status": "text"}) == {}

    def test_non_string_filter_values_dropped(self):
        v = _vocab(section_filters={"upcoming": {"status": None,  # type: ignore
                                                  "kind": "regular"}})
        out = resolve_section_filter(v, "upcoming",
                                     {"status": "text", "kind": "text"})
        assert out == {"kind": "regular"}


# ── split_collection_into_sections ───────────────────────────────────


class TestSplitCollectionIntoSections:
    def _setup(self):
        v = _vocab(
            section_recipes={"my-bookings": ["upcoming", "past"]},
            section_filters={
                "upcoming": {"status": "confirmed"},
                "past":     {"status": "attended"},
            },
        )
        return {
            "vocabulary": v,
            "base_node": _base_node("bookings"),
            "base_ds_name": "bookings",
            "base_data_sources": [_base_ds("bookings", "bookings")],
            "sections": ["upcoming", "past"],
            "entity_columns": {"status": "text", "className": "text",
                                "id": "uuid", "startAt": "timestamp"},
        }

    def test_empty_sections_returns_base_unchanged(self):
        args = self._setup()
        args["sections"] = []
        node, ds = split_collection_into_sections(**args)
        assert node is args["base_node"]
        assert ds is args["base_data_sources"]

    def test_two_sections_produce_two_cards(self):
        args = self._setup()
        node, ds = split_collection_into_sections(**args)
        assert node["type"] == "Stack"
        assert len(node["children"]) == 2
        for card in node["children"]:
            assert card["type"] == "Card"
        assert node["props"].get("data-signature-move") == "section-split"

    def test_each_card_carries_a_heading(self):
        args = self._setup()
        node, _ = split_collection_into_sections(**args)
        headings = []
        for card in node["children"]:
            stack = card["children"][0]
            heading = stack["children"][0]
            headings.append(heading["props"]["content"])
        assert headings == ["Upcoming", "Past"]

    def test_each_card_has_section_key_attr(self):
        args = self._setup()
        node, _ = split_collection_into_sections(**args)
        keys = [c["props"]["data-section-key"] for c in node["children"]]
        assert keys == ["upcoming", "past"]

    def test_data_sources_expanded_with_section_filter(self):
        args = self._setup()
        _, ds = split_collection_into_sections(**args)
        assert len(ds) == 2
        assert ds[0]["name"] == "bookings_upcoming"
        assert ds[0]["filter"] == {"status": "confirmed"}
        assert ds[0]["section"] == "upcoming"
        assert ds[1]["name"] == "bookings_past"
        assert ds[1]["filter"] == {"status": "attended"}
        assert ds[1]["section"] == "past"

    def test_bindings_rebound_per_section(self):
        args = self._setup()
        node, _ = split_collection_into_sections(**args)
        # First card's Repeat must bind to bookings_upcoming, second to
        # bookings_past — the composer replaces the placeholder in
        # every string prop on the cloned node.
        first_repeat = node["children"][0]["children"][0]["children"][1]["children"][0]
        second_repeat = node["children"][1]["children"][0]["children"][1]["children"][0]
        assert first_repeat["props"]["bind"] == "{{bookings_upcoming}}"
        assert second_repeat["props"]["bind"] == "{{bookings_past}}"

    def test_item_bindings_not_rewritten(self):
        # `{{item.className}}` is inside the Repeat template, bound to
        # the iteration variable — NOT the dataSource name. The
        # rebinder must not clobber it.
        args = self._setup()
        node, _ = split_collection_into_sections(**args)
        first_heading = (node["children"][0]["children"][0]
                          ["children"][1]["children"][0]["children"][0]
                          ["children"][0])
        assert first_heading["props"]["content"] == "{{item.className}}"

    def test_section_with_missing_filter_column_drops_filter(self):
        args = self._setup()
        args["entity_columns"] = {"className": "text", "id": "uuid"}
        _, ds = split_collection_into_sections(**args)
        # Both sections filter on `status` but the entity doesn't have
        # it — sections still emit as Cards, but their dataSources
        # carry no filter.
        assert ds[0].get("filter") in (None, {})
        assert ds[1].get("filter") in (None, {})

    def test_original_node_and_data_sources_untouched(self):
        args = self._setup()
        original_node_copy = copy.deepcopy(args["base_node"])
        original_ds_copy = copy.deepcopy(args["base_data_sources"])
        split_collection_into_sections(**args)
        assert args["base_node"] == original_node_copy
        assert args["base_data_sources"] == original_ds_copy

    def test_unexpected_multi_data_source_returns_base(self):
        # If the composer already emitted multiple dataSources (unusual
        # for a base collection), the split must bail rather than
        # produce ambiguous output.
        args = self._setup()
        args["base_data_sources"] = [_base_ds("bookings", "bookings"),
                                      _base_ds("extra", "extra")]
        node, ds = split_collection_into_sections(**args)
        assert node is args["base_node"]
        assert ds is args["base_data_sources"]


# ── Integration: booking-platform vocabulary produces splits ─────────


class TestBookingPlatformSplitIntegration:
    def _vocab(self):
        v = load_vocabulary("booking-platform")
        assert v is not None
        return v

    def test_my_bookings_route_resolves_two_sections(self):
        assert resolve_sections(self._vocab(), "/my-bookings") == \
            ["upcoming", "past"]

    def test_schedule_route_resolves_two_sections(self):
        assert resolve_sections(self._vocab(), "/schedule") == \
            ["today", "this-week"]

    def test_upcoming_filters_by_confirmed_status(self):
        out = resolve_section_filter(self._vocab(), "upcoming",
                                     {"status": "text"})
        assert out == {"status": "confirmed"}

    def test_past_filters_by_attended_status(self):
        out = resolve_section_filter(self._vocab(), "past",
                                     {"status": "text"})
        assert out == {"status": "attended"}

    def test_today_has_no_filter(self):
        # today/this-week are sub-headers with no server filter yet.
        # A follow-on runtime slice adds real date-range support.
        assert resolve_section_filter(self._vocab(), "today",
                                      {"startAt": "timestamp"}) == {}

    def test_my_bookings_end_to_end_split(self):
        v = self._vocab()
        base = _base_node("bookings")
        ds = [_base_ds("bookings", "bookings")]
        sections = resolve_sections(v, "/my-bookings")
        node, expanded_ds = split_collection_into_sections(
            base_node=base,
            base_ds_name="bookings",
            base_data_sources=ds,
            sections=sections,
            vocabulary=v,
            entity_columns={"status": "text", "className": "text",
                            "id": "uuid"},
        )
        assert len(node["children"]) == 2
        assert [c["props"]["data-section-key"] for c in node["children"]] == \
            ["upcoming", "past"]
        assert len(expanded_ds) == 2
        assert expanded_ds[0]["filter"] == {"status": "confirmed"}
        assert expanded_ds[1]["filter"] == {"status": "attended"}
