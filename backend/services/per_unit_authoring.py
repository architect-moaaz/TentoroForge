"""Per-unit page-detail authoring + plan assembly (spec B2, enterprise scale).

The app-map planner (B2a, ``agents/app_map_agent.py``) emits a LEAN skeleton: a
plan-shaped dict where each page carries only ``route``/``name``/``entity``/
``archetype``/``description`` — no ``fields``/``widgets``/``actions``. This module
is the SECOND pass: it authors that per-page DETAIL, each page in its OWN bounded
registry-slice context (B1's :func:`build_resource_context_slice`), then assembles
a FULL plan that is shape-identical to a one-shot plan so the existing pipeline
(``build_canonical_registry`` → schema → pages → …) consumes it unchanged.

Two seams:

* :func:`author_page_detail` — enrich ONE page with its detail. Only forms,
  dashboards, and action-pages need authored detail; a routine CRUD list/detail
  page is SHORT-CIRCUITED (returned as-is, no LLM call) because the deterministic
  builders already render it from the registry.
* :func:`author_all_units` — orchestration: write the registry so slices are
  readable, author every page, and assemble the full plan.

The LLM boundary is INJECTABLE via ``_query(system_prompt, user_prompt) -> str``
— the default hits the real Anthropic SDK (mirrors app_map_agent's
``_default_query``); tests pass a fake returning canned detail JSON (no network).

ADDITIVE: nothing here is wired into the pipeline yet — task B2c does that. This
module NEVER raises at the orchestration level: a page whose authoring fails (bad
LLM output, a raising ``_query``, a reader bug) falls back to its skeleton page,
which still yields a registry-derived CRUD form downstream.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from typing import Any, Callable

from agents.planner import _extract_plan_object
from services.resource_registry import build_canonical_registry, write_registry
from services.resource_registry_context import build_resource_context_slice

logger = logging.getLogger(__name__)


# ── archetype → what detail to author ────────────────────────────────────────
# A page's archetype decides which detail key it needs. Anything not listed here
# is a routine CRUD page the deterministic builders render from the registry, so
# it is short-circuited (no LLM call).
_FIELD_ARCHETYPES = {"form", "create", "edit", "new", "wizard"}
_WIDGET_ARCHETYPES = {"dashboard", "report", "analytics", "overview", "home"}
_ACTION_ARCHETYPES = {
    "approval", "review", "workflow", "inbox", "kanban", "board", "pipeline",
}


def _detail_kind(page: dict) -> str | None:
    """Which detail key this page needs authored: ``"fields"`` (forms),
    ``"widgets"`` (dashboards/reports), ``"actions"`` (action-pages), or ``None``
    for a routine CRUD list/detail page that needs no LLM authoring."""
    archetype = str((page or {}).get("archetype") or "").strip().lower()
    if archetype in _FIELD_ARCHETYPES:
        return "fields"
    if archetype in _WIDGET_ARCHETYPES:
        return "widgets"
    if archetype in _ACTION_ARCHETYPES:
        return "actions"
    return None


_FIELDS_INSTRUCTION = (
    "Author this create/edit FORM's fields. Emit a single JSON object "
    '{"fields": [ ... ]} where each field is '
    '{"name","control","semanticType","required","enum","order"}. Map each '
    "field name to a REAL column of the focal entity (bind FK/uuid columns to a "
    "relational Select via the referenced entity slug, never a free-text Input). "
    "Exclude lifecycle *At columns. No prose, no fences."
)
_WIDGETS_INSTRUCTION = (
    "Author this dashboard/report's widgets. Emit a single JSON object "
    '{"widgets": [ ... ]} where each widget is {"type","entity", ...} binding '
    "its data to a REAL entity slug (or a derived dataSource declared over one). "
    "No prose, no fences."
)
_ACTIONS_INSTRUCTION = (
    "Author this page's actions. Emit a single JSON object "
    '{"actions": [ ... ]} where each action is {"label","workflow","setValues"}. '
    "Reference only REAL workflow ids; for a state transition put the target "
    "state in setValues. No prose, no fences."
)
_INSTRUCTION_BY_KIND = {
    "fields": _FIELDS_INSTRUCTION,
    "widgets": _WIDGETS_INSTRUCTION,
    "actions": _ACTIONS_INSTRUCTION,
}

_SYSTEM_PROMPT = (
    "You are authoring the DETAIL for ONE page of an application, given the "
    "CLOSED set of real backend resources for that page's focal entity. Bind "
    "ONLY to resources in that set — never invent an entity, column, or "
    "workflow id. Output a SINGLE JSON object, no prose, no markdown fences."
)


def _build_user_prompt(page: dict, kind: str, context: str) -> str:
    """The per-page user prompt: the bounded resource slice + the page's identity
    + the kind-specific authoring instruction."""
    name = page.get("name") or page.get("route") or "(unnamed)"
    route = page.get("route") or page.get("path") or ""
    entity = page.get("entity") or "(none)"
    archetype = page.get("archetype") or ""
    desc = page.get("description") or ""
    parts = []
    if context:
        parts.append(context)
        parts.append("")
    parts.append(
        f"Page: {name} (route: {route}; archetype: {archetype}; "
        f"focal entity: {entity})"
    )
    if desc:
        parts.append(f"Purpose: {desc}")
    parts.append("")
    parts.append(_INSTRUCTION_BY_KIND[kind])
    return "\n".join(parts)


async def _default_query(system_prompt: str, user_prompt: str) -> str:
    """Default LLM boundary — a single headless Anthropic call (mirrors
    app_map_agent's ``_default_query``). Injected over in tests; never hit there."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "author_page_detail requires ANTHROPIC_API_KEY (or an injected "
            "_query). Set it in the backend env or pass _query=..."
        )
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def author_page_detail(
    page: dict,
    output_dir: str,
    *,
    _query: Callable[[str, str], str] | None = None,
) -> dict:
    """Return ``page`` ENRICHED with its authored detail.

    DETERMINISTIC SHORT-CIRCUIT: a routine CRUD list/detail page (any archetype
    not in the form/dashboard/action sets) is returned AS-IS with NO LLM call —
    the deterministic builders already render it from the registry.

    For a form/create/edit page authors ``fields[]``; a dashboard/report authors
    ``widgets[]``; an action-page authors ``actions[]`` (with ``setValues`` for
    state transitions). The bounded context is B1's per-entity registry slice.
    The LLM call goes through the injectable ``_query`` seam.

    NEVER raises: on a malformed / empty / key-missing response, or a raising
    ``_query``, the page is returned UNCHANGED (a page with no detail still
    yields a registry-derived CRUD form downstream).
    """
    if not isinstance(page, dict):
        return page

    kind = _detail_kind(page)
    if kind is None:
        # Routine CRUD page — no authored detail needed, no LLM call.
        return page

    query_fn = _query or _default_query

    try:
        context = build_resource_context_slice(output_dir, page.get("entity"))
    except Exception:  # noqa: BLE001 — a reader bug must not lose the page
        context = ""

    system_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(page, kind, context or "")

    try:
        result = query_fn(system_prompt, user_prompt)
        if inspect.isawaitable(result):
            import asyncio

            result = asyncio.run(result)
    except Exception:  # noqa: BLE001 — never raise; fall back to skeleton page
        logger.exception("author_page_detail: query failed for %s", page.get("route"))
        return page

    if not isinstance(result, str) or not result.strip():
        return page

    raw = _extract_plan_object(result)
    if not isinstance(raw, dict):
        return page

    detail = raw.get(kind)
    if not isinstance(detail, list):
        return page

    enriched = dict(page)
    enriched[kind] = detail
    return enriched


