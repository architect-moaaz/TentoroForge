"""Tests for design_brief_author's JSON self-heal path.

Covers the case that just cost a live generation its brief:
the LLM emits a valid-shape brief but with invalid JSON syntax.
"""
from __future__ import annotations

import json

import pytest

from services import design_brief_author as dba


# ── Local repair (no LLM) ──────────────────────────────────────────────

def test_extract_json_happy_path():
    result = dba._extract_json('{"a": 1, "b": "two"}')
    assert result == {"a": 1, "b": "two"}


def test_extract_json_strips_prose_wrapper():
    raw = 'Sure! Here is the JSON:\n{"a": 1}\nHope this helps!'
    assert dba._extract_json(raw) == {"a": 1}


def test_extract_json_repairs_trailing_commas():
    raw = '{"a": 1, "b": 2,}'
    assert dba._extract_json(raw) == {"a": 1, "b": 2}


def test_extract_json_repairs_trailing_comma_in_array():
    raw = '{"list": [1, 2, 3,]}'
    assert dba._extract_json(raw) == {"list": [1, 2, 3]}


def test_extract_json_repairs_code_fence_residue():
    raw = '```json\n{"a": 1}\n```'
    assert dba._extract_json(raw) == {"a": 1}


def test_extract_json_raises_on_unrecoverable_error():
    # Valid brace-balanced object but syntactically busted (unescaped quote
    # inside a string). Local repair cannot save this — must raise.
    with pytest.raises(dba.BriefAuthorError, match="invalid JSON"):
        dba._extract_json('{"a": "he said "hi""}')


def test_extract_json_raises_when_no_object():
    with pytest.raises(dba.BriefAuthorError, match="no JSON object"):
        dba._extract_json("just plain prose, no braces")


# ── Self-heal (LLM fallback) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_self_heal_recovers_valid_json():
    """The heal call returns clean JSON; we parse it and return."""
    async def _heal_query(system, user):
        # The heal prompt asks for corrected JSON — return it clean.
        assert "corrected JSON" in system
        assert "Parse error:" in user
        return '{"palette": {"brand": "#6366F1"}}'

    result = await dba._self_heal_json(_heal_query, raw="{bad json", parse_error="expecting ,")
    assert result == {"palette": {"brand": "#6366F1"}}


@pytest.mark.asyncio
async def test_self_heal_still_fails_raises_briefauthor_error():
    async def _bad_heal(system, user):
        return "still not JSON, still broken"

    with pytest.raises(dba.BriefAuthorError):
        await dba._self_heal_json(_bad_heal, raw="junk", parse_error="err")


# ── Integration: author() uses self-heal when the first parse fails ────

@pytest.mark.asyncio
async def test_author_uses_self_heal_when_first_parse_fails(monkeypatch):
    """Author path: LLM emits invalid JSON on first call → self-heal
    fires with the parse error → healed JSON parses → brief returned."""
    # Bypass the disk cache so we go down the LLM path deterministically.
    monkeypatch.setattr(dba.design_brief_cache, "get", lambda d: None)
    monkeypatch.setattr(dba.design_brief_cache, "put", lambda d, b: None)

    # Build a minimum-viable brief payload the DesignBrief validator will accept.
    healed_brief = {
        "domain":  "Healthcare",
        "identity": {"kind": "app", "product_name": "Test", "tagline": "t"},
        "palette":  {"brand": "#6366F1"},
        "signature_moves": [{"kind": "ledger_row"}],
    }

    calls: list[str] = []

    async def _fake_llm(system, user):
        calls.append(system[:30])
        # First call = author (returns invalid JSON with an unclosed string
        # so no local repair can salvage it).
        # Second call = self-heal (returns valid JSON).
        if len(calls) == 1:
            return '{"palette": {"brand": "#6366F1", "unclosed": "'
        return json.dumps(healed_brief)

    # Patch DesignBrief validator so the minimal payload survives the round-trip
    # without needing to hand-author every required nested field.
    class _StubBrief:
        def __init__(self, **kw): self.data = kw
        @classmethod
        def model_validate(cls, d): return cls(**d)
        def model_dump_json(self, indent=2): return json.dumps(self.data, indent=indent)

    monkeypatch.setattr(dba, "DesignBrief", _StubBrief)

    brief = await dba.author("Healthcare", query_fn=_fake_llm)
    assert brief.data["palette"]["brand"] == "#6366F1"
    assert len(calls) == 2  # first author call + self-heal call


# ── Schema self-heal ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_self_heal_schema_reformats_from_validation_error():
    """The schema heal call gets the Pydantic error text + the original
    payload, returns a corrected payload."""
    original = {"voice": "way too long, over 40 chars for the free field"}
    corrected = {"voice": "punchy"}

    async def _heal(system, user):
        assert "schema validation" in system
        assert "Validation errors:" in user
        assert "voice" in user  # the original was included
        return json.dumps(corrected)

    result = await dba._self_heal_schema(_heal, original, "voice: too long")
    assert result == corrected


@pytest.mark.asyncio
async def test_author_deterministic_truncation_beats_llm_selfheal(monkeypatch):
    """When the LLM emits a string_too_long violation, deterministic
    truncation kicks in FIRST and skips the LLM self-heal round-trip
    (saves latency, avoids the LLM re-emitting an over-limit string).
    LLM self-heal only fires for non-truncatable violations.
    """
    monkeypatch.setattr(dba.design_brief_cache, "get", lambda d: None)
    monkeypatch.setattr(dba.design_brief_cache, "put", lambda d, b: None)

    from pydantic import ValidationError as _RealVE

    calls: list[str] = []

    async def _fake_llm(system, user):
        calls.append(system[:40])
        # First call: author. Returns valid-JSON but string_too_long violation.
        # No second call expected — truncation handles it.
        if len(calls) == 1:
            return json.dumps({"palette": {"brand": "#000000"}, "voice_free": "X" * 100})
        # If a second call happens (test failure), return anything.
        return json.dumps({"palette": {"brand": "#000000"}, "voice_free": "fallback"})

    class _StubBrief:
        def __init__(self, **kw): self.data = kw
        @classmethod
        def model_validate(cls, d):
            if len(d.get("voice_free", "")) > 40:
                # Emulate Pydantic's string_too_long on the free field.
                raise _RealVE.from_exception_data(
                    "DesignBrief",
                    [{"type": "string_too_long", "loc": ("voice_free",),
                      "input": d["voice_free"], "ctx": {"max_length": 40}}],
                )
            return cls(**d)
        def model_dump_json(self, indent=2): return json.dumps(self.data, indent=indent)

    monkeypatch.setattr(dba, "DesignBrief", _StubBrief)

    brief = await dba.author("Healthcare", query_fn=_fake_llm)
    # Deterministic truncation cut 100 X's → 40 X's; LLM never re-called.
    assert brief.data["voice_free"] == "X" * 40
    assert len(calls) == 1, f"LLM self-heal fired unexpectedly ({len(calls)} calls)"
