"""Verify design_agent injects typography from the picked register."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from agents.design_agent import _inject_typography_into_globals


def _seed_globals_css(path: Path) -> None:
    """Write a minimal globals.css that resembles design_agent's template."""
    path.write_text(
        "@tailwind base;\n"
        "@tailwind components;\n"
        "@tailwind utilities;\n\n"
        "@layer base {\n"
        "  :root {\n"
        "    --background: 0 0% 100%;\n"
        "    --foreground: 222.2 84% 4.9%;\n"
        "  }\n"
        "}\n"
    )


def test_inject_typography_adds_google_fonts_import():
    with tempfile.TemporaryDirectory() as td:
        css_path = Path(td) / "globals.css"
        _seed_globals_css(css_path)
        register = {
            "id": "editorial-luxe",
            "heading_font": "Playfair Display",
            "body_font": "Source Sans 3",
            "heading_weight": 700,
            "body_weight": 400,
            "heading_tracking": "-0.01em",
        }
        _inject_typography_into_globals(css_path, register)
        css = css_path.read_text(encoding="utf-8")
        assert "fonts.googleapis.com" in css
        assert "Playfair+Display" in css
        assert "Source+Sans+3" in css


def test_inject_typography_adds_css_variables():
    with tempfile.TemporaryDirectory() as td:
        css_path = Path(td) / "globals.css"
        _seed_globals_css(css_path)
        register = {
            "id": "modern-minimal",
            "heading_font": "Inter",
            "body_font": "Inter",
            "heading_weight": 600,
            "body_weight": 400,
            "heading_tracking": "-0.02em",
        }
        _inject_typography_into_globals(css_path, register)
        css = css_path.read_text(encoding="utf-8")
        assert "--font-heading:" in css
        assert "'Inter'" in css or '"Inter"' in css
        assert "--font-body:" in css
        assert "--font-heading-weight: 600" in css
        assert "--font-heading-tracking: -0.02em" in css


def test_inject_typography_is_idempotent():
    """Running twice should not produce duplicate @import lines."""
    with tempfile.TemporaryDirectory() as td:
        css_path = Path(td) / "globals.css"
        _seed_globals_css(css_path)
        register = {
            "id": "modern-minimal",
            "heading_font": "Inter",
            "body_font": "Inter",
            "heading_weight": 600,
            "body_weight": 400,
            "heading_tracking": "-0.02em",
        }
        _inject_typography_into_globals(css_path, register)
        first = css_path.read_text(encoding="utf-8")
        _inject_typography_into_globals(css_path, register)
        second = css_path.read_text(encoding="utf-8")
        assert first == second
        assert second.count("fonts.googleapis.com") == 1
        assert second.count("--font-heading:") == 1


def test_inject_typography_preserves_existing_css():
    with tempfile.TemporaryDirectory() as td:
        css_path = Path(td) / "globals.css"
        _seed_globals_css(css_path)
        register = {
            "id": "technical-mono",
            "heading_font": "Space Grotesk",
            "body_font": "Inter",
            "heading_weight": 700,
            "body_weight": 400,
            "heading_tracking": "0em",
        }
        _inject_typography_into_globals(css_path, register)
        css = css_path.read_text(encoding="utf-8")
        assert "@tailwind base;" in css
        assert "--background: 0 0% 100%;" in css
        assert "--foreground: 222.2 84% 4.9%;" in css
