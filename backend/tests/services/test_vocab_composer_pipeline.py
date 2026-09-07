"""Tests for services.vocab_composer_pipeline — flag gate + disk cache
+ pool selection.

The composer + modifier LLM seams are monkeypatched. Disk cache uses
``tmp_path`` so tests never touch the real output/ tree.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import (
    vocab_composer,
    vocab_composer_pipeline,
    vocab_modifier,
    vocab_modifier_pipeline,
)
from services.vocab_composer_pipeline import (
    CACHE_FILENAME,
    FLAG_ENV,
    LIBRARY_MANIFEST_COMPACT_FILENAME,
    load_compose_and_modify_vocab,
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
            "direct-message threads, workspace channels, and monthly "
            "subscription billing tiers. KYC and compliance included."
        ),
        "entities": [
            {"name": "Account"},
            {"name": "Transaction"},
            {"name": "ChatChannel"},
        ],
        "actors": [{"role": "member"}, {"role": "support"}],
    }


def _low_signal_plan() -> dict:
    return {
        "description": "A whimsical widget for arranging pebbles by luminosity.",
        "entities": [{"name": "Pebble"}],
    }


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    vocab_composer._reset_cache_for_tests()
    vocab_modifier._reset_cache_for_tests()
    vocab_composer_pipeline._reset_manifest_cache_for_tests()
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(vocab_modifier_pipeline.FLAG_ENV, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield
    vocab_composer._reset_cache_for_tests()
    vocab_modifier._reset_cache_for_tests()
    vocab_composer_pipeline._reset_manifest_cache_for_tests()


# --------------------------------------------------------------------- #
# Flag OFF
# --------------------------------------------------------------------- #

def test_composition_runs_without_any_flag(monkeypatch, tmp_path):
    """No env gate. Choosing a business vocabulary IS how an app gets its
    design, so it happens on every build — a merge that only runs when a
    flag is set is a merge that never runs. (Replaces the old
    test_flag_off_returns_single_vocab_result, which asserted the gate.)"""
    composer_calls = {"n": 0}

    async def fake_composer_llm(*_a, **_kw):
        composer_calls["n"] += 1
        return {}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)
    monkeypatch.delenv("FORGE_VOCAB_COMPOSER", raising=False)

    vocab, lock, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] != "flag_disabled"
    assert composer_calls["n"] >= 1, "composer never ran without the flag"

def test_flag_on_no_candidates_falls_back_to_single(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG_ENV, "1")
    monkeypatch.setenv(vocab_modifier_pipeline.FLAG_ENV, "1")

    composer_calls = {"n": 0}

    async def fake_composer_llm(*_a, **_kw):
        composer_calls["n"] += 1
        return {}

    async def fake_modifier_llm(*_a, **_kw):
        return {}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)
    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_modifier_llm)

    vocab, lock, prov = _run(load_compose_and_modify_vocab(
        _low_signal_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "no_candidates"
    assert composer_calls["n"] == 0  # composer never called
    # No compose cache file written.
    assert not (tmp_path / "contracts" / CACHE_FILENAME).exists()


# --------------------------------------------------------------------- #
# Flag ON + candidates → compose + persist
# --------------------------------------------------------------------- #

def test_flag_on_candidates_calls_composer_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG_ENV, "1")

    async def fake_composer_llm(*_a, **_kw):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "reasoning": "Banking anchors; messaging adds channel screens.",
            "vocab": {
                "signature_states": {"empty_transactions": "Composed copy."},
            },
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)

    vocab, lock, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "composed"
    assert prov["primary_vocab"] == "banking-platform"
    assert vocab.signature_states["empty_transactions"] == "Composed copy."

    # Cache file written.
    cache_file = tmp_path / "contracts" / CACHE_FILENAME
    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and len(data) == 1
    entry = next(iter(data.values()))
    assert "vocab" in entry and "visual_lock" in entry


# --------------------------------------------------------------------- #
# Cache HIT
# --------------------------------------------------------------------- #

def test_cache_hit_skips_llm(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG_ENV, "1")
    call_count = {"n": 0}

    async def fake_composer_llm(*_a, **_kw):
        call_count["n"] += 1
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {"signature_states": {"empty_transactions": "First call."}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)

    plan = _hybrid_plan()
    v1, _l1, prov1 = _run(load_compose_and_modify_vocab(
        plan, brief=None, output_dir=tmp_path,
    ))
    assert prov1["source"] == "composed"
    assert call_count["n"] == 1

    # Wipe in-memory cache so ONLY disk cache can save the second call.
    vocab_composer._reset_cache_for_tests()

    v2, _l2, prov2 = _run(load_compose_and_modify_vocab(
        plan, brief=None, output_dir=tmp_path,
    ))
    assert prov2["source"] == "cached"
    assert call_count["n"] == 1  # LLM NOT called again
    assert v2.signature_states["empty_transactions"] == "First call."


# --------------------------------------------------------------------- #
# Corrupted cache file
# --------------------------------------------------------------------- #

def test_corrupt_cache_falls_back_to_fresh_call(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG_ENV, "1")
    cache_dir = tmp_path / "contracts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / CACHE_FILENAME).write_text("{ not valid json ", encoding="utf-8")

    call_count = {"n": 0}

    async def fake_composer_llm(*_a, **_kw):
        call_count["n"] += 1
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "vocab": {"signature_states": {"empty_transactions": "Recovered."}},
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)

    vocab, _lock, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "composed"
    assert call_count["n"] == 1
    assert vocab.signature_states["empty_transactions"] == "Recovered."


# --------------------------------------------------------------------- #
# Fallback source NOT persisted
# --------------------------------------------------------------------- #

# --------------------------------------------------------------------- #
# Patterns loaded from discovery.json + threaded into composer
# --------------------------------------------------------------------- #

def test_patterns_from_discovery_are_threaded_to_composer(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG_ENV, "1")

    # Author a discovery.json with two designPatterns.
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "discovery.json").write_text(json.dumps({
        "domain": "Banking",
        "designPatterns": [
            {"name": "Capacity Bar", "description": "slot saturation"},
            {"name": "Waitlist FIFO", "description": "queue order"},
        ],
    }), encoding="utf-8")

    seen_kwargs: dict = {}

    async def fake_compose(candidates, presets, plan, brief, **kwargs):
        seen_kwargs.update(kwargs)
        from services.archetype_vocabulary import load_vocabulary
        from services.visual_lock_presets import TRUST_NAVY
        return load_vocabulary("banking-platform"), TRUST_NAVY, {
            "source": "composed", "candidates": [c.id for c in candidates],
            "preset_source": "cherry_picked", "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy", "changes": {}, "reasoning": None,
        }

    monkeypatch.setattr(vocab_composer_pipeline, "compose_vocab_and_design", fake_compose)

    _v, _l, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "composed"
    patterns = seen_kwargs.get("patterns") or []
    names = {(p.get("name") if isinstance(p, dict) else p) for p in patterns}
    assert "Capacity Bar" in names
    assert "Waitlist FIFO" in names
    # Variance seed threaded (int or None; per-plan-deterministic).
    assert "variance_seed" in seen_kwargs


def test_missing_discovery_still_composes(monkeypatch, tmp_path):
    """No discovery.json → patterns=[] but composer still runs."""
    monkeypatch.setenv(FLAG_ENV, "1")

    seen_kwargs: dict = {}

    async def fake_compose(candidates, presets, plan, brief, **kwargs):
        seen_kwargs.update(kwargs)
        from services.archetype_vocabulary import load_vocabulary
        from services.visual_lock_presets import TRUST_NAVY
        return load_vocabulary("banking-platform"), TRUST_NAVY, {
            "source": "composed", "candidates": [c.id for c in candidates],
            "preset_source": "cherry_picked", "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy", "changes": {}, "reasoning": None,
        }

    monkeypatch.setattr(vocab_composer_pipeline, "compose_vocab_and_design", fake_compose)

    _v, _l, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "composed"
    assert seen_kwargs.get("patterns") == []


def test_single_fallback_not_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv(FLAG_ENV, "1")

    async def fake_composer_llm(*_a, **_kw):
        raise RuntimeError("composer down")

    async def fake_modifier_llm(*_a, **_kw):
        return {"signature_states": {"empty_transactions": "modifier saved."}}

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)
    monkeypatch.setattr(vocab_modifier, "_call_llm", fake_modifier_llm)

    _v, _l, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "single_fallback"
    cache_file = tmp_path / "contracts" / CACHE_FILENAME
    assert not cache_file.exists() or json.loads(cache_file.read_text(encoding="utf-8")) == {}


# --------------------------------------------------------------------- #
# CREATIVE-4 — brief-authored locks flow through the pipeline
# --------------------------------------------------------------------- #

def test_locked_accent_survives_composer_pipeline(monkeypatch, tmp_path):
    """End-to-end: a brief-authored locked accent beats the LLM's proposal."""
    monkeypatch.setenv(FLAG_ENV, "1")

    from schemas.design_brief import VisualLock

    async def fake_composer_llm(*_a, **_kw):
        return {
            "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy",
            "visual_lock": {"palette": {"accent": "#1B4332"}},  # LLM's suggestion
        }

    monkeypatch.setattr(vocab_composer, "_call_llm", fake_composer_llm)

    class _Identity:
        register = ["professional"]

    class _Brief:
        identity = _Identity()
        visual_lock = VisualLock(palette={"accent": "#6B21A8"})
        _locked_fields = ["palette.accent"]

    _v, lock, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=_Brief(), output_dir=tmp_path,
    ))
    assert prov["source"] == "composed"
    # Brief's locked accent wins over the LLM's #1B4332 proposal.
    assert lock.palette["accent"] == "#6B21A8"
    kept = prov["changes"].get("locked_field_kept") or []
    assert any(
        k.get("path") == "palette.accent" and k.get("source") == "brief"
        for k in kept
    )


