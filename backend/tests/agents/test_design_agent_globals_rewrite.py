"""Regression: design_agent rewrites globals.css :root from colorPalette.

The LLM is unreliable at hex→HSL math (observed: ``#F0F9FF`` background
became ``--background: 0 0% 100%``), so we deterministically rewrite the
``:root { ... }`` block from the design-spec ``colorPalette`` after the
LLM produces globals.css.
"""

from pathlib import Path


def test_hex_to_hsl_channels():
    from agents.design_agent import _hex_to_hsl_channels

    assert _hex_to_hsl_channels("#F0F9FF") == "204 100% 97%"
    assert _hex_to_hsl_channels("#FFFFFF") == "0 0% 100%"
    assert _hex_to_hsl_channels("#000000") == "0 0% 0%"
    assert _hex_to_hsl_channels("#FF0000") == "0 100% 50%"


def test_hex_to_hsl_channels_short_form():
    from agents.design_agent import _hex_to_hsl_channels

    # 3-char hex expands to 6-char
    assert _hex_to_hsl_channels("#fff") == _hex_to_hsl_channels("#FFFFFF")
    assert _hex_to_hsl_channels("#000") == _hex_to_hsl_channels("#000000")


def test_rewrite_globals_root_replaces_values(tmp_path: Path):
    from agents.design_agent import _rewrite_globals_root

    globals_path = tmp_path / "globals.css"
    globals_path.write_text(
        """@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --background: 0 0% 100%;
  --card: 0 0% 100%;
  --primary: 221 83% 53%;
}

.dark {
  --background: 222 84% 5%;
}

body { color: hsl(var(--foreground)); }
"""
    )

    palette = {
        "background": "#F0F9FF",
        "surface": "#FFFFFF",
        "primary": "#0284C7",
        "error": "#EF4444",
    }
    _rewrite_globals_root(globals_path, palette)

    rewritten = globals_path.read_text()
    # New value present and matches the colorPalette truth, NOT the LLM's stale value
    assert "--background: 204 100% 97%" in rewritten
    # Old default for --primary should be REPLACED in the main :root (not appended)
    primary_lines = [
        line
        for line in rewritten.split("\n")
        if "--primary:" in line and ".dark" not in line
    ]
    assert len(primary_lines) == 1
    # #0284C7 → roughly 199 88% 40% (allow neighbouring hue/sat values)
    assert any(tok in primary_lines[0] for tok in (" 198 ", " 199 ", " 200 ", " 201 "))
    # .dark block preserved
    assert ".dark" in rewritten
    assert "222 84% 5%" in rewritten  # .dark --background still intact
    # @tailwind directives preserved
    assert "@tailwind base" in rewritten
    # body rule preserved
    assert "body { color: hsl(var(--foreground)); }" in rewritten


def test_rewrite_globals_root_is_idempotent(tmp_path: Path):
    """Running rewrite twice should produce the same output."""
    from agents.design_agent import _rewrite_globals_root

    globals_path = tmp_path / "globals.css"
    globals_path.write_text(":root { --background: 0 0% 100%; }")
    palette = {"background": "#F0F9FF"}

    _rewrite_globals_root(globals_path, palette)
    first = globals_path.read_text()
    _rewrite_globals_root(globals_path, palette)
    second = globals_path.read_text()
    assert first == second


def test_rewrite_globals_root_creates_block_when_missing(tmp_path: Path):
    """If globals.css has no :root block, append one."""
    from agents.design_agent import _rewrite_globals_root

    globals_path = tmp_path / "globals.css"
    globals_path.write_text("@tailwind base;\n@tailwind utilities;\n")
    _rewrite_globals_root(globals_path, {"background": "#F0F9FF", "primary": "#0284C7"})

    rewritten = globals_path.read_text()
    assert ":root {" in rewritten
    assert "--background: 204 100% 97%" in rewritten
    assert "--primary:" in rewritten
    # Original content preserved
    assert "@tailwind base;" in rewritten


def test_rewrite_globals_root_skips_when_file_missing(tmp_path: Path):
    """Missing globals.css is not an error — just a no-op."""
    from agents.design_agent import _rewrite_globals_root

    missing = tmp_path / "globals.css"
    _rewrite_globals_root(missing, {"background": "#F0F9FF"})
    assert not missing.exists()


def test_rewrite_globals_root_ignores_non_hex_values(tmp_path: Path):
    """Palette values that are not ``#RRGGBB`` strings are skipped, not crashed on."""
    from agents.design_agent import _rewrite_globals_root

    globals_path = tmp_path / "globals.css"
    globals_path.write_text(":root { --background: 0 0% 100%; }")
    # mix of valid + various junk
    palette = {
        "background": "#F0F9FF",
        "primary": "tokens.color.primary.500",  # token path, not hex
        "surface": None,
        "muted": 123,
    }
    _rewrite_globals_root(globals_path, palette)

    rewritten = globals_path.read_text()
    assert "--background: 204 100% 97%" in rewritten
    # Non-hex values should not show up as broken declarations
    assert "tokens.color" not in rewritten


