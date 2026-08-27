"""Tests for services.vocab_modifier_pipeline — flag gate + disk cache.

The modifier LLM seam is monkeypatched. Disk cache round-trip uses
``tmp_path`` so tests never touch the real output/ tree.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import vocab_modifier, vocab_modifier_pipeline
from services.archetype_vocabulary import load_vocabulary
from services.vocab_modifier_pipeline import (
    CACHE_FILENAME,
    load_and_modify_vocab,
)


def _run(coro):
    # Fresh loop per call: keeps us independent of whatever earlier tests
    # in the sweep did to the thread's default loop (some close it).
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _plan() -> dict:
    return {
        "description": "Community credit union loan origination for gig-economy borrowers.",
        "entities": [
            {"name": "Application", "columns": ["applicantName", "amount"]},
        ],
        "actors": [{"role": "member"}, {"role": "loan_officer"}],
    }


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    vocab_modifier._reset_cache_for_tests()
    monkeypatch.delenv(vocab_modifier_pipeline.FLAG_ENV, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield
    vocab_modifier._reset_cache_for_tests()


# --------------------------------------------------------------------- #
# Flag OFF
# --------------------------------------------------------------------- #

def test_flag_off_returns_base_no_llm(monkeypatch, tmp_path):
    call_count = {"n": 0}

    async def fake_llm(*_a, **_kw):
        call_count["n"] += 1
        return {}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    vocab, prov = _run(load_and_modify_vocab(
        "banking-platform", _plan(), brief=None, output_dir=tmp_path,
    ))
    assert vocab is not None
    assert vocab.id == "banking-platform"
    assert prov["source"] == "flag_disabled"
    assert call_count["n"] == 0
    # No cache file written.
    assert not (tmp_path / "contracts" / CACHE_FILENAME).exists()


def test_no_vocab_for_unknown_archetype(tmp_path):
    vocab, prov = _run(load_and_modify_vocab(
        "not-a-real-archetype", _plan(), brief=None, output_dir=tmp_path,
    ))
    assert vocab is None
    assert prov["source"] == "no_vocab"


# --------------------------------------------------------------------- #
# Flag ON + no cache
# --------------------------------------------------------------------- #

def test_flag_on_calls_modifier_and_writes_cache(monkeypatch, tmp_path):
    monkeypatch.setenv(vocab_modifier_pipeline.FLAG_ENV, "1")

    async def fake_llm(*_a, **_kw):
        return {"signature_states": {"empty_transactions": "Fresh copy."}}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    vocab, prov = _run(load_and_modify_vocab(
        "banking-platform", _plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "modified"
    assert vocab.signature_states["empty_transactions"] == "Fresh copy."

    cache_file = tmp_path / "contracts" / CACHE_FILENAME
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert isinstance(data, dict) and len(data) == 1
    entry = next(iter(data.values()))
    assert entry["vocab"]["id"] == "banking-platform"
    assert "timestamp" in entry


# --------------------------------------------------------------------- #
# Flag ON + cache hit
# --------------------------------------------------------------------- #

def test_flag_on_cache_hit_skips_llm(monkeypatch, tmp_path):
    monkeypatch.setenv(vocab_modifier_pipeline.FLAG_ENV, "1")
    call_count = {"n": 0}

    async def fake_llm(*_a, **_kw):
        call_count["n"] += 1
        return {"signature_states": {"empty_transactions": "First call copy."}}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    plan = _plan()
    # First call — populates disk cache.
    v1, prov1 = _run(load_and_modify_vocab(
        "banking-platform", plan, brief=None, output_dir=tmp_path,
    ))
    assert prov1["source"] == "modified"
    assert call_count["n"] == 1

    # Reset in-memory cache to prove the DISK cache is what's saving us.
    vocab_modifier._reset_cache_for_tests()

    # Second call — must hit disk, not LLM.
    v2, prov2 = _run(load_and_modify_vocab(
        "banking-platform", plan, brief=None, output_dir=tmp_path,
    ))
    assert prov2["source"] == "cached"
    assert call_count["n"] == 1  # LLM was NOT called again
    assert v2.signature_states["empty_transactions"] == "First call copy."


# --------------------------------------------------------------------- #
# Cache corruption → fresh call, no crash
# --------------------------------------------------------------------- #

def test_corrupt_cache_file_falls_back_to_fresh_call(monkeypatch, tmp_path):
    monkeypatch.setenv(vocab_modifier_pipeline.FLAG_ENV, "1")

    # Write garbage into the cache file.
    cache_dir = tmp_path / "contracts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / CACHE_FILENAME).write_text("{ not valid json ")

    call_count = {"n": 0}

    async def fake_llm(*_a, **_kw):
        call_count["n"] += 1
        return {"signature_states": {"empty_transactions": "Recovered copy."}}

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    vocab, prov = _run(load_and_modify_vocab(
        "banking-platform", _plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "modified"
    assert call_count["n"] == 1
    assert vocab.signature_states["empty_transactions"] == "Recovered copy."


def test_base_fallback_not_persisted_to_cache(monkeypatch, tmp_path):
    """Flaky LLM must not poison the cache with base_fallback."""
    monkeypatch.setenv(vocab_modifier_pipeline.FLAG_ENV, "1")

    async def fake_llm(*_a, **_kw):
        raise RuntimeError("network flake")

    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_llm)

    vocab, prov = _run(load_and_modify_vocab(
        "banking-platform", _plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "base_fallback"
    # No cache file written — a future healthy call gets to try again.
    cache_file = tmp_path / "contracts" / CACHE_FILENAME
    assert not cache_file.exists() or json.loads(cache_file.read_text()) == {}
