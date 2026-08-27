"""Tests for services.visual_lock_presets — Slice A (2026-08-13)."""
from __future__ import annotations

import pytest

from schemas.design_brief import VisualLock
from services.visual_lock_presets import (
    ACADEMIC_FRESH,
    ADMIN_NEUTRAL,
    CLINICAL_CALM,
    CREATIVE_BOLD,
    DATA_DENSE,
    EDITORIAL_LIGHT,
    FIELD_UTILITY,
    TRUST_NAVY,
    WELLNESS_WARM,
    pick_preset,
    pick_preset_from_plan,
)


# Every preset — used by the generic shape parametrization tests below
# so all 9 presets are validated by the same invariants.
_ALL_PRESETS = (
    WELLNESS_WARM, ADMIN_NEUTRAL, CREATIVE_BOLD, DATA_DENSE, TRUST_NAVY,
    EDITORIAL_LIGHT, ACADEMIC_FRESH, CLINICAL_CALM, FIELD_UTILITY,
)


# --------------------------------------------------------------------------- #
# Preset shape
# --------------------------------------------------------------------------- #


_REQUIRED_PALETTE_KEYS = {"bg", "fg", "accent", "muted", "badge",
                          "danger", "success", "subtle"}
_REQUIRED_TYPOGRAPHY_KEYS = {"display", "body"}


@pytest.mark.parametrize("preset", _ALL_PRESETS)
def test_preset_has_full_palette(preset: VisualLock):
    """Every preset must ship all 8 palette keys — downstream picks any
    of them and a partial preset would leave gaps that fall back to
    derived (undoing the whole point of the lock)."""
    assert _REQUIRED_PALETTE_KEYS <= set(preset.palette.keys())
    for k in _REQUIRED_PALETTE_KEYS:
        v = preset.palette[k]
        assert isinstance(v, str) and v.startswith("#") and len(v) == 7, \
            f"{preset.preset_name}.palette.{k} = {v!r} not a #RRGGBB"


@pytest.mark.parametrize("preset", _ALL_PRESETS)
def test_preset_typography_ships_display_and_body(preset: VisualLock):
    assert _REQUIRED_TYPOGRAPHY_KEYS <= set(preset.typography.keys())


@pytest.mark.parametrize("preset", _ALL_PRESETS)
def test_preset_radius_scale(preset: VisualLock):
    assert {"sm", "md", "lg"} <= set(preset.radius.keys())
    # Monotonic non-decreasing: sm <= md <= lg
    assert preset.radius["sm"] <= preset.radius["md"] <= preset.radius["lg"]


@pytest.mark.parametrize("preset", _ALL_PRESETS)
def test_preset_names_are_distinct_and_populated(preset: VisualLock):
    assert preset.preset_name  # non-empty


def test_preset_names_are_all_distinct():
    names = {p.preset_name for p in _ALL_PRESETS}
    assert len(names) == len(_ALL_PRESETS)


def test_visual_lock_is_active_flag():
    assert VisualLock().is_active() is False
    assert WELLNESS_WARM.is_active() is True


# --------------------------------------------------------------------------- #
# pick_preset dispatch
# --------------------------------------------------------------------------- #


def test_pick_preset_yoga_studio_hits_wellness():
    """A yoga studio booking app is the canonical wellness case.
    'yoga', 'studio', 'booking', 'class', 'session' all hit; we need 2+."""
    got = pick_preset(
        domain="wellness",
        industry="yoga studios",
        description="A booking platform for yoga classes and sessions.",
    )
    assert got.preset_name == "wellness-warm"


def test_pick_preset_agency_portfolio_hits_creative():
    got = pick_preset(
        domain="creative",
        industry="design agency",
        description="A portfolio and brand showcase for a boutique agency.",
    )
    assert got.preset_name == "creative-bold"


def test_pick_preset_iot_sensor_dashboard_hits_data():
    got = pick_preset(
        domain="analytics",
        industry="IoT",
        description="Sensor telemetry dashboard with real-time metrics.",
    )
    assert got.preset_name == "data-dense"


