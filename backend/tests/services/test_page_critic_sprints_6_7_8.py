"""Tests for Sprint 6/7/8 integration into page_critic.

Verifies:
  · Sprint 6: signature-moves detector gap MERGES into critique gaps.
  · Sprint 7: brand-echo detector gap MERGES into critique gaps.
  · Sprint 6+7: HIGH detector gap escalates the merged critique's
    ``passes`` to False even when the LLM said pass.
  · Sprint 8: vision path triggers ``_default_vision_query`` when
    ``vision_enabled()`` AND screenshot bytes are provided.
  · Sprint 8: gracefully falls back to text when screenshot bytes empty.
  · page_screenshot: capture returns None when service not configured.
"""
from __future__ import annotations

import json

import pytest

from services import page_critic as pc
from services import page_screenshot as ps


# --------------------------------------------------------------------------- #
# Sprint 6/7 — detector gaps merge into critique
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_brand_echo_gap_appended_when_hex_missing(monkeypatch):
    """The LLM said pass=8; brand detector finds 0/3 echoes; result
    has a brand-echo gap appended and score stays at 8 (detector doesn't
    rewrite the score, only appends)."""
    async def _lgtm(_prompt):
        return json.dumps({"score": 8, "passes": True, "gaps": [], "prose": "solid"})

    monkeypatch.delenv("FORGE_PAGE_BRAND_ECHO_GATE", raising=False)  # medium sev

    result = await pc.critique_page_schema(
        schema={"root": {"props": {}}},
        page_purpose_prose="p",
        brief_primary_hex="#6366F1",
        query_fn=_lgtm,
    )
    # Detector added a MEDIUM gap; passes stays True (only HIGH escalates).
    assert result["score"] == 8
    assert result["passes"] is True
    gap_notes = [g.get("note", "") for g in result["gaps"]]
    assert any("Brand color under-echoed" in n for n in gap_notes)


@pytest.mark.asyncio
async def test_signature_moves_gap_appended_when_none_applied(monkeypatch):
    async def _lgtm(_prompt):
        return json.dumps({"score": 7, "passes": True, "gaps": [], "prose": ""})

    monkeypatch.delenv("FORGE_PAGE_SIGNATURE_MOVES_GATE", raising=False)
    monkeypatch.setenv("FORGE_PAGE_SIGNATURE_MOVES_MIN", "2")

    result = await pc.critique_page_schema(
        schema={"root": {"props": {"variant": "default"}}},
        page_purpose_prose="p",
        brief_signature_moves=["ledger_row", "warm_serif_h1"],
        query_fn=_lgtm,
    )
    notes = [g.get("note", "") for g in result["gaps"]]
    assert any("Signature moves under-applied" in n for n in notes)


@pytest.mark.asyncio
async def test_high_detector_gap_escalates_passes_to_false(monkeypatch):
    """When the gate flag is ON, detector gaps carry HIGH severity — a
    HIGH gap must flip an LLM-said-pass verdict to failing."""
    async def _lgtm(_prompt):
        return json.dumps({"score": 8, "passes": True, "gaps": [], "prose": ""})

    monkeypatch.setenv("FORGE_PAGE_BRAND_ECHO_GATE", "1")

    result = await pc.critique_page_schema(
        schema={"root": {}},
        page_purpose_prose="p",
        brief_primary_hex="#6366F1",
        query_fn=_lgtm,
    )
    assert result["passes"] is False
    assert any(g.get("severity") == "high" for g in result["gaps"])


@pytest.mark.asyncio
async def test_brand_detector_silent_without_brief_hex():
    """No primary hex → brand-echo detector adds nothing (signature-moves
    still has its registered-defaults fallback and may fire; scoped to
    brand only here)."""
    async def _lgtm(_prompt):
        return json.dumps({"score": 8, "passes": True, "gaps": [], "prose": ""})

    result = await pc.critique_page_schema(
        schema={"root": {}},
        page_purpose_prose="p",
        brief_primary_hex=None,
        brief_signature_moves=[],  # explicit empty to skip moves detector
        query_fn=_lgtm,
    )
    assert result["gaps"] == []


