"""Tests for services.vocab_composer — multi-vocab COMPOSE stack.

The LLM seam is monkeypatched. Merge + validate logic runs against real
production vocabularies + presets so the invariants are enforced against
shipping data shapes.
"""
from __future__ import annotations

import asyncio

import pytest

from schemas.design_brief import VisualLock
from services import vocab_composer, vocab_modifier
from services.archetype_vocabulary import load_vocabulary
from services.vocab_composer import compose_vocab_and_design
from services.visual_lock_presets import (
    ADMIN_NEUTRAL,
    CREATIVE_BOLD,
    TRUST_NAVY,
    CLINICAL_CALM,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _hybrid_plan() -> dict:
    return {
        "description": (
            "A neobank for freelancers with in-app support chat, "
            "direct-message threads and subscription billing tiers."
        ),
        "entities": [
            {"name": "Account", "columns": ["holder", "balance"]},
            {"name": "Transaction", "columns": ["amount", "postedAt"]},
            {"name": "ChatChannel", "columns": ["name"]},
        ],
        "actors": [
            {"role": "member"},
            {"role": "support"},
        ],
    }


def _candidates() -> list:
    return [
        load_vocabulary("banking-platform"),
        load_vocabulary("messaging-platform"),
    ]


def _presets() -> list:
    return [TRUST_NAVY, CREATIVE_BOLD]


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    vocab_composer._reset_cache_for_tests()
    vocab_modifier._reset_cache_for_tests()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield
    vocab_composer._reset_cache_for_tests()
    vocab_modifier._reset_cache_for_tests()


# --------------------------------------------------------------------- #
# Happy path — LLM composes across candidates
# --------------------------------------------------------------------- #

def test_happy_path_composes_vocab_and_lock(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "reasoning": "Banking is the anchor; messaging adds channels/threads screens.",
            "vocab": {
                "primary_screens_per_persona": {
                    "support": ["channels", "threads", "accounts"],
                },
                "signature_states": {
                    "empty_accounts": "No accounts yet. Open one to get started.",
                },
            },
            "visual_lock": {
                # Moderate desaturated green — clears 3:1 contrast on
                # TRUST_NAVY's near-white bg (#F5F6F8) and stays under
                # the default 0.75 saturation cap. Verifies novel-hex
                # acceptance under the relaxed palette rule (no brief
                # provided → default cap).
                "palette": {"accent": "#2E5C3E"},
                "typography": {"display": "Space Grotesk"},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)

    vocab, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert prov["source"] == "composed"
    assert prov["primary_vocab"] == "banking-platform"
    assert prov["primary_preset"] == "trust-navy"
    assert prov["preset_source"] == "cherry_picked"

    # Primary vocab persona added.
    assert "support" in vocab.primary_screens_per_persona
    assert vocab.primary_screens_per_persona["support"] == ["channels", "threads", "accounts"]

    # Novel accent + cherry-picked font landed.
    assert lock.palette["accent"] == "#2E5C3E"
    assert lock.typography["display"] == "Space Grotesk"
    # Non-overridden slots came from TRUST_NAVY.
    assert lock.palette["bg"] == TRUST_NAVY.palette["bg"]

    # Secondary vocab's personas filled in gaps.
    banking = load_vocabulary("banking-platform")
    for role in banking.primary_screens_per_persona:
        assert role in vocab.primary_screens_per_persona


# --------------------------------------------------------------------- #
# Remove authority
# --------------------------------------------------------------------- #

def test_remove_persona_applied(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "remove": {"personas": ["compliance"]},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)

    base = load_vocabulary("banking-platform")
    assert "compliance" in base.primary_screens_per_persona
    vocab, _lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert "compliance" not in vocab.primary_screens_per_persona
    assert "compliance" in prov["changes"]["personas_removed"]


def test_remove_refuses_when_only_one_persona_would_remain(monkeypatch):
    """Guard: never drop below one persona/screen."""
    solo = load_vocabulary("banking-platform")

    async def fake_llm(_prompt, *, model, timeout_s):
        # Ask to remove every persona.
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "remove": {"personas": list(solo.primary_screens_per_persona.keys())},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(
        compose_vocab_and_design([solo], [TRUST_NAVY], _hybrid_plan()),
    )
    # At least one persona survives.
    assert len(vocab.primary_screens_per_persona) >= 1
    warnings = " ".join(prov["changes"]["warnings"])
    assert "refused to remove last persona" in warnings


# --------------------------------------------------------------------- #
# Shape rejection
# --------------------------------------------------------------------- #

def test_invalid_shape_dropped(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "component_preferences": {
                    "chats": {"shape": "custom-view", "primary_field": "name"},
                    "channels": {"shape": "card-list", "primary_field": "name"},
                }
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    rejected = " ".join(prov["changes"]["shapes_rejected"])
    assert "chats" in rejected and "custom-view" in rejected
    # Valid entry landed.
    assert vocab.component_preferences["channels"].shape == "card-list"


# --------------------------------------------------------------------- #
# Hex validation (WCAG contrast + saturation, NOT preset allowlist)
# --------------------------------------------------------------------- #

def test_low_contrast_accent_rejected_and_replaced(monkeypatch):
    """Light lavender accent on TRUST_NAVY's near-white bg tanks contrast."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {
                # #ABCDEF (light lavender) on #F5F6F8 bg = ~1.5:1 — below
                # the 3.0:1 UI-component bar for accent. The relaxed rule
                # no longer requires the hex to appear in a candidate
                # preset; it only requires that it clear the accessibility
                # threshold. This one fails contrast, so it's rejected.
                "palette": {"accent": "#ABCDEF"},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    rejected = " ".join(prov["changes"]["hexes_rejected"])
    assert "accent" in rejected and "ABCDEF" in rejected.upper()
    assert "contrast" in rejected.lower()
    # Fell back to TRUST_NAVY's accent.
    assert lock.palette["accent"] == TRUST_NAVY.palette["accent"]


def test_novel_hex_survives_when_contrast_ok(monkeypatch):
    """LLM may propose a hex NOT present in the candidate presets."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            # #1B4332 (deep evergreen) — not in TRUST_NAVY or CREATIVE_BOLD,
            # clears 3:1 on #F5F6F8 bg, moderate saturation. New rule
            # says: pass it through.
            "visual_lock": {"palette": {"accent": "#1B4332"}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert lock.palette["accent"] == "#1B4332"
    rejected = " ".join(prov["changes"]["hexes_rejected"])
    assert "1B4332" not in rejected.upper()


class _FakeIdentity:
    """Minimal duck-typed identity for the composer's register reader."""
    def __init__(self, register):
        self.register = register


class _FakeBrief:
    def __init__(self, register):
        self.identity = _FakeIdentity(register)


def test_oversaturated_accent_rejected_on_calm_brief(monkeypatch):
    """Hot pink accent on a 'calm' brief exceeds the 0.55 saturation cap."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            # Deep pink — contrast is fine against light bg, but
            # saturation is ~1.0, well above the calm cap of 0.55.
            "visual_lock": {"palette": {"accent": "#FF1493"}},
        }

    brief = _FakeBrief(register=["calm", "professional"])

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    rejected = " ".join(prov["changes"]["hexes_rejected"])
    assert "accent" in rejected and "FF1493" in rejected.upper()
    assert "saturation" in rejected.lower()
    assert lock.palette["accent"] == TRUST_NAVY.palette["accent"]


def test_saturated_accent_allowed_on_playful_brief(monkeypatch):
    """A vivid pink (sat ~0.82) survives on a 'playful' brief (cap 0.95)."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            # #E91E63 (pink-500) — sat ~0.82; would fail the default 0.75
            # cap and the calm 0.55 cap, but sits under the bold 0.95 cap.
            "visual_lock": {"palette": {"accent": "#E91E63"}},
        }

    brief = _FakeBrief(register=["bold", "playful"])
    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    rejected = " ".join(prov["changes"]["hexes_rejected"])
    assert "E91E63" not in rejected.upper()
    assert lock.palette["accent"] == "#E91E63"


def test_invalid_hex_format_rejected(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {"palette": {"accent": "not-a-hex"}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    rejected = " ".join(prov["changes"]["hexes_rejected"])
    assert "accent" in rejected and "invalid hex" in rejected.lower()
    assert lock.palette["accent"] == TRUST_NAVY.palette["accent"]


# --------------------------------------------------------------------- #
# Font rejection
# --------------------------------------------------------------------- #

def test_invalid_font_replaced_with_primary_preset(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {
                "typography": {"body": "Comic Sans"},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    rejected = " ".join(prov["changes"]["fonts_rejected"])
    assert "body" in rejected and "Comic Sans" in rejected
    assert lock.typography["body"] == TRUST_NAVY.typography["body"]


# --------------------------------------------------------------------- #
# Section invariant enforcement
# --------------------------------------------------------------------- #

def test_section_missing_empty_state_dropped(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                # "invoices" section — but no matching empty_invoices_draft state.
                "section_recipes": {"invoices": ["draft"]},
                # Provide the filter but NOT the signature state.
                "section_filters": {"draft": {"status": ["draft"]}},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert "invoices" not in vocab.section_recipes
    warnings = " ".join(prov["changes"]["warnings"])
    assert "draft" in warnings


# --------------------------------------------------------------------- #
# Single-fallback cascade
# --------------------------------------------------------------------- #

def test_single_fallback_on_llm_timeout(monkeypatch):
    async def fake_composer_llm(_prompt, *, model, timeout_s):
        raise asyncio.TimeoutError("composer timed out")

    # modify_vocab's LLM seam still works — returns a small diff.
    async def fake_modifier_llm(_prompt, *, model, timeout_s):
        return {"signature_states": {"empty_transactions": "single-fallback copy."}}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)
    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_modifier_llm)

    vocab, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert prov["source"] == "single_fallback"
    assert prov["primary_vocab"] == "banking-platform"
    assert prov["primary_preset"] == "trust-navy"
    assert "timed out" in prov["reason"].lower() or "timeout" in prov["reason"].lower()
    # Single-vocab modifier's payload survived.
    assert vocab.signature_states["empty_transactions"] == "single-fallback copy."
    # Lock came from candidate_presets[0].
    assert lock is TRUST_NAVY


# --------------------------------------------------------------------- #
# Base-fallback cascade
# --------------------------------------------------------------------- #

def test_base_fallback_when_both_layers_fail(monkeypatch):
    async def fake_composer_llm(*_a, **_kw):
        raise RuntimeError("composer down")

    async def fake_modifier_llm(*_a, **_kw):
        raise RuntimeError("modifier down too")

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)
    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_modifier_llm)

    vocab, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert prov["source"] == "base_fallback"
    # Base candidate returned untouched.
    assert vocab is _candidates()[0] or vocab.id == "banking-platform"
    assert lock is TRUST_NAVY


# --------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------- #

def test_cache_returns_after_first_call(monkeypatch):
    call_count = {"n": 0}

    async def fake_llm(_prompt, *, model, timeout_s):
        call_count["n"] += 1
        return {"primary_vocab": "banking-platform", "primary_preset": "trust-navy", "vocab": {}}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)

    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    v1, l1, prov1 = _run(compose_vocab_and_design(cands, presets, plan))
    v2, l2, prov2 = _run(compose_vocab_and_design(cands, presets, plan))
    assert call_count["n"] == 1
    assert prov1["source"] == "composed"
    assert prov2["source"] == "cached"


# --------------------------------------------------------------------- #
# Validation of required inputs
# --------------------------------------------------------------------- #

def test_empty_candidates_raises():
    with pytest.raises(ValueError):
        _run(compose_vocab_and_design([], [TRUST_NAVY], _hybrid_plan()))


def test_empty_presets_raises():
    with pytest.raises(ValueError):
        _run(compose_vocab_and_design(_candidates(), [], _hybrid_plan()))


# --------------------------------------------------------------------- #
# Patterns block in the prompt
# --------------------------------------------------------------------- #

def test_patterns_appear_in_built_prompt():
    """User-selected patterns render as a bulleted block with implied-hint."""
    patterns = [
        {
            "name": "Capacity Bar",
            "description": "Visual saturation indicator for slot bookings",
            "design_hint": "prefer horizontal fill widgets over numeric readouts",
        },
        {"title": "Waitlist FIFO", "summary": "First-in-first-out queue"},
        "Tiered Windows",  # string form also accepted
    ]
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
        patterns=patterns,
    )
    assert "USER-SELECTED DESIGN PATTERNS" in prompt
    assert "Capacity Bar" in prompt
    assert "Waitlist FIFO" in prompt
    assert "First-in-first-out queue" in prompt
    assert "Tiered Windows" in prompt
    # design_hint surfaces as implied-line.
    assert "prefer horizontal fill widgets" in prompt


def test_patterns_block_absent_when_no_patterns():
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
    )
    assert "USER-SELECTED DESIGN PATTERNS" not in prompt


def test_cache_key_differs_when_patterns_differ():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    k_none = vocab_composer.cache_key(cands, presets, plan)
    k_a = vocab_composer.cache_key(cands, presets, plan, patterns=[{"name": "Capacity Bar"}])
    k_b = vocab_composer.cache_key(cands, presets, plan, patterns=[{"name": "Waitlist FIFO"}])
    assert k_none != k_a
    assert k_a != k_b
    # Order-independent: same set of patterns hashes identically regardless of order.
    k_a_reorder = vocab_composer.cache_key(
        cands, presets, plan,
        patterns=[{"name": "Waitlist FIFO"}, {"name": "Capacity Bar"}],
    )
    k_ab = vocab_composer.cache_key(
        cands, presets, plan,
        patterns=[{"name": "Capacity Bar"}, {"name": "Waitlist FIFO"}],
    )
    assert k_a_reorder == k_ab


# --------------------------------------------------------------------- #
# Variance seed
# --------------------------------------------------------------------- #

def test_variance_seed_appears_in_built_prompt():
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
        variance_seed=0xDEADBEEF,
    )
    assert "VARIANCE TOKEN" in prompt
    assert str(0xDEADBEEF) in prompt


