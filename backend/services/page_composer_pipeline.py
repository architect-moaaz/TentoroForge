"""Pipeline wiring for the LLM page composer (CREATIVE-6b).

Sibling to :mod:`services.vocab_composer_pipeline`. Wraps
:func:`services.page_composer.compose_page` with the production
concerns the pure composer intentionally stays out of:

  - ``FORGE_PAGE_COMPOSER=1`` env flag (default OFF). Off → returns
    ``(None, {"source": "flag_disabled"})``. On → runs the composer.

  - Loads composer inputs the deterministic apply_*_maquette callers
    don't already carry: full library manifest (module-scope memo),
    composite vocab + preset (via
    :func:`vocab_composer_pipeline.load_compose_and_modify_vocab_sync`),
    user-selected design patterns (from ``contracts/discovery.json``),
    per-plan variance seed.

  - Project-scoped disk cache at
    ``<output_dir>/contracts/page-composer-cache.json``. Keyed on the
    composer's :func:`page_composer.cache_key` so an in-memory hit and
    a disk hit resolve identically. Failures are NEVER persisted — a
    flaky LLM should not stick as the cached answer.

  - Exactly-one INFO log per call summarising source + counts.

  - Fail-open cascade — any error returns ``(None, provenance)`` so
    each deterministic apply_*_maquette caller transparently falls
    through to its existing recipe.

Also exposes :func:`_write_page_schema` — the tiny helper each
apply_*_maquette caller uses to persist an LLM-composed schema to
the same on-disk location the deterministic path would have written.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.library_manifest import build_library_manifest
from services.page_composer import cache_key, compose_page
from services.list_sort_authority import apply_list_sort
from services.pipeline.variance import variance_seed_for

logger = logging.getLogger(__name__)

FLAG_ENV = "FORGE_PAGE_COMPOSER"
CONCURRENCY_ENV = "FORGE_PAGE_COMPOSER_CONCURRENCY"
VISION_ENV = "FORGE_COMPOSER_VISION"
CACHE_FILENAME = "page-composer-cache.json"
DEFAULT_CONCURRENCY = 4
_OFF_VALUES = frozenset({"0", "false", "no", "off"})


# --------------------------------------------------------------------- #
# Module-scope caches (library manifest is stable per process)
# --------------------------------------------------------------------- #

_LIBRARY_MANIFEST_CACHE: dict | None = None

# Disk-cache memo, keyed by path → (mtime, parsed). The cache file is
# read once per composed page and grows with every entry written, so on
# an 85-page app the naive path re-parses a steadily larger JSON blob 85
# times — quadratic I/O for data this process itself just wrote. mtime
# guards it: an external writer still invalidates.
_DISK_CACHE_MEMO: dict[str, tuple[float, dict]] = {}


def _reset_manifest_cache_for_tests() -> None:
    global _LIBRARY_MANIFEST_CACHE
    _LIBRARY_MANIFEST_CACHE = None
    _DISK_CACHE_MEMO.clear()


def _get_library_manifest() -> dict:
    global _LIBRARY_MANIFEST_CACHE
    if _LIBRARY_MANIFEST_CACHE is None:
        try:
            _LIBRARY_MANIFEST_CACHE = build_library_manifest()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[page-composer] manifest build failed: %s", exc)
            _LIBRARY_MANIFEST_CACHE = {"components": {}}
    return _LIBRARY_MANIFEST_CACHE


# --------------------------------------------------------------------- #
# Flag + cache path helpers (mirror vocab_composer_pipeline)
# --------------------------------------------------------------------- #

def _flag_on() -> bool:
    """Return True when FORGE_PAGE_COMPOSER is explicitly enabled."""
    raw = os.getenv(FLAG_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _concurrency() -> int:
    """How many page compositions may be in flight at once.

    Deliberately modest by default. The ceiling here is the Anthropic
    account's rate limit, not the local machine — push it too high and
    every request pays retry/backoff, which costs more wall-clock than
    the parallelism buys. Raise via ``FORGE_PAGE_COMPOSER_CONCURRENCY``
    on accounts with the headroom; 1 restores strictly sequential.
    """
    raw = os.getenv(CONCURRENCY_ENV, "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return min(n, 32)
        except ValueError:
            logger.warning(
                "[page-composer] ignoring non-integer %s=%r", CONCURRENCY_ENV, raw,
            )
    return DEFAULT_CONCURRENCY


def is_flag_on() -> bool:
    """Public accessor — callers use it to short-circuit expensive setup
    when the composer would be a no-op anyway (see the early-exit hooks
    inside each :mod:`services.apply_*_maquette`)."""
    return _flag_on()


def _cache_path(output_dir: Path | str | None) -> Path | None:
    if not output_dir:
        return None
    return Path(output_dir) / "contracts" / CACHE_FILENAME


def _load_disk_cache(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        key = str(path)
        mtime = path.stat().st_mtime
        memo = _DISK_CACHE_MEMO.get(key)
        if memo is not None and memo[0] == mtime:
            return memo[1]
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        _DISK_CACHE_MEMO[key] = (mtime, data)
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] disk cache read failed: %s", exc)
        return {}


def _write_disk_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        try:
            _DISK_CACHE_MEMO[str(path)] = (path.stat().st_mtime, data)
        except OSError:
            _DISK_CACHE_MEMO.pop(str(path), None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] disk cache write failed: %s", exc)


def _load_patterns_from_disk(output_dir: Path | str | None) -> list[dict]:
    """Return the ``designPatterns`` list from ``contracts/discovery.json``.

    Duplicated from vocab_composer_pipeline (rather than imported) so a
    change there doesn't silently reshape page composition.
    """
    if not output_dir:
        return []
    base = Path(output_dir)
    for p in (
        base / "contracts" / "discovery.json",
        base / "src" / "contracts" / "discovery.json",
    ):
        try:
            if not p.is_file():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[page-composer] discovery read failed at %s: %s", p, exc)
            continue
        if not isinstance(data, dict):
            continue
        patterns = data.get("designPatterns")
        if isinstance(patterns, list):
            return [pat for pat in patterns if isinstance(pat, (dict, str))]
    return []


# --------------------------------------------------------------------- #
# Vocab + preset load — reuses the vocab_composer pipeline
# --------------------------------------------------------------------- #

def _load_vocab_and_preset(plan: dict, brief: Any | None, output_dir: Path | str | None):
    """Return ``(vocab, preset)`` via the vocab composer pipeline.

    Returns ``(None, None)`` when the vocab pipeline itself fails — the
    caller treats that as "cannot compose" and returns
    ``source: "failed"``. Never raises.
    """
    try:
        from services.vocab_composer_pipeline import load_compose_and_modify_vocab_sync
        vocab, preset, _prov = load_compose_and_modify_vocab_sync(
            plan=plan or {}, brief=brief, output_dir=output_dir,
        )
        return vocab, preset
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] vocab/preset load failed: %s", exc)
        return None, None


# --------------------------------------------------------------------- #
# Shared composer inputs
#
# Every page in a run composes against the SAME vocab, preset, manifest,
# patterns and variance seed — they derive from the plan and the brief,
# not from the page. Loading them per page (as the single-page path did
# on its own) re-entered the vocab composer pipeline once per page: on a
# 46-page plan that is 46 rebuilds of an identical object, each carrying
# its own retry/backoff against the API. Load once, pass down.
# --------------------------------------------------------------------- #

def _load_composer_inputs(
    plan: dict, brief: Any | None, output_dir: Path | str | None,
) -> dict | None:
    """Return the run-scoped inputs every page composition shares.

    Returns ``None`` when a required input can't be built — the caller
    turns that into ``source: "failed"`` and falls through to the
    deterministic path, exactly as before.
    """
    try:
        library_manifest = _get_library_manifest()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] manifest load failed: %s", exc)
        return None

    vocab, preset = _load_vocab_and_preset(plan or {}, brief, output_dir)
    if vocab is None or preset is None:
        return None

    return {
        "library_manifest": library_manifest,
        "vocab": vocab,
        "preset": preset,
        "patterns": _load_patterns_from_disk(output_dir),
        "variance": variance_seed_for(plan or {}) or None,
        "brief": brief,
        "reference_images": _load_reference_images(output_dir),
    }


def _vision_enabled() -> bool:
    """Whether the composer may look at the montage. On unless opted out.

    The switch exists so the same build can be run with and without the
    screens and the two outputs compared — the whole point of the change
    is to find out how much the pictures are worth versus the paragraph
    the vision call currently boils them down to.
    """
    raw = os.getenv(VISION_ENV, "").strip().lower()
    return raw not in _OFF_VALUES


def _load_reference_images(output_dir: Path | str | None) -> list[dict]:
    """The montage image blocks for this app, or ``[]``.

    The composition reference records which project it was read from
    (see ``plan_finalize.ensure_composition_reference``); the images
    themselves stay in the attachment store rather than being copied
    into the app directory, since they can be several megabytes and the
    app dir is shipped.

    Returns ``[]`` for every failure mode — no montage designated, no
    project id (the built-in default reference has none), attachment
    store unreachable — and the composer then behaves exactly as it did
    before, on prose alone.
    """
    if not output_dir or not _vision_enabled():
        return []
    for cand in ("src/contracts/composition-reference.json",
                 "contracts/composition-reference.json"):
        ref = _load_disk_json(Path(output_dir) / cand)
        if not isinstance(ref, dict):
            continue
        project_id = ref.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            return []
        try:
            from services.chat_attachments import attachments_root
            from services.design_reference import load_design_reference_blocks
            blocks = load_design_reference_blocks(attachments_root(), project_id)
        except Exception as exc:  # noqa: BLE001 — best-effort by contract
            logger.info("[page-composer] montage images unavailable: %s", exc)
            return []
        if blocks:
            logger.info("[page-composer] composing against %d montage screen(s)",
                        len(blocks))
        return list(blocks)
    return []


# --------------------------------------------------------------------- #
# Built-in reference screens
# --------------------------------------------------------------------- #
#
# Almost no project designates its own montage, so the branch above is the
# rare case. The repo already carries 24 curated reference screens under
# ``fixtures/reference_images``, indexed by domain AND page type — and
# until now the only thing that read them was the fidelity scorer, which
# graded finished pages against them AFTER the fact.
#
# Composing against the same image the scorer will grade against closes
# that loop: the composer is no longer guessing at a bar it is later
# measured by. It also beats a nine-screen montage on precision — a list
# page gets the list reference, not a dashboard it must ignore.
#
# Domain resolution is fidelity_scorer's, not a second copy, so author-
# time and score-time can never disagree about which reference applies.

# Composer page kinds → reference-index page types. Kinds absent here
# (settings, and anything unrecognised) get no built-in reference rather
# than a poor match — a wrong reference is worse than none, since the
# model is told to follow it.
_KIND_TO_REFERENCE_TYPE = {
    "list": "list", "collection": "list",
    "detail": "detail", "record": "detail",
    "dashboard": "dashboard",
    "form": "form", "create": "form", "edit": "form",
    "login": "login", "signup": "login", "auth": "login",
    "calendar": "calendar", "schedule": "calendar",
}


@lru_cache(maxsize=32)
def _builtin_reference_block(domain: str, page_type: str) -> tuple | None:
    """One base64 image block for a curated reference, or None.

    Cached as a tuple of pairs because ``lru_cache`` needs a hashable
    return and these are ~600 KB of base64 each — decoding the same PNG
    once per page on an 85-page app would be pure waste.
    """
    from services.fidelity_scorer import reference_path_for

    try:
        path = reference_path_for(domain, page_type)
        if path is None:
            return None
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — a missing fixture is not fatal
        logger.info("[page-composer] reference %s/%s unreadable: %s",
                    domain, page_type, exc)
        return None
    return (("media_type", "image/png"), ("data", data))


def _reference_images_for(inputs: dict, page: dict, plan: dict) -> list[dict]:
    """The screens this page composes against, best available first.

    A project's own designated montage wins outright — it is what this
    product's designer chose. Only when there is none does the built-in
    curated reference for (domain, page kind) fill the silence.
    """
    designated = inputs.get("reference_images")
    if designated:
        return list(designated)
    if not _vision_enabled():
        return []

    kind = str((page or {}).get("kind") or (page or {}).get("type") or "").strip().lower()
    page_type = _KIND_TO_REFERENCE_TYPE.get(kind)
    if not page_type:
        return []

    from services.fidelity_scorer import normalize_domain

    domain = normalize_domain(
        (plan or {}).get("domain") or (plan or {}).get("industry") or "")
    block = _builtin_reference_block(domain, page_type)
    if block is None:
        return []
    fields = dict(block)
    return [
        {"type": "text",
         "text": f"Reference screen — a well-designed {page_type} page."},
        {"type": "image",
         "source": {"type": "base64",
                    "media_type": fields["media_type"],
                    "data": fields["data"]}},
    ]


def _load_disk_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _cache_key_for(page: dict, plan: dict, inputs: dict) -> str:
    """Cache key for ``page`` under the run's shared ``inputs``.

    One implementation so the single-page and prefetch paths cannot
    drift: a key computed by the prefetch MUST be the key the per-page
    lookup later asks for, or the prefetch silently buys nothing.

    ``cache_key`` fingerprints the manifest subset the composer filters
    to internally, not the whole manifest — mirror that here.
    """
    from services.page_composer import _filter_manifest_for_page
    manifest_subset = _filter_manifest_for_page(
        inputs["library_manifest"],
        (page or {}).get("kind") or (page or {}).get("type") or "",
    )
    return cache_key(
        page or {}, plan or {}, inputs["vocab"], inputs["preset"], manifest_subset,
        patterns=inputs["patterns"], variance_seed=inputs["variance"],
        brief=inputs["brief"],
        reference_images=_reference_images_for(inputs, page or {}, plan or {}),
    )


# --------------------------------------------------------------------- #
# Page-schema write helper — one place so all three apply_*_maquette
# callers use the same on-disk location as the deterministic path.
# --------------------------------------------------------------------- #

def _route_to_slug(route: str) -> str:
    return route.strip("/") or "index"


def _load_plan_json(output_dir: Path | str) -> dict:
    """Read ``src/contracts/plan.json`` — returns ``{}`` on any failure."""
    try:
        p = Path(output_dir) / "src" / "contracts" / "plan.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001
        logger.debug("[page-composer] plan load failed: %s", exc)
    return {}


def _find_plan_page(plan: dict, route: str) -> dict | None:
    """Look up the plan page matching ``route`` — used to enrich the page
    dict passed to :func:`compose_page` with title/description/etc that
    the maquette itself doesn't carry."""
    if not (isinstance(plan, dict) and isinstance(route, str)):
        return None
    for p in plan.get("pages") or []:
        if isinstance(p, dict) and p.get("route") == route:
            return p
    return None


