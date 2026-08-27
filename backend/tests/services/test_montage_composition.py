"""The montage is a reference for LAYOUT, page composition and data richness.

Not colour. An earlier pass read the montage for palette/type/radius and fed
it to the design brief — wrong target, now unwired. Colour comes from the
design option the user picks at the research gate.

What a montage actually shows is shape: this kind of screen carries a stat
strip above the table, the table runs eight columns not three, the detail
page has a right rail, the cards carry a thumbnail and three meta lines. That
is the standard the generated app should meet, and it is exactly what the
maquette authors decide — so the reference belongs in their prompt.

Two boundaries make this safe:

* It must carry NO colour. Hexes are the design option's job, and a montage
  hex reaching the maquette would silently compete with the user's pick.
* It must name NO entities or columns. The pipeline owns what is on each
  page — the plan and registry decide that a screen is about Sessions and
  that `startTime` is a real column. The montage only says how MUCH and in
  what arrangement. A reference that named "Invoices" would push a domain
  the app does not have.

So the extractor is constrained to shape vocabulary and the renderer strips
anything that slipped through.
"""
from __future__ import annotations

import json

import pytest

from services.montage_composition import (
    extract_composition_reference,
    render_composition_block,
    MontageCompositionError,
)


def _llm(payload: str):
    """Stand-in for the vision call — these tests pin the contract, not the model."""
    def _call(*_a, **_kw):
        return payload
    return _call


_GOOD = json.dumps({
    "layout": "fixed left sidebar, wide fluid content column, no right rail",
    "screens": {
        "dashboard": {
            "regions": ["kpi strip of 4 tiles", "wide primary chart",
                        "two half-width secondary charts", "recent activity table"],
            "density": "dense — 4 KPIs above the fold, 2 charts, 10-row table",
        },
        "collection": {
            "regions": ["title with primary action", "filter chip row",
                        "table", "pagination"],
            "density": "7-8 columns per row including a status pill and a trailing menu",
        },
        "record": {
            "regions": ["header with 4 stat chips", "two-column body",
                        "right rail with metadata", "activity timeline"],
            "density": "12-16 fields split across two columns",
        },
    },
})


class TestItReadsShapeNotColour:
    def test_layout_survives(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_GOOD))
        assert "sidebar" in ref["layout"]

    def test_regions_are_captured_per_screen_kind(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_GOOD))
        assert "kpi strip of 4 tiles" in ref["screens"]["dashboard"]["regions"]
        assert any("filter" in r for r in ref["screens"]["collection"]["regions"])

    def test_density_is_captured(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_GOOD))
        assert "7-8 columns" in ref["screens"]["collection"]["density"]

    def test_the_rendered_block_reaches_the_prompt(self):
        block = render_composition_block(
            extract_composition_reference([{"type": "image"}], llm=_llm(_GOOD)))
        assert "REFERENCE COMPOSITION" in block
        assert "kpi strip of 4 tiles" in block
        assert "two-column body" in block


class TestColourNeverLeaksThrough:
    """Colour is the picked design option's job — a montage hex must not compete."""

    _WITH_HEX = json.dumps({
        "layout": "sidebar in #0B1220 with #FFFFFF content",
        "screens": {"collection": {"regions": ["table with #F1F5F9 row stripes"],
                                   "density": "6 columns"}},
    })

    def test_hexes_are_stripped_from_layout(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(self._WITH_HEX))
        assert "#0B1220" not in json.dumps(ref)
        assert "#FFFFFF" not in json.dumps(ref)

    def test_hexes_are_stripped_from_regions(self):
        block = render_composition_block(
            extract_composition_reference([{"type": "image"}], llm=_llm(self._WITH_HEX)))
        assert "#" not in block

    def test_the_surrounding_words_survive_the_strip(self):
        """Stripping colour must not destroy the shape description."""
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(self._WITH_HEX))
        assert "sidebar" in ref["layout"]
        assert any("row stripes" in r for r in ref["screens"]["collection"]["regions"])