def test_variance_line_absent_when_no_seed():
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
    )
    assert "VARIANCE TOKEN" not in prompt


def test_cache_key_differs_when_variance_differs():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    k_none = vocab_composer.cache_key(cands, presets, plan)
    k_1 = vocab_composer.cache_key(cands, presets, plan, variance_seed=1)
    k_2 = vocab_composer.cache_key(cands, presets, plan, variance_seed=2)
    assert k_none != k_1
    assert k_1 != k_2
    # Same seed → same key.
    k_1b = vocab_composer.cache_key(cands, presets, plan, variance_seed=1)
    assert k_1 == k_1b


def test_same_seed_same_inputs_hits_cache(monkeypatch):
    """Two calls with identical inputs + seed → LLM invoked once."""
    calls = {"n": 0}

    async def fake_llm(_prompt, *, model, timeout_s):
        calls["n"] += 1
        return {"primary_vocab": "banking-platform", "primary_preset": "trust-navy", "vocab": {}}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    plan = _hybrid_plan()
    _run(compose_vocab_and_design(_candidates(), _presets(), plan, variance_seed=42))
    _v, _l, prov = _run(compose_vocab_and_design(_candidates(), _presets(), plan, variance_seed=42))
    assert calls["n"] == 1
    assert prov["source"] == "cached"