def test_pick_preset_generic_crud_falls_back_to_admin():
    got = pick_preset(
        domain="general",
        industry="internal tool",
        description="An internal tool for managing employees and reports.",
    )
    assert got.preset_name == "admin-neutral"


def test_pick_preset_case_insensitive():
    """Uppercased inputs still hit."""
    got = pick_preset(
        domain="WELLNESS",
        industry="YOGA STUDIOS",
        description="Booking flow for Meditation Classes.",
    )
    assert got.preset_name == "wellness-warm"


def test_pick_preset_single_hit_does_not_trigger():
    """One keyword is not enough — a stray 'gallery' in an admin app
    must not switch the whole app to CREATIVE_BOLD."""
    got = pick_preset(
        domain="internal",
        industry="ops",
        description="Employee gallery of headshots for the internal directory.",
    )
    # Only "gallery" from CREATIVE; falls back to admin.
    assert got.preset_name == "admin-neutral"


def test_pick_preset_wellness_wins_over_creative_when_both_hit():
    """A 'photography studio booking' app must pick WELLNESS (booking is
    the dominant intent), not CREATIVE. The picker's order enforces this."""
    got = pick_preset(
        domain="services",
        industry="photography studio",
        description="Booking classes and sessions for photography students.",
    )
    assert got.preset_name == "wellness-warm"


# --------------------------------------------------------------------------- #
# TRUST_NAVY — the banking / fintech preset
# --------------------------------------------------------------------------- #


def test_trust_navy_preset_name():
    assert TRUST_NAVY.preset_name == "trust-navy"


def test_trust_navy_palette_hex_values_are_byte_exact():
    """These hexes are the contract — downstream code (design_language,
    design_compiler, brand_extractor) may pin to specific values so a
    silent drift here would be an invisible break."""
    assert TRUST_NAVY.palette["bg"] == "#F5F6F8"
    assert TRUST_NAVY.palette["fg"] == "#0B2545"
    assert TRUST_NAVY.palette["accent"] == "#1D3557"
    assert TRUST_NAVY.palette["badge"] == "#C9A961"
    assert TRUST_NAVY.palette["subtle"] == "#FFFFFF"


def test_trust_navy_typography_families():
    assert TRUST_NAVY.typography["display"] == "Source Serif 4"
    assert TRUST_NAVY.typography["body"] == "Source Sans 3"
    assert TRUST_NAVY.typography["mono"] == "JetBrains Mono"


def test_pick_preset_banking_hits_trust_navy():
    """Two-hit threshold: 'bank' + 'loan' triggers TRUST_NAVY."""
    got = pick_preset_from_plan({
        "description": "Community bank loan origination platform for officers",
    })
    assert got.preset_name == "trust-navy"


def test_pick_preset_fintech_dashboard_still_hits_trust_navy():
    """A fintech dashboard mentions 'dashboard' (DATA keyword) but should
    still land on TRUST_NAVY because 'fintech' + 'account' both trigger
    banking, and the picker runs banking before data."""
    got = pick_preset_from_plan({
        "description": "Fintech dashboard for account monitoring and treasury",
    })
    assert got.preset_name == "trust-navy"


def test_pick_preset_yoga_still_wellness_after_trust_added():
    """Regression guard: adding TRUST_NAVY must not steal wellness apps.
    'Yoga studio booking' should still resolve to WELLNESS_WARM."""
    got = pick_preset_from_plan({
        "description": "Yoga studio booking",
    })
    assert got.preset_name == "wellness-warm"


def test_pick_preset_single_banking_hit_falls_back_to_admin():
    """A single 'bank' hit (e.g. 'file cabinet' — no it isn't but you
    get the idea) shouldn't trigger the banking preset. Only 'credit'
    hits here; one hit stays on ADMIN_NEUTRAL."""
    got = pick_preset("", "", "A tool to track credit card rewards points")
    # "credit" hits banking (1); "card" is not in the banking vocab.
    # 1 hit → admin fallback.
    assert got.preset_name == "admin-neutral"


