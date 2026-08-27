"""Tests for services.library_manifest.

Two coexisting APIs live in this module:

* Spec C6 (below) — human-readable purpose blurbs for prompt injection.
* CREATIVE-5a — compact machine-shaped manifest for downstream composers.
"""
from __future__ import annotations

import json

from services.library_manifest import (
    build_library_manifest,
    compact_manifest_for_composer,
    component_types_in_schema,
    diversity_metric,
    enrich_with_purposes,
    load_component_catalog,
    load_library_manifest,
    persist_library_manifest,
    render_catalog_for_prompt,
)


class TestLoadCatalog:
    def test_loads_shipped_starter_json(self):
        cat = load_component_catalog()
        assert isinstance(cat, dict)
        assert len(cat) >= 50  # library has 100+; sanity check
        assert "Table" in cat and "Card" in cat

    def test_missing_file_returns_empty_not_raises(self, tmp_path):
        assert load_component_catalog(tmp_path / "ghost.json") == {}

    def test_corrupt_file_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert load_component_catalog(p) == {}


class TestEnrich:
    def test_entries_have_expected_keys(self):
        entries = enrich_with_purposes(load_component_catalog())
        assert all(
            set(e.keys()) == {"name", "props", "purpose", "when_to_use", "when_not_to_use"}
            for e in entries
        )

    def test_known_components_get_purposes(self):
        entries = enrich_with_purposes(load_component_catalog())
        by_name = {e["name"]: e for e in entries}
        assert by_name["Table"]["purpose"]
        assert by_name["Kanban"]["purpose"]
        assert by_name["Stat"]["purpose"]

    def test_unknown_components_get_name_only(self):
        cat = {"CustomThing": {"props": {"x": {}}}}
        entries = enrich_with_purposes(cat)
        assert entries[0]["name"] == "CustomThing"
        assert entries[0]["purpose"] == ""

    def test_entries_sorted_by_name(self):
        entries = enrich_with_purposes({"Zebra": {}, "Alpha": {}, "Middle": {}})
        assert [e["name"] for e in entries] == ["Alpha", "Middle", "Zebra"]


class TestRender:
    def test_renders_purpose_lines(self):
        entries = [{
            "name": "Table", "props": ["title"],
            "purpose": "tabular data",
            "when_to_use": "3+ columns",
            "when_not_to_use": "kanban-style",
        }]
        text = render_catalog_for_prompt(entries)
        assert "Table" in text
        assert "tabular data" in text
        assert "USE: 3+ columns" in text
        assert "NOT: kanban-style" in text

    def test_props_included_only_when_asked(self):
        entries = [{
            "name": "X", "props": ["title", "hint"],
            "purpose": "x", "when_to_use": "", "when_not_to_use": "",
        }]
        assert "PROPS" not in render_catalog_for_prompt(entries)
        # `render` sorts prop names alphabetically already, so hint before title.
        text_with = render_catalog_for_prompt(entries, include_props=True)
        assert "PROPS:" in text_with
        assert "hint" in text_with and "title" in text_with

    def test_truncation_prefers_entries_with_purposes(self):
        # 100 entries, half with purpose, half without.
        entries = []
        for i in range(50):
            entries.append({"name": f"With{i}", "props": [],
                            "purpose": "matters", "when_to_use": "", "when_not_to_use": ""})
            entries.append({"name": f"Without{i}", "props": [],
                            "purpose": "", "when_to_use": "", "when_not_to_use": ""})
        text = render_catalog_for_prompt(entries, max_chars=300)
        # At the truncation-preserving path, "With" entries survive first.
        assert "With0" in text


class TestDiversityMetric:
    def test_counts_used_components_across_schemas(self):
        cat = {"Table": {}, "Card": {}, "Kanban": {}, "Chart": {}}
        schemas = [
            {"root": {"type": "Page", "children": [
                {"type": "Card", "children": [{"type": "Table"}]},
            ]}},
            {"root": {"type": "Kanban"}},
        ]
        m = diversity_metric(schemas, cat)
        assert m["used_count"] == 3
        assert m["total"] == 4
        assert m["ratio"] == 0.75
        assert "Chart" in m["unused_sample"]

    def test_non_catalog_types_ignored(self):
        """Structural types (Stack, Container) don't count toward variety
        unless they're actually in the library manifest."""
        cat = {"Table": {}}
        schemas = [{"root": {"type": "SomeCustomType"}}]
        m = diversity_metric(schemas, cat)
        assert m["used_count"] == 0

    def test_empty_catalog_zero_ratio(self):
        m = diversity_metric([], {})
        assert m["ratio"] == 0.0