def test_different_seed_misses_cache(monkeypatch):
    """Same inputs, different seed → separate LLM call."""
    calls = {"n": 0}

    async def fake_llm(_prompt, *, model, timeout_s):
        calls["n"] += 1
        return {"primary_vocab": "banking-platform", "primary_preset": "trust-navy", "vocab": {}}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    plan = _hybrid_plan()
    _run(compose_vocab_and_design(_candidates(), _presets(), plan, variance_seed=42))
    _run(compose_vocab_and_design(_candidates(), _presets(), plan, variance_seed=43))
    assert calls["n"] == 2


# --------------------------------------------------------------------- #
# CREATIVE-4 — user-pinned visual-lock fields survive composition
# --------------------------------------------------------------------- #

class _LockedBrief:
    """Duck-typed DesignBrief carrying a visual_lock + _locked_fields.

    Mirrors the shape the composer reads: an object with an
    ``identity`` (for saturation-cap lookup), a ``visual_lock`` object
    with palette/typography/radius/shadow dicts, and a
    ``_locked_fields`` list of dot-paths.
    """

    def __init__(self, visual_lock, locked_fields, register=None):
        self.identity = _FakeIdentity(register or ["professional"])
        self.visual_lock = visual_lock
        self._locked_fields = list(locked_fields)


