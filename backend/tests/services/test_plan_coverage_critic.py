"""Tests for services.plan_coverage_critic.

Only the pure parts: validation, trimming, Violation bridge,
env-gate. The LLM call itself is not tested here (it's an
integration concern behind the env gate + API key).
"""
from __future__ import annotations

import os

import pytest

from services.plan_coverage_critic import (
    COVERAGE_RULE_PREFIX,
    CoverageGap,
    _abbreviate_brief,
    _trim_plan_for_critic,
    _validate_gap,
    format_coverage_gaps,
    gap_to_dict,
    is_coverage_critic_enabled,
    to_violations,
)


# ── env gate ─────────────────────────────────────────────────────────

def test_env_gate_default_off(monkeypatch):
    monkeypatch.delenv("FORGE_COVERAGE_CRITIC", raising=False)
    monkeypatch.delenv("FORGE_QUALITY", raising=False)
    assert is_coverage_critic_enabled() is False


def test_env_gate_on_variants(monkeypatch):
    monkeypatch.delenv("FORGE_QUALITY", raising=False)
    for val in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("FORGE_COVERAGE_CRITIC", val)
        assert is_coverage_critic_enabled() is True


def test_env_gate_off_variants(monkeypatch):
    monkeypatch.delenv("FORGE_QUALITY", raising=False)
    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("FORGE_COVERAGE_CRITIC", val)
        assert is_coverage_critic_enabled() is False


# ── FORGE_QUALITY meta-flag integration ────────────────────────────

def test_forge_quality_full_turns_critic_on_regardless(monkeypatch):
    """FORGE_QUALITY=full is the one-switch quality mode — must enable
    the coverage critic even when its per-gate flag is unset or off."""
    monkeypatch.delenv("FORGE_COVERAGE_CRITIC", raising=False)
    monkeypatch.setenv("FORGE_QUALITY", "full")
    assert is_coverage_critic_enabled() is True

    # Even an explicit per-gate "off" is overridden by full mode —
    # matches flag_profile's contract.
    monkeypatch.setenv("FORGE_COVERAGE_CRITIC", "0")
    assert is_coverage_critic_enabled() is True


def test_forge_quality_off_disables_critic_regardless(monkeypatch):
    """FORGE_QUALITY=off is the kill switch — must disable the critic
    even when its per-gate flag is explicitly on."""
    monkeypatch.setenv("FORGE_QUALITY", "off")
    monkeypatch.setenv("FORGE_COVERAGE_CRITIC", "1")
    assert is_coverage_critic_enabled() is False


# ── validation — reject hallucinated/malformed gaps ──────────────────

def test_validate_gap_accepts_full_valid():
    raw = {
        "kind": "missing_entity",
        "what": "Notification",
        "why": "brief says 'notify managers'",
        "suggested_fix": "add Notification entity",
    }
    g = _validate_gap(raw)
    assert g is not None
    assert g.kind == "missing_entity"
    assert g.what == "Notification"
    assert g.why.startswith("brief says")
    assert g.suggested_fix.startswith("add Notification")


def test_validate_gap_rejects_unknown_kind():
    """Prevents LLM from inventing kinds we don't handle downstream."""
    raw = {"kind": "missing_widget",
           "what": "chart",
           "why": "brief says chart"}
    assert _validate_gap(raw) is None


def test_validate_gap_rejects_missing_what():
    raw = {"kind": "missing_entity", "what": "", "why": "brief says X"}
    assert _validate_gap(raw) is None


def test_validate_gap_rejects_missing_why():
    """Gap with no source quote is exactly what we want to prevent."""
    raw = {"kind": "missing_entity", "what": "Something", "why": ""}
    assert _validate_gap(raw) is None


def test_validate_gap_rejects_non_dict():
    assert _validate_gap("just a string") is None
    assert _validate_gap(None) is None
    assert _validate_gap([]) is None


def test_validate_gap_truncates_long_fields():
    """Guard against pathological LLM output that would blow REVISE."""
    raw = {
        "kind": "missing_entity",
        "what": "X" * 500,
        "why": "Y" * 800,
        "suggested_fix": "Z" * 500,
    }
    g = _validate_gap(raw)
    assert g is not None
    assert len(g.what) <= 200
    assert len(g.why) <= 400
    assert len(g.suggested_fix) <= 300


def test_validate_gap_suggested_fix_optional():
    raw = {"kind": "missing_entity", "what": "X", "why": "Y"}
    g = _validate_gap(raw)
    assert g is not None
    assert g.suggested_fix == ""


# ── plan trimming — bound token cost ─────────────────────────────────

def test_trim_plan_keeps_shape_keys_only():
    plan = {
        "archetype": "doc-intel",
        "description": "an app",
        "entities": {
            "Doc": {
                "columns": [
                    {"name": "id", "type": "uuid"},
                    {"name": "filename", "type": "varchar"},
                ],
                # Should be dropped
                "table_hints": {"index": "gin"},
                "seed_notes": "…",
            },
        },
        "pages": [{"route": "/docs", "kind": "list", "title": "Docs",
                   "widget_hints": {}, "internal": "stuff"}],
        "workflows": [{"name": "Upload", "trigger": "form_submit",
                       "steps": [{"actionType": "insert", "config": {"table": "docs"}},
                                 {"actionType": "notify", "config": {}}],
                       "internal_notes": "…"}],
        "actors": [{"name": "admin", "role": "admin", "extra": "x"}],
        # Full brief-level bloat that should be dropped:
        "colorPalette": {"primary": "#123456"},
        "typography": {"families": {}},
        "signature_moves": ["…"],
    }
    out = _trim_plan_for_critic(plan)
    assert out["archetype"] == "doc-intel"
    assert out["description"] == "an app"
    assert out["entities"] == [{"name": "Doc", "columns": ["id", "filename"]}]
    assert out["pages"] == [{"route": "/docs", "kind": "list", "title": "Docs"}]
    assert out["workflows"] == [
        {"name": "Upload", "trigger": "form_submit",
         "steps": ["insert", "notify"]},
    ]
    assert out["actors"] == [{"name": "admin", "role": "admin"}]
    # Design tokens etc. dropped
    assert "colorPalette" not in out
    assert "typography" not in out
    assert "signature_moves" not in out


