"""Shared pre-page-authoring steps that both the standard and Figma
pipelines must run. Extracted from routers/generate.py so the two
entry points don't drift.

Two responsibilities:

1. **Domain re-classification.** The planner LLM is prompted to return
   ``plan.domain`` from a 5-value enum (``general | hr | fintech |
   healthcare | saas``). Real products don't fit — a yoga studio or
   recruitment agency always classifies as ``general``, and every
   downstream domain-aware seam then falls back to generic behaviour
   (photo picker, palette bias, domain-appropriate patterns).
   :func:`reclassify_plan_domain` re-runs the 17-bucket keyword
   classifier from :mod:`services.domain_context` and overwrites
   ``plan.domain`` when the planner returned generic.

2. **Dashboard maquette authoring.** One focused LLM turn produces
   ``contracts/dashboard-maquette.json`` — the content decision
   (KPIs, primary chart, activity feed, hero) that the downstream
   deterministic composer assembles into the actual page schema.
   :func:`author_dashboard_maquette_if_enabled` handles the gate
   check + persistence.

3. **Composition reference.** When the user designated a montage as the
   design reference, :func:`ensure_composition_reference` reads it once for
   LAYOUT and DENSITY and persists ``contracts/composition-reference.json``.
   It must run *before* the three maquette authors: they all read that file
   to learn what a screen of their kind should carry and how dense it should
   be. One call here serves all three — and until this existed, nothing
   wrote the file they were already reading. When no montage is designated
   it falls back to the built-in general-business reference
   (:mod:`services.default_composition`), so the bar applies to every app
   rather than only to projects that upload one.

All are idempotent + fail-closed: a failure logs and skips, the
pipeline continues with whatever the previous authority produced.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


_GENERIC_DOMAIN_VALUES = {"", "general", "generic", "other", "misc", "app"}


def reclassify_plan_domain(plan: dict, description: str | None = None) -> tuple[str, str, bool]:
    """Re-run the richer domain classifier and stamp ``plan.domain``.

    Returns ``(before, after, changed)``. Never raises — on any failure
    the plan is left untouched and ``(before, before, False)`` is returned.

    The planner LLM's ``domain`` is a 5-value enum
    (``general | hr | fintech | healthcare | saas``) that maps almost
    every real product to ``general``. Downstream seams (photo picker,
    palette bias, domain-appropriate patterns in the schema prompt,
    `industry_design.py` register selection) branch on this value and
    silently fall back when it's generic. Re-classifying with the
    17-bucket keyword matcher from :mod:`services.domain_context` gives
    a value like ``Wellness & Fitness`` or ``Hospitality & Food`` that
    those seams can actually specialize on.

    Priority order for the source text: explicit ``description`` arg,
    then ``plan.description``, then ``plan.brief``, then
    ``plan.module_name`` as a last resort.
    """
    if not isinstance(plan, dict):
        return ("", "", False)
    before = str(plan.get("domain") or "")
    text = (
        description
        or str(plan.get("description") or "")
        or str(plan.get("brief") or "")
        or str(plan.get("module_name") or "")
    )
    if not text.strip():
        return (before, before, False)
    if before.strip().lower() not in _GENERIC_DOMAIN_VALUES:
        # Planner picked a non-generic value — trust it, don't clobber.
        return (before, before, False)
    try:
        from services.domain_context import _classify_domain
        richer = _classify_domain(text.lower(), text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] domain reclassify failed: %s", exc)
        return (before, before, False)
    if not richer or richer.strip().lower() in _GENERIC_DOMAIN_VALUES:
        return (before, before, False)
    plan["domain"] = richer
    logger.info("[plan-finalize] domain %r → %r (from description)", before, richer)
    return (before, richer, True)


def _design_reference_blocks(project_id: str) -> list[dict]:
    """Anthropic image blocks for the project's designated montage, or `[]`.

    A seam of its own so tests can supply blocks without standing up the
    attachment store.
    """
    from services.chat_attachments import attachments_root
    from services.design_reference import load_design_reference_blocks

    return load_design_reference_blocks(attachments_root(), project_id)


async def ensure_composition_reference(
    plan: dict,
    output_dir: str,
    project_id: str | None,
) -> Optional[dict]:
    """Read the designated montage for composition; persist it for the authors.

    Returns the reference dict, or None when there is no montage, no project,
    or anything at all went wrong. Must be called before the maquette authors
    — they read the file this writes.

    Idempotent by file existence, which also makes it resume-safe: a build
    that crashes after this point and resumes from a checkpoint reuses the
    reference instead of paying for a second vision call.
    """
    if not project_id:
        return None

    from services.montage_composition import (
        _FILENAME, extract_composition_reference, save_composition_reference,
    )

    existing = Path(output_dir) / "src" / "contracts" / _FILENAME
    if existing.is_file():
        try:
            return json.loads(existing.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — corrupt file: re-author below
            logger.info("[montage] existing reference unreadable; re-authoring")

    try:
        blocks = _design_reference_blocks(project_id)
    except Exception as exc:  # noqa: BLE001
        logger.info("[montage] design-reference lookup failed: %s", exc)
        return None
    if not blocks:
        # Nothing designated — the common case, and until now the end of the
        # road. Fall back to the built-in reference so every app inherits a
        # bar instead of only the projects that upload a montage.
        from services.default_composition import default_composition_reference

        fallback = default_composition_reference(plan)
        if fallback is None:
            return None
        try:
            save_composition_reference(output_dir, fallback)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[montage] could not persist default reference: %s", exc)
            return None
        logger.info("[montage] no project montage; using built-in default (%s)",
                    fallback.get("source") or "general-business")
        return fallback

    try:
        # Blocking vision call: off the event loop, same as the other
        # LLM turns in this pipeline (see BUG-ASYNC-1/2).
        import asyncio
        reference = await asyncio.to_thread(extract_composition_reference, blocks)
    except Exception as exc:  # noqa: BLE001 — includes MontageCompositionError
        logger.info("[montage] composition read failed: %s", exc)
        return None

    # Record which project the montage came from. The vision call above
    # compresses nine screens into a paragraph, and until now that
    # paragraph was the only thing any downstream author ever saw — the
    # images were fetched, read once, and dropped. Stamping the id lets
    # the page composer re-load the actual screens at compose time and
    # look at them, which is a different order of information than
    # "fixed left sidebar with grouped primary and admin sections".
    # Only the id is persisted; the images stay in the attachment store.
    if isinstance(reference, dict):
        reference["project_id"] = project_id

    try:
        save_composition_reference(output_dir, reference)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[montage] could not persist composition reference: %s", exc)
        return None

    logger.info("[montage] composition reference ready for %s screen kind(s)",
                len(reference.get("screens") or {}))
    return reference


async def author_dashboard_maquette_if_enabled(
    plan: dict,
    output_dir: str,
    contracts_dir: Path | None = None,
) -> Optional[dict]:
    """Author + persist the dashboard maquette when the profile requires it.

    Returns the maquette dict on success, None when skipped or failed.
    Writes to ``<output_dir>/src/contracts/dashboard-maquette.json``.

    Gated on the persisted generation profile's richness contract —
    enabled when the profile requires a KPI row + primary chart (Fast
    and Complete both do today — see :mod:`services.generation_profile`).
    """
    if not isinstance(plan, dict):
        return None

    on = False
    try:
        from services.generation_profile import load_profile
        prof = load_profile(output_dir)
        if prof is not None:
            on = bool(prof.require_kpi_row and prof.require_primary_chart)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] profile load failed: %s", exc)
    if not on:
        return None

    try:
        from services.dashboard_maquette import author_dashboard_maquette
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] maquette module import failed: %s", exc)
        return None

    brief_text = str(plan.get("description") or plan.get("brief") or "")
    try:
        maquette = await author_dashboard_maquette(
            {**plan, "_output_dir": str(output_dir)},
            brief_text=brief_text or None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] maquette author raised: %s", exc)
        return None
    if maquette is None:
        return None

    # Splice in structured directives the user embedded in the prompt.
    # `plan.hints.gauges` was extracted by services.plan_directive_parser
    # from lines like "Net Revenue Retention Gauge, 0-150, target 110".
    # The LLM maquette author doesn't know about Gauges — this is where
    # user requirement becomes maquette content (Slice 1a of the
    # requirement-as-central-piece direction).
    maq_dict = maquette.to_dict()
    _hints = plan.get("hints") if isinstance(plan.get("hints"), dict) else {}
    # Fallback: plan.hints often gets clobbered by later plan-persist
    # passes. Read requirement.json.parsed_directives as authority when
    # plan.hints is missing gauges. (Same fallback shape as
    # apply_hints_to_pages.)
    _gauges = _hints.get("gauges") if isinstance(_hints.get("gauges"), list) else []
    if not _gauges:
        try:
            _req_path = Path(output_dir) / "src" / "contracts" / "requirement.json"
            if _req_path.is_file():
                _req = json.loads(_req_path.read_text(encoding="utf-8"))
                _parsed = _req.get("parsed_directives") or {}
                if isinstance(_parsed.get("gauges"), list):
                    _gauges = _parsed["gauges"]
        except Exception:  # noqa: BLE001
            pass
    if _gauges:
        maq_dict["gauges"] = _gauges

    # Persist to disk so the downstream composer can consume it (both
    # pipelines share the same on-disk contract).
    _dir = contracts_dir if contracts_dir is not None else (
        Path(output_dir) / "src" / "contracts"
    )
    try:
        _dir.mkdir(parents=True, exist_ok=True)
        (_dir / "dashboard-maquette.json").write_text(
            json.dumps(maq_dict, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] maquette write failed: %s", exc)
        return None
    return maq_dict


# ─── Collection + Record maquette authoring ────────────────────────────
#
# Same seam + same profile gate as the dashboard maquette. Iterates
# plan.pages, filters by type, authors one LLM turn per page (capped
# to keep total pipeline latency + $$ predictable), persists to a
# single JSON file each. Downstream composers
# (:mod:`services.apply_collection_maquette` +
# :mod:`services.apply_record_maquette`) read those files during
# post_generate.

# Page-type sets. Both collection + record share the "page.type" key on
# plan entries, but the exact values vary between pipeline paths
# (planner LLM emits "list"/"form"/… ; some fixtures use "kanban" or
# "detail"). Keeping this here + tolerant means adding a new type name
# elsewhere doesn't silently drop maquette coverage.
_COLLECTION_PAGE_TYPES = {"list", "kanban", "calendar", "cards", "timeline", "board", "grid"}
_RECORD_PAGE_TYPES = {"form", "detail", "create", "edit", "record", "new"}

# Hard cap on LLM turns per pipeline run. Each authoring call is one
# LLM turn; a 20-page app would otherwise take 20 extra turns just for
# maquettes. The cap trims the fanout tail — the composer skips any
# page without a maquette, and the existing deterministic builder keeps
# handling it. Set generously enough that MOST typical apps (≤ 8-10
# pages per class) get full coverage.
_MAX_COLLECTION_MAQUETTES = 8
_MAX_RECORD_MAQUETTES = 8


def _pages_of_type(plan: dict, type_set: set[str]) -> list[dict]:
    """Return plan pages whose ``type`` (or ``archetype``) matches."""
    out: list[dict] = []
    for p in plan.get("pages") or []:
        if not isinstance(p, dict):
            continue
        t = str(p.get("type") or p.get("archetype") or "").strip().lower()
        if t in type_set:
            out.append(p)
    return out


def _resolve_entity(page: dict, plan: dict) -> str | None:
    """Return the entity a page targets.

    Falls back through the fields the planner has emitted in practice
    (``entity``, ``primary_entity``, ``page.entity``) so we cover both
    the one-shot planner and the decomposition planner outputs.
    """
    for k in ("entity", "primary_entity", "target_entity"):
        v = page.get(k)
        if isinstance(v, str) and v.strip() and v in (plan.get("entities") or {}):
            return v
    return None


async def author_collection_maquettes_if_enabled(
    plan: dict,
    output_dir: str,
    contracts_dir: Path | None = None,
) -> Optional[list[dict]]:
    """Author + persist collection maquettes for the plan's collection pages.

    Returns the list of maquette dicts on success (possibly empty when
    no collection pages exist), None when the gate is off or the plan
    is malformed. Writes to
    ``<output_dir>/src/contracts/collection-maquettes.json``.

    Gate: same profile check as :func:`author_dashboard_maquette_if_enabled`
    (Fast + Complete both require a KPI row + primary chart). When the
    gate is off, callers get None and the deterministic list/kanban/
    calendar builders keep the pre-Phase-2 behaviour.

    Per-page LLM turns are capped at :data:`_MAX_COLLECTION_MAQUETTES`
    so a wide plan doesn't blow the latency budget. Pages beyond the
    cap are logged and skipped — the composer treats them as
    "no maquette" and the deterministic builder keeps rendering them.
    """
    if not isinstance(plan, dict):
        return None
    if not _maquette_profile_on(output_dir):
        return None

    pages = _pages_of_type(plan, _COLLECTION_PAGE_TYPES)
    if not pages:
        return []

    try:
        from services.collection_maquette import author_collection_maquette
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] collection-maquette import failed: %s", exc)
        return None

    brief_text = str(plan.get("description") or plan.get("brief") or "") or None
    picked = pages[:_MAX_COLLECTION_MAQUETTES]
    if len(pages) > _MAX_COLLECTION_MAQUETTES:
        logger.info(
            "[plan-finalize] collection-maquette cap: authoring %d of %d pages",
            _MAX_COLLECTION_MAQUETTES, len(pages),
        )

    entries: list[dict] = []
    for page in picked:
        entity = _resolve_entity(page, plan)
        route = page.get("route")
        if not (entity and isinstance(route, str) and route.startswith("/")):
            continue
        try:
            m = await author_collection_maquette(
                {**plan, "_output_dir": str(output_dir)},
                entity, route, brief_text=brief_text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[plan-finalize] collection-maquette author raised for %s: %s",
                           route, exc)
            continue
        if m is None:
            continue
        entries.append(m.to_dict())

    _dir = contracts_dir if contracts_dir is not None else (
        Path(output_dir) / "src" / "contracts"
    )
    try:
        _dir.mkdir(parents=True, exist_ok=True)
        (_dir / "collection-maquettes.json").write_text(
            json.dumps(entries, indent=2), encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] collection-maquettes write failed: %s", exc)
        return None
    return entries


async def author_record_maquettes_if_enabled(
    plan: dict,
    output_dir: str,
    contracts_dir: Path | None = None,
) -> Optional[list[dict]]:
    """Author + persist record maquettes for the plan's record pages.

    Same gate + cap pattern as :func:`author_collection_maquettes_if_enabled`.

    Mode inference from the page's type/archetype:
      * ``form`` / ``create`` / ``new`` → ``create``
      * ``edit`` → ``edit``
      * ``detail`` / ``record`` → ``view``
    """
    if not isinstance(plan, dict):
        return None
    if not _maquette_profile_on(output_dir):
        return None

    pages = _pages_of_type(plan, _RECORD_PAGE_TYPES)
    if not pages:
        return []

    try:
        from services.record_maquette import author_record_maquette
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] record-maquette import failed: %s", exc)
        return None

    brief_text = str(plan.get("description") or plan.get("brief") or "") or None
    picked = pages[:_MAX_RECORD_MAQUETTES]
    if len(pages) > _MAX_RECORD_MAQUETTES:
        logger.info(
            "[plan-finalize] record-maquette cap: authoring %d of %d pages",
            _MAX_RECORD_MAQUETTES, len(pages),
        )

    entries: list[dict] = []
    for page in picked:
        entity = _resolve_entity(page, plan)
        route = page.get("route")
        if not (entity and isinstance(route, str) and route.startswith("/")):
            continue
        mode = _infer_record_mode(page, route)
        try:
            m = await author_record_maquette(
                {**plan, "_output_dir": str(output_dir)},
                entity, route, mode=mode, brief_text=brief_text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[plan-finalize] record-maquette author raised for %s: %s",
                           route, exc)
            continue
        if m is None:
            continue
        entries.append(m.to_dict())

    _dir = contracts_dir if contracts_dir is not None else (
        Path(output_dir) / "src" / "contracts"
    )
    try:
        _dir.mkdir(parents=True, exist_ok=True)
        (_dir / "record-maquettes.json").write_text(
            json.dumps(entries, indent=2), encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] record-maquettes write failed: %s", exc)
        return None
    return entries


def _maquette_profile_on(output_dir: str) -> bool:
    """Return True when the profile enables maquette authoring.

    Kept in a single helper so all three authors (dashboard + collection
    + record) key off the SAME flag — no drift where dashboards run but
    the others don't.
    """
    try:
        from services.generation_profile import load_profile
        prof = load_profile(output_dir)
        if prof is None:
            return False
        return bool(prof.require_kpi_row and prof.require_primary_chart)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-finalize] profile load failed: %s", exc)
        return False


def _infer_record_mode(page: dict, route: str) -> str:
    """Infer view/edit/create from the page's type + route shape."""
    t = str(page.get("type") or page.get("archetype") or "").strip().lower()
    if t in ("form", "create", "new"):
        return "create"
    if t == "edit":
        return "edit"
    if t in ("detail", "record"):
        return "view"
    # Route-shape fallbacks — /entity/new → create, /entity/[id]/edit → edit,
    # /entity/[id] → view.
    r = route.rstrip("/").lower()
    if r.endswith("/new"):
        return "create"
    if r.endswith("/edit"):
        return "edit"
    return "view"