def page_from_maquette(maquette: dict, plan: dict, kind: str) -> dict:
    """Build the ``page`` dict that :func:`compose_page` expects from a
    maquette entry (collection/record) or a whole-dashboard maquette.

    Enriches with the matching ``plan.pages[]`` entry when it's on disk;
    otherwise sticks to what the maquette itself carries.
    """
    mq = maquette if isinstance(maquette, dict) else {}
    route = mq.get("route") or ""
    entity = mq.get("entity") or ""
    plan_page = _find_plan_page(plan, route) or {}
    if not entity:
        entity = plan_page.get("entity") or ""
    return {
        "id": plan_page.get("id") or (route.strip("/").replace("/", "-") or "page"),
        "route": route,
        "kind": kind,
        "entity": entity,
        "title": plan_page.get("title") or plan_page.get("name") or mq.get("title") or "",
        "description": plan_page.get("description") or "",
    }


def _write_page_schema(page: dict, schema: dict, output_dir: Path | str) -> Path | None:
    """Persist an LLM-composed page schema to ``src/schemas/<slug>.json``.

    ``page`` needs a ``route`` (used to derive the slug). The composer
    stamps ``meta`` with a marker key so the deterministic apply_*_maquette
    callers know to skip re-composing on a subsequent run.

    Returns the written path on success, None on any failure.
    """
    route = (page or {}).get("route") if isinstance(page, dict) else None
    if not (isinstance(route, str) and route.startswith("/")):
        logger.warning("[page-composer] write skipped — missing/bad page.route")
        return None
    slug = _route_to_slug(route)
    schemas_dir = Path(output_dir) / "src" / "schemas"
    target = schemas_dir / f"{slug}.json"
    try:
        # Stamp both deterministic markers so the collection / record /
        # dashboard apply_*_maquette passes recognise our write and don't
        # rewrite the file with their own composer.
        meta = schema.setdefault("meta", {}) if isinstance(schema, dict) else {}
        if isinstance(meta, dict):
            meta.setdefault("page_composer_composed", True)
            meta.setdefault("maquette_composed", True)
            meta.setdefault("collection_maquette_composed", True)
            meta.setdefault("record_maquette_composed", True)
        # Sanitize before write — matches the deterministic path.
        try:
            from services.composer_prop_hygiene import sanitize_schema as _sanitize
            _sanitize(schema)
        except Exception:  # noqa: BLE001
            pass
        schemas_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        return target
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] write failed for %s: %s", target, exc)
        return None