@pytest.mark.asyncio
async def test_detectors_populate_critique_metadata_section():
    """Both detectors stash their raw results under `_detectors` for
    observability (persisted to the report file)."""
    async def _lgtm(_prompt):
        return json.dumps({"score": 6, "passes": False, "gaps": [], "prose": ""})

    result = await pc.critique_page_schema(
        schema={"root": {"props": {"color": "#6366F1"}}},
        page_purpose_prose="p",
        brief_primary_hex="#6366F1",
        brief_signature_moves=["ledger_row"],
        query_fn=_lgtm,
    )
    assert "_detectors" in result
    assert "brand_echo" in result["_detectors"]
    assert "signature_moves" in result["_detectors"]


# --------------------------------------------------------------------------- #
# Sprint 8 — vision seam
# --------------------------------------------------------------------------- #

def test_vision_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_CRITIC_VISION", raising=False)
    assert pc.vision_enabled() is False


def test_vision_enabled_when_flag_is_one(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_CRITIC_VISION", "1")
    assert pc.vision_enabled() is True


@pytest.mark.asyncio
async def test_vision_path_takes_screenshot_bytes(monkeypatch):
    """When vision is on AND screenshot bytes provided AND no query_fn
    override, the vision boundary is used. We can't hit the real SDK in
    tests, so patch the boundary and assert it was called."""
    monkeypatch.setenv("FORGE_PAGE_CRITIC_VISION", "1")

    calls: list[tuple[str, bytes]] = []

    async def _fake_vision(prompt, screenshot_bytes):
        calls.append((prompt[:20], screenshot_bytes))
        return json.dumps({"score": 8, "passes": True, "gaps": [], "prose": ""})

    monkeypatch.setattr(pc, "_default_vision_query", _fake_vision)

    result = await pc.critique_page_schema(
        schema={"root": {}},
        page_purpose_prose="p",
        screenshot_bytes=b"\x89PNG\r\n\x1a\nfake",
    )
    assert len(calls) == 1
    assert calls[0][1] == b"\x89PNG\r\n\x1a\nfake"
    assert result["score"] == 8


@pytest.mark.asyncio
async def test_text_path_when_no_screenshot_even_if_vision_on(monkeypatch):
    """No screenshot bytes → text-only path even when vision flag on."""
    monkeypatch.setenv("FORGE_PAGE_CRITIC_VISION", "1")

    vision_calls = []
    text_calls = []

    async def _fake_vision(*args, **kwargs):
        vision_calls.append(1)
        return "{}"

    async def _fake_text(prompt):
        text_calls.append(1)
        return json.dumps({"score": 7, "passes": True, "gaps": [], "prose": ""})

    monkeypatch.setattr(pc, "_default_vision_query", _fake_vision)
    monkeypatch.setattr(pc, "_default_critic_query", _fake_text)

    await pc.critique_page_schema(
        schema={},
        page_purpose_prose="p",
        screenshot_bytes=None,
    )
    assert vision_calls == []
    assert text_calls == [1]


# --------------------------------------------------------------------------- #
# page_screenshot capture
# --------------------------------------------------------------------------- #

def test_screenshot_unavailable_by_default(monkeypatch):
    monkeypatch.delenv("FORGE_PAGE_SCREENSHOT_URL", raising=False)
    assert ps.screenshot_available() is False
    # Capture returns None with no URL configured — no HTTP call attempted.
    assert ps.capture_page_screenshot("/tmp/nowhere", "dash", "/dashboard") is None


def test_screenshot_available_when_url_set(monkeypatch):
    monkeypatch.setenv("FORGE_PAGE_SCREENSHOT_URL", "http://example.invalid")
    assert ps.screenshot_available() is True


def test_screenshot_capture_swallows_http_errors(monkeypatch):
    """When the configured URL is unreachable, capture returns None
    silently — never raises."""
    monkeypatch.setenv("FORGE_PAGE_SCREENSHOT_URL", "http://127.0.0.1:1")  # closed port
    monkeypatch.setenv("FORGE_PAGE_SCREENSHOT_TIMEOUT_S", "1")
    result = ps.capture_page_screenshot("/tmp", "x", "/x")
    assert result is None
