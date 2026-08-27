"""Tests for the source + locked_fields extension to DesignBrief.

Spec A Slice 6b (schema) + Slice 6c (editor enforcement). Additive
schema change: existing briefs still validate (defaults preserve
behavior); Figma-sourced briefs mark specific fields as locked so
edit_brief and Smith tools refuse mutations to them.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from schemas.design_brief import DesignBrief, Identity, Palette, Typography, Layout
from services.design_brief_editor import BriefEditError, apply_patch


def _brief_payload() -> dict:
    """Baseline valid DesignBrief payload — no locks, source defaulted."""
    return {
        "identity": {
            "domain": "Test",
            "register": ["calm"],
            "voice": "warm_precise",
            "modes": ["light"],
        },
        "palette": {
            "brand": "#2D5A8E",
            "accent": "#E8A020",
            "neutrals_base": "#F0F2F5",
            "neutrals_tint": "cool",
            "surface_bg": "#F5F7FA",
            "surface_elevated": "#FFFFFF",
            "foreground_primary": "#111827",
            "foreground_muted": "#4B5A6E",
        },
        "typography": {
            "display_family": "DM Sans",
            "body_family": "IBM Plex Sans",
            "utility_family": "IBM Plex Mono",
            "scale": "tight_1.15",
        },
        "layout": {
            "density": "compact",
            "radius": "sharp_2",
            "grid": "12col",
        },
        "signature_moves": [{"kind": "ledger_row", "detail": "4px left-border"}],
    }


# --------------------------------------------------------------------------- #
# source field on Identity
# --------------------------------------------------------------------------- #


class TestIdentitySource:
    def test_default_source_is_authored(self):
        """Existing briefs without a source field still validate."""
        brief = DesignBrief.model_validate(_brief_payload())
        assert brief.identity.source == "authored"

    def test_can_explicitly_set_authored(self):
        p = _brief_payload()
        p["identity"]["source"] = "authored"
        brief = DesignBrief.model_validate(p)
        assert brief.identity.source == "authored"

    def test_can_set_figma_source(self):
        p = _brief_payload()
        p["identity"]["source"] = "figma"
        brief = DesignBrief.model_validate(p)
        assert brief.identity.source == "figma"

    def test_unknown_source_rejected(self):
        p = _brief_payload()
        p["identity"]["source"] = "invented"
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(p)

    def test_source_survives_round_trip_json(self):
        p = _brief_payload()
        p["identity"]["source"] = "figma"
        brief = DesignBrief.model_validate(p)
        text = brief.model_dump_json()
        again = DesignBrief.model_validate_json(text)
        assert again.identity.source == "figma"


# --------------------------------------------------------------------------- #
# locked_fields on Palette / Typography / Layout
# --------------------------------------------------------------------------- #


class TestPaletteLockedFields:
    def test_default_locked_fields_empty(self):
        brief = DesignBrief.model_validate(_brief_payload())
        assert brief.palette.locked_fields == set()

    def test_can_set_locked_fields(self):
        p = _brief_payload()
        p["palette"]["locked_fields"] = ["brand", "accent"]
        brief = DesignBrief.model_validate(p)
        assert brief.palette.locked_fields == {"brand", "accent"}

    def test_locked_fields_survives_json_round_trip(self):
        p = _brief_payload()
        p["palette"]["locked_fields"] = ["brand", "surface_elevated"]
        brief = DesignBrief.model_validate(p)
        text = brief.model_dump_json()
        again = DesignBrief.model_validate_json(text)
        assert again.palette.locked_fields == {"brand", "surface_elevated"}

    def test_locked_fields_from_list_becomes_set(self):
        p = _brief_payload()
        p["palette"]["locked_fields"] = ["brand", "brand", "accent"]  # dup
        brief = DesignBrief.model_validate(p)
        assert brief.palette.locked_fields == {"brand", "accent"}  # dedup


class TestTypographyLockedFields:
    def test_default_empty(self):
        brief = DesignBrief.model_validate(_brief_payload())
        assert brief.typography.locked_fields == set()

    def test_can_set(self):
        p = _brief_payload()
        p["typography"]["locked_fields"] = ["display_family", "body_family"]
        brief = DesignBrief.model_validate(p)
        assert brief.typography.locked_fields == {"display_family", "body_family"}


class TestLayoutLockedFields:
    def test_default_empty(self):
        brief = DesignBrief.model_validate(_brief_payload())
        assert brief.layout.locked_fields == set()

    def test_can_set(self):
        p = _brief_payload()
        p["layout"]["locked_fields"] = ["radius"]
        brief = DesignBrief.model_validate(p)
        assert brief.layout.locked_fields == {"radius"}


# --------------------------------------------------------------------------- #
# Backward compat — existing briefs (no source/locks) work unchanged
# --------------------------------------------------------------------------- #


class TestBackwardCompat:
    def test_existing_brief_json_still_parses(self):
        # A brief JSON saved before Slice 6b (no source, no locked_fields)
        # must still deserialize cleanly.
        legacy_json = json.dumps(_brief_payload())
        brief = DesignBrief.model_validate_json(legacy_json)
        assert brief.identity.source == "authored"
        assert brief.palette.locked_fields == set()
        assert brief.typography.locked_fields == set()
        assert brief.layout.locked_fields == set()

    def test_summary_line_unchanged(self):
        # summary_line() is Smith's memory format — must not regress.
        brief = DesignBrief.model_validate(_brief_payload())
        line = brief.summary_line()
        assert "warm_precise" in line
        assert "#2D5A8E" in line


# --------------------------------------------------------------------------- #
# Slice 6c — edit_brief refuses mutations to locked fields
# --------------------------------------------------------------------------- #


def _locked_brief() -> DesignBrief:
    """Figma-sourced brief with palette.brand and typography.body_family locked."""
    p = _brief_payload()
    p["identity"]["source"] = "figma"
    p["palette"]["locked_fields"] = ["brand", "surface_elevated"]
    p["typography"]["locked_fields"] = ["body_family"]
    p["layout"]["locked_fields"] = ["radius"]
    return DesignBrief.model_validate(p)


class TestEditBriefRespectsPaletteLocks:
    def test_edit_locked_brand_raises(self):
        with pytest.raises(BriefEditError) as excinfo:
            apply_patch(_locked_brief(), {"palette": {"brand": "#000000"}})
        assert "locked" in str(excinfo.value).lower()

    def test_edit_locked_surface_elevated_raises(self):
        with pytest.raises(BriefEditError):
            apply_patch(_locked_brief(), {"palette": {"surface_elevated": "#EEEEEE"}})

    def test_edit_unlocked_accent_succeeds(self):
        after = apply_patch(_locked_brief(), {"palette": {"accent": "#00FF00"}})
        assert after.palette.accent == "#00FF00"
        # Locked fields still intact.
        assert after.palette.brand == "#2D5A8E"

    def test_error_message_names_the_field(self):
        # The Smith tool + frontend surface the error message to the user.
        # It must clearly say which field(s) are locked.
        with pytest.raises(BriefEditError) as excinfo:
            apply_patch(_locked_brief(), {"palette": {"brand": "#000000"}})
        assert "brand" in str(excinfo.value)


class TestEditBriefRespectsTypographyLocks:
    def test_edit_locked_body_family_raises(self):
        with pytest.raises(BriefEditError):
            apply_patch(_locked_brief(), {"typography": {"body_family": "Comic Sans"}})

    def test_edit_unlocked_display_family_succeeds(self):
        after = apply_patch(_locked_brief(), {"typography": {"display_family": "Georgia"}})
        assert after.typography.display_family == "Georgia"
        assert after.typography.body_family == "IBM Plex Sans"


class TestEditBriefRespectsLayoutLocks:
    def test_edit_locked_radius_raises(self):
        with pytest.raises(BriefEditError):
            apply_patch(_locked_brief(), {"layout": {"radius": "pill"}})

    def test_edit_unlocked_density_succeeds(self):
        after = apply_patch(_locked_brief(), {"layout": {"density": "spacious"}})
        assert after.layout.density.value == "spacious"


class TestEditBriefLockedFieldsForAuthoredBrief:
    def test_authored_brief_has_no_locks_by_default(self):
        # Backward-compat: an LLM-authored brief has no locks, so all
        # fields are editable — no behavior change from Slice 6b/6c.
        brief = DesignBrief.model_validate(_brief_payload())
        after = apply_patch(brief, {"palette": {"brand": "#123456"}})
        assert after.palette.brand == "#123456"

    def test_partial_lock_only_blocks_listed_fields(self):
        # Adjacent fields under the same section stay editable.
        brief = _locked_brief()
        after = apply_patch(brief, {
            "palette": {"foreground_muted": "#333333"},  # not in locked_fields
        })
        assert after.palette.foreground_muted == "#333333"
        assert after.palette.brand == "#2D5A8E"  # still locked