def _lock_with(**slots) -> VisualLock:
    """VisualLock helper — accepts kwargs like palette={...}, typography={...}."""
    return VisualLock(
        palette=slots.get("palette", {}),
        typography=slots.get("typography", {}),
        radius=slots.get("radius", {}),
        shadow=slots.get("shadow", {}),
        preset_name=slots.get("preset_name", ""),
    )


def test_locked_palette_slot_survives_llm_override(monkeypatch):
    """User pinned palette.accent — LLM's differing hex is discarded."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {"palette": {"accent": "#1B4332"}},  # would be kept absent lock
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    brief = _LockedBrief(
        visual_lock=_lock_with(palette={"accent": "#6B21A8"}),
        locked_fields=["palette.accent"],
    )
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    assert lock.palette["accent"] == "#6B21A8"
    kept = prov["changes"]["locked_field_kept"]
    assert any(
        k["path"] == "palette.accent"
        and k["source"] == "brief"
        and k["replaced_with"] == "#6B21A8"
        for k in kept
    )


def test_locked_typography_slot_survives_llm_override(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            # Valid font from the allowlist that isn't Fraunces.
            "visual_lock": {"typography": {"display": "Space Grotesk"}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    brief = _LockedBrief(
        visual_lock=_lock_with(typography={"display": "Fraunces"}),
        locked_fields=["typography.display"],
    )
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    assert lock.typography["display"] == "Fraunces"
    kept = prov["changes"]["locked_field_kept"]
    assert any(
        k["path"] == "typography.display" and k["source"] == "brief"
        for k in kept
    )


def test_multiple_locked_fields_preserved_simultaneously(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {
                "palette": {"accent": "#1B4332"},
                "typography": {"display": "Space Grotesk", "body": "Space Grotesk"},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    brief = _LockedBrief(
        visual_lock=_lock_with(
            palette={"accent": "#6B21A8"},
            typography={"display": "Fraunces", "body": "Inter"},
        ),
        locked_fields=["palette.accent", "typography.display", "typography.body"],
    )
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    assert lock.palette["accent"] == "#6B21A8"
    assert lock.typography["display"] == "Fraunces"
    assert lock.typography["body"] == "Inter"
    kept_paths = {k["path"] for k in prov["changes"]["locked_field_kept"]}
    assert kept_paths >= {"palette.accent", "typography.display", "typography.body"}


def test_lock_with_missing_brief_value_falls_back_to_primary_preset(monkeypatch):
    """Path locked but brief doesn't carry the value → preset supplies it."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {"palette": {"accent": "#1B4332"}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    # Brief locked palette.accent but didn't record a value there.
    brief = _LockedBrief(
        visual_lock=_lock_with(palette={"bg": "#FFFFFF"}),
        locked_fields=["palette.accent"],
    )
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    assert lock.palette["accent"] == TRUST_NAVY.palette["accent"]
    kept = prov["changes"]["locked_field_kept"]
    assert any(
        k["path"] == "palette.accent" and k["source"] == "preset"
        for k in kept
    )


