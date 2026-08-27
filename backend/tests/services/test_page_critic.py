"""Tests for services.page_critic — Sprint 3 of Forge Great Again.

Covers: env gating, prompt shape, JSON-parsing robustness, verdict-shape
validation, gap filtering, REVISE-notes formatting, persistence, and the
critical failure-open behavior (critic errors never break generation).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import page_critic as pc


# --------------------------------------------------------------------------- #
# Env gating
# --------------------------------------------------------------------------- #

def test_page_critic_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_CRITIC", raising=False)
    assert pc.page_critic_enabled() is False


def test_page_critic_enabled_when_flag_is_one(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_CRITIC", "1")
    assert pc.page_critic_enabled() is True


def test_revise_loop_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_CRITIC_REVISE", raising=False)
    assert pc.revise_loop_enabled() is False


def test_revise_loop_enabled_when_flag_is_one(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_CRITIC_REVISE", "1")
    assert pc.revise_loop_enabled() is True


# --------------------------------------------------------------------------- #
# Prompt assembly — tests can inspect the exact shape without an LLM.
# --------------------------------------------------------------------------- #

def test_build_critic_prompt_includes_purpose_and_schema():
    prompt = pc.build_critic_prompt(
        schema={"root": {"type": "Stack", "children": []}},
        page_purpose_prose="Manager needs at-a-glance rent status.",
        brief_prose="",
    )
    assert "Manager needs at-a-glance rent status." in prompt
    assert '"type": "Stack"' in prompt
    # Design rubric is embedded — key dimensions the critic scores against.
    for dim in ("HERO", "READING ORDER", "BRAND ECHO", "SEMANTIC COLOR",
                "COPY", "CARDS", "EMPTY STATES", "SIGNATURE MOVES"):
        assert dim in prompt


def test_build_critic_prompt_omits_brief_block_when_absent():
    prompt = pc.build_critic_prompt(
        schema={}, page_purpose_prose="p", brief_prose="",
    )
    assert "DESIGN BRIEF" not in prompt


def test_build_critic_prompt_includes_brief_block_when_present():
    prompt = pc.build_critic_prompt(
        schema={}, page_purpose_prose="p",
        brief_prose="Palette: brand #6366F1. Voice: confident, calm.",
    )
    assert "DESIGN BRIEF" in prompt
    assert "#6366F1" in prompt


def test_build_critic_prompt_truncates_huge_schemas():
    """A 40k-char schema should be trimmed to keep the critic within its
    token budget. Trim marker must be present."""
    huge = {"root": {"type": "X", "children": [{"n": i} for i in range(5000)]}}
    prompt = pc.build_critic_prompt(
        schema=huge, page_purpose_prose="p", brief_prose="",
    )
    assert "(schema truncated for brevity)" in prompt


# --------------------------------------------------------------------------- #
# JSON parsing — robust to model wrapping in prose or adding fences.
# --------------------------------------------------------------------------- #

def test_parse_critique_pure_json():
    text = json.dumps({
        "score": 8, "passes": True,
        "gaps": [{"severity": "low", "note": "eyebrow could be tighter"}],
        "prose": "Solid.",
    })
    result = pc.parse_critique(text)
    assert result is not None
    assert result["score"] == 8
    assert result["passes"] is True
    assert result["gaps"][0]["severity"] == "low"


def test_parse_critique_extracts_from_prose_wrapper():
    text = 'Here is my verdict:\n{"score": 4, "passes": false, "gaps": [], "prose": "Weak."}\nThanks.'
    result = pc.parse_critique(text)
    assert result is not None
    assert result["score"] == 4


def test_parse_critique_returns_none_on_garbage():
    assert pc.parse_critique("not json at all") is None
    assert pc.parse_critique("") is None
    assert pc.parse_critique(None) is None  # type: ignore[arg-type]


def test_parse_critique_clamps_score_to_1_10():
    r = pc.parse_critique('{"score": 42, "passes": true, "gaps": [], "prose": ""}')
    assert r["score"] == 10
    r = pc.parse_critique('{"score": -5, "passes": false, "gaps": [], "prose": ""}')
    assert r["score"] == 1


def test_parse_critique_normalizes_bad_severity_to_medium():
    r = pc.parse_critique(json.dumps({
        "score": 6, "passes": False,
        "gaps": [{"severity": "critical", "note": "n1"},
                 {"severity": "", "note": "n2"}],
        "prose": "",
    }))
    assert r["gaps"][0]["severity"] == "medium"
    assert r["gaps"][1]["severity"] == "medium"


def test_parse_critique_drops_gaps_without_notes():
    r = pc.parse_critique(json.dumps({
        "score": 5, "passes": False,
        "gaps": [{"severity": "high", "note": ""},
                 {"severity": "high", "note": "real"}],
        "prose": "",
    }))
    assert len(r["gaps"]) == 1
    assert r["gaps"][0]["note"] == "real"


# --------------------------------------------------------------------------- #
# High-severity detection + REVISE-notes rendering
# --------------------------------------------------------------------------- #

def test_has_high_severity_gap_true():
    critique = {"gaps": [{"severity": "medium", "note": "x"},
                          {"severity": "high", "note": "y"}]}
    assert pc.has_high_severity_gap(critique) is True


def test_has_high_severity_gap_false():
    assert pc.has_high_severity_gap({"gaps": []}) is False
    assert pc.has_high_severity_gap({"gaps": [{"severity": "low", "note": "x"}]}) is False
    assert pc.has_high_severity_gap({}) is False
    assert pc.has_high_severity_gap(None) is False  # type: ignore[arg-type]


def test_format_gaps_for_revise_sorts_high_first():
    critique = {"gaps": [
        {"severity": "low", "note": "eyebrow"},
        {"severity": "high", "note": "no hero"},
        {"severity": "medium", "note": "brand echo weak"},
    ]}
    text = pc.format_gaps_for_revise(critique)
    # High severity note appears before medium, which appears before low.
    lines = text.splitlines()
    idx_hero = next(i for i, l in enumerate(lines) if "no hero" in l)
    idx_brand = next(i for i, l in enumerate(lines) if "brand echo weak" in l)
    idx_eye = next(i for i, l in enumerate(lines) if "eyebrow" in l)
    assert idx_hero < idx_brand < idx_eye
    assert "<revise-notes>" in text
    assert "</revise-notes>" in text


def test_format_gaps_for_revise_empty_returns_empty():
    assert pc.format_gaps_for_revise({"gaps": []}) == ""
    assert pc.format_gaps_for_revise({}) == ""


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def test_persist_critique_writes_json_to_reports_page_critic(tmp_path):
    critique = {"score": 7, "passes": True, "gaps": [], "prose": "OK"}
    path = pc.persist_critique(str(tmp_path), "dashboard", critique)
    assert path is not None
    assert path.exists()
    reloaded = json.loads(path.read_text())
    assert reloaded == critique
    # Path shape.
    assert path.parent == tmp_path / "reports" / "page-critic"
    assert path.name == "dashboard.json"


def test_persist_critique_swallows_errors(tmp_path):
    """When the output dir can't be written to (e.g. a file blocks the
    reports/ dir), persistence returns None instead of raising."""
    blocker = tmp_path / "reports"
    blocker.write_text("i am a file, not a dir")
    result = pc.persist_critique(str(tmp_path), "x", {"score": 1})
    assert result is None  # blocker prevents mkdir, but no exception


# --------------------------------------------------------------------------- #
# Fail-open behavior — the critic must never break generation.
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_critique_page_schema_returns_no_verdict_on_llm_error():
    async def _boom(_prompt):
        raise RuntimeError("model gone")

    result = await pc.critique_page_schema(
        schema={}, page_purpose_prose="p", query_fn=_boom,
    )
    # Fail-open: passes=True so the caller ships the page.
    assert result["passes"] is True
    assert result["score"] == 0
    assert "critic unavailable" in result["prose"]


@pytest.mark.asyncio
async def test_critique_page_schema_returns_no_verdict_on_bad_json():
    async def _garbage(_prompt):
        return "the model went off-script and refused to output json"

    result = await pc.critique_page_schema(
        schema={}, page_purpose_prose="p", query_fn=_garbage,
    )
    assert result["passes"] is True
    assert result["score"] == 0


@pytest.mark.asyncio
async def test_critique_page_schema_happy_path():
    async def _good(_prompt):
        return json.dumps({
            "score": 8, "passes": True,
            "gaps": [{"severity": "low", "note": "chart legend redundant"}],
            "prose": "Reads as designed.",
        })

    result = await pc.critique_page_schema(
        schema={"root": {}}, page_purpose_prose="p",
        brief_prose="brand=indigo", query_fn=_good,
    )
    assert result["score"] == 8
    assert result["passes"] is True
    assert len(result["gaps"]) == 1
    assert result["gaps"][0]["severity"] == "low"
    assert "designed" in result["prose"]