class TestItNeverNamesTheDomain:
    """The pipeline decides WHAT is on a page; the montage only says how much."""

    _WITH_ENTITIES = json.dumps({
        "layout": "sidebar",
        "screens": {"collection": {
            "regions": ["Invoices table", "Customer filter chips"],
            "density": "6 columns: Invoice No, Customer, Amount, Due Date",
        }},
    })

    def test_the_block_warns_the_author_off_borrowed_nouns(self):
        block = render_composition_block(
            extract_composition_reference([{"type": "image"}], llm=_llm(self._WITH_ENTITIES)))
        # The instruction must be explicit, because the region strings
        # themselves may still carry a stray noun from the reference.
        assert "shape" in block.lower()
        assert "not" in block.lower()
        assert "entit" in block.lower() or "column" in block.lower()


class TestFailSoft:
    """A montage is optional. Nothing here may block or change a normal build."""

    def test_no_images_raises_a_typed_error_the_caller_swallows(self):
        with pytest.raises(MontageCompositionError):
            extract_composition_reference([], llm=_llm(_GOOD))

    def test_unparseable_response_raises_typed(self):
        with pytest.raises(MontageCompositionError):
            extract_composition_reference([{"type": "image"}], llm=_llm("not json"))

    def test_empty_reference_renders_to_nothing(self):
        assert render_composition_block({}) == ""
        assert render_composition_block(None) == ""

    def test_a_reference_with_no_screens_renders_to_nothing(self):
        assert render_composition_block({"layout": "sidebar", "screens": {}}) == ""

    def test_fenced_json_is_tolerated(self):
        ref = extract_composition_reference(
            [{"type": "image"}], llm=_llm(f"```json\n{_GOOD}\n```"))
        assert ref["screens"]["dashboard"]["regions"]


class TestBounded:
    def test_unknown_screen_kinds_are_dropped(self):
        payload = json.dumps({"layout": "x", "screens": {
            "dashboard": {"regions": ["a"], "density": "d"},
            "wizard": {"regions": ["b"], "density": "d"},
        }})
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(payload))
        assert set(ref["screens"]) == {"dashboard"}

    def test_region_lists_are_capped(self):
        payload = json.dumps({"layout": "x", "screens": {
            "dashboard": {"regions": [f"region {i}" for i in range(50)], "density": "d"}}})
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(payload))
        assert len(ref["screens"]["dashboard"]["regions"]) <= 8


# ── Typed picks ─────────────────────────────────────────────────────────────
# Prose alone can only override, never compose. "7-8 columns including a
# status pill" is unactionable: the maquette layer speaks in enums (5
# collection layouts, 5 hero kinds, 3 rhythms) and integers. So the montage
# must speak that language too, clamped to the vocabularies the maquette
# modules actually own — read from those modules, never re-declared here,
# because a second copy is a drift waiting to happen.

import json as _json

from services.montage_composition import (
    composition_targets,
    save_composition_reference,
)

_TYPED = _json.dumps({
    "layout": "fixed left sidebar, wide fluid content",
    "screens": {
        "dashboard": {
            "regions": ["kpi strip", "primary chart"],
            "density": "4 KPIs above the fold",
            "hero_kind": "kpi-strip", "rhythm": "tight",
            "kpis_target": 4, "sections_target": 5,
        },
        "collection": {
            "regions": ["title", "filter chips", "table"],
            "density": "7-8 columns including a status pill",
            "shape": "table", "columns_target": 8,
        },
        "record": {
            "regions": ["header with stat chips", "body"],
            "density": "12-16 fields",
            "hero_kind": "status-led", "sections_target": 4, "fields_target": 14,
        },
    },
})


