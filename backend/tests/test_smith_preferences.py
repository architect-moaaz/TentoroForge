"""Tests for the pure parts of services/smith_preferences.py (Phase 1c).

CRUD helpers are async-DB-bound and covered by the router-integration
tests. Here we test the pure surface:
  * is_known_key whitelist
  * render_preferences_block ordering + empty behavior
"""

from __future__ import annotations

import pytest

from services.smith_preferences import (
    KNOWN_KEYS,
    is_known_key,
    render_preferences_block,
)


class TestKnownKeyWhitelist:
    def test_expected_keys_present(self):
        assert "confirm_on_delete" in KNOWN_KEYS
        assert "default_generation_profile" in KNOWN_KEYS

    def test_unknown_key_rejected(self):
        assert not is_known_key("delete_all_the_things")
        assert not is_known_key("")
        assert not is_known_key("confirm_on_delete ")  # trailing space
        assert not is_known_key(None)  # type: ignore[arg-type]

    def test_known_key_accepted(self):
        assert is_known_key("confirm_on_delete")


class TestRenderPreferencesBlock:
    def test_empty_dict_yields_empty_string(self):
        assert render_preferences_block({}) == ""

    def test_unknown_keys_filtered(self):
        # If someone snuck a bogus key past set_pref (defense-in-depth),
        # the renderer still filters at read time.
        s = render_preferences_block({"bogus": "value"})
        assert s == ""

    def test_single_known_key_renders(self):
        s = render_preferences_block({"confirm_on_delete": "yes"})
        assert "USER PREFERENCES" in s
        assert "confirm_on_delete = yes" in s

    def test_multiple_keys_alphabetically_sorted(self):
        s = render_preferences_block({
            "preferred_theme": "midnight",
            "confirm_on_delete": "yes",
            "default_generation_profile": "fast",
        })
        idx_confirm = s.index("confirm_on_delete")
        idx_default = s.index("default_generation_profile")
        idx_theme = s.index("preferred_theme")
        assert idx_confirm < idx_default < idx_theme

    def test_block_has_apply_instruction(self):
        s = render_preferences_block({"confirm_on_delete": "yes"})
        assert "Apply these standing rules" in s
        assert "set_preference" in s
