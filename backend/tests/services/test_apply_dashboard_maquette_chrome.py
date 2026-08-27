"""Tests for Slice C composer emission — the chrome nodes prepended
to the dashboard page schema (subtitle Text + filter-bar Cluster of
Selects + reset chip).

These are pure structural tests against ``_build_sections`` — no
schema-page rendering, no dataSource wiring. The Slice-C contract is:
"if the maquette declared X, the composer emits Y at position 0 of
sections."
"""
from __future__ import annotations

from services.apply_dashboard_maquette import _build_sections


class TestSubtitleEmission:
    def test_subtitle_emits_text_node_at_top(self):
        sections, _ = _build_sections({
            "subtitle": "Evaluating batch processing across archivists",
        })
        assert len(sections) >= 1
        first = sections[0]
        assert first["type"] == "Text"
        assert first["props"]["content"] == (
            "Evaluating batch processing across archivists"
        )

    def test_subtitle_uses_muted_variant(self):
        # Editorial subtitle reads as body prose beneath the H1, not
        # another heading. Muted styling keeps it from competing.
        sections, _ = _build_sections({"subtitle": "Ops overview"})
        first = sections[0]
        assert first["props"]["variant"] == "muted"

    def test_no_subtitle_no_text_node(self):
        sections, _ = _build_sections({})
        # First non-chrome section should be something else (or absent)
        # — but definitely not a stray Text node.
        assert not sections or sections[0]["type"] != "Text" \
            or "muted" not in (sections[0].get("props") or {}).get("variant", "")


class TestFilterBarEmission:
    def test_single_select_filter_becomes_filter_bar_chip(self):
        # A select filter MUST become a FilterBar chip, not a bare Select.
        # renderSchemaPage builds its allowed-filter set from FilterBar chip
        # keys; a Select declares nothing, so its value was never applied.
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["queued", "processing", "complete"]},
            ],
        })
        clusters = [s for s in sections if s.get("type") == "Cluster"]
        assert len(clusters) == 1
        bars = [c for c in clusters[0].get("children", [])
                if c.get("type") == "FilterBar"]
        assert len(bars) == 1
        chips = bars[0]["props"]["chips"]
        assert len(chips) == 1
        assert chips[0]["key"] == "status"
        assert chips[0]["label"] == "Status"
        # FilterBar renders its own "Any" cleared state, so no placeholder
        # option is synthesised — only the real enum values.
        assert [o["value"] for o in chips[0]["options"]] == [
            "queued", "processing", "complete",
        ]

    def test_date_range_filter_becomes_date_range_picker(self):
        sections, _ = _build_sections({
            "filters": [
                {"kind": "date-range", "field": "createdAt", "label": "Date"},
            ],
        })
        cluster = next(s for s in sections if s.get("type") == "Cluster")
        picker = cluster["children"][0]
        assert picker["type"] == "DateRangePicker"
        assert picker["props"]["name"] == "createdAt"

    def test_text_filter_turns_on_filter_bar_search(self):
        # Free text rides FilterBar's own search box (bound to "q") rather
        # than a bare Input nothing reads.
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["open", "closed"]},
                {"kind": "text", "field": "search", "label": "Search"},
            ],
        })
        cluster = next(s for s in sections if s.get("type") == "Cluster")
        bar = cluster["children"][0]
        assert bar["type"] == "FilterBar"
        assert bar["props"]["showSearch"] is True

    def test_text_filter_alone_emits_no_bar(self):
        # FilterBarNode requires >= 1 chip, so a search-only bar is not
        # expressible; and "q" is excluded from dataSource narrowing anyway,
        # so emitting one would be another chip that filters nothing.
        sections, _ = _build_sections({
            "filters": [
                {"kind": "text", "field": "search", "label": "Search"},
            ],
        })
        assert not any(s.get("type") == "Cluster" for s in sections)

    def test_multiple_filters_emit_in_order(self):
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "risk", "label": "Loan Risk",
                 "options": ["low", "high"]},
                {"kind": "select", "field": "brand", "label": "Card Brand",
                 "options": ["visa", "amex"]},
                {"kind": "date-range", "field": "createdAt", "label": "Date"},
            ],
        })
        cluster = next(s for s in sections if s.get("type") == "Cluster")
        # FilterBar leads (carrying both selects, in order), pickers follow.
        assert cluster["children"][0]["type"] == "FilterBar"
        assert [c["key"] for c in cluster["children"][0]["props"]["chips"]] == [
            "risk", "brand",
        ]
        assert cluster["children"][1]["type"] == "DateRangePicker"
        assert cluster["children"][1]["props"]["name"] == "createdAt"

    def test_filter_key_is_declared_so_the_page_honours_it(self):
        # The page applies a URL param ONLY if the schema declares it
        # filterable, and FilterBar chip keys are that declaration. This
        # replaces the old `data-dashboard-filter` attribute, which nothing
        # in the renderer, library or template ever read.
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["open", "closed"]},
            ],
        })
        cluster = next(s for s in sections if s.get("type") == "Cluster")
        bar = cluster["children"][0]
        assert bar["type"] == "FilterBar"
        assert [c["key"] for c in bar["props"]["chips"]] == ["status"]

    def test_select_without_options_is_dropped(self):
        # FilterChip requires >= 1 option. A chip with none can only offer
        # "Any" — it filters nothing — so it must not be emitted at all
        # rather than shipped as a node the renderer rejects.
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status"},
            ],
        })
        assert not any(
            s.get("type") == "Cluster"
            and any(c.get("type") == "FilterBar" for c in s.get("children", []))
            for s in sections
        )

    def test_no_filters_no_cluster(self):
        sections, _ = _build_sections({})
        assert not any(
            s.get("type") == "Cluster"
            and any(c.get("type") == "FilterBar" for c in s.get("children", []))
            for s in sections
        )


