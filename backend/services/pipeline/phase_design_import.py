"""The per-page import phase shared by every design provider.

For each plan page that names a design ref, ask the provider for that
page's markup, turn it into a PageV2 schema (JSX, HTML, or a tree the
provider mapped itself), cache its assets, and write
``src/schemas/<slug>.json``. Then two provider-neutral follow-ups: theme
tokens the provider measured go to ``src/theme/tokens.custom.json``, and
a page whose markup was mapped deterministically (the ``schema`` kind)
is restructured into a responsive component tree by the schema refiner,
with the provider's preview image as its eyes.

The phase never overwrites a page it could not import: a missing or
failed markup leaves whatever an earlier phase wrote (or nothing, so the
schema authoring phase fills the gap later).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from sse_helpers import sse_event
from services.design_source.base import DesignMarkup as DesignMarkupT
from services.design_source.base import DesignSource, DesignSourceError, route_slug

logger = logging.getLogger(__name__)

_PROVIDER_LABEL = {"figma": "Figma", "uxpilot": "UX Pilot"}


def design_pages(plan: dict) -> list[dict]:
    """Plan pages that name a design ref, in plan order. The Figma-era key
    is honoured for plans written before ``design_ref`` existed."""
    out: list[dict] = []
    for p in (plan or {}).get("pages") or []:
        if not isinstance(p, dict):
            continue
        ref = p.get("design_ref") or p.get("figma_node_id")
        if ref:
            out.append(p)
    return out


def page_ref(page: dict) -> str:
    return str(page.get("design_ref") or page.get("figma_node_id") or "")


async def phase_design_import(
    state: Any,
    plan: dict,
    *,
    source: DesignSource,
    output_dir: str,
    project_id: Any = None,
    imported_routes: set[str],
    concurrency: int = 3,
) -> AsyncIterator[dict]:
    """Import every design page in ``plan`` through ``source``.

    ``imported_routes`` is populated in place with the routes whose schema
    this phase wrote, so the frontend phase skips them.

    **Emits:** SSE events (status, log).
    """
    label = _PROVIDER_LABEL.get(source.provider, source.provider)
    tag = f"[{label}Import]"
    pages = design_pages(plan)
    if not pages:
        yield sse_event("log", {"text": f"{tag} No pages carry a design ref — skipping"})
        return

    reachable = getattr(source, "reachable", None)
    if reachable is not None:
        try:
            ok = await reachable()
        except Exception as exc:  # noqa: BLE001
            ok = False
            logger.info("%s reachability probe failed: %s", tag, exc)
        if not ok:
            yield sse_event("log", {"text": f"{tag} {label} design server not reachable — skipping import"})
            return

    yield sse_event("status", {"message": f"Importing {len(pages)} page(s) from {label}..."})

    # The closed vocabulary the element classifiers read (routes, workflow
    # names, the component registry, nav icons) comes from the plan, whichever
    # provider the markup does. Empty lists mean "keyword classifiers only".
    try:
        from services.figma_llm_ctx import context_from_plan, set_figma_llm_context
        _ctx = context_from_plan(plan)
        set_figma_llm_context(**_ctx)
    except Exception as exc:  # noqa: BLE001 — classifiers fall back to keywords
        logger.info("%s classifier context not populated: %s", tag, exc)

    prefetch = getattr(source, "prefetch", None)
    if prefetch is not None:
        try:
            await prefetch([page_ref(p) for p in pages])
        except Exception as exc:  # noqa: BLE001 — per-page fetches still run
            yield sse_event("log", {"text": f"{tag} prefetch failed: {exc} — fetching per page"})

    from services.figma_mcp_pipeline import build_schema_from_markup

    sem = asyncio.Semaphore(concurrency)

    async def _fetch(page: dict):
        async with sem:
            return await source.markup(page_ref(page))

    results = await asyncio.gather(*(_fetch(p) for p in pages), return_exceptions=True)

    imported = 0
    mapped: list[tuple[dict, Path, DesignMarkupT]] = []
    for page, result in zip(pages, results):
        route = page.get("route", "?")
        if isinstance(result, Exception):
            yield sse_event("log", {"text": f"{tag} ⚠ {route}: {result} — keeping existing schema"})
            continue
        if result is None:
            yield sse_event("log", {"text": f"{tag} ⚠ {route}: no markup returned — keeping existing schema"})
            continue
        try:
            slug = route_slug(route)
            rel = page.get("file") or f"src/schemas/{slug}.json"
            schema, asset_paths = await build_schema_from_markup(
                result,
                output_dir,
                project_id=str(project_id) if project_id else None,
                route=route,
                title=page.get("name") or page.get("title"),
                schema_filename=Path(rel).name,
                assets=source.assets,
                origin={"provider": source.provider, "ref": page_ref(page), "container": source.container},
            )
            file_path = Path(output_dir) / rel
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(json.dumps(schema, indent=2))
            imported_routes.add(route)
            imported += 1
            suffix = f" ({len(asset_paths)} asset(s) cached)" if asset_paths else ""
            if result.kind == "schema":
                suffix += f" (mapped from the node tree, {result.incomplete} unclassified node(s))" if result.incomplete else " (mapped from the node tree)"
                mapped.append((page, file_path, result))
            yield sse_event("log", {"text": f"{tag} ✓ {route}{suffix}"})
        except DesignSourceError as exc:
            yield sse_event("log", {"text": f"{tag} ⚠ {route}: {exc} — keeping existing schema"})
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s %s failed", tag, route)
            yield sse_event("log", {"text": f"{tag} ⚠ {route}: {exc} — keeping existing schema"})

    yield sse_event("log", {"text": f"{tag} ✓ {imported}/{len(pages)} page(s) imported"})

    async for evt in _write_theme_tokens(source, output_dir, tag):
        yield evt
    async for evt in _refine_mapped_pages(source, mapped, output_dir, project_id, tag):
        yield evt


async def _write_theme_tokens(source: DesignSource, output_dir: str, tag: str) -> AsyncIterator[dict]:
    """Merge the provider's theme categories into ``src/theme/tokens.custom.json``
    (shallow per category, so neighbouring categories survive)."""
    theme = getattr(source, "theme_tokens", None)
    if theme is None:
        return
    try:
        merged = theme() or {}
    except Exception as exc:  # noqa: BLE001
        yield sse_event("log", {"text": f"{tag} theme tokens skipped: {exc}"})
        return
    if not merged:
        return
    tokens_path = Path(output_dir) / "src" / "theme" / "tokens.custom.json"
    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if tokens_path.exists():
        try:
            existing = json.loads(tokens_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}
    for cat, sub in merged.items():
        if isinstance(sub, dict) and isinstance(existing.get(cat), dict):
            existing[cat] = {**existing[cat], **sub}
        else:
            existing[cat] = sub
    tokens_path.write_text(json.dumps(existing, indent=2))
    yield sse_event("log", {"text": f"{tag} theme tokens merged ({', '.join(sorted(merged))})"})


async def _refine_mapped_pages(
    source: DesignSource, mapped: list, output_dir: str, project_id: Any, tag: str,
) -> AsyncIterator[dict]:
    """A deterministically mapped page is a fixed-pixel tree. The refiner
    restructures it into a responsive component-library tree, looking at the
    provider's preview when there is one, and keeps the mapped tree on any
    failure."""
    if not mapped:
        return
    try:
        from agents.figma_schema_refiner import run_figma_schema_refiner
        from services.schema_prompt import _format_library_descriptor
        descriptor = _format_library_descriptor()
    except Exception as exc:  # noqa: BLE001
        yield sse_event("log", {"text": f"{tag} refiner unavailable: {exc} — mapped trees kept"})
        return
    for page, file_path, markup in mapped:
        route = page.get("route", "?")
        shot_path = None
        if markup.preview_url:
            try:
                local = await source.assets([markup.preview_url], output_dir, str(project_id) if project_id else None)
                public = local.get(markup.preview_url)
                if public:
                    shot_path = str(Path(output_dir) / "public" / public.split("/figma/", 1)[-1]) if "/figma/" in public else None
                    if shot_path and not Path(shot_path).exists():
                        shot_path = str(Path(output_dir) / "public" / "figma" / Path(public).name)
            except Exception as exc:  # noqa: BLE001
                yield sse_event("log", {"text": f"{tag} {route} preview fetch failed ({exc}) — refining text-only"})
        try:
            det_schema = json.loads(file_path.read_text())
            yield sse_event("status", {"message": f"Refining {route} into a responsive layout..."})
            refined = await run_figma_schema_refiner(det_schema, shot_path, descriptor)
            if refined is not None:
                refined["id"] = det_schema.get("id", route_slug(route))
                refined.setdefault("schemaVersion", det_schema.get("schemaVersion", "2"))
                for marker in ("_figmaDerived", "_designOrigin"):
                    if marker in det_schema:
                        refined[marker] = det_schema[marker]
                file_path.write_text(json.dumps(refined, indent=2))
                yield sse_event("log", {"text": f"{tag} ✓ {route} → responsive schema"})
            else:
                yield sse_event("log", {"text": f"{tag} {route} kept mapped tree (refine rejected)"})
        except Exception as exc:  # noqa: BLE001
            yield sse_event("log", {"text": f"{tag} {route} refine error: {exc} — kept mapped tree"})