def author_all_units(
    skeleton: dict,
    output_dir: str,
    *,
    _query: Callable[[str, str], str] | None = None,
    concurrency: int = 5,
) -> dict:
    """Author per-page detail across a skeleton and ASSEMBLE a full plan.

    ``skeleton`` is a normalized, plan-shaped dict (as produced by
    ``run_app_map_planner`` — ``data_models`` list + lean ``pages`` +
    ``workflows`` + ``roles``).

    Orchestration:
    1. ``write_registry(build_canonical_registry(skeleton), output_dir)`` FIRST,
       so :func:`build_resource_context_slice` can read the per-entity slices.
    2. Author every page (SEQUENTIAL — chosen over the semaphore fan-out for
       simplicity + determinism; ``concurrency`` is accepted for the wiring
       task's signature but the pass is I/O-light per page and order-stable this
       way). Each page independently falls back to its skeleton form on failure.
    3. Assemble: return the skeleton with each page replaced by its authored
       version, ``data_models``/``workflows``/``roles`` carried through unchanged.

    The result is shape-identical to a one-shot plan so
    ``build_canonical_registry`` and the downstream pipeline consume it unchanged.
    NEVER raises: a failed unit falls back to its skeleton page; a registry-write
    failure is logged and authoring proceeds with whatever slices exist.
    """
    if not isinstance(skeleton, dict):
        return skeleton

    # 1. Materialize the registry so per-page slices are readable.
    try:
        write_registry(build_canonical_registry(skeleton), output_dir)
    except Exception:  # noqa: BLE001 — proceed; slices fall back to whole-app/empty
        logger.exception("author_all_units: registry write failed (continuing)")

    # 2. Author each page (sequential; per-page fallback baked into author_page_detail).
    pages = skeleton.get("pages")
    authored_pages: list = []
    if isinstance(pages, list):
        for page in pages:
            try:
                authored_pages.append(
                    author_page_detail(page, output_dir, _query=_query)
                )
            except Exception:  # noqa: BLE001 — belt-and-suspenders; never lose a page
                logger.exception("author_all_units: unit failed (using skeleton page)")
                authored_pages.append(page)

    # 3. Assemble the full plan — skeleton with pages replaced, everything else
    #    carried through unchanged (shape-identical to a one-shot plan).
    result = dict(skeleton)
    result["pages"] = authored_pages
    return result