# --------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------- #

def _log_summary(page_id: str, prov: dict) -> None:
    """Emit exactly one INFO log per call."""
    source = (prov or {}).get("source", "?")
    if source == "composed":
        changes = (prov or {}).get("changes") or {}
        # Count nodes by walking the schema when the composer returned it —
        # cheap and gives one clear number the operator can eyeball.
        nodes = changes.get("nodes_composed")
        ds = changes.get("data_sources_emitted")
        logger.info(
            "[page-composer] page=%s source=composed nodes=%s dataSources=%s",
            page_id, nodes if nodes is not None else "?",
            ds if ds is not None else "?",
        )
    elif source == "cached":
        age = (prov or {}).get("age_seconds")
        logger.info(
            "[page-composer] page=%s source=cached age=%ss",
            page_id, f"{age:.1f}" if isinstance(age, (int, float)) else "?",
        )
    elif source == "failed":
        logger.info(
            "[page-composer] page=%s source=failed reason=%s",
            page_id, (prov or {}).get("reason") or "?",
        )
    elif source == "flag_disabled":
        logger.info("[page-composer] page=%s source=flag_disabled", page_id)
    else:
        logger.info("[page-composer] page=%s source=%s", page_id, source)


def _count_nodes(schema: dict) -> int:
    """Depth-first node count for the log line. Never raises."""
    count = 0
    stack: list[Any] = [schema.get("root") if isinstance(schema, dict) else None]
    while stack:
        n = stack.pop()
        if isinstance(n, dict) and isinstance(n.get("type"), str):
            count += 1
            children = n.get("children")
            if isinstance(children, list):
                stack.extend(children)
    return count