def test_lock_with_brief_and_preset_missing_skips_cleanly(monkeypatch):
    """Locked path with no value anywhere → skip silently, no crash."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    brief = _LockedBrief(
        visual_lock=_lock_with(),  # empty
        locked_fields=["shadow.xl"],  # neither brief nor TRUST_NAVY carry shadow.xl
    )
    _v, lock, prov = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan(), brief=brief),
    )
    # Composition succeeded; the locked path is silently skipped.
    assert "xl" not in lock.shadow
    kept = prov["changes"]["locked_field_kept"]
    assert not any(k["path"] == "shadow.xl" for k in kept)


def test_empty_lock_list_leaves_composite_unchanged(monkeypatch):
    """Baseline / parity: no locks → composite matches classic composer path."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {"palette": {"accent": "#1B4332"}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)

    # No brief.
    _v1, lock_no_brief, prov_no_brief = _run(
        compose_vocab_and_design(_candidates(), _presets(), _hybrid_plan()),
    )
    assert lock_no_brief.palette["accent"] == "#1B4332"
    assert prov_no_brief["changes"]["locked_field_kept"] == []

    # Fresh cache — brief with empty locks should yield the same accent.
    vocab_composer._reset_cache_for_tests()
    brief_empty = _LockedBrief(
        visual_lock=_lock_with(palette={"accent": "#6B21A8"}),
        locked_fields=[],
    )
    _v2, lock_empty, prov_empty = _run(
        compose_vocab_and_design(
            _candidates(), _presets(), _hybrid_plan(), brief=brief_empty,
        ),
    )
    assert lock_empty.palette["accent"] == "#1B4332"
    assert prov_empty["changes"]["locked_field_kept"] == []


