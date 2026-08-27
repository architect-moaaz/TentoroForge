"""Typography tokens: the design-spec's fonts + type scale must be compiled into
the generated app (globals.css fonts/vars + tailwind.config.ts fontSize/fontFamily).

Two failure modes this guards:
  PART A — globals.css fonts came from a domain register catalogue, never the
           spec, so distinctive spec fonts (Manrope/Fraunces) were never loaded
           and `--font-body` was dead (nothing referenced it).
  PART B — the generated app's tailwind.config.ts (written by runtime_injector)
           had colors + borderRadius only — NO fontSize — so the Heading
           component's `text-page-title` / `text-caption` classes silently
           no-op'd and headings rendered at browser-default sizes.
"""
import json
from pathlib import Path


# ─────────────────────────── PART A ────────────────────────────────────────

def test_spec_fonts_drive_register_and_globals(tmp_path):
    from agents.design_agent import (
        _register_from_spec_fonts,
        _build_typography_block,
        _build_google_fonts_url,
        _inject_typography_into_globals,
    )

    typography = {
        "fontFamily": "Manrope, system-ui, sans-serif",
        "headingFontFamily": "Fraunces, system-ui, sans-serif",
        "headingWeight": "600",
        "bodyWeight": "400",
        "lineHeight": "1.6",
    }

    register = _register_from_spec_fonts(typography)
    assert register is not None
    # First family extracted, quotes + fallback stack stripped.
    assert register["heading_font"] == "Fraunces"
    assert register["body_font"] == "Manrope"
    assert str(register["heading_weight"]) == "600"

    # Google-fonts @import must carry the spec fonts, spaces url-encoded as '+'.
    url = _build_google_fonts_url(register)
    assert "Fraunces" in url
    assert "Manrope" in url

    block = _build_typography_block(register)
    assert "--font-heading: 'Fraunces'" in block
    assert "--font-body: 'Manrope'" in block
    # --font-body must actually be APPLIED, not just declared.
    assert "body {" in block
    assert "font-family: var(--font-body)" in block

    # End-to-end into a real globals.css.
    css_path = tmp_path / "globals.css"
    css_path.write_text("@tailwind base;\n:root { --x: 1; }\n")
    _inject_typography_into_globals(css_path, register)
    css = css_path.read_text()
    assert "Fraunces" in css  # in the @import line
    assert "--font-heading: 'Fraunces'" in css
    assert "--font-body: 'Manrope'" in css
    assert "font-family: var(--font-body)" in css


def test_register_from_spec_fonts_none_when_no_fonts(tmp_path):
    from agents.design_agent import _register_from_spec_fonts

    assert _register_from_spec_fonts({}) is None
    assert _register_from_spec_fonts({"headingWeight": "700"}) is None


# ─────────────────────────── PART B ────────────────────────────────────────

def _write_spec(output_dir: Path, scale: dict, heading_weight="600"):
    contracts = output_dir / "src" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "design-spec.json").write_text(json.dumps({
        "typography": {
            "fontFamily": "Manrope, system-ui, sans-serif",
            "headingFontFamily": "Fraunces, system-ui, sans-serif",
            "headingWeight": heading_weight,
            "scale": scale,
        }
    }))


def test_tailwind_config_carries_spec_type_scale(tmp_path):
    from services.runtime_injector import _fix_tailwind_config

    _write_spec(tmp_path, {
        "h1": "2.5rem",
        "h2": "1.875rem",
        "h3": "1.5rem",
        "body": "1.0625rem",
        "caption": "0.875rem",
    })
    _fix_tailwind_config(tmp_path)

    out = (tmp_path / "tailwind.config.ts").read_text()
    assert "fontSize:" in out
    # Exact keys the Heading component references.
    for key in ("page-title", "section-title", "card-title", "body", "caption", "micro"):
        assert f'"{key}"' in out
    # page-title size must be derived from the spec's h1.
    assert "2.5rem" in out
    assert '"page-title": ["2.5rem"' in out
    # caption size from spec.
    assert '"caption": ["0.875rem"' in out
    # fontFamily maps the CSS vars so font-heading/font-body resolve.
    assert "fontFamily:" in out
    assert "var(--font-heading)" in out
    assert "var(--font-body)" in out
    # colors + radius stay intact.
    assert 'border: "hsl(var(--border))"' in out
    assert "borderRadius:" in out


def test_tailwind_config_baseline_scale_without_spec(tmp_path):
    """No design-spec present → baseline scale still emits every fontSize key."""
    from services.runtime_injector import _fix_tailwind_config

    _fix_tailwind_config(tmp_path)
    out = (tmp_path / "tailwind.config.ts").read_text()
    assert "fontSize:" in out
    for key in ("page-title", "section-title", "card-title", "body", "caption", "micro"):
        assert f'"{key}"' in out
    assert "var(--font-body)" in out


def test_shadcn_constant_includes_type_scale():
    """The baseline constant itself must carry the fontSize keys (not empty)."""
    from services.runtime_injector import _SHADCN_TAILWIND_CONFIG

    assert "fontSize:" in _SHADCN_TAILWIND_CONFIG
    assert '"page-title"' in _SHADCN_TAILWIND_CONFIG
    assert '"caption"' in _SHADCN_TAILWIND_CONFIG
    assert "var(--font-body)" in _SHADCN_TAILWIND_CONFIG
