"""Pipeline wiring for the Level 2 vocab modifier — flag gate + disk cache.

Provides :func:`load_and_modify_vocab`, the single call every generator
site uses. Wraps :func:`services.vocab_modifier.modify_vocab` with:

  - ``FORGE_VOCAB_MODIFIER=1`` env flag (default OFF — modifier is off
    unless explicitly enabled; identical rollout pattern to
    ``FORGE_PRODUCT_BRIEF``).

  - Project-scoped disk cache at
    ``<output_dir>/contracts/vocab-modifier-cache.json``. Keyed on the
    same hash the in-memory cache uses. Cache hit → return the persisted
    vocab; cache miss → call the modifier and persist.

  - Exactly-one INFO log per call summarising source + counts. The pipe
    observer (or a grep over stdout) is enough to spot regressions.

Kept in a separate module from :mod:`vocab_modifier` so the pure
modifier stays unit-testable without disk / env / logging concerns.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
    load_vocabulary,
)
from services.vocab_modifier import cache_key, modify_vocab

logger = logging.getLogger(__name__)

FLAG_ENV = "FORGE_VOCAB_MODIFIER"
CACHE_FILENAME = "vocab-modifier-cache.json"


def _flag_on() -> bool:
    """Return True when FORGE_VOCAB_MODIFIER is explicitly enabled."""
    raw = os.getenv(FLAG_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _cache_path(output_dir: Path | str | None) -> Path | None:
    if not output_dir:
        return None
    root = Path(output_dir)
    return root / "contracts" / CACHE_FILENAME


def _load_disk_cache(path: Path) -> dict:
    """Read the cache file, returning ``{}`` on any failure. Corruption
    (bad JSON, missing keys) triggers a fresh call — never a crash."""
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("[vocab-modifier] disk cache read failed: %s", exc)
        return {}


def _write_disk_cache(path: Path, data: dict) -> None:
    """Idempotent write. Parents get created on demand."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[vocab-modifier] disk cache write failed: %s", exc)


def _serialize_vocab(vocab: ArchetypeVocabulary) -> dict:
    return asdict(vocab)


def _deserialize_vocab(data: dict) -> ArchetypeVocabulary:
    prefs = {}
    for k, v in (data.get("component_preferences") or {}).items():
        if isinstance(v, dict):
            prefs[k] = ComponentPreference(
                shape=str(v.get("shape") or "table"),
                primary_field=str(v.get("primary_field") or ""),
                context=str(v.get("context") or ""),
            )
    return ArchetypeVocabulary(
        id=str(data.get("id") or ""),
        primary_screens_per_persona=dict(data.get("primary_screens_per_persona") or {}),
        section_recipes=dict(data.get("section_recipes") or {}),
        component_preferences=prefs,
        signature_states=dict(data.get("signature_states") or {}),
        status_badges=dict(data.get("status_badges") or {}),
        section_filters=dict(data.get("section_filters") or {}),
        dashboard_recipe=dict(data.get("dashboard_recipe") or {}),
        page_recipes=dict(data.get("page_recipes") or {}),
    )


def _log_summary(archetype_id: str, provenance: dict) -> None:
    source = provenance.get("source", "?")
    if source == "modified":
        changes = provenance.get("changes") or {}
        logger.info(
            "[vocab-modifier] archetype=%s source=modified "
            "sections_added=%d personas_added=%d shapes_rejected=%d warnings=%d",
            archetype_id,
            len(changes.get("sections_added") or []),
            len(changes.get("personas_added") or []),
            len(changes.get("shapes_rejected") or []),
            len(changes.get("warnings") or []),
        )
    elif source == "cached":
        age = provenance.get("age_seconds")
        logger.info(
            "[vocab-modifier] archetype=%s source=cached age=%s",
            archetype_id,
            f"{age:.1f}" if isinstance(age, (int, float)) else "?",
        )
    elif source == "base_fallback":
        logger.info(
            "[vocab-modifier] archetype=%s source=base_fallback reason=%s",
            archetype_id, provenance.get("reason") or "?",
        )
    elif source == "flag_disabled":
        logger.info(
            "[vocab-modifier] archetype=%s source=flag_disabled",
            archetype_id,
        )
    else:
        logger.info(
            "[vocab-modifier] archetype=%s source=%s",
            archetype_id, source,
        )