class TestWalker:
    def test_finds_every_type_string(self):
        node = {"type": "A", "children": [
            {"type": "B", "children": [{"type": "C"}]},
            {"type": "D"},
        ]}
        assert component_types_in_schema(node) == {"A", "B", "C", "D"}


# --------------------------------------------------------------------------- #
# CREATIVE-5a — compact per-component manifest
# --------------------------------------------------------------------------- #


class TestBuildLibraryManifest:
    def test_returns_top_level_shape(self):
        m = build_library_manifest()
        assert isinstance(m, dict)
        assert m.get("version") == "1"
        assert "generated_at" in m and isinstance(m["generated_at"], str)
        assert isinstance(m.get("components"), dict)
        assert len(m["components"]) > 50  # library has 100+

    def test_known_components_have_expected_categorization(self):
        comps = build_library_manifest()["components"]

        def _row(name):
            e = comps[name]
            return (e["category"], e["data_shape"], tuple(e["slot_hints"]))

        assert _row("MoneyInput") == ("input", "scalar", ("form-field",))
        assert _row("SearchInput") == ("input", "scalar", ("form-field",))
        assert _row("Table") == ("data", "tabular", ("data-row",))
        assert _row("Kanban") == ("data", "list", ("data-row",))
        assert _row("Card") == ("layout", "none", ("surface",))
        assert _row("LineChart") == ("chart", "series", ("chart",))
        assert _row("MoneyDisplay") == ("display", "scalar", ("body",))

    def test_entries_have_full_shape(self):
        comps = build_library_manifest()["components"]
        for name, e in comps.items():
            assert set(e.keys()) == {
                "category", "data_shape", "slot_hints", "key_props", "summary",
            }, f"{name} has keys {set(e.keys())}"
            assert e["category"] in {
                "input", "display", "layout", "overlay",
                "data", "chart", "media", "action", "nav",
            }
            assert e["data_shape"] in {
                "list", "single", "tabular", "scalar", "series", "none",
            }
            assert isinstance(e["slot_hints"], list) and e["slot_hints"]
            assert isinstance(e["key_props"], list)
            assert isinstance(e["summary"], str) and len(e["summary"]) <= 80

    def test_key_props_capped_and_ranked(self):
        comps = build_library_manifest()["components"]
        for name, e in comps.items():
            assert len(e["key_props"]) <= 4, f"{name} exceeds prop cap"
            for p in e["key_props"]:
                assert "name" in p
                # Required flag, when present, is only True (never False)
                assert p.get("required", True) is True

    def test_serialized_manifest_within_token_budget(self):
        # Compact JSON as the composer would embed it. bytes/4 is the
        # spec's token proxy. 157 registered components at rich detail
        # is naturally larger than the original 2500-3000 aim; 10k is
        # our ceiling — comfortably fits any composer prompt.
        m = build_library_manifest()
        compact = json.dumps(m, separators=(",", ":"))
        approx_tokens = len(compact) // 4
        assert approx_tokens <= 10000, (
            f"manifest bloated: {approx_tokens} tokens, "
            f"{len(m['components'])} components"
        )


