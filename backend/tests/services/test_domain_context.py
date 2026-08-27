"""Tests for backend/services/domain_context.py.

Focus: `build_domain_profile()` — the unified accessor that every
downstream agent now uses to inject discovery-dossier context into its
system prompt.

`detect_domain()` is a deterministic keyword classifier and is exercised
indirectly via the planner path; not duplicated here.
"""
from __future__ import annotations

import pytest

from services.domain_context import (
    _ROLE_SECTIONS,
    build_domain_profile,
    build_archetype_context,
)


# ── Sample dossier (mirrors the schema produced by domain_agent) ────────────

FULL_DOSSIER = {
    "domain": "Hospitality",
    "description": "Boutique hotel chain with guest experience focus",
    "confidence": 0.9,
    "personas": {
        "planner": "You are a hospitality systems planner.",
        "auth_agent": "You design auth for guest + staff users.",
        "schema_designer": "You model reservations + rooms + guests.",
        "qa_tester": "You validate guest-flow correctness.",
        "page_assembler": "You lay out booking-centric pages.",
    },
    "complianceNotes": ["pci", "gdpr"],
    "commonPitfalls": [
        "Forgetting room-availability calendar logic",
        "Mixing guest-facing and staff-facing surfaces",
    ],
    "entitySuggestions": [
        {"name": "Reservation", "likelyFields": ["guestId", "roomId", "checkIn", "checkOut"]},
        {"name": "Room", "likelyFields": ["number", "type", "rate"]},
        {"name": "Guest"},  # no fields
    ],
    "designPatterns": [
        {"name": "Reservation calendar", "description": "Drag-to-extend stays."},
        {"name": "Guest profile card", "description": "Loyalty + preferences."},
    ],
    "visualLanguage": {
        "paletteCharacter": "warm earth tones",
        "typographyTone": "refined serif",
        "densityPreference": "spacious",
    },
    "formPatterns": [
        {"pattern": "Multi-step booking form with date pickers"},
    ],
    "uncertainAreas": ["Whether housekeeping is in scope"],
}


# ── Falsy / empty inputs ────────────────────────────────────────────────────


def test_returns_empty_for_none():
    assert build_domain_profile(None, "planner") == ""


def test_returns_empty_for_empty_dict():
    assert build_domain_profile({}, "planner") == ""


def test_returns_empty_for_non_dict():
    """Defensive — caller might accidentally pass a string."""
    assert build_domain_profile("not a dict", "planner") == ""


def test_returns_empty_when_no_label_and_no_sections():
    """A dossier with neither a domain label nor any role-relevant content
    yields an empty profile — agent falls back to its generic prompt."""
    ctx = {"personas": {"planner": ""}, "commonPitfalls": []}
    assert build_domain_profile(ctx, "planner") == ""


# ── Role-aware section selection ────────────────────────────────────────────


def test_auth_agent_gets_compliance_and_pitfalls():
    """Auth agent has frozenset({persona, pitfalls, compliance}) — should
    see those but NOT visual language or design patterns (irrelevant to
    backend auth wiring)."""
    out = build_domain_profile(FULL_DOSSIER, "auth_agent")
    assert "Compliance regimes that apply" in out
    assert "Common pitfalls" in out
    assert "Your role-specific guidance" in out
    # Visual stuff is for UI agents — not for auth
    assert "Visual language" not in out
    assert "Design patterns" not in out


def test_component_builder_gets_visual_and_patterns():
    """Component builder is a UI agent — visual + patterns, no compliance."""
    out = build_domain_profile(FULL_DOSSIER, "component_builder")
    assert "Visual language" in out
    assert "Design patterns" in out
    assert "Common pitfalls" in out
    # Backend constraints don't belong in the component builder prompt
    assert "Compliance" not in out


def test_qa_tester_gets_uncertain_areas():
    """QA gets uncertainAreas — these are explicit caution flags."""
    out = build_domain_profile(FULL_DOSSIER, "qa_tester")
    assert "Areas of uncertainty" in out
    assert "housekeeping" in out
    assert "Compliance" in out


def test_planner_gets_everything_but_no_visual():
    """Planner sees pitfalls/compliance/entities/patterns/uncertain — but
    NOT visual language (that's the UI agents' concern)."""
    out = build_domain_profile(FULL_DOSSIER, "planner")
    assert "Common pitfalls" in out
    assert "Compliance" in out
    assert "Entity hints" in out
    assert "Design patterns" in out
    assert "Areas of uncertainty" in out
    assert "Visual language" not in out