def test_save_design_spec_rewrites_globals_from_palette(tmp_path: Path):
    """End-to-end: ``save_design_spec`` rewrites ``src/app/globals.css``
    when the spec has a ``colorPalette``.
    """
    from agents.design_agent import save_design_spec

    # Lay out the project structure the LLM normally produces.
    (tmp_path / "src" / "app").mkdir(parents=True)
    globals_path = tmp_path / "src" / "app" / "globals.css"
    globals_path.write_text(
        ":root {\n  --background: 0 0% 100%;\n  --primary: 221 83% 53%;\n}\n"
    )

    spec = {
        "colorPalette": {
            "background": "#F0F9FF",
            "surface": "#FFFFFF",
            "primary": "#0284C7",
        },
        "register": "default",
    }
    save_design_spec(str(tmp_path), spec)

    rewritten = globals_path.read_text()
    assert "--background: 204 100% 97%" in rewritten
    # The wrong LLM default `221 83% 53%` should be gone
    assert "221 83% 53%" not in rewritten


# ── 2026-08-13: visual-lock font @import injection ─────────────────────


class TestVisualLockFontInjection:
    """The visual-lock typography (Fraunces + Inter for wellness) must
    reach globals.css as a Google Fonts @import — otherwise the browser
    falls back to system fonts and the wellness app loses its serif
    display face entirely. Covers both the direct helper and the
    _rewrite_globals_root pass-through path used by the post-hoc
    rebuild script."""

    def _typography_visual_lock(self):
        return {
            "display": {"family": "Fraunces", "weights": [500, 700]},
            "body":    {"family": "Inter",    "weights": [400, 500, 600]},
            "utility": {"family": "JetBrains Mono"},
            "fontFamily":        "Inter",
            "headingFontFamily": "Fraunces",
        }

    def test_build_url_from_visual_lock_shape(self):
        from agents.design_agent import _build_google_fonts_import_from_typography
        url = _build_google_fonts_import_from_typography(self._typography_visual_lock())
        assert url is not None
        # Both faces, both with their weight lists, one @import.
        assert "Fraunces:wght@500;700" in url
        assert "Inter:wght@400;500;600" in url
        assert "display=swap" in url
        assert url.startswith("@import url('https://fonts.googleapis.com/css2?family=")

    def test_build_url_from_legacy_flat_shape(self):
        from agents.design_agent import _build_google_fonts_import_from_typography
        # Legacy shape without weight lists still yields a valid URL.
        url = _build_google_fonts_import_from_typography(
            {"fontFamily": "Inter", "headingFontFamily": "Fraunces",
             "bodyWeight": 400, "headingWeight": 700}
        )
        assert url is not None
        assert "Fraunces" in url and "Inter" in url

    def test_build_url_returns_none_when_empty(self):
        from agents.design_agent import _build_google_fonts_import_from_typography
        assert _build_google_fonts_import_from_typography(None) is None
        assert _build_google_fonts_import_from_typography({}) is None
        # A typography block with only 'scale' (no families) → None.
        assert _build_google_fonts_import_from_typography({"scale": {"body": "1rem"}}) is None

    def test_inject_is_idempotent(self, tmp_path):
        from agents.design_agent import _inject_font_import_from_typography
        p = tmp_path / "globals.css"
        p.write_text("@tailwind base;\n:root { --x: 1; }\n")
        _inject_font_import_from_typography(p, self._typography_visual_lock())
        once = p.read_text()
        _inject_font_import_from_typography(p, self._typography_visual_lock())
        assert p.read_text() == once, "font injection must be idempotent"
        # @import lives at the very top so the browser fetches it before
        # any @tailwind directive parses.
        assert once.splitlines()[0].startswith("@import url('https://fonts.googleapis.com/css2?family=Fraunces")

    def test_rewrite_globals_root_typography_arg_injects_import(self, tmp_path):
        from agents.design_agent import _rewrite_globals_root
        p = tmp_path / "globals.css"
        p.write_text("@tailwind base;\n:root { --x: 1; }\n")
        _rewrite_globals_root(
            p, palette={"primary": "#5A6B4A"}, radius_md="12px",
            typography=self._typography_visual_lock(),
        )
        text = p.read_text()
        assert "Fraunces" in text and "Inter" in text
        assert "@import url('https://fonts.googleapis.com/css2" in text
        # --font-display / --font-body reach the :root so the vendored
        # layout.tsx's `var(--font-display)` reference actually resolves.
        assert "--font-display" in text
        assert "--font-body" in text

    def test_rewrite_globals_root_without_typography_leaves_fonts_alone(self, tmp_path):
        from agents.design_agent import _rewrite_globals_root
        p = tmp_path / "globals.css"
        p.write_text("@tailwind base;\n:root { --x: 1; }\n")
        _rewrite_globals_root(p, palette={"primary": "#5A6B4A"}, radius_md="12px")
        text = p.read_text()
        # No typography passed → no Google Fonts @import injected.
        assert "fonts.googleapis.com" not in text