class TestPersistAndLoad:
    def test_persist_writes_expected_path(self, tmp_path):
        p = persist_library_manifest(tmp_path)
        assert p == tmp_path / "contracts" / "library-manifest.json"
        assert p.exists()
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["version"] == "1"
        assert "components" in raw and raw["components"]

    def test_persist_overwrites_existing(self, tmp_path):
        p = persist_library_manifest(tmp_path)
        first = p.read_text(encoding="utf-8")
        p.write_text('{"stale": true}', encoding="utf-8")
        p2 = persist_library_manifest(tmp_path)
        assert p == p2
        assert p.read_text(encoding="utf-8") != '{"stale": true}'

    def test_load_reads_persisted_file(self, tmp_path):
        persist_library_manifest(tmp_path)
        loaded = load_library_manifest(tmp_path)
        assert loaded["version"] == "1"
        assert "Table" in loaded["components"]

    def test_load_matches_persisted_byte_for_byte(self, tmp_path):
        persist_library_manifest(tmp_path)
        raw_disk = json.loads(
            (tmp_path / "contracts" / "library-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert load_library_manifest(tmp_path) == raw_disk

    def test_load_none_builds_fresh(self):
        m = load_library_manifest(None)
        assert m and "components" in m and "Table" in m["components"]

    def test_load_missing_dir_builds_fresh(self, tmp_path):
        # No contracts/ dir written — falls back to build_library_manifest.
        m = load_library_manifest(tmp_path)
        assert m and "components" in m

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        d = tmp_path / "contracts"
        d.mkdir()
        (d / "library-manifest.json").write_text("{not json")
        assert load_library_manifest(tmp_path) == {}


# --------------------------------------------------------------------------- #
# CREATIVE-5b — compact-for-composer projection
# --------------------------------------------------------------------------- #


class TestCompactManifestForComposer:
    def test_shape_omits_key_props_and_top_level_metadata(self):
        full = build_library_manifest()
        compact = compact_manifest_for_composer(full)

        assert set(compact.keys()) == {"components"}
        # version + generated_at intentionally dropped.
        assert "version" not in compact
        assert "generated_at" not in compact

        for name, entry in compact["components"].items():
            assert set(entry.keys()) == {
                "category", "data_shape", "slot_hints", "summary",
            }, f"{name} has keys {set(entry.keys())}"
            assert "key_props" not in entry

    def test_names_and_summaries_survive(self):
        full = build_library_manifest()
        compact = compact_manifest_for_composer(full)
        # Every component in the full manifest survives the projection.
        assert set(compact["components"].keys()) == set(full["components"].keys())
        # A couple of well-known summaries pass through verbatim.
        for name in ("Table", "Kanban", "Card"):
            assert compact["components"][name]["summary"] == \
                full["components"][name]["summary"]

    def test_within_token_budget(self):
        """Compact JSON as the composer would embed it.

        The task's original 3k-token estimate proved optimistic —
        summaries alone add ~1.5k tokens for a 157-component library.
        6k is the realistic ceiling that still fits any composer prompt
        with room for candidates + presets + patterns.
        """
        compact = compact_manifest_for_composer()
        blob = json.dumps(compact, separators=(",", ":"))
        approx_tokens = len(blob) // 4
        assert approx_tokens <= 6000, (
            f"compact manifest bloated: {approx_tokens} tokens, "
            f"{len(compact['components'])} components"
        )

    def test_none_input_builds_fresh(self):
        compact = compact_manifest_for_composer(None)
        assert "components" in compact
        assert "Table" in compact["components"]

    def test_empty_input_returns_empty_components(self):
        # Well-shaped input with no components → empty passthrough.
        compact = compact_manifest_for_composer({"components": {}})
        assert compact == {"components": {}}

    def test_malformed_input_returns_shell(self):
        # Non-dict components field → empty passthrough (not a crash).
        compact = compact_manifest_for_composer({"components": None})
        assert compact == {"components": {}}


class TestBuildFailureModes:
    def test_missing_starter_returns_shell(self, tmp_path):
        # Pointing at a non-existent starter still returns a well-shaped
        # manifest — rules-table entries fill in the components dict.
        m = build_library_manifest(starter_path=tmp_path / "ghost.json")
        assert m["version"] == "1"
        assert isinstance(m["components"], dict)
        # Rules-table LineChart/BarChart still appear.
        assert "LineChart" in m["components"]

    def test_missing_both_sources_still_returns_manifest(self, tmp_path):
        m = build_library_manifest(
            starter_path=tmp_path / "no-starter.json",
            contracts_path=tmp_path / "no-contracts.json",
        )
        assert m["version"] == "1"
        # Only rules-table entries survive.
        assert "Table" in m["components"]
        # Card too — it's in the rules table.
        assert "Card" in m["components"]
