"""Pipeline wiring for the multi-vocab COMPOSE stack — flag gate + disk
cache + candidate-pool selection.

Sibling to :mod:`services.vocab_modifier_pipeline`. Wraps the composer
with the same production concerns:

  - No env flag. Composition always runs: it picks a candidate pool
    (scored against the app's requirement, not just plan prose),
    composes, and persists. It used to sit behind
    ``FORGE_VOCAB_COMPOSER`` which defaulted OFF, so the merge this
    module exists to perform never actually happened on a real build.

  - Project-scoped disk cache at
    ``<output_dir>/contracts/vocab-composer-cache.json``. Keyed on the
    composer's ``cache_key`` so an in-memory hit and a disk hit resolve
    identically.

  - Exactly-one INFO log per call summarising source + counts.

The composer stays pure so it can be unit-tested without disk / env
/ logging concerns.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from schemas.design_brief import VisualLock
from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
    load_vocabulary,
)
from services.library_manifest import (
    build_library_manifest,
    compact_manifest_for_composer,
)
from services.pipeline.variance import variance_seed_for
from services.product_brief import _archetype_from_plan
from services.vocab_composer import cache_key, compose_vocab_and_design
from services.vocab_modifier_pipeline import (
    load_and_modify_vocab,
    load_and_modify_vocab_sync,
)
from services.vocab_ranker import select_candidate_pool
from services.visual_lock_presets import (
    ACADEMIC_FRESH,
    ADMIN_NEUTRAL,
    CLINICAL_CALM,
    CREATIVE_BOLD,
    DATA_DENSE,
    EDITORIAL_LIGHT,
    FIELD_UTILITY,
    TRUST_NAVY,
    WELLNESS_WARM,
    pick_preset_from_plan,
)

logger = logging.getLogger(__name__)

FLAG_ENV = "FORGE_VOCAB_COMPOSER"
CACHE_FILENAME = "vocab-composer-cache.json"
LIBRARY_MANIFEST_COMPACT_FILENAME = "library-manifest-compact.json"

# Module-scope memo — building the library manifest scans starter.json +
# contracts + docblocks; the result is stable for the process lifetime, so
# every pipeline call in the same worker reuses one build.
_COMPACT_MANIFEST_CACHE: dict | None = None


def _reset_manifest_cache_for_tests() -> None:
    """Test hook — clear the memoised compact manifest between tests."""
    global _COMPACT_MANIFEST_CACHE
    _COMPACT_MANIFEST_CACHE = None


def _get_compact_manifest() -> dict:
    global _COMPACT_MANIFEST_CACHE
    if _COMPACT_MANIFEST_CACHE is None:
        try:
            _COMPACT_MANIFEST_CACHE = compact_manifest_for_composer(
                build_library_manifest(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[vocab-composer] manifest build failed: %s", exc)
            _COMPACT_MANIFEST_CACHE = {"components": {}}
    return _COMPACT_MANIFEST_CACHE


def _persist_compact_manifest(output_dir: Path | str | None, manifest: dict) -> None:
    """Write the compact manifest to ``contracts/library-manifest-compact.json``.

    Idempotent — skips the write when the file already exists (the manifest
    is stable per project). Failure is non-fatal; a missing file just means
    the manifest isn't inspectable on disk for this run.
    """
    if not output_dir:
        return
    try:
        out_dir = Path(output_dir) / "contracts"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / LIBRARY_MANIFEST_COMPACT_FILENAME
        if path.exists():
            return
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[vocab-composer] manifest persist failed: %s", exc)


# Vocab-id → preset mapping. Sourced from the domain groupings the
# preset-picker keyword sets already document (see visual_lock_presets.py
# comments). One preset per vocab so cherry-picking across candidates
# maps 1:1 to picking each candidate's default preset.
_VOCAB_TO_PRESET: dict[str, VisualLock] = {
    "booking-platform":               WELLNESS_WARM,
    "banking-platform":               TRUST_NAVY,
    "payment-processing-platform":    TRUST_NAVY,
    "subscription-billing-platform":  TRUST_NAVY,
    "healthcare-platform":            CLINICAL_CALM,
    "field-service-platform":         FIELD_UTILITY,
    "learning-platform":              ACADEMIC_FRESH,
    "content-platform":               EDITORIAL_LIGHT,
    "messaging-platform":             CREATIVE_BOLD,
    "dev-tools-platform":             DATA_DENSE,
    "analytics-dashboard-platform":   DATA_DENSE,
    "document-intelligence-platform": DATA_DENSE,
    "marketplace-platform":           ADMIN_NEUTRAL,
    "crm-platform":                   ADMIN_NEUTRAL,
    "inventory-platform":             ADMIN_NEUTRAL,
    "project-platform":               ADMIN_NEUTRAL,
}


# --------------------------------------------------------------------- #
# Pattern loading — the user-selected design patterns live in
# ``contracts/discovery.json`` under the ``designPatterns`` key
# (a list of ``{name, description, evidence, ...}`` objects authored by
# ``agents.domain_agent`` and adjustable via ``services.discovery_adjust``).
# ProductBrief itself does NOT carry a patterns list — the discovery
# dossier is the source of truth.
# --------------------------------------------------------------------- #

def _load_patterns_from_disk(output_dir: Path | str | None) -> list[dict]:
    """Return the ``designPatterns`` list from ``contracts/discovery.json``.

    Returns an empty list on any failure — missing file, corrupt JSON,
    wrong shape. Never raises; a pattern-loading hiccup should not
    take composition down.

    Looks in two locations because different pipeline layouts write
    the dossier to either root ``contracts/`` or ``src/contracts/``.
    """
    if not output_dir:
        return []
    base = Path(output_dir)
    candidates = [
        base / "contracts" / "discovery.json",
        base / "src" / "contracts" / "discovery.json",
    ]
    for p in candidates:
        try:
            if not p.is_file():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[vocab-composer] discovery read failed at %s: %s", p, exc)
            continue
        if not isinstance(data, dict):
            continue
        patterns = data.get("designPatterns")
        if isinstance(patterns, list):
            return [pat for pat in patterns if isinstance(pat, (dict, str))]
    return []


# FORGE_VOCAB_COMPOSER is no longer read. Composition is how an app gets
# its business vocabulary, so it runs on every build; the name is kept
# only so an old export in someone's shell is inert rather than an error.


def load_requirement(output_dir: Path | str | None) -> str:
    """The user's own words for what this app must do.

    ``requirement.json`` is the authoritative record of the ask — it names
    the tiles, the columns, the filters, the row-click targets. Vocabulary
    selection used to run on keyword hits against the plan's description
    alone, so an app whose requirement spelled out a revenue dashboard was
    matched on whichever archetype happened to share the most substrings.
    Returns "" when absent; callers then fall back to plan-only scoring.
    """
    if not output_dir:
        return ""
    try:
        p = Path(output_dir) / "src" / "contracts" / "requirement.json"
        if not p.is_file():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[vocab-compose] requirement unreadable: %s", exc)
        return ""
    if isinstance(data, dict):
        parts = [str(data.get("original_prompt") or "")]
        for key in ("must_have", "named_components", "named_routes",
                    "named_action_types", "out_of_scope"):
            v = data.get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        parts.append(" ".join(
                            str(x) for x in item.values() if isinstance(x, (str, int))))
        return " ".join(p for p in parts if p).strip()
    return str(data or "")


def _cache_path(output_dir: Path | str | None) -> Path | None:
    if not output_dir:
        return None
    return Path(output_dir) / "contracts" / CACHE_FILENAME


def _load_disk_cache(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("[vocab-composer] disk cache read failed: %s", exc)
        return {}


def _write_disk_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[vocab-composer] disk cache write failed: %s", exc)


def _serialize_vocab(v: ArchetypeVocabulary) -> dict:
    return asdict(v)


def _deserialize_vocab(data: dict) -> ArchetypeVocabulary:
    prefs = {}
    for k, v in (data.get("component_preferences") or {}).items():
        if isinstance(v, dict):
            prefs[k] = ComponentPreference(
                shape=str(v.get("shape") or "table"),
                primary_field=str(v.get("primary_field") or ""),
                context=str(v.get("context") or ""),
                primary_component=str(v.get("primary_component") or ""),
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


def _serialize_lock(l: VisualLock) -> dict:
    try:
        return l.model_dump(mode="json")
    except AttributeError:
        return l.dict()  # type: ignore[attr-defined]


def _deserialize_lock(data: dict) -> VisualLock:
    return VisualLock(**data)


def _preset_for_vocab(vocab_id: str) -> VisualLock:
    return _VOCAB_TO_PRESET.get(vocab_id, ADMIN_NEUTRAL)


def _log_summary(prov: dict) -> None:
    source = prov.get("source", "?")
    cands = prov.get("candidates") or []
    if source == "composed":
        changes = prov.get("changes") or {}
        logger.info(
            "[vocab-composer] candidates=%s source=composed primary=%s preset=%s "
            "sections_added=%d personas_added=%d shapes_rejected=%d "
            "hexes_rejected=%d fonts_rejected=%d",
            cands,
            prov.get("primary_vocab") or "?",
            prov.get("primary_preset") or "?",
            len(changes.get("sections_added") or []),
            len(changes.get("personas_added") or []),
            len(changes.get("shapes_rejected") or []),
            len(changes.get("hexes_rejected") or []),
            len(changes.get("fonts_rejected") or []),
        )
    elif source == "cached":
        age = prov.get("age_seconds")
        logger.info(
            "[vocab-composer] candidates=%s source=cached age=%s",
            cands, f"{age:.1f}" if isinstance(age, (int, float)) else "?",
        )
    elif source == "single_fallback":
        logger.info(
            "[vocab-composer] source=single_fallback reason=%s",
            prov.get("reason") or "?",
        )
    elif source == "base_fallback":
        logger.info(
            "[vocab-composer] source=base_fallback reason=%s",
            prov.get("reason") or "?",
        )
    elif source == "flag_disabled":
        logger.info("[vocab-composer] source=flag_disabled")
    elif source == "no_candidates":
        logger.info(
            "[vocab-composer] source=no_candidates fallback=%s",
            prov.get("fallback") or "?",
        )
    else:
        logger.info("[vocab-composer] source=%s", source)


async def load_compose_and_modify_vocab(
    plan: dict,
    brief: Any | None = None,
    output_dir: Path | str | None = None,
) -> tuple[ArchetypeVocabulary | None, VisualLock, dict]:
    """Full compose pipeline: rank → select candidates → LLM compose → cache.

    Return shape ``(vocab, visual_lock, provenance)``.

    Behaviour:
      - Flag off → returns single-vocab modifier's result + preset-picker
        preset (provenance ``source="flag_disabled"``). Preserves current
        behavior exactly when flag is unset.
      - Flag on + no candidates crossed the min-score bar → falls back to
        single-vocab modifier on ``_archetype_from_plan`` (or ADMIN_NEUTRAL
        preset when no archetype resolves).
      - Flag on + one or more candidates → compose, persist to disk cache.
      - Disk cache hit → return cached vocab+lock, skip LLM.
      - Corrupted cache file → fresh composer call, no crash.
    """
    # No flag. Composition is how a business vocabulary is chosen for an
    # app, so it runs on every build — a merge that only happens when an
    # env var is set is a merge that never happens.
    requirement = load_requirement(output_dir)
    pool = select_candidate_pool(plan or {}, requirement=requirement)
    if not pool:
        # No hybrid signal — cascade to the single-vocab modifier so the
        # generator gets *something* to work with.
        single_id = _archetype_from_plan(plan or {})
        vocab, mod_prov = await load_and_modify_vocab(
            single_id, plan or {}, brief, output_dir,
        )
        preset = pick_preset_from_plan(plan)
        prov = {
            "source": "no_candidates",
            "candidates": [],
            "preset_source": "single",
            "primary_vocab": vocab.id if vocab is not None else single_id,
            "primary_preset": preset.preset_name,
            "fallback": mod_prov.get("source"),
        }
        _log_summary(prov)
        return vocab, preset, prov

    candidates: list[ArchetypeVocabulary] = []
    presets: list[VisualLock] = []
    for slug in pool:
        v = load_vocabulary(slug)
        if v is None:
            continue
        candidates.append(v)
        presets.append(_preset_for_vocab(slug))
    if not candidates:
        # Every pool member unregistered (shouldn't happen — ranker only
        # returns registered vocab ids — but be defensive).
        preset = pick_preset_from_plan(plan)
        prov = {
            "source": "no_candidates",
            "candidates": [],
            "preset_source": "single",
            "primary_vocab": "",
            "primary_preset": preset.preset_name,
            "fallback": "no_registered_vocabs",
        }
        _log_summary(prov)
        return None, preset, prov

    # Creative inputs — user-selected patterns (from discovery.json) +
    # variance seed (deterministic per-plan, so re-generation is stable
    # but two different plans in the same domain diverge).
    patterns = _load_patterns_from_disk(output_dir)
    variance = variance_seed_for(plan or {}) or None

    # Library manifest — cached at module scope. Persisted next to the
    # composer cache so it's inspectable + versioned with the project.
    library_manifest = _get_compact_manifest()
    _persist_compact_manifest(output_dir, library_manifest)

    # Disk cache lookup.
    key = cache_key(
        candidates, presets, plan or {}, brief,
        patterns=patterns, variance_seed=variance,
        library_manifest_compact=library_manifest,
        requirement=requirement,
    )
    disk_path = _cache_path(output_dir)
    disk_data = _load_disk_cache(disk_path) if disk_path else {}
    entry = disk_data.get(key) if isinstance(disk_data, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get("vocab"), dict) and isinstance(entry.get("visual_lock"), dict):
        try:
            cached_vocab = _deserialize_vocab(entry["vocab"])
            cached_lock = _deserialize_lock(entry["visual_lock"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[vocab-composer] cache entry corrupt: %s", exc)
            cached_vocab = None
            cached_lock = None
        if cached_vocab is not None and cached_lock is not None:
            prov = dict(entry.get("provenance") or {})
            prov["source"] = "cached"
            ts = entry.get("timestamp")
            if isinstance(ts, (int, float)):
                prov["age_seconds"] = max(0.0, time.time() - float(ts))
            _log_summary(prov)
            return cached_vocab, cached_lock, prov

    # Cache miss → run composer.
    vocab, lock, prov = await compose_vocab_and_design(
        candidates, presets, plan or {}, brief,
        patterns=patterns, variance_seed=variance,
        library_manifest_compact=library_manifest,
    )
    _log_summary(prov)

    # Only persist real compositions — flaky-LLM fallbacks stay volatile.
    if disk_path is not None and prov.get("source") == "composed":
        disk_data = disk_data if isinstance(disk_data, dict) else {}
        disk_data[key] = {
            "vocab": _serialize_vocab(vocab),
            "visual_lock": _serialize_lock(lock),
            "provenance": prov,
            "timestamp": time.time(),
        }
        _write_disk_cache(disk_path, disk_data)

    return vocab, lock, prov


def _run_coro_in_thread(coro_factory, timeout_s: float = 120.0):
    """Run an async coroutine on a fresh event loop inside a worker thread.

    Called when the sync facade is invoked from a context that already has a
    running asyncio loop (e.g. inside a FastAPI request handler) — the standard
    ``asyncio.run`` refuses to nest, so we bridge via a worker thread.

    ``coro_factory`` is a zero-arg callable that returns the coroutine object.
    The factory pattern (rather than a pre-created coroutine) avoids the
    "coroutine was never awaited" warning if construction is deferred to the
    worker thread's event loop context.
    """
    import asyncio, threading
    result: dict[str, Any] = {}

    def _runner() -> None:
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            result["value"] = new_loop.run_until_complete(coro_factory())
        except Exception as err:  # noqa: BLE001
            result["error"] = err
        finally:
            try:
                new_loop.close()
            except Exception:  # noqa: BLE001
                pass

    t = threading.Thread(target=_runner, daemon=True, name="vocab-composer-bridge")
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        raise TimeoutError(f"composer coroutine did not complete within {timeout_s}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def load_compose_and_modify_vocab_sync(
    plan: dict | None = None,
    brief: Any | None = None,
    output_dir: Path | str | None = None,
) -> tuple[ArchetypeVocabulary | None, VisualLock, dict]:
    """Sync facade — matches :func:`load_and_modify_vocab_sync`'s shape.

    Runs the async composer unconditionally — this facade is what every
    real caller uses, so a gate here is a gate on the whole feature. (It
    carried its own copy of the async path's flag check; removing only
    the async one left composition switched off for every caller, which
    is the failure mode this whole change exists to end.)

    If no event loop is active, uses the ordinary ``asyncio.run``; if a
    loop IS already running (typical FastAPI request-handler path),
    bridges to a worker thread with its own fresh loop via
    ``_run_coro_in_thread``. On any composer error (including the bridge
    timing out), falls back to the primary base vocab so the pipeline
    never crashes because vocab specialization failed.
    """
    import asyncio

    plan_arg = plan or {}
    coro_factory = lambda: load_compose_and_modify_vocab(plan_arg, brief, output_dir)

    # Prefer plain asyncio.run when no loop is active; otherwise bridge via a
    # worker thread so a running FastAPI loop doesn't block us.
    loop_running = False
    try:
        loop = asyncio.get_event_loop()
        loop_running = loop.is_running()
    except RuntimeError:
        loop_running = False

    try:
        if loop_running:
            return _run_coro_in_thread(coro_factory, timeout_s=120.0)
        return asyncio.run(coro_factory())
    except Exception as err:  # noqa: BLE001
        # Composer bridge / run failed — degrade to base vocab so the caller
        # still gets a workable result. The composer already has an internal
        # fail-open cascade, so reaching here means an infrastructure error
        # (bridge timeout, loop shutdown, etc.) rather than an LLM issue.
        preset = pick_preset_from_plan(plan_arg)
        single_id = _archetype_from_plan(plan_arg)
        vocab = load_vocabulary(single_id)
        prov = {
            "source": "base_fallback",
            "candidates": [single_id] if single_id else [],
            "preset_source": "single",
            "primary_vocab": vocab.id if vocab is not None else single_id,
            "primary_preset": preset.preset_name,
            "reason": f"bridge failed: {type(err).__name__}: {err}",
        }
        _log_summary(prov)
        return vocab, preset, prov


__all__ = [
    "CACHE_FILENAME",
    "FLAG_ENV",
    "LIBRARY_MANIFEST_COMPACT_FILENAME",
    "load_compose_and_modify_vocab",
    "load_compose_and_modify_vocab_sync",
]