# --------------------------------------------------------------------- #
# Public entrypoints
# --------------------------------------------------------------------- #

async def compose_page_via_pipeline(
    page: dict,
    plan: dict,
    output_dir: Path | str,
    *,
    brief: Any | None = None,
) -> tuple[dict | None, dict]:
    """Full pipeline invocation of the page composer.

    Behaviour:
      - Flag off → ``(None, {"source": "flag_disabled"})`` — the LLM is
        NEVER invoked (deterministic composers keep the default path).
      - Cache hit (disk) → returns the cached schema, marks ``source: "cached"``.
      - Otherwise: builds inputs, calls :func:`page_composer.compose_page`.
      - On any failure returns ``(None, provenance)`` so the caller can
        fall through to the deterministic composer. Failures are NOT
        persisted to disk cache.
    """
    page_id = (page or {}).get("route") or (page or {}).get("id") or "?"

    if not _flag_on():
        prov = {"source": "flag_disabled"}
        _log_summary(page_id, prov)
        return None, prov

    # Load composer inputs. Any failure short-circuits to source="failed".
    inputs = _load_composer_inputs(plan or {}, brief, output_dir)
    if inputs is None:
        prov = {"source": "failed", "reason": "vocab_or_preset_missing"}
        _log_summary(page_id, prov)
        return None, prov

    library_manifest = inputs["library_manifest"]
    vocab = inputs["vocab"]
    preset = inputs["preset"]
    patterns = inputs["patterns"]
    variance = inputs["variance"]

    key = _cache_key_for(page or {}, plan or {}, inputs)
    disk_path = _cache_path(output_dir)
    disk_data = _load_disk_cache(disk_path) if disk_path else {}
    entry = disk_data.get(key) if isinstance(disk_data, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get("schema"), dict):
        cached_schema = entry["schema"]
        cached_prov = dict(entry.get("provenance") or {})
        cached_prov["source"] = "cached"
        ts = entry.get("timestamp")
        if isinstance(ts, (int, float)):
            cached_prov["age_seconds"] = max(0.0, time.time() - float(ts))
        apply_list_sort(cached_schema, plan or {}, vocab)
        _log_summary(page_id, cached_prov)
        return cached_schema, cached_prov

    # Cache miss → run the composer.
    schema, prov = await compose_page(
        page or {}, plan or {}, vocab, preset, library_manifest,
        patterns=patterns, variance_seed=variance, brief=brief,
        reference_images=_reference_images_for(inputs, page or {}, plan or {}),
    )

    if schema is not None and prov.get("source") == "composed":
        # The domain owns row order — see services.list_sort_authority for
        # why this is not a line in the composer's prompt.
        sorted_sources = apply_list_sort(schema, plan or {}, vocab)
        # Enrich prov with node count for the log + downstream inspection.
        prov = dict(prov)
        changes = dict(prov.get("changes") or {})
        changes["nodes_composed"] = _count_nodes(schema)
        if sorted_sources:
            changes["list_order_set"] = len(sorted_sources)
        prov["changes"] = changes

        # Persist only successful compositions to disk cache.
        if disk_path is not None:
            disk_data = disk_data if isinstance(disk_data, dict) else {}
            disk_data[key] = {
                "schema": schema,
                "provenance": prov,
                "timestamp": time.time(),
                "page_id": page_id,
            }
            _write_disk_cache(disk_path, disk_data)

    _log_summary(page_id, prov)
    return schema, prov