def test_pick_preset_handles_missing_inputs():
    """None / empty inputs should not crash — plans in the wild sometimes
    omit industry or description entirely."""
    got = pick_preset("", "", "")
    assert got.preset_name == "admin-neutral"
    got = pick_preset(None, None, None)  # type: ignore[arg-type]
    assert got.preset_name == "admin-neutral"


# --------------------------------------------------------------------------- #
# EDITORIAL_LIGHT / ACADEMIC_FRESH / CLINICAL_CALM / FIELD_UTILITY
# --------------------------------------------------------------------------- #


def test_editorial_light_preset_name():
    assert EDITORIAL_LIGHT.preset_name == "editorial-light"


def test_editorial_light_palette_hex_values_are_byte_exact():
    """Byte-exact — downstream may pin. Silent drift = invisible break."""
    assert EDITORIAL_LIGHT.palette["bg"] == "#FAFAF8"
    assert EDITORIAL_LIGHT.palette["fg"] == "#1A1A1A"
    assert EDITORIAL_LIGHT.palette["accent"] == "#7C2D12"
    assert EDITORIAL_LIGHT.palette["badge"] == "#B45309"
    assert EDITORIAL_LIGHT.palette["subtle"] == "#FFFFFF"


def test_editorial_light_typography_families():
    assert EDITORIAL_LIGHT.typography["display"] == "Fraunces"
    assert EDITORIAL_LIGHT.typography["body"] == "Inter"
    assert EDITORIAL_LIGHT.typography["mono"] == "JetBrains Mono"


def test_academic_fresh_preset_name():
    assert ACADEMIC_FRESH.preset_name == "academic-fresh"


def test_academic_fresh_palette_hex_values_are_byte_exact():
    assert ACADEMIC_FRESH.palette["bg"] == "#F0F7FA"
    assert ACADEMIC_FRESH.palette["fg"] == "#0F172A"
    assert ACADEMIC_FRESH.palette["accent"] == "#0369A1"
    assert ACADEMIC_FRESH.palette["badge"] == "#059669"
    assert ACADEMIC_FRESH.palette["subtle"] == "#FFFFFF"


def test_academic_fresh_typography_families():
    assert ACADEMIC_FRESH.typography["display"] == "Merriweather"
    assert ACADEMIC_FRESH.typography["body"] == "Inter"


def test_clinical_calm_preset_name():
    assert CLINICAL_CALM.preset_name == "clinical-calm"


def test_clinical_calm_palette_hex_values_are_byte_exact():
    assert CLINICAL_CALM.palette["bg"] == "#F8FAFC"
    assert CLINICAL_CALM.palette["fg"] == "#0F172A"
    assert CLINICAL_CALM.palette["accent"] == "#0891B2"
    assert CLINICAL_CALM.palette["badge"] == "#059669"
    assert CLINICAL_CALM.palette["subtle"] == "#FFFFFF"


def test_clinical_calm_typography_families():
    assert CLINICAL_CALM.typography["display"] == "Source Sans 3"
    assert CLINICAL_CALM.typography["body"] == "Source Sans 3"


def test_field_utility_preset_name():
    assert FIELD_UTILITY.preset_name == "field-utility"


def test_field_utility_palette_hex_values_are_byte_exact():
    assert FIELD_UTILITY.palette["bg"] == "#F8FAFC"
    assert FIELD_UTILITY.palette["fg"] == "#0F172A"
    assert FIELD_UTILITY.palette["accent"] == "#EA580C"
    assert FIELD_UTILITY.palette["badge"] == "#0F172A"
    assert FIELD_UTILITY.palette["subtle"] == "#FFFFFF"


def test_field_utility_typography_families():
    # Utility surface — no serif on either axis.
    assert FIELD_UTILITY.typography["display"] == "Inter"
    assert FIELD_UTILITY.typography["body"] == "Inter"


def test_pick_preset_clinical_domain_hits_clinical_calm():
    got = pick_preset_from_plan({
        "description": "Medical clinic patient appointment scheduling and prescriptions",
    })
    assert got.preset_name == "clinical-calm"


def test_pick_preset_field_service_hits_field_utility():
    got = pick_preset_from_plan({
        "description": "HVAC field service dispatch and work order tracking for technicians",
    })
    assert got.preset_name == "field-utility"