def test_cache_key_differs_when_locked_fields_differ():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    brief_a = _LockedBrief(
        visual_lock=_lock_with(palette={"accent": "#6B21A8"}),
        locked_fields=["palette.accent"],
    )
    brief_b = _LockedBrief(
        visual_lock=_lock_with(palette={"accent": "#6B21A8"}),
        locked_fields=[],
    )
    k_locked = vocab_composer.cache_key(cands, presets, plan, brief_a)
    k_unlocked = vocab_composer.cache_key(cands, presets, plan, brief_b)
    assert k_locked != k_unlocked


def test_cache_key_lock_order_insensitive():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    lock = _lock_with(
        palette={"accent": "#6B21A8"},
        typography={"display": "Fraunces"},
    )
    # Share the identity instance so repr()-based hashing (fallback for
    # duck-typed identities) doesn't diverge on object id.
    shared_identity = _FakeIdentity(["professional"])
    brief_ab = _LockedBrief(
        visual_lock=lock, locked_fields=["palette.accent", "typography.display"],
    )
    brief_ab.identity = shared_identity
    brief_ba = _LockedBrief(
        visual_lock=lock, locked_fields=["typography.display", "palette.accent"],
    )
    brief_ba.identity = shared_identity
    assert vocab_composer.cache_key(cands, presets, plan, brief_ab) == \
        vocab_composer.cache_key(cands, presets, plan, brief_ba)


def test_locked_fields_appear_in_built_prompt():
    """Prompt tells the LLM which paths not to touch — token savings."""
    brief = _LockedBrief(
        visual_lock=_lock_with(palette={"accent": "#6B21A8"}),
        locked_fields=["palette.accent", "typography.display"],
    )
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=brief,
    )
    assert "USER-LOCKED VISUAL-LOCK FIELDS" in prompt
    assert "palette.accent" in prompt
    assert "typography.display" in prompt


def test_no_locks_prompt_says_none():
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
    )
    assert "USER-LOCKED VISUAL-LOCK FIELDS" in prompt
    assert "none" in prompt.lower()


# --------------------------------------------------------------------- #
# CREATIVE-5b — primary_component hint validation
# --------------------------------------------------------------------- #


def _stub_manifest() -> dict:
    """Tiny synthetic library manifest sufficient for validation tests.

    Uses shapes/categories from the real taxonomy so the composer's
    compatibility check runs against production-shaped data.
    """
    return {
        "components": {
            "Kanban": {
                "category": "data", "data_shape": "list",
                "slot_hints": ["data-row"], "summary": "kanban board",
            },
            "ResourceTimeline": {
                "category": "data", "data_shape": "tabular",
                "slot_hints": ["data-row"], "summary": "resource × day grid",
            },
            "Stat": {
                "category": "chart", "data_shape": "scalar",
                "slot_hints": ["chart"], "summary": "single KPI number",
            },
        }
    }