class TestTypedPicksSurvive:
    def test_collection_shape_and_column_target(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_TYPED))
        col = ref["screens"]["collection"]
        assert col["shape"] == "table"
        assert col["columns_target"] == 8

    def test_dashboard_hero_rhythm_and_counts(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_TYPED))
        dash = ref["screens"]["dashboard"]
        assert dash["hero_kind"] == "kpi-strip"
        assert dash["rhythm"] == "tight"
        assert dash["kpis_target"] == 4

    def test_record_hero_and_field_target(self):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_TYPED))
        rec = ref["screens"]["record"]
        assert rec["hero_kind"] == "status-led"
        assert rec["fields_target"] == 14

    def test_targets_reach_the_prompt_as_an_explicit_bar(self):
        """A number the author can aim at — not a sentence it may paraphrase."""
        block = render_composition_block(
            extract_composition_reference([{"type": "image"}], llm=_llm(_TYPED)))
        assert "TARGET" in block
        assert "columns=8" in block


class TestPicksAreClampedToTheRealVocabularies:
    """The maquette modules own these lists; an off-list value must not reach
    a prompt telling the author to emit something the schema rejects."""

    def test_an_invented_collection_shape_is_dropped(self):
        payload = _json.dumps({"layout": "x", "screens": {"collection": {
            "regions": ["table"], "density": "d",
            "shape": "masonry-wall", "columns_target": 6}}})
        col = extract_composition_reference(
            [{"type": "image"}], llm=_llm(payload))["screens"]["collection"]
        assert "shape" not in col
        assert col["columns_target"] == 6      # the valid sibling survives

    def test_an_invented_hero_kind_is_dropped(self):
        payload = _json.dumps({"layout": "x", "screens": {"record": {
            "regions": ["header"], "density": "d", "hero_kind": "parallax-splash"}}})
        rec = extract_composition_reference(
            [{"type": "image"}], llm=_llm(payload))["screens"]["record"]
        assert "hero_kind" not in rec

    def test_a_hero_kind_from_the_wrong_screen_kind_is_dropped(self):
        """`kpi-strip` is a dashboard hero; a record must not borrow it."""
        payload = _json.dumps({"layout": "x", "screens": {"record": {
            "regions": ["header"], "density": "d", "hero_kind": "kpi-strip"}}})
        rec = extract_composition_reference(
            [{"type": "image"}], llm=_llm(payload))["screens"]["record"]
        assert "hero_kind" not in rec

    def test_counts_are_clamped_to_a_sane_range(self):
        payload = _json.dumps({"layout": "x", "screens": {"collection": {
            "regions": ["table"], "density": "d", "columns_target": 400}}})
        col = extract_composition_reference(
            [{"type": "image"}], llm=_llm(payload))["screens"]["collection"]
        assert col["columns_target"] <= 12

    def test_a_range_string_is_read_as_its_upper_bound(self):
        """Models write "7-8". The bar is the higher number, not the lower."""
        payload = _json.dumps({"layout": "x", "screens": {"collection": {
            "regions": ["table"], "density": "d", "columns_target": "7-8"}}})
        col = extract_composition_reference(
            [{"type": "image"}], llm=_llm(payload))["screens"]["collection"]
        assert col["columns_target"] == 8

    def test_junk_counts_are_dropped_not_defaulted(self):
        payload = _json.dumps({"layout": "x", "screens": {"collection": {
            "regions": ["table"], "density": "d", "columns_target": "lots"}}})
        col = extract_composition_reference(
            [{"type": "image"}], llm=_llm(payload))["screens"]["collection"]
        assert "columns_target" not in col


class TestTargetsAreReadableByAGate:
    """Density stops being a side effect only if something can check it."""

    def test_targets_round_trip_through_the_persisted_file(self, tmp_path):
        ref = extract_composition_reference([{"type": "image"}], llm=_llm(_TYPED))
        save_composition_reference(str(tmp_path), ref)
        assert composition_targets(str(tmp_path))["collection"]["columns_target"] == 8

    def test_no_montage_means_no_targets_rather_than_an_error(self, tmp_path):
        assert composition_targets(str(tmp_path)) == {}

    def test_prose_only_reference_yields_no_targets(self, tmp_path):
        save_composition_reference(str(tmp_path), _json.loads(_GOOD))
        assert composition_targets(str(tmp_path)) == {}
