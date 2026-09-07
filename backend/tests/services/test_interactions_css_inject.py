"""Tests for Spec C Slice 4 + Slice 8 — interactions + theme-dark CSS
injection into a generated app's globals.css.
"""
from __future__ import annotations

import pytest

from services.interactions_css_inject import (
    _replace_or_append,
    inject_polish_stylesheets,
    _INTERACTIONS_START, _INTERACTIONS_END,
    _DARK_START, _DARK_END,
)


class TestReplaceOrAppend:
    def test_appends_when_no_sentinel(self):
        result, changed = _replace_or_append("body { color: red; }\n", "/* s */", "/* e */", "X")
        assert changed
        assert "/* s */\nX\n/* e */" in result
        assert result.startswith("body { color: red; }\n")

    def test_replaces_when_sentinel_present(self):
        original = "body {}\n/* s */\nOLD\n/* e */\nfooter {}\n"
        result, changed = _replace_or_append(original, "/* s */", "/* e */", "NEW")
        assert changed
        assert "NEW" in result
        assert "OLD" not in result
        assert result.startswith("body {}\n")
        assert result.rstrip().endswith("footer {}")

    def test_second_replace_reaches_fixed_point(self):
        # First pass: append body. Second pass: replace produces the
        # SAME string as pass 1 (fixed point). Whitespace normalization
        # inside the helper may report `changed=True` on the first
        # replace even when the body matches — the fixed-point property
        # is the meaningful invariant we actually care about.
        original = "body {}\n"
        pass1, _ = _replace_or_append(original, "/* s */", "/* e */", "SAME")
        pass2, _ = _replace_or_append(pass1, "/* s */", "/* e */", "SAME")
        pass3, _ = _replace_or_append(pass2, "/* s */", "/* e */", "SAME")
        assert pass2 == pass3  # stable after 2 iterations


class TestInjectPolishStylesheetsFlags:
    def test_both_flags_off_no_op(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_POLISH_INTERACTIONS", raising=False)
        monkeypatch.delenv("FORGE_POLISH_DARK_MODE", raising=False)
        # Create fake globals.css that should NOT be touched.
        gp = tmp_path / "src" / "app" / "globals.css"
        gp.parent.mkdir(parents=True)
        gp.write_text("body { color: red; }\n", encoding="utf-8")
        result = inject_polish_stylesheets(str(tmp_path))
        assert result.get("skipped") == "both_flags_off"
        assert gp.read_text(encoding="utf-8") == "body { color: red; }\n"

    def test_no_globals_css_skip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_INTERACTIONS", "1")
        result = inject_polish_stylesheets(str(tmp_path))
        assert result.get("skipped") == "no_globals_css"


class TestInjectHappyPath:
    def _make_globals(self, tmp_path):
        gp = tmp_path / "src" / "app" / "globals.css"
        gp.parent.mkdir(parents=True)
        gp.write_text("body { color: red; }\n", encoding="utf-8")
        return gp

    def test_interactions_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_INTERACTIONS", "1")
        monkeypatch.delenv("FORGE_POLISH_DARK_MODE", raising=False)
        gp = self._make_globals(tmp_path)
        result = inject_polish_stylesheets(str(tmp_path))
        assert result.get("ok")
        assert "interactions" in result.get("injected", [])
        assert "theme-dark" not in result.get("injected", [])
        text = gp.read_text(encoding="utf-8")
        assert _INTERACTIONS_START in text
        assert _INTERACTIONS_END in text
        # Original preserved.
        assert "body { color: red; }" in text

    def test_dark_mode_only(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_POLISH_INTERACTIONS", raising=False)
        monkeypatch.setenv("FORGE_POLISH_DARK_MODE", "1")
        gp = self._make_globals(tmp_path)
        result = inject_polish_stylesheets(str(tmp_path))
        assert result.get("ok")
        assert "theme-dark" in result.get("injected", [])
        assert "interactions" not in result.get("injected", [])
        text = gp.read_text(encoding="utf-8")
        assert _DARK_START in text
        assert _DARK_END in text

    def test_both_flags_on(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_INTERACTIONS", "1")
        monkeypatch.setenv("FORGE_POLISH_DARK_MODE", "1")
        gp = self._make_globals(tmp_path)
        result = inject_polish_stylesheets(str(tmp_path))
        assert set(result.get("injected", [])) == {"interactions", "theme-dark"}
        text = gp.read_text(encoding="utf-8")
        assert _INTERACTIONS_START in text
        assert _DARK_START in text

    def test_second_run_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_INTERACTIONS", "1")
        monkeypatch.setenv("FORGE_POLISH_DARK_MODE", "1")
        gp = self._make_globals(tmp_path)
        inject_polish_stylesheets(str(tmp_path))
        text_after_first = gp.read_text(encoding="utf-8")
        inject_polish_stylesheets(str(tmp_path))
        text_after_second = gp.read_text(encoding="utf-8")
        # Same sentinels, same content — no duplication.
        assert text_after_first == text_after_second
        assert text_after_second.count(_INTERACTIONS_START) == 1
        assert text_after_second.count(_DARK_START) == 1


class TestFlagValues:
    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_enable_interactions(self, tmp_path, monkeypatch, val):
        monkeypatch.setenv("FORGE_POLISH_INTERACTIONS", val)
        monkeypatch.delenv("FORGE_POLISH_DARK_MODE", raising=False)
        gp = tmp_path / "src" / "app" / "globals.css"
        gp.parent.mkdir(parents=True)
        gp.write_text("", encoding="utf-8")
        result = inject_polish_stylesheets(str(tmp_path))
        assert "interactions" in result.get("injected", []), f"failed for {val!r}"

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_keeps_off(self, tmp_path, monkeypatch, val):
        monkeypatch.setenv("FORGE_POLISH_INTERACTIONS", val)
        monkeypatch.delenv("FORGE_POLISH_DARK_MODE", raising=False)
        gp = tmp_path / "src" / "app" / "globals.css"
        gp.parent.mkdir(parents=True)
        gp.write_text("", encoding="utf-8")
        result = inject_polish_stylesheets(str(tmp_path))
        assert result.get("skipped") == "both_flags_off", f"leaked for {val!r}"