async def prefetch_pages_via_pipeline(
    pages: list[dict],
    plan: dict,
    output_dir: Path | str,
    *,
    brief: Any | None = None,
    concurrency: int | None = None,
) -> dict:
    """Compose many pages concurrently and warm the disk cache.

    This exists because composition is per-page but its *cost* is
    per-run. Each ``compose_page`` is one LLM round-trip of roughly a
    minute; driven one at a time from the apply loop, a 46-page plan
    spends over half an hour serialised on latency it never had to pay.
    Nothing about the calls is ordered — no page reads another page's
    output — so the only reason they ran in sequence was the shape of
    the caller.

    The design is deliberately additive: this only WRITES the disk
    cache. ``_apply_one`` keeps calling the single-page entrypoint
    unchanged, and simply finds a hit. So every fallback the appliers
    already have still applies, and if this whole pass fails the build
    degrades to exactly today's sequential behaviour instead of
    breaking. That also means it is safe to call speculatively for
    pages that may never be composed — a wasted entry costs cache
    bytes, not correctness.

    Returns a diagnostic dict; never raises.
    """
    stats = {"requested": 0, "cached": 0, "composed": 0, "failed": 0, "skipped": 0}
    if not _flag_on():
        stats["skipped"] = len(pages or [])
        return stats

    wanted = [p for p in (pages or []) if isinstance(p, dict) and p.get("route")]
    stats["requested"] = len(wanted)
    if not wanted:
        return stats

    inputs = _load_composer_inputs(plan or {}, brief, output_dir)
    if inputs is None:
        logger.warning("[page-composer] prefetch skipped — composer inputs unavailable")
        stats["failed"] = len(wanted)
        return stats

    disk_path = _cache_path(output_dir)
    disk_data = _load_disk_cache(disk_path) if disk_path else {}
    if not isinstance(disk_data, dict):
        disk_data = {}
    # Copy: we mutate our own dict and write once, rather than racing
    # the memo that _load_disk_cache may have handed us by reference.
    disk_data = dict(disk_data)

    # Compute keys up front and drop the ones already on disk, so a
    # resumed or re-run build pays nothing for work it already did.
    todo: list[tuple[str, dict]] = []
    for page in wanted:
        try:
            key = _cache_key_for(page, plan or {}, inputs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[page-composer] prefetch key failed for %s: %s",
                         page.get("route"), exc)
            stats["failed"] += 1
            continue
        entry = disk_data.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("schema"), dict):
            stats["cached"] += 1
            continue
        todo.append((key, page))

    if not todo:
        logger.info(
            "[page-composer] prefetch: %d page(s) already cached, nothing to compose",
            stats["cached"],
        )
        return stats

    limit = concurrency if isinstance(concurrency, int) and concurrency > 0 else _concurrency()
    sem = asyncio.Semaphore(limit)
    logger.info(
        "[page-composer] prefetch: composing %d page(s) at concurrency=%d (%d cached)",
        len(todo), limit, stats["cached"],
    )

    async def _one(key: str, page: dict) -> tuple[str, dict | None, dict]:
        async with sem:
            try:
                schema, prov = await compose_page(
                    page, plan or {}, inputs["vocab"], inputs["preset"],
                    inputs["library_manifest"], patterns=inputs["patterns"],
                    variance_seed=inputs["variance"], brief=inputs["brief"],
                    reference_images=_reference_images_for(
                        inputs, page, plan or {}),
                )
                return key, schema, prov
            except Exception as exc:  # noqa: BLE001
                # One page's failure must not abort the batch — it falls
                # back to the deterministic composer like any other miss.
                return key, None, {
                    "source": "failed", "reason": "prefetch_error",
                    "detail": f"{type(exc).__name__}: {exc}",
                }

    results = await asyncio.gather(
        *(_one(k, p) for k, p in todo), return_exceptions=True,
    )

    by_key = {k: p for k, p in todo}
    for res in results:
        if isinstance(res, BaseException):
            stats["failed"] += 1
            continue
        key, schema, prov = res
        page = by_key.get(key) or {}
        page_id = page.get("route") or page.get("id") or "?"
        if schema is not None and (prov or {}).get("source") == "composed":
            prov = dict(prov)
            changes = dict(prov.get("changes") or {})
            changes["nodes_composed"] = _count_nodes(schema)
            prov["changes"] = changes
            disk_data[key] = {
                "schema": schema,
                "provenance": prov,
                "timestamp": time.time(),
                "page_id": page_id,
            }
            stats["composed"] += 1
        else:
            # Failures are never persisted — a flaky call must not stick
            # as the cached answer for the rest of the build.
            stats["failed"] += 1
        _log_summary(page_id, prov)

    if disk_path is not None and stats["composed"]:
        _write_disk_cache(disk_path, disk_data)

    logger.info(
        "[page-composer] prefetch done: composed=%d cached=%d failed=%d",
        stats["composed"], stats["cached"], stats["failed"],
    )
    return stats


