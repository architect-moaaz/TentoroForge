"""Every menu item draws a glyph: its icon by canonical or alias name, else
the label's initial. Personal Finance's rail showed thirteen icons with two
anonymous circles — "plus-circle" (an alias lucide's `icons` object lacks)
and "Onboarding Setup" (no keyword) — which reads as a broken menu."""
from __future__ import annotations

import re
from pathlib import Path

LAYOUT = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "app" / "(dashboard)" / "layout.tsx"


def test_alias_icon_names_resolve_and_the_fallback_is_the_initial():
    text = LAYOUT.read_text()
    assert 'import * as lucideAll from "lucide-react";' in text
    assert "const alias = (lucideAll as unknown as Record<string, unknown>)[pascal];" in text
    assert "const initial = (label || \"\").trim().charAt(0).toUpperCase();" in text
    assert 'return "circle";' not in text
    # Every rail draws its glyphs with the label at hand.
    calls = re.findall(r"<RailGlyph name=\{[a-z]+\.icon\}[^/]*/>", text)
    assert calls and all("label={" in c for c in calls), calls


def test_the_keywords_cover_what_a_finance_app_adds_to_its_menu():
    text = LAYOUT.read_text()
    block = text[text.index("const ICON_MAP"):text.index("function iconFor")]
    for word in ("onboard", "import", "budget", "categor", "recur", "scenario"):
        assert word in block, word