async def load_and_modify_vocab(
    archetype_id: str,
    plan: dict,
    brief: Any | None = None,
    output_dir: Path | str | None = None,
) -> tuple[ArchetypeVocabulary | None, dict]:
    """Load the base vocab for ``archetype_id`` and (optionally) modify it.

    Returns ``(vocab, provenance)``. ``vocab`` is None when the archetype
    is unregistered — callers keep their existing fall-back-to-legacy path.

    Behaviour:
      - No archetype match → ``(None, {source: "no_vocab"})``.
      - Flag off → ``(base, {source: "flag_disabled"})``.
      - Flag on + disk cache hit → ``(cached_vocab, {source: "cached"})``.
      - Flag on + disk cache miss → call modifier, persist, return.
      - Any modifier exception (fail-open) → ``(base, {source: "base_fallback"})``.
    """
    base = load_vocabulary(archetype_id)
    if base is None:
        prov = {"source": "no_vocab", "reason": f"archetype {archetype_id!r} unregistered"}
        _log_summary(archetype_id or "?", prov)
        return None, prov

    if not _flag_on():
        prov = {"source": "flag_disabled"}
        _log_summary(base.id, prov)
        return base, prov

    key = cache_key(base, plan, brief)
    disk_path = _cache_path(output_dir)
    disk_data = _load_disk_cache(disk_path) if disk_path else {}
    entry = disk_data.get(key) if isinstance(disk_data, dict) else None

    if isinstance(entry, dict) and isinstance(entry.get("vocab"), dict):
        try:
            cached_vocab = _deserialize_vocab(entry["vocab"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[vocab-modifier] cache entry corrupt: %s", exc)
            cached_vocab = None
        if cached_vocab is not None:
            prov = dict(entry.get("provenance") or {})
            prov["source"] = "cached"
            ts = entry.get("timestamp")
            if isinstance(ts, (int, float)):
                prov["age_seconds"] = max(0.0, time.time() - float(ts))
            _log_summary(base.id, prov)
            return cached_vocab, prov

    # Cache miss → call modifier.
    modified, prov = await modify_vocab(base, plan, brief)
    _log_summary(base.id, prov)

    # Only persist real modifications (not base_fallback — a network flake
    # shouldn't stick as the cached answer forever).
    if disk_path is not None and prov.get("source") == "modified":
        disk_data = disk_data if isinstance(disk_data, dict) else {}
        disk_data[key] = {
            "vocab": _serialize_vocab(modified),
            "provenance": prov,
            "timestamp": time.time(),
        }
        _write_disk_cache(disk_path, disk_data)

    return modified, prov


def load_and_modify_vocab_sync(
    archetype_id: str,
    plan: dict | None = None,
    brief: Any | None = None,
    output_dir: Path | str | None = None,
) -> tuple[ArchetypeVocabulary | None, dict]:
    """Sync facade for callers that don't live in an async context.

    When the flag is OFF (the default), returns the base vocab immediately
    without touching asyncio — identical semantics to a direct
    ``load_vocabulary`` call. When the flag is ON, runs the async
    modifier via ``asyncio.run``; if a loop is already running, falls
    back to the base vocab (the async path is available to async callers
    directly).
    """
    if not _flag_on():
        base = load_vocabulary(archetype_id)
        if base is None:
            prov = {"source": "no_vocab", "reason": f"archetype {archetype_id!r} unregistered"}
        else:
            prov = {"source": "flag_disabled"}
        _log_summary(base.id if base is not None else (archetype_id or "?"), prov)
        return base, prov

    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async caller — they should invoke the async
            # variant directly. Fall open to base rather than risk a
            # cross-loop deadlock.
            base = load_vocabulary(archetype_id)
            prov = {"source": "base_fallback", "reason": "sync facade called from async loop"}
            _log_summary(base.id if base is not None else (archetype_id or "?"), prov)
            return base, prov
    except RuntimeError:
        pass  # No running loop — safe to spin our own.

    return asyncio.run(load_and_modify_vocab(archetype_id, plan or {}, brief, output_dir))


__all__ = [
    "CACHE_FILENAME",
    "FLAG_ENV",
    "load_and_modify_vocab",
    "load_and_modify_vocab_sync",
]
