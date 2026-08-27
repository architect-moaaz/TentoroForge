"""Tests that _DOMAIN_ALIAS is applied inside generate_design_spec_from_industry.

This exercises the PRODUCTION pipeline path — the relay pipeline in
routers/generate.py calls generate_design_spec_from_industry, NOT
get_industry_design.  The Task 6 alias fix only covered get_industry_design;
this test would FAIL if the one-line alias was reverted from
generate_design_spec_from_industry.
"""

import pytest
from services.industry_design import (
    generate_design_spec_from_industry,
    _THEME_COLORS,
)


# Ocean primary — the "collapse" sentinel value (the un-aliased default)
_OCEAN_PRIMARY = _THEME_COLORS["ocean"]["primary"]   # "#0284C7"


def _spec(domain: str) -> dict:
    """Call with no dossier so DOMAIN_THEME/DOMAIN_LAYOUT are the fallback."""
    return generate_design_spec_from_industry(domain, description="", plan=None, domain_context=None)


# ---------------------------------------------------------------------------
# Core regression: saas must NOT collapse to ocean/default
# ---------------------------------------------------------------------------

def test_saas_primary_is_not_ocean():
    """Without the alias, 'saas' falls through DOMAIN_THEME.get() to 'ocean';
    with it, 'saas' → 'Government' → 'sharp' theme → primary #1E293B."""
    spec = _spec("saas")
    primary = spec["colorPalette"]["primary"]
    assert primary != _OCEAN_PRIMARY, (
        f"'saas' resolved to the ocean fallback primary ({_OCEAN_PRIMARY!r}); "
        "the alias is not being applied inside generate_design_spec_from_industry."
    )
    # sharp theme primary
    assert primary == _THEME_COLORS["sharp"]["primary"]


def test_saas_layout_navigation_is_topbar():
    """saas → Government layout which uses 'topbar', not the default 'sidebar'."""
    spec = _spec("saas")
    assert spec["layout"]["navigation"] == "topbar", (
        f"Expected 'topbar' for saas, got {spec['layout']['navigation']!r}"
    )


def test_saas_layout_density_is_compact():
    spec = _spec("saas")
    assert spec["layout"]["density"] == "compact"


# ---------------------------------------------------------------------------
# Alias coverage across common coarse domains
# ---------------------------------------------------------------------------

def test_hr_uses_hr_theme():
    spec = _spec("hr")
    assert spec["colorPalette"]["primary"] == _THEME_COLORS["hr"]["primary"]


def test_fintech_uses_finance_theme():
    spec = _spec("fintech")
    assert spec["colorPalette"]["primary"] == _THEME_COLORS["finance"]["primary"]


def test_healthcare_uses_healthcare_theme():
    spec = _spec("healthcare")
    assert spec["colorPalette"]["primary"] == _THEME_COLORS["healthcare"]["primary"]


# ---------------------------------------------------------------------------
# Diversity: coarse domains produce at least 3 distinct primary colors
# ---------------------------------------------------------------------------

def test_coarse_domains_produce_diverse_primaries():
    domains = ["general", "hr", "fintech", "healthcare", "saas"]
    primaries = {d: _spec(d)["colorPalette"]["primary"] for d in domains}
    distinct = set(primaries.values())
    assert len(distinct) >= 3, (
        f"Expected ≥3 distinct primary colors across {domains}, "
        f"got {len(distinct)}: {primaries}"
    )


# ---------------------------------------------------------------------------
# Palette override path is NOT broken by the alias
# (pass a minimal dossier that triggers the palette-character path)
# ---------------------------------------------------------------------------

def test_dossier_palette_override_still_works():
    """When the dossier carries a valid colorAnchor, it must override
    the domain-derived palette — the alias should not clobber that."""
    dossier = {
        "visualLanguage": {
            "colorAnchors": {"primary": "#FF0000"},
        }
    }
    spec = generate_design_spec_from_industry(
        "saas", description="", plan=None, domain_context=dossier
    )
    # The dossier anchor drives the color, not the domain alias
    # derive_palette("#FF0000") will produce a red-family primary, not ocean/sharp
    primary = spec["colorPalette"]["primary"]
    assert primary != _OCEAN_PRIMARY, "dossier override was ignored"
    assert primary != _THEME_COLORS["sharp"]["primary"], (
        "dossier override should produce a red-family primary, not the domain-alias sharp primary"
    )
