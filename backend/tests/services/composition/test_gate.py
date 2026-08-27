"""Slice 6 tests — the build-time gate catches invalid page_recipes refs."""
from __future__ import annotations

import pytest

from schemas.design_brief import (
    DesignBrief, Identity, Layout, Palette, SignatureMove, Typography,
)
from services.composition.gate import (
    CompositionGateError,
    assert_valid_or_raise,
    validate_page_recipes,
)


def _brief(page_recipes: dict[str, str] | None = None) -> DesignBrief:
    b = DesignBrief(
        identity=Identity(domain="Test", register=["structured"], voice="warm_precise"),
        palette=Palette(
            brand="#2D5A8E", accent="#E8A020",
            neutrals_base="#F5F5F5", neutrals_tint="cool",
            surface_bg="#FFFFFF", surface_elevated="#FFFFFF",
            foreground_primary="#111111", foreground_muted="#666666",
        ),
        typography=Typography(display_family="Serif", body_family="Sans"),
        layout=Layout(density="compact", radius="soft_8", grid="12col"),
        signature_moves=[SignatureMove(kind="warm_serif_h1", detail="x")],
    )
    if page_recipes:
        b = b.model_copy(update={"page_recipes": page_recipes})
    return b


# ────────────────────────────────────────────────────────────
# validate_page_recipes — never raises
# ────────────────────────────────────────────────────────────

class TestValidatePageRecipes:
    def test_empty_page_recipes_ok(self):
        assert validate_page_recipes(_brief()) == []

    def test_valid_recipe_passes(self):
        errors = validate_page_recipes(_brief({"/home": "member_home"}))
        assert errors == []

    def test_unknown_recipe_reported(self):
        errors = validate_page_recipes(_brief({"/home": "does_not_exist"}))
        assert len(errors) == 1
        assert errors[0].kind == "unknown_recipe"
        assert errors[0].route == "/home"
        assert errors[0].recipe == "does_not_exist"

    def test_no_v1_anchors_reported_as_warning_kind(self):
        # operator_console is a real recipe but no anchor has impl_status=v1
        errors = validate_page_recipes(_brief({"/ops": "citizen_service"}))
        assert len(errors) == 1
        assert errors[0].kind == "no_v1_anchors"
        assert errors[0].route == "/ops"

    def test_multiple_errors_all_reported(self):
        errors = validate_page_recipes(_brief({
            "/a": "does_not_exist",
            "/b": "citizen_service",
            "/home": "member_home",  # valid
        }))
        kinds = sorted(e.kind for e in errors)
        assert kinds == ["no_v1_anchors", "unknown_recipe"]


# ────────────────────────────────────────────────────────────
# assert_valid_or_raise — mode-aware
# ────────────────────────────────────────────────────────────

class TestAssertValidOrRaise:
    def test_flag_off_returns_empty_never_raises(self, monkeypatch):
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        # Even a broken brief passes when the flag is off.
        errors = assert_valid_or_raise(_brief({"/home": "does_not_exist"}))
        assert errors == []

    def test_warn_mode_returns_errors_but_never_raises(self, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        errors = assert_valid_or_raise(_brief({"/home": "does_not_exist"}))
        assert len(errors) == 1
        assert errors[0].kind == "unknown_recipe"

    def test_strict_mode_raises_on_unknown_recipe(self, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "strict")
        with pytest.raises(CompositionGateError) as exc_info:
            assert_valid_or_raise(_brief({"/home": "does_not_exist"}))
        assert "unknown_recipe" in str(exc_info.value)

    def test_strict_mode_does_not_raise_on_no_v1_anchors(self, monkeypatch):
        # `no_v1_anchors` is a "recipe registered but nothing built" signal —
        # a warning even in strict mode, since the classic path handles it fine.
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "strict")
        errors = assert_valid_or_raise(_brief({"/ops": "citizen_service"}))
        assert len(errors) == 1
        assert errors[0].kind == "no_v1_anchors"

    def test_strict_mode_raises_only_on_fatal(self, monkeypatch):
        # Mix of fatal (unknown_recipe) + warning (no_v1_anchors) → still raises,
        # and the exception mentions only the fatal one.
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "strict")
        with pytest.raises(CompositionGateError) as exc_info:
            assert_valid_or_raise(_brief({
                "/a": "does_not_exist",
                "/b": "citizen_service",
            }))
        msg = str(exc_info.value)
        assert "unknown_recipe" in msg
        assert "no_v1_anchors" not in msg

    def test_valid_brief_passes_strict(self, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "strict")
        errors = assert_valid_or_raise(_brief({"/home": "member_home"}))
        assert errors == []