def test_trim_plan_entities_as_list_shape():
    """Plans emitted as data_models list-form should trim the same way."""
    plan = {
        "entities": [
            {"name": "User", "columns": [{"name": "id"}, {"name": "email"}]},
        ],
    }
    out = _trim_plan_for_critic(plan)
    assert out["entities"] == [{"name": "User", "columns": ["id", "email"]}]


def test_trim_plan_empty_plan_returns_empty_shape():
    assert _trim_plan_for_critic({}) == {"archetype": None,
                                         "description": None,
                                         "landing": None}


def test_trim_plan_non_dict_returns_empty():
    assert _trim_plan_for_critic(None) == {}
    assert _trim_plan_for_critic("not a plan") == {}


# ── brief abbreviation — drop visual-only fields ─────────────────────

def test_abbreviate_brief_keeps_semantic_fields():
    brief = {
        "identity": {"domain": "doc-intel", "register": "formal"},
        "signature_moves": [{"kind": "rail"}],
        "content_bank": {"empty_states": {}},
        "personas": [{"name": "admin"}],
        # Visual-only — should drop
        "palette": {"brand": "#123"},
        "typography": {"display_family": "Inter"},
        "layout": {"density": "comfortable"},
    }
    out = _abbreviate_brief(brief)
    assert out.keys() == {"identity", "signature_moves", "content_bank", "personas"}


def test_abbreviate_brief_missing_fields_no_crash():
    assert _abbreviate_brief({}) == {}
    assert _abbreviate_brief(None) == {}


# ── Violation bridge — plug into existing REVISE loop ────────────────

def test_to_violations_prefixes_rule_slug():
    """Downstream loggers need to tell coverage rules apart from other
    completeness rules — the prefix is the tell."""
    gap = CoverageGap(kind="missing_entity", what="Notification",
                      why="notify managers", suggested_fix="add it")
    vs = to_violations([gap])
    assert len(vs) == 1
    v = vs[0]
    assert v.rule.startswith(COVERAGE_RULE_PREFIX)
    assert v.rule == "coverage:missing_entity"


def test_to_violations_msg_contains_what_and_why():
    """REVISE prompt shows this msg to the planner — it must carry both
    the missing thing AND the brief evidence, so the planner knows what
    to add and why."""
    gap = CoverageGap(kind="missing_workflow",
                      what="notify_manager",
                      why="brief says 'notify managers'",
                      suggested_fix="add trigger=schedule daily")
    v = to_violations([gap])[0]
    assert "notify_manager" in v.msg
    assert "notify managers" in v.msg
    assert "add trigger=schedule daily" in v.msg


def test_to_violations_empty_list():
    assert to_violations([]) == []


def test_to_violations_missing_suggested_fix_ok():
    gap = CoverageGap(kind="missing_entity", what="X", why="Y")
    v = to_violations([gap])[0]
    assert "X" in v.msg
    assert "Y" in v.msg
    assert "fix:" not in v.msg


# ── REVISE prompt block formatting ───────────────────────────────────

def test_format_coverage_gaps_empty_returns_empty_str():
    assert format_coverage_gaps([]) == ""


def test_format_coverage_gaps_multiple_gaps_numbered():
    gaps = [
        CoverageGap(kind="missing_entity", what="Notification",
                    why="notify managers", suggested_fix="add entity"),
        CoverageGap(kind="missing_workflow", what="approve_report",
                    why="approvals block publishing", suggested_fix="add workflow"),
    ]
    out = format_coverage_gaps(gaps)
    assert "COVERAGE GAPS TO FIX:" in out
    assert "1." in out
    assert "2." in out
    assert "Notification" in out
    assert "approve_report" in out
    assert "notify managers" in out
    assert "approvals block publishing" in out
    assert "add entity" in out
    assert "add workflow" in out


def test_format_coverage_gaps_carries_kind_tag():
    """Planner uses the kind tag to route the fix to the right emitter."""
    gap = CoverageGap(kind="missing_role", what="Manager",
                      why="notifies managers")
    out = format_coverage_gaps([gap])
    assert "[missing_role]" in out
    assert "[COVERAGE]" in out


# ── serialization for persistence ────────────────────────────────────

def test_gap_to_dict_roundtrips_all_fields():
    gap = CoverageGap(kind="missing_capability", what="audit trail",
                      why="regulatory compliance",
                      suggested_fix="add AuditLog entity")
    d = gap_to_dict(gap)
    assert d == {
        "kind": "missing_capability",
        "what": "audit trail",
        "why": "regulatory compliance",
        "suggested_fix": "add AuditLog entity",
    }