# ────────────────────────────────────────────────────────────
# Async twin — parallel per-page authoring for smith-arch
# ────────────────────────────────────────────────────────────

async def author_page_detail_async(
    page: dict,
    output_dir: str,
    *,
    _query: Callable[[str, str], Any] | None = None,
) -> dict:
    """Async twin of :func:`author_page_detail`.

    Same short-circuit + fallback semantics — a routine CRUD page returns
    unchanged, an empty/malformed LLM response falls back to the skeleton
    page. The only difference: awaits ``_query`` directly, so callers can
    fan out many of these with ``asyncio.gather`` without the sync
    version's ``asyncio.run(result)`` blowing up ("cannot be called from
    a running event loop")."""
    if not isinstance(page, dict):
        return page

    kind = _detail_kind(page)
    if kind is None:
        return page

    query_fn = _query if _query is not None else _default_query

    try:
        context = build_resource_context_slice(page, output_dir) or ""
    except Exception:  # noqa: BLE001
        context = ""

    system_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(page, kind, context or "")

    try:
        result = query_fn(system_prompt, user_prompt)
        if inspect.isawaitable(result):
            result = await result
    except Exception:  # noqa: BLE001 — never raise; skeleton page is the fallback
        logger.exception(
            "author_page_detail_async: query failed for %s", page.get("route")
        )
        return page

    if not isinstance(result, str) or not result.strip():
        return page

    raw = _extract_plan_object(result)
    if not isinstance(raw, dict):
        return page

    detail = raw.get(kind)
    if not isinstance(detail, list):
        return page

    enriched = dict(page)
    enriched[kind] = detail
    return enriched


async def author_all_units_async(
    skeleton: dict,
    output_dir: str,
    *,
    _query: Callable[[str, str], Any] | None = None,
    concurrency: int = 6,
    emit_fn: Callable[[str, dict], None] | None = None,
    per_unit_timeout_sec: float = 180.0,
) -> dict:
    """Parallel version of :func:`author_all_units`.

    Same contract on the return: a plan dict shape-identical to a one-shot
    plan. Difference: pages are authored CONCURRENTLY via
    ``asyncio.gather`` bounded by a semaphore, so a 20-page ATS run
    completes in ~1 min of wall-clock instead of ~10.

    Concurrency:
      * ``concurrency`` caps concurrent LLM calls to respect Anthropic
        tier limits. Start at 6; drop if you see 429s.
      * ``per_unit_timeout_sec`` — a hung page can't stall the batch;
        its slot fills back into the pool after this deadline. Falls
        back to the skeleton page.

    Emission:
      * ``emit_fn("unit_authored", {text, unit_name, completed, total})``
        fires per completed unit for SSE progress in the chip stream.

    Failure mode: **never raises**. A registry-write failure is logged
    and authoring proceeds. Per-unit exceptions / timeouts fall back to
    the skeleton page for that unit. If everything fails, returns the
    skeleton with pages as-is — same fallback shape as the sync version.
    """
    if not isinstance(skeleton, dict):
        return skeleton

    # 1. Materialize the registry so per-page slices are readable —
    #    unchanged from the sync path.
    try:
        write_registry(build_canonical_registry(skeleton), output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("author_all_units_async: registry write failed (continuing)")

    pages = skeleton.get("pages")
    if not isinstance(pages, list) or not pages:
        result = dict(skeleton)
        result["pages"] = pages if isinstance(pages, list) else []
        return result

    total = len(pages)
    sem = asyncio.Semaphore(max(1, concurrency))
    done_count = 0

    async def _authored_one(page: dict) -> dict:
        nonlocal done_count
        async with sem:
            try:
                authored = await asyncio.wait_for(
                    author_page_detail_async(page, output_dir, _query=_query),
                    timeout=per_unit_timeout_sec,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "author_all_units_async: unit %r timed out after %ss "
                    "(using skeleton page)",
                    page.get("route"), per_unit_timeout_sec,
                )
                authored = page
            except Exception:  # noqa: BLE001 — defensive; skeleton page is fallback
                logger.exception(
                    "author_all_units_async: unit %r failed (using skeleton page)",
                    page.get("route"),
                )
                authored = page

            done_count += 1
            if emit_fn is not None:
                try:
                    emit_fn("unit_authored", {
                        "text":       f"+ {page.get('route') or page.get('name') or '<page>'}",
                        "unit_name":  page.get("route") or page.get("id") or "",
                        "completed":  done_count,
                        "total":      total,
                    })
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "author_all_units_async: emit_fn(unit_authored) failed"
                    )
            return authored

    authored_pages = await asyncio.gather(
        *(_authored_one(p) for p in pages),
        return_exceptions=False,
    )

    result = dict(skeleton)
    result["pages"] = list(authored_pages)
    return result