def prefetch_pages_via_pipeline_sync(
    pages: list[dict],
    plan: dict,
    output_dir: Path | str,
    *,
    brief: Any | None = None,
    concurrency: int | None = None,
) -> dict:
    """Sync facade over :func:`prefetch_pages_via_pipeline`.

    Mirrors :func:`compose_page_via_pipeline_sync`'s bridge, but with a
    timeout scaled to the batch: the whole point is that many pages are
    in flight, so a single-page timeout would kill the pass just as it
    started paying off.
    """
    if not _flag_on():
        return {"requested": 0, "cached": 0, "composed": 0, "failed": 0,
                "skipped": len(pages or [])}

    n = len([p for p in (pages or []) if isinstance(p, dict)])
    limit = concurrency if isinstance(concurrency, int) and concurrency > 0 else _concurrency()
    # Per-page budget × waves, floored so small batches still get room.
    waves = max(1, (n + limit - 1) // max(1, limit))
    timeout_s = max(300.0, min(3600.0, 120.0 * waves))

    coro_factory = lambda: prefetch_pages_via_pipeline(
        pages, plan, output_dir, brief=brief, concurrency=concurrency,
    )
    loop_running = False
    try:
        loop_running = asyncio.get_event_loop().is_running()
    except RuntimeError:
        loop_running = False
    try:
        if loop_running:
            return _run_coro_in_thread(coro_factory, timeout_s=timeout_s)
        return asyncio.run(coro_factory())
    except Exception as err:  # noqa: BLE001
        # Non-fatal by construction: callers proceed to their per-page
        # path, which composes on demand exactly as it did before.
        logger.warning("[page-composer] prefetch bridge failed (non-fatal): %s", err)
        return {"requested": n, "cached": 0, "composed": 0, "failed": n, "skipped": 0}


def prefetch_maquette_pages(
    output_dir: Path | str,
    maquette_entries: list[dict],
    kind: str,
) -> dict:
    """Batch-warm the composer cache from a list of maquette entries.

    The convenience wrapper the ``apply_*_maquette`` batch loops call:
    loads plan + brief from disk (the appliers each already do this
    per page), converts entries to composer ``page`` dicts via
    :func:`page_from_maquette`, then hands off to the concurrent
    prefetch. Returns its stats dict; never raises.
    """
    if not _flag_on():
        return {"requested": 0, "cached": 0, "composed": 0, "failed": 0, "skipped": 0}
    try:
        root = Path(output_dir)
        plan = _load_plan_json(root)
        try:
            from services.page_vocabulary import _load_brief
            brief = _load_brief(root)
        except Exception:  # noqa: BLE001
            brief = None
        pages = [
            page_from_maquette(e, plan, kind)
            for e in (maquette_entries or [])
            if isinstance(e, dict)
        ]
        return prefetch_pages_via_pipeline_sync(pages, plan, root, brief=brief)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] maquette prefetch skipped: %s", exc)
        return {"requested": 0, "cached": 0, "composed": 0, "failed": 0, "skipped": 0}