def test_pick_preset_e_learning_hits_academic_fresh():
    got = pick_preset_from_plan({
        "description": "Online course platform for cohort-based e-learning with quizzes",
    })
    assert got.preset_name == "academic-fresh"


def test_pick_preset_editorial_cms_hits_editorial_light():
    got = pick_preset_from_plan({
        "description": "Editorial CMS for a magazine with drafts and review workflow",
    })
    assert got.preset_name == "editorial-light"


# ── Regression: existing presets still win on their canonical descriptions

def test_regression_yoga_still_wellness_after_new_presets():
    got = pick_preset_from_plan({"description": "Yoga studio class booking and membership"})
    assert got.preset_name == "wellness-warm"


def test_regression_community_bank_loan_still_trust_navy():
    got = pick_preset_from_plan({"description": "Community bank loan origination portal"})
    assert got.preset_name == "trust-navy"


def test_regression_agency_portfolio_still_creative():
    got = pick_preset_from_plan({
        "description": "A portfolio and brand showcase for a boutique agency",
    })
    assert got.preset_name == "creative-bold"


def test_regression_iot_dashboard_still_data_dense():
    got = pick_preset_from_plan({
        "description": "Sensor telemetry dashboard with real-time metrics",
    })
    assert got.preset_name == "data-dense"


def test_single_editorial_hit_falls_back_to_admin():
    """A stray 'blog' in an unrelated app should not switch EVERYTHING to
    editorial. Two-hit threshold enforces this."""
    got = pick_preset("", "", "An HR tool with a small blog for company updates.")
    assert got.preset_name == "admin-neutral"


# --------------------------------------------------------------------------- #
# New-vocab preset routing — payment / subscription / analytics / messaging
# / dev-tools. All map to EXISTING presets (no new presets introduced).
# --------------------------------------------------------------------------- #


def test_pick_preset_payment_processing_hits_trust_navy():
    """A Stripe-style payment platform routes to TRUST_NAVY — same
    restrained fintech identity as banking."""
    got = pick_preset_from_plan({
        "description": "Stripe-style payment gateway for merchants with "
                       "chargebacks and payouts",
    })
    assert got.preset_name == "trust-navy"


def test_pick_preset_subscription_billing_hits_trust_navy():
    """SaaS subscription billing lives on the same trust-navy preset."""
    got = pick_preset_from_plan({
        "description": "SaaS subscription billing with dunning management "
                       "and MRR reporting",
    })
    assert got.preset_name == "trust-navy"


def test_pick_preset_bi_platform_hits_data_dense():
    """Business intelligence dashboards route to DATA_DENSE."""
    got = pick_preset_from_plan({
        "description": "Business intelligence dashboard platform for "
                       "analysts, connected datasources",
    })
    assert got.preset_name == "data-dense"


def test_pick_preset_messaging_hits_creative_bold():
    """Slack-style messaging routes to CREATIVE_BOLD — the bold-identity
    register fits the chat product read."""
    got = pick_preset_from_plan({
        "description": "Slack-style team messaging platform with channels "
                       "and threads",
    })
    assert got.preset_name == "creative-bold"


def test_pick_preset_dev_tools_hits_data_dense():
    """CI/CD + observability tooling routes to DATA_DENSE — same dense-
    utility read as the analytics vocab."""
    got = pick_preset_from_plan({
        "description": "CI/CD monitoring platform with incidents alerts "
                       "and oncall",
    })
    assert got.preset_name == "data-dense"


# ── Regression: existing presets still win on their canonical descriptions
# after the new keyword additions.


def test_regression_credit_card_rewards_still_admin():
    """Single 'credit' hit — the added payment/subscription keywords must
    not cause a spurious trust-navy trigger for a rewards-tracker."""
    got = pick_preset("", "", "A tool to track credit card rewards points")
    assert got.preset_name == "admin-neutral"


def test_regression_hr_blog_still_admin_after_messaging_added():
    """A stray 'blog' + no messaging keywords still falls to admin."""
    got = pick_preset("", "", "An HR tool with a small blog for company updates.")
    assert got.preset_name == "admin-neutral"
