"""Tests for services.brand_echo_detector — Sprint 7."""
from __future__ import annotations

import pytest

from services import brand_echo_detector as bed


# ── Env gating ──────────────────────────────────────────────────────────

def test_gate_default_off(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_BRAND_ECHO_GATE", raising=False)
    assert bed.brand_echo_gate_enabled() is False


def test_gate_on_when_flag_is_one(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_BRAND_ECHO_GATE", "1")
    assert bed.brand_echo_gate_enabled() is True


def test_min_required_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_BRAND_ECHO_MIN", raising=False)
    assert bed.min_brand_echoes_required() == 3


def test_min_required_env_override(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_BRAND_ECHO_MIN", "5")
    assert bed.min_brand_echoes_required() == 5


# ── Detection ──────────────────────────────────────────────────────────

def test_no_brief_verdict_when_hex_missing():
    result = bed.detect_brand_echo({"root": {}}, None)
    assert result["primary_hex"] is None
    assert result["meets_minimum"] is True  # no expectations = fail-open


def test_no_brief_verdict_when_hex_malformed():
    result = bed.detect_brand_echo({"root": {}}, "not-a-hex")
    assert result["meets_minimum"] is True


def test_counts_literal_hex_occurrences():
    schema = {
        "root": {
            "props": {"color": "#6366F1"},
            "children": [
                {"props": {"iconColor": "#6366F1"}},
                {"props": {"stripeColor": "#6366F1"}},
            ]
        }
    }
    result = bed.detect_brand_echo(schema, "#6366F1")
    assert result["hex_count"] == 3
    assert result["meets_minimum"] is True


def test_hex_matching_is_case_insensitive():
    schema = {"root": {"props": {"color": "#6366F1"}}}
    result = bed.detect_brand_echo(schema, "#6366f1")
    assert result["hex_count"] == 1


def test_counts_token_references():
    schema = {
        "root": {
            "props": {"backgroundColor": "tokens.color.primary"},
            "children": [
                {"props": {"variant": "brand.primary"}},
            ]
        }
    }
    result = bed.detect_brand_echo(schema, "#6366F1")
    assert result["token_count"] >= 2


def test_counts_color_prop_named_values():
    """A color prop with value 'primary' counts as a brand echo."""
    schema = {
        "root": {
            "props": {"variant": "primary"},
            "children": [
                {"props": {"color": "brand"}},
                {"props": {"tone": "accent"}},
            ]
        }
    }
    result = bed.detect_brand_echo(schema, "#6366F1")
    assert result["name_count"] == 3


def test_total_echoes_sums_all_three_channels():
    schema = {
        "root": {
            "props": {"color": "#6366F1", "variant": "primary"},
            "children": [
                {"props": {"backgroundColor": "tokens.color.primary"}},
            ]
        }
    }
    result = bed.detect_brand_echo(schema, "#6366F1")
    assert result["hex_count"] == 1
    assert result["token_count"] >= 1
    assert result["name_count"] == 1
    assert result["total_echoes"] == (
        result["hex_count"] + result["token_count"] + result["name_count"]
    )


def test_fails_when_below_minimum(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_BRAND_ECHO_MIN", "3")
    schema = {"root": {"props": {"color": "#6366F1"}}}
    result = bed.detect_brand_echo(schema, "#6366F1")
    assert result["total_echoes"] == 1
    assert result["meets_minimum"] is False


def test_as_critic_gap_medium_when_gate_off(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_BRAND_ECHO_GATE", raising=False)
    detection = {
        "primary_hex": "#6366F1",
        "total_echoes": 1,
        "min_required": 3,
        "meets_minimum": False,
    }
    gap = bed.as_critic_gap(detection)
    assert gap["severity"] == "medium"
    assert "#6366f1" in gap["note"].lower()


def test_as_critic_gap_high_when_gate_on(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_BRAND_ECHO_GATE", "1")
    detection = {
        "primary_hex": "#6366F1",
        "total_echoes": 0,
        "min_required": 3,
        "meets_minimum": False,
    }
    gap = bed.as_critic_gap(detection)
    assert gap["severity"] == "high"


def test_as_critic_gap_none_when_minimum_met():
    detection = {
        "primary_hex": "#6366F1",
        "total_echoes": 5,
        "min_required": 3,
        "meets_minimum": True,
    }
    assert bed.as_critic_gap(detection) is None


def test_as_critic_gap_none_when_no_hex():
    detection = {"primary_hex": None, "meets_minimum": True}
    assert bed.as_critic_gap(detection) is None