def _run_coro_in_thread(coro_factory, timeout_s: float = 120.0):
    """Run an async coroutine on a fresh event loop inside a worker thread.

    Mirrors :func:`vocab_composer_pipeline._run_coro_in_thread` — used when
    the sync facade is invoked from a context that already has a running
    asyncio loop (FastAPI request handler).
    """
    import threading
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

    t = threading.Thread(target=_runner, daemon=True, name="page-composer-pipeline-bridge")
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        raise TimeoutError(f"page composer pipeline did not complete within {timeout_s}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def compose_page_via_pipeline_sync(
    page: dict,
    plan: dict,
    output_dir: Path | str,
    *,
    brief: Any | None = None,
) -> tuple[dict | None, dict]:
    """Sync facade over :func:`compose_page_via_pipeline`.

    Fast-path: when the flag is OFF, returns immediately without touching
    asyncio or loading any inputs. Otherwise bridges to a worker thread
    when a loop is running, plain ``asyncio.run`` when it isn't. Any
    bridge-level failure returns ``source: "failed"``.
    """
    if not _flag_on():
        page_id = (page or {}).get("route") or (page or {}).get("id") or "?"
        prov = {"source": "flag_disabled"}
        _log_summary(page_id, prov)
        return None, prov

    coro_factory = lambda: compose_page_via_pipeline(
        page, plan, output_dir, brief=brief,
    )
    loop_running = False
    try:
        loop = asyncio.get_event_loop()
        loop_running = loop.is_running()
    except RuntimeError:
        loop_running = False
    try:
        if loop_running:
            return _run_coro_in_thread(coro_factory, timeout_s=180.0)
        return asyncio.run(coro_factory())
    except Exception as err:  # noqa: BLE001
        page_id = (page or {}).get("route") or (page or {}).get("id") or "?"
        prov = {
            "source": "failed",
            "reason": "bridge_error",
            "detail": f"{type(err).__name__}: {err}",
        }
        logger.warning("[page-composer] sync bridge failed: %s", err)
        _log_summary(page_id, prov)
        return None, prov


__all__ = [
    "CACHE_FILENAME",
    "CONCURRENCY_ENV",
    "VISION_ENV",
    "DEFAULT_CONCURRENCY",
    "FLAG_ENV",
    "compose_page_via_pipeline",
    "compose_page_via_pipeline_sync",
    "is_flag_on",
    "page_from_maquette",
    "prefetch_pages_via_pipeline",
    "prefetch_pages_via_pipeline_sync",
    "_write_page_schema",
]