def test_primary_component_valid_survives(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "component_preferences": {
                    "channels": {
                        "shape": "kanban", "primary_field": "name",
                        "primary_component": "Kanban",
                    },
                }
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(compose_vocab_and_design(
        _candidates(), _presets(), _hybrid_plan(),
        library_manifest_compact=_stub_manifest(),
    ))
    assert vocab.component_preferences["channels"].primary_component == "Kanban"
    rejected = prov["changes"]["primary_component_rejected"]
    assert not any(r["entity"] == "channels" for r in rejected)


def test_primary_component_unknown_dropped(monkeypatch):
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "component_preferences": {
                    "channels": {
                        "shape": "kanban", "primary_field": "name",
                        "primary_component": "MadeUpMegaGrid",
                    },
                }
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(compose_vocab_and_design(
        _candidates(), _presets(), _hybrid_plan(),
        library_manifest_compact=_stub_manifest(),
    ))
    # Nominated primary_component was scrubbed; shape is preserved.
    pref = vocab.component_preferences["channels"]
    assert pref.primary_component == ""
    assert pref.shape == "kanban"
    rejected = prov["changes"]["primary_component_rejected"]
    assert any(
        r["entity"] == "channels"
        and r["proposed_name"] == "MadeUpMegaGrid"
        and r["reason"] == "not_in_library"
        for r in rejected
    )


def test_primary_component_shape_mismatch_dropped(monkeypatch):
    """Stat is a scalar — cannot render a collection shape like 'kanban'."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "component_preferences": {
                    "channels": {
                        "shape": "kanban", "primary_field": "name",
                        "primary_component": "Stat",
                    },
                }
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(compose_vocab_and_design(
        _candidates(), _presets(), _hybrid_plan(),
        library_manifest_compact=_stub_manifest(),
    ))
    assert vocab.component_preferences["channels"].primary_component == ""
    rejected = prov["changes"]["primary_component_rejected"]
    assert any(
        r["entity"] == "channels"
        and r["proposed_name"] == "Stat"
        and r["reason"] == "data_shape_mismatch"
        for r in rejected
    )


def test_no_manifest_leaves_primary_component_alone(monkeypatch):
    """Backwards-compat: no manifest → validator is a no-op."""
    async def fake_llm(_prompt, *, model, timeout_s):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {
                "component_preferences": {
                    "channels": {
                        "shape": "kanban",
                        # Would be dropped by the validator if the
                        # manifest were provided.
                        "primary_component": "MadeUpMegaGrid",
                    },
                }
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_llm)
    vocab, _lock, prov = _run(compose_vocab_and_design(
        _candidates(), _presets(), _hybrid_plan(),
    ))
    # Validator is a no-op with no manifest — the nomination survives.
    assert vocab.component_preferences["channels"].primary_component == "MadeUpMegaGrid"
    assert prov["changes"]["primary_component_rejected"] == []


def test_library_manifest_appears_in_built_prompt():
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
        library_manifest_compact=_stub_manifest(),
    )
    assert "LIBRARY COMPONENTS AVAILABLE" in prompt
    assert "Kanban" in prompt
    assert "ResourceTimeline" in prompt
    assert "primary_component" in prompt


def test_library_manifest_absent_when_not_supplied():
    prompt = vocab_composer._build_prompt(
        _candidates(), _presets(), _hybrid_plan(), brief=None,
    )
    assert "LIBRARY COMPONENTS AVAILABLE" not in prompt


def test_cache_key_differs_when_manifest_names_differ():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    manifest_a = {"components": {"Kanban": {"data_shape": "list"}}}
    manifest_b = {"components": {"Kanban": {"data_shape": "list"},
                                 "Calendar": {"data_shape": "list"}}}
    k_a = vocab_composer.cache_key(
        cands, presets, plan, library_manifest_compact=manifest_a,
    )
    k_b = vocab_composer.cache_key(
        cands, presets, plan, library_manifest_compact=manifest_b,
    )
    assert k_a != k_b


def test_cache_key_stable_across_manifest_reads():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    manifest_a = {"components": {"Kanban": {"data_shape": "list"},
                                 "Calendar": {"data_shape": "list"}}}
    # Same names, different insertion order — key still hashes identically.
    manifest_b = {"components": {"Calendar": {"data_shape": "list"},
                                 "Kanban": {"data_shape": "list"}}}
    k_a = vocab_composer.cache_key(
        cands, presets, plan, library_manifest_compact=manifest_a,
    )
    k_b = vocab_composer.cache_key(
        cands, presets, plan, library_manifest_compact=manifest_b,
    )
    assert k_a == k_b


def test_cache_key_no_manifest_matches_none_input():
    plan = _hybrid_plan()
    cands = _candidates()
    presets = _presets()
    assert vocab_composer.cache_key(cands, presets, plan) == \
        vocab_composer.cache_key(
            cands, presets, plan, library_manifest_compact=None,
        )
