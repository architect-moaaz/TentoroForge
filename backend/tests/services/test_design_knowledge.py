"""Tests for the ui-ux-pro-max knowledge-base injector.

Verifies the flag gate, domain → product-type mapping, and the shape of the
composed prompt block. Deliberately does not assert exact prompt strings —
the CSV content evolves upstream — instead checks structural invariants.
"""
from __future__ import annotations

import pytest

from services.design_knowledge import (
    _DOMAIN_TO_PRODUCT_TYPES,
    _product_types_for_domain,
    compose_prompt,
    is_enabled,
)


class TestFlagGate:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("FORGE_UI_UX_PRO_MAX", raising=False)
        assert is_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "on", "yes", "warn", "strict"])
    def test_on_for_truthy(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_UI_UX_PRO_MAX", val)
        assert is_enabled() is True

    @pytest.mark.parametrize("val", ["", "0", "off", "false", "no", "asdf"])
    def test_off_for_falsy(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_UI_UX_PRO_MAX", val)
        assert is_enabled() is False


class TestDomainMapping:
    def test_exact_wellness(self):
        assert _product_types_for_domain("wellness") == ("Wellness", "Beauty", "Fitness", "Health")

    def test_substring_match(self):
        # "Wellness & Fitness Studio" doesn't match a bucket key exactly,
        # but the substring fallback should detect "wellness".
        types = _product_types_for_domain("Wellness & Fitness Studio")
        assert "Wellness" in types

    def test_unknown_falls_back_to_saas_b2b(self):
        assert _product_types_for_domain("some-obscure-domain") == ("SaaS", "B2B")

    def test_empty_domain(self):
        assert _product_types_for_domain(None) == ("SaaS", "B2B")
        assert _product_types_for_domain("") == ("SaaS", "B2B")

    def test_every_bucket_key_has_at_least_one_product_type(self):
        for key, buckets in _DOMAIN_TO_PRODUCT_TYPES.items():
            assert buckets, f"empty bucket for {key}"


class TestComposePrompt:
    def test_flag_off_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FORGE_UI_UX_PRO_MAX", raising=False)
        assert compose_prompt("wellness") == ""

    def test_flag_on_returns_content(self, monkeypatch):
        monkeypatch.setenv("FORGE_UI_UX_PRO_MAX", "on")
        out = compose_prompt("wellness")
        # Structural checks — the vendored CSV content evolves, but the
        # shape of the emitted block is stable.
        assert "UI/UX PRO MAX" in out
        assert "wellness" in out.lower()
        assert "PROVEN PALETTES" in out or "TYPE PAIRINGS" in out or "UI STYLES" in out
        assert "HARD RULES" in out
        # Our anti-pattern rules — the tr7rfk34 regressions we saw this session.
        assert "font-size: 0" in out
        assert "box-shadow" in out
        assert "!important" in out

    def test_domain_unknown_still_produces_block(self, monkeypatch):
        # Fallback to SaaS/B2B should still emit a block, not an empty string.
        monkeypatch.setenv("FORGE_UI_UX_PRO_MAX", "on")
        out = compose_prompt("some-unknown-domain")
        assert out
        assert "SaaS" in out or "B2B" in out

    def test_wellness_prompt_names_expected_palettes(self, monkeypatch):
        monkeypatch.setenv("FORGE_UI_UX_PRO_MAX", "on")
        out = compose_prompt("wellness")
        # Rough correctness check — a wellness prompt should pull at least
        # one bucket string from the wellness/health/beauty family.
        assert any(k in out for k in ("Wellness", "Beauty", "Fitness", "Health"))

    def test_prompt_stays_reasonable_size(self, monkeypatch):
        # Guard against the prompt block ballooning if the CSVs get much
        # bigger upstream. 20KB is the tail-end of "compact reference".
        monkeypatch.setenv("FORGE_UI_UX_PRO_MAX", "on")
        for domain in ("wellness", "saas", "ecommerce", "finance"):
            out = compose_prompt(domain)
            assert len(out) < 20_000, f"prompt too big for {domain}: {len(out)}"