def test_page_assembler_gets_forms():
    """Page assembler renders forms — formPatterns should appear."""
    out = build_domain_profile(FULL_DOSSIER, "page_assembler")
    assert "Form patterns" in out
    assert "booking form" in out


def test_seed_generator_gets_only_entities():
    """Seed generator just needs entity hints — no personas, no compliance,
    no visual, no patterns."""
    out = build_domain_profile(FULL_DOSSIER, "seed_generator")
    assert "Entity hints" in out
    assert "Common pitfalls" not in out
    assert "Compliance" not in out
    assert "Visual" not in out


def test_unknown_role_falls_back_to_persona_only():
    """An unrecognised role still gets the persona (if present) + header.
    No crash, no extra sections. This protects against typos in agent
    callsites."""
    ctx_with_persona = dict(FULL_DOSSIER)
    ctx_with_persona["personas"] = {"unknown_role": "Some persona text"}
    out = build_domain_profile(ctx_with_persona, "unknown_role")
    assert "## [DOMAIN PROFILE]" in out
    assert "Some persona text" in out
    assert "Common pitfalls" not in out


# ── Section rendering details ───────────────────────────────────────────────


def test_compliance_drops_lone_none():
    """'none' as the sole compliance entry means 'no regimes apply' — we
    skip rendering the section rather than emitting an empty list."""
    ctx = {"domain": "X", "complianceNotes": ["none"]}
    out = build_domain_profile(ctx, "auth_agent")
    assert "Compliance" not in out


def test_compliance_drops_none_when_mixed():
    """'none' alongside real regimes is just noise — drop it."""
    ctx = {"domain": "X", "complianceNotes": ["none", "hipaa"]}
    out = build_domain_profile(ctx, "auth_agent")
    assert "Compliance" in out
    assert "hipaa" in out
    assert "- none" not in out


def test_entity_hints_skipped_when_all_malformed():
    """A list of garbage (non-dict, empty) entities renders nothing."""
    ctx = {"domain": "X", "entitySuggestions": [None, {}, "junk"]}
    out = build_domain_profile(ctx, "contract_writer")
    assert "Entity hints" not in out


def test_entity_hints_renders_when_only_names():
    """Entities without `likelyFields` still render — just the name."""
    ctx = {
        "domain": "X",
        "entitySuggestions": [{"name": "Guest"}],
    }
    out = build_domain_profile(ctx, "contract_writer")
    assert "**Guest**" in out


def test_visual_section_omitted_when_all_fields_blank():
    """If paletteCharacter/typographyTone/densityPreference are all
    empty strings, don't render an empty section."""
    ctx = {
        "domain": "X",
        "visualLanguage": {
            "paletteCharacter": "",
            "typographyTone": "",
            "densityPreference": "",
        },
    }
    out = build_domain_profile(ctx, "page_assembler")
    assert "Visual" not in out


def test_visual_section_renders_color_anchors_when_present():
    """Dossier-provided hex anchors are surfaced in the [DOMAIN PROFILE]
    block so downstream agents (design, component, page) see exact hex
    codes — not just a free-text palette character. This is what makes
    option-1 (discovery-emits-hex) actually reach the LLM prompts."""
    ctx = {
        "domain": "Hospitality",
        "visualLanguage": {
            "paletteCharacter": "warm earth tones",
            "colorAnchors": {
                "primary": "#B26B3B",
                "secondary": "#7B9E89",
                "accent": "#D4A574",
            },
        },
    }
    out = build_domain_profile(ctx, "component_builder")
    assert "Color anchors (researched)" in out
    assert "#B26B3B" in out
    assert "#7B9E89" in out
    assert "#D4A574" in out
    # Anti-defaults note still mentions the bad anchors to avoid
    assert "#3b82f6" in out or "#10b981" in out


def test_visual_section_falls_back_when_only_palette_character():
    """When the dossier has paletteCharacter but no colorAnchors, render
    the legacy 'translate into hex' instruction so the LLM still knows
    not to default to generic SaaS colors."""
    ctx = {
        "domain": "X",
        "visualLanguage": {"paletteCharacter": "clinical blue-whites"},
    }
    out = build_domain_profile(ctx, "component_builder")
    assert "clinical blue-whites" in out
    assert "Color anchors" not in out
    # Anti-defaults guidance still present
    assert "#3b82f6" in out


def test_visual_section_renders_partial_anchors():
    """If only primary is provided, render that — don't crash on missing
    secondary/accent."""
    ctx = {
        "domain": "X",
        "visualLanguage": {
            "paletteCharacter": "neon-on-dark",
            "colorAnchors": {"primary": "#A855F7"},
        },
    }
    out = build_domain_profile(ctx, "component_builder")
    assert "#A855F7" in out
    assert "primary" in out


