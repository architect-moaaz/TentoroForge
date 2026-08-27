"""Tests for services.section_authoring — the Spec D Wave 6 replacement
for the 15-item ``section_templates`` catalog."""
from __future__ import annotations

import pytest

from services.section_authoring import author_section, list_section_kinds


# ── list_section_kinds ───────────────────────────────────────────────────

class TestListSectionKinds:
    def test_returns_the_documented_15_kinds(self) -> None:
        kinds = list_section_kinds()
        assert len(kinds) == 15
        ids = {k["id"] for k in kinds}
        assert ids == {
            "hero", "features", "cta", "testimonials", "pricing", "footer",
            "stats", "gallery", "contact", "faq", "team", "timeline",
            "logos", "video", "subscribe",
        }

    def test_every_entry_has_the_frontend_safe_shape(self) -> None:
        for k in list_section_kinds():
            assert set(k.keys()) == {"id", "name", "category", "description"}
            for v in k.values():
                assert isinstance(v, str) and v

    def test_returns_copies_not_shared_state(self) -> None:
        # Mutating the returned list must NOT mutate the module-level source.
        first = list_section_kinds()
        first[0]["name"] = "MUTATED"
        second = list_section_kinds()
        assert second[0]["name"] != "MUTATED"


# ── author_section ───────────────────────────────────────────────────────

class TestAuthorSection:
    def test_hero_returns_the_hero_shape(self) -> None:
        out = author_section("hero")
        assert out["id"] == "hero"
        assert out["category"] == "hero"
        assert "hero" in out["prompt"].lower()

    def test_features_returns_grid_prompt(self) -> None:
        out = author_section("features")
        assert out["id"] == "features"
        assert "grid" in out["prompt"].lower()

    def test_unknown_kind_falls_back_to_generic_content(self) -> None:
        # Old callers may still pass template ids like "hero-centered" —
        # the generic recipe must keep them working, not crash.
        out = author_section("hero-centered")
        assert out["id"] == "hero-centered"
        assert "content" in out["category"].lower() or out["category"] == "content"
        assert out["prompt"]  # non-empty

    def test_category_id_still_resolves_a_recipe(self) -> None:
        # The frontend groups by ``category``; a caller that passes a
        # category string ('cta') instead of an exact id should also
        # get the right recipe.
        out = author_section("cta")
        assert out["category"] == "cta"
        assert "call" in out["prompt"].lower() or "cta" in out["prompt"].lower()

    def test_brief_palette_shows_up_in_prompt(self) -> None:
        brief = {
            "palette": {
                "brand": "#2E5C7E", "accent": "#0F8A6A",
                "surface_bg": "#FAFCFD",
            },
        }
        out = author_section("hero", brief=brief)
        assert "#2E5C7E" in out["prompt"]
        assert "#0F8A6A" in out["prompt"]

    def test_brief_visual_stance_shows_up_in_prompt(self) -> None:
        brief = {
            "identity": {
                "visual_stance": {
                    "temperature": "cool",
                    "principles": ["restraint", "precision"],
                },
            },
        }
        out = author_section("features", brief=brief)
        assert "cool" in out["prompt"]
        assert "restraint" in out["prompt"]

    def test_no_brief_still_returns_usable_prompt(self) -> None:
        out = author_section("pricing")
        assert out["prompt"]
        # No palette / stance tail
        assert "Palette:" not in out["prompt"]
        assert "Visual stance:" not in out["prompt"]

    @pytest.mark.parametrize("kind", [k["id"] for k in list_section_kinds()])
    def test_every_kind_yields_a_non_empty_prompt(self, kind: str) -> None:
        out = author_section(kind)
        assert out["prompt"].strip()
        assert out["id"] == kind

    def test_page_context_argument_is_accepted(self) -> None:
        # Signature-stability: page_context is reserved but currently
        # ignored. Callers must be able to pass it without crashing.
        out = author_section("hero", page_context={"file": "src/app/page.tsx"})
        assert out["id"] == "hero"
