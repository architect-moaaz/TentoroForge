"""Tests for the Phase 1 design brief modules.

Covers:
  - Schema validation (hex, weights, register length, signature count)
  - Anchor validity (all 6 hand-authored briefs parse cleanly)
  - Cache basics (get/put/clear/anchors always present)
  - LLM author path with injected query_fn (no wire hits)
  - JSON extraction resilience (fenced, prose-wrapped, garbage)
  - Base antipatterns are always merged onto authored briefs
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from schemas.design_brief import DesignBrief
from services import design_brief_cache
from services.design_brief_antipatterns import BASE_ANTI_PATTERNS
from services.design_brief_author import BriefAuthorError, author


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

def _valid_brief_payload() -> dict:
    return {
        "identity": {
            "domain": "Test Domain",
            "register": ["calm"],
            "voice": "warm_precise",
            "modes": ["light"],
        },
        "palette": {
            "brand": "#123456",
            "accent": "#ABCDEF",
            "neutrals_base": "#F0F0F0",
            "neutrals_tint": "warm",
            "surface_bg": "#FFFFFF",
            "surface_elevated": "#FFFFFF",
            "foreground_primary": "#111111",
            "foreground_muted": "#666666",
        },
        "typography": {
            "display_family": "Serif",
            "body_family": "Sans",
        },
        "layout": {"density": "comfortable", "radius": "soft_8"},
        "signature_moves": [{"kind": "x", "detail": "y"}],
    }


class TestSchema:
    def test_valid_payload_parses(self):
        b = DesignBrief.model_validate(_valid_brief_payload())
        assert b.identity.domain == "Test Domain"
        assert b.palette.brand == "#123456"

    def test_hex_bad_length_rejected(self):
        payload = _valid_brief_payload()
        payload["palette"]["brand"] = "#12345"
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_hex_non_digits_rejected(self):
        payload = _valid_brief_payload()
        payload["palette"]["brand"] = "#GGGGGG"
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_hex_uppercased(self):
        payload = _valid_brief_payload()
        payload["palette"]["brand"] = "#abcdef"
        b = DesignBrief.model_validate(payload)
        assert b.palette.brand == "#ABCDEF"

    def test_register_too_long_rejected(self):
        payload = _valid_brief_payload()
        payload["identity"]["register"] = ["a", "b", "c"]
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_register_empty_rejected(self):
        payload = _valid_brief_payload()
        payload["identity"]["register"] = []
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_zero_signature_moves_rejected(self):
        payload = _valid_brief_payload()
        payload["signature_moves"] = []
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_three_signature_moves_rejected(self):
        payload = _valid_brief_payload()
        payload["signature_moves"] = [
            {"kind": "a", "detail": "x"},
            {"kind": "b", "detail": "y"},
            {"kind": "c", "detail": "z"},
        ]
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_bad_weight_rejected(self):
        payload = _valid_brief_payload()
        payload["typography"]["display_weights"] = [450]
        with pytest.raises(ValidationError):
            DesignBrief.model_validate(payload)

    def test_summary_line(self):
        b = DesignBrief.model_validate(_valid_brief_payload())
        s = b.summary_line()
        assert "warm_precise" in s
        assert "#123456" in s
        assert "Serif" in s
        assert "comfortable" in s


# --------------------------------------------------------------------------- #
# Anchors removed in Slice 7b — per-domain hand-authored briefs were the
# same anti-pattern as per-industry recipes. TestAnchors deleted along
# with services/design_brief_anchors.py.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _reset_cache():
    design_brief_cache.clear()
    yield
    design_brief_cache.clear()


class TestCache:
    def test_starts_empty_after_reset(self):
        # Spec A Slice 7: cache no longer pre-primes with anchor briefs.
        # Fresh cache starts empty; only LLM-authored briefs land in it.
        assert design_brief_cache.all_domains() == []

    def test_disk_persistence_round_trip(self, tmp_path, monkeypatch):
        # Slice 7b: put() writes to disk; a fresh process (simulated via
        # clearing in-memory store) still finds the brief.
        monkeypatch.setenv("FORGE_BRIEF_CACHE_DIR", str(tmp_path))
        b = DesignBrief.model_validate(_valid_brief_payload())
        design_brief_cache.put("Novel Domain", b)
        design_brief_cache._store.clear()  # simulate process restart
        recovered = design_brief_cache.get("Novel Domain")
        assert recovered is not None
        assert recovered.palette.brand == b.palette.brand

    def test_disk_slug_is_case_insensitive(self, tmp_path, monkeypatch):
        # Domains like "Property Management" and "property management"
        # slug to the same file — the second put() overwrites the first.
        monkeypatch.setenv("FORGE_BRIEF_CACHE_DIR", str(tmp_path))
        b = DesignBrief.model_validate(_valid_brief_payload())
        design_brief_cache.put("Property Management", b)
        files = list((tmp_path).glob("*.json"))
        assert len(files) == 1
        assert files[0].name == "property-management.json"

    def test_put_then_get(self):
        b = DesignBrief.model_validate(_valid_brief_payload())
        design_brief_cache.put("Novel Domain", b)
        assert design_brief_cache.get("Novel Domain") is b

    def test_get_missing(self):
        assert design_brief_cache.get("Nonexistent") is None

    def test_clear_one_preserves_others(self):
        b1 = DesignBrief.model_validate(_valid_brief_payload())
        b2 = DesignBrief.model_validate(_valid_brief_payload())
        design_brief_cache.put("Novel", b1)
        design_brief_cache.put("Kept", b2)
        design_brief_cache.clear("Novel")
        assert not design_brief_cache.has("Novel")
        # Non-cleared entries survive.
        assert design_brief_cache.has("Kept")


# --------------------------------------------------------------------------- #
# Author — cache path
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
class TestAuthorCache:
    async def test_first_author_hits_llm(self):
        # Spec A Slice 7: no more anchor pre-prime. Every first-time
        # domain hits the LLM (which lands in cache for the second call).
        called = False

        async def fake(_s, _u):
            nonlocal called
            called = True
            return json.dumps(_valid_brief_payload())

        await author("Some Novel Domain", query_fn=fake)
        assert called, "novel domain must hit LLM (cache started empty)"

    async def test_cache_hit_after_first_author(self):
        # Prime with a fake response.
        calls = 0
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "Fresh Domain"

        async def fake(_s, _u):
            nonlocal calls
            calls += 1
            return json.dumps(payload)

        b1 = await author("Fresh Domain", query_fn=fake)
        b2 = await author("Fresh Domain", query_fn=fake)
        assert calls == 1
        assert b2 is b1


# --------------------------------------------------------------------------- #
# Author — LLM path
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
class TestAuthorLLM:
    async def test_llm_response_parsed_and_cached(self):
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "Novel"

        async def fake(_s, _u):
            return json.dumps(payload)

        b = await author("Novel", query_fn=fake)
        assert b.identity.domain == "Novel"
        assert design_brief_cache.has("Novel")

    async def test_llm_response_with_prose_wrapper(self):
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "Novel"

        async def fake(_s, _u):
            return f"Here you go!\n\n{json.dumps(payload)}\n\nThat's the brief."

        b = await author("Novel", query_fn=fake)
        assert b.identity.domain == "Novel"

    async def test_llm_response_no_json_raises(self):
        async def fake(_s, _u):
            return "sorry I can't do that"

        with pytest.raises(BriefAuthorError):
            await author("Novel", query_fn=fake)

    async def test_llm_invalid_schema_raises(self):
        async def fake(_s, _u):
            return '{"identity": "not a dict"}'

        with pytest.raises(BriefAuthorError):
            await author("Novel", query_fn=fake)

    async def test_base_anti_patterns_always_merged(self):
        """LLM only supplies domain-specific ones; base ALWAYS present."""
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "Novel"
        payload["anti_patterns"] = ["domain_specific_x"]

        async def fake(_s, _u):
            return json.dumps(payload)

        b = await author("Novel", query_fn=fake)
        aps = set(b.anti_patterns)
        assert "domain_specific_x" in aps
        for base in BASE_ANTI_PATTERNS:
            assert base in aps, f"missing base antipattern: {base}"

    async def test_force_llm_bypasses_cache(self):
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "Healthcare"
        calls = 0

        async def fake(_s, _u):
            nonlocal calls
            calls += 1
            return json.dumps(payload)

        # Anchor exists — normally we'd cache-hit.
        await author("Healthcare", query_fn=fake, force_llm=True)
        assert calls == 1

    async def test_empty_domain_raises(self):
        with pytest.raises(BriefAuthorError):
            await author("", query_fn=None)


# --------------------------------------------------------------------------- #
# Spec D Wave 4 — prompt extension gated on FORGE_CLEANUP_WAVE_4
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
class TestWave4PromptExtension:
    """The Wave 4 extension teaches the LLM about the free-form / numeric
    companions to the enum buckets. It appends to the system prompt only
    when FORGE_CLEANUP_WAVE_4=1; the schema always accepts the fields."""

    async def test_flag_off_prompt_unchanged(self, monkeypatch):
        monkeypatch.delenv("FORGE_CLEANUP_WAVE_4", raising=False)
        captured = {}

        async def fake(system, _u):
            captured["system"] = system
            return json.dumps(_valid_brief_payload())

        await author("Novel1", query_fn=fake)
        assert "Wave 4" not in captured["system"]
        assert "voice_free" not in captured["system"]
        assert "radius_px" not in captured["system"]

    async def test_flag_on_appends_extension(self, monkeypatch):
        monkeypatch.setenv("FORGE_CLEANUP_WAVE_4", "1")
        captured = {}

        async def fake(system, _u):
            captured["system"] = system
            return json.dumps(_valid_brief_payload())

        await author("Novel2", query_fn=fake)
        s = captured["system"]
        # Extension mentions each new field by name so the model can emit it.
        assert "Wave 4" in s
        assert "voice_free" in s
        assert "neutrals_tint_free" in s
        assert "radius_px" in s
        assert "density_pt" in s
        # Base prompt still fully present (extension is APPENDED, not replaced).
        assert "You are a design director." in s
        assert "Hard blocklist" in s

    async def test_various_truthy_values_enable_extension(self, monkeypatch):
        for val in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("FORGE_CLEANUP_WAVE_4", val)
            captured = {}

            async def fake(system, _u):
                captured["system"] = system
                return json.dumps(_valid_brief_payload())

            # Force LLM so cache doesn't short-circuit across the parameterized loop.
            await author(f"Novel_{val}", query_fn=fake, force_llm=True)
            assert "Wave 4" in captured["system"], f"failed for {val!r}"

    async def test_falsy_values_leave_extension_off(self, monkeypatch):
        for val in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("FORGE_CLEANUP_WAVE_4", val)
            captured = {}

            async def fake(system, _u):
                captured["system"] = system
                return json.dumps(_valid_brief_payload())

            await author(f"Novel_off_{val}", query_fn=fake, force_llm=True)
            assert "Wave 4" not in captured["system"], f"leaked for {val!r}"

    async def test_wave4_populated_brief_validates_and_caches(self, monkeypatch):
        """End-to-end: LLM emits the new fields, DesignBrief accepts them,
        cache round-trip preserves them."""
        monkeypatch.setenv("FORGE_CLEANUP_WAVE_4", "1")
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "Wave4Novel"
        payload["identity"]["voice_free"] = "warm and quietly precise"
        payload["palette"]["neutrals_tint_free"] = "cool with green"
        payload["layout"]["radius_px"] = 12
        payload["layout"]["density_pt"] = 8

        async def fake(_s, _u):
            return json.dumps(payload)

        b = await author("Wave4Novel", query_fn=fake, force_llm=True)
        assert b.identity.voice_free == "warm and quietly precise"
        assert b.palette.neutrals_tint_free == "cool with green"
        assert b.layout.radius_px == 12
        assert b.layout.density_pt == 8

    async def test_flag_off_wave4_fields_omitted_still_validates(self, monkeypatch):
        """Regression: schema accepts payloads without the Wave 4 fields
        whether the flag is on or off. Old readers keep working."""
        monkeypatch.delenv("FORGE_CLEANUP_WAVE_4", raising=False)
        payload = _valid_brief_payload()
        payload["identity"]["domain"] = "OldReaderNovel"

        async def fake(_s, _u):
            return json.dumps(payload)

        b = await author("OldReaderNovel", query_fn=fake, force_llm=True)
        assert b.identity.voice_free is None
        assert b.palette.neutrals_tint_free is None
        assert b.layout.radius_px is None
        assert b.layout.density_pt is None