def test_visual_section_renders_font_family_as_constraint():
    """When dossier provides a concrete fontFamily, surface it as a
    bind-don't-swap constraint with both spec and CSS guidance."""
    ctx = {
        "domain": "Boutique Hotels",
        "visualLanguage": {
            "typographyTone": "editorial",
            "fontFamily": '"Playfair Display", Georgia, serif',
        },
    }
    out = build_domain_profile(ctx, "design_agent")
    assert "Playfair Display" in out
    # Should reference both the spec and CSS surface
    assert "typography.fontFamily" in out
    assert "globals.css" in out
    # Anti-default note
    assert "Inter" in out


def test_visual_section_falls_back_to_tone_hint_without_font_family():
    """typographyTone alone (no fontFamily) renders the legacy hint about
    picking a tone-appropriate font."""
    ctx = {
        "domain": "X",
        "visualLanguage": {"typographyTone": "playful"},
    }
    out = build_domain_profile(ctx, "design_agent")
    assert "playful" in out
    assert "serif for refined" in out  # legacy hint copy
    # No specific font name surfaced
    assert "Playfair" not in out


def test_pitfalls_strips_empty_strings():
    """Empty / whitespace pitfalls don't render as `- ` bullets."""
    ctx = {
        "domain": "X",
        "commonPitfalls": ["Real one", "", "  ", "Another"],
    }
    out = build_domain_profile(ctx, "planner")
    assert "- Real one" in out
    assert "- Another" in out
    assert "- \n" not in out


def test_uncertain_caps_at_six():
    """Defensive cap — keeps prompt size bounded when the dossier
    flagged unusually many uncertain areas."""
    ctx = {
        "domain": "X",
        "uncertainAreas": [f"area-{i}" for i in range(20)],
    }
    out = build_domain_profile(ctx, "qa_tester")
    assert out.count("- area-") == 6


# ── Output framing ──────────────────────────────────────────────────────────


def test_output_starts_with_double_newline():
    """The block prepends \\n\\n so it concatenates cleanly to a base prompt
    via `BASE + build_domain_profile(...)`. The trailing newline keeps
    the section visually separated."""
    out = build_domain_profile(FULL_DOSSIER, "planner")
    assert out.startswith("\n\n")
    assert out.endswith("\n")


def test_output_contains_canonical_header():
    """Header format is stable — agents may grep for it in tests."""
    out = build_domain_profile(FULL_DOSSIER, "planner")
    assert "## [DOMAIN PROFILE] — Hospitality" in out


def test_output_includes_description_when_present():
    out = build_domain_profile(FULL_DOSSIER, "planner")
    assert "Boutique hotel chain" in out


def test_output_omits_description_when_blank():
    ctx = dict(FULL_DOSSIER)
    ctx["description"] = ""
    out = build_domain_profile(ctx, "planner")
    assert "## [DOMAIN PROFILE]" in out
    assert "Boutique hotel chain" not in out


# ── Coverage of every known role ────────────────────────────────────────────


@pytest.mark.parametrize("role", sorted(_ROLE_SECTIONS.keys()))
def test_every_role_produces_non_empty_block_with_full_dossier(role):
    """Every role in _ROLE_SECTIONS produces a non-empty block when given
    a complete dossier. Guards against typos in section keys or missing
    renderers when a new role is added."""
    out = build_domain_profile(FULL_DOSSIER, role)
    assert out, f"role={role} produced empty block from full dossier"
    assert "## [DOMAIN PROFILE]" in out


# ── Slice 3: app-archetype context blocks ───────────────────────────────


def test_archetype_context_returns_empty_for_none_or_unknown():
    assert build_archetype_context(None) == ""
    assert build_archetype_context("") == ""
    assert build_archetype_context("no-such-archetype") == ""


def test_visual_product_search_archetype_context_covers_persona_data_ux():
    """The visual-product-search block must give the planner all three
    prompt-anchor sections: persona, data shape, UX cues."""
    out = build_archetype_context("visual-product-search")
    assert out.startswith("\n\n")
    assert out.endswith("\n")
    assert "## [APP ARCHETYPE CONTEXT]" in out
    assert "Visual Product Search" in out
    # Persona
    assert "Persona" in out
    assert "camera" in out.lower()
    # Data shape — the canonical entities
    assert "scan_events" in out
    assert "retail_sources" in out
    assert "users" in out
    # UX cues
    assert "Mobile-first" in out or "mobile" in out.lower()
    assert "Grid" in out or "cards" in out.lower()