class TestResetChip:
    def test_reset_true_adds_reset_button_to_filter_bar(self):
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["open", "closed"]},
            ],
            "reset_filters": True,
        })
        cluster = next(s for s in sections if s.get("type") == "Cluster")
        buttons = [c for c in cluster["children"] if c.get("type") == "Button"]
        assert len(buttons) == 1
        b = buttons[0]
        assert "Reset" in b["props"]["label"]
        # A real, editor-toggleable behaviour — the library Button clears the
        # query string and fires forge:urlstate. The old `data-reset-filters`
        # attribute was implemented nowhere, so the chip did nothing.
        assert b["props"]["clearsFilters"] is True

    def test_reset_true_without_filters_still_no_bar(self):
        # A Reset chip with nothing to reset is confusing UX; skip it
        # unless there's at least one filter to accompany.
        sections, _ = _build_sections({"reset_filters": True})
        clusters = [s for s in sections if s.get("type") == "Cluster"]
        assert clusters == []

    def test_reset_false_no_button(self):
        sections, _ = _build_sections({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["open", "closed"]},
            ],
            "reset_filters": False,
        })
        cluster = next(s for s in sections if s.get("type") == "Cluster")
        buttons = [c for c in cluster["children"] if c.get("type") == "Button"]
        assert buttons == []


class TestChromePosition:
    def test_chrome_precedes_ornament_and_hero(self):
        # The chrome must be the FIRST thing on the page — otherwise a
        # decorative flourish or a hero photo will float above the
        # editorial header and break the reading order.
        sections, _ = _build_sections({
            "subtitle": "S",
            "filters": [{"kind": "select", "field": "x", "label": "X",
                              "options": ["a"]}],
            "ornament": {"kind": "eyebrow-line", "placement": "before-hero"},
            "hero": {"kind": "personalised-greeting", "greeting": "Welcome"},
        })
        # Sections start with: subtitle Text → filter Cluster → ornament → hero
        types = [s.get("type") for s in sections]
        assert types[:2] == ["Text", "Cluster"]

    def test_empty_maquette_yields_no_chrome_sections(self):
        # Backwards-safe: a maquette with no chrome fields must not
        # inject any Text/Cluster nodes.
        sections, _ = _build_sections({})
        # No Text node from chrome — future non-chrome sections may add
        # their own; check specifically for the muted subtitle marker.
        subtitle_texts = [
            s for s in sections
            if s.get("type") == "Text"
            and (s.get("props") or {}).get("variant") == "muted"
        ]
        assert subtitle_texts == []
        # No filter-bar Cluster either.
        filter_clusters = [
            s for s in sections
            if s.get("type") == "Cluster"
            and any(c.get("type") == "FilterBar" for c in s.get("children", []))
        ]
        assert filter_clusters == []