# --------------------------------------------------------------------- #
# CREATIVE-5b — library manifest threaded + persisted
# --------------------------------------------------------------------- #


def test_library_manifest_threaded_to_composer_and_persisted(monkeypatch, tmp_path):
    """Compact manifest reaches the composer + lands on disk for inspection."""
    monkeypatch.setenv(FLAG_ENV, "1")

    seen_kwargs: dict = {}

    async def fake_compose(candidates, presets, plan, brief, **kwargs):
        seen_kwargs.update(kwargs)
        from services.archetype_vocabulary import load_vocabulary
        from services.visual_lock_presets import TRUST_NAVY
        return load_vocabulary("banking-platform"), TRUST_NAVY, {
            "source": "composed", "candidates": [c.id for c in candidates],
            "preset_source": "cherry_picked", "primary_vocab": "banking-platform",
            "primary_preset": "trust-navy", "changes": {}, "reasoning": None,
        }

    monkeypatch.setattr(vocab_composer_pipeline, "compose_vocab_and_design", fake_compose)

    _v, _l, prov = _run(load_compose_and_modify_vocab(
        _hybrid_plan(), brief=None, output_dir=tmp_path,
    ))
    assert prov["source"] == "composed"

    # Manifest handed to the composer as the compact projection.
    manifest = seen_kwargs.get("library_manifest_compact")
    assert isinstance(manifest, dict)
    comps = manifest.get("components") or {}
    assert "Table" in comps
    # Sample entry has the compact shape (no key_props).
    assert "key_props" not in comps["Table"]

    # Persisted next to the composer cache for inspection.
    manifest_path = tmp_path / "contracts" / LIBRARY_MANIFEST_COMPACT_FILENAME
    assert manifest_path.exists()
    disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(disk["components"].keys()) == set(manifest["components"].keys())
