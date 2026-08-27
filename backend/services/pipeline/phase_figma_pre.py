"""Figma-only pre-frontend phases.

These four phases run in the Figma pipeline BEFORE the standard Phase
1-3 authoring (contract / schema / parallel-agents). They translate the
Figma file into per-page schema JSON so the downstream authoring phases
can start from a real UI shape rather than an empty tree.

Phase 1e of the pipeline cleanup — Phase 1d locked the contracts,
Phase 1e lifts the bodies out of :mod:`routers.generate` and keeps
the legacy ``_run_figma_relay_pipeline`` wrapper delegating to these
phase functions. The wrapper's control flow is unchanged; each phase's
BODY moved here.

Execution order in the Figma pipeline:
    phase_figma_deterministic_map
      → phase_figma_schema_refine   (gated on FIGMA_SCHEMA_REFINE)
      → phase_figma_mcp             (gated on Dev Mode MCP availability)
      → phase_figma_binding_pass
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from sse_helpers import sse_event
from services.pipeline.state import PipelineState


async def phase_figma_deterministic_map(
    state: PipelineState,
    plan: dict,
    *,
    figma_url: str,
    figma_token: Optional[str],
    deterministic_pages: set[str],   # populated in place
    deterministic_failures: list,    # (route, reason) tuples, populated in place
) -> AsyncIterator[dict]:
    """The Figma → deterministic schema mapper.

    **Lift source:** ``routers.generate._run_figma_relay_pipeline`` lines 3722-4011.

    Parses the Figma URL, batches ``fetch_figma_node_batched`` for every
    ``plan.pages[*].figma_node_id``, walks each frame tree, extracts
    tokens + typography into ``tokens.custom.json``, downloads SVG
    assets, then invokes ``build_page_schema`` per page to write
    ``src/schemas/<slug>.json``.

    Populates ``deterministic_pages`` (the set of route paths this
    mapper successfully emitted) so :func:`phase_frontend_figma`'s
    ``skip_routes`` filter can prevent the LLM branch from overwriting
    what the mapper already wrote.

    Also seeds ``figma_llm_ctx`` (via ``services.figma_llm.context_from_plan``)
    and, behind ``FIGMA_SHELL_EXTRACT``, extracts a shell frame from
    the top-level document.

    **Runs FIRST in the Figma pipeline** — before any LLM authoring —
    because backend LLM agents can wedge on ``claude_agent_sdk``
    subprocess timeouts. Running the mapper first guarantees Figma
    frames land on disk regardless of what happens downstream.

    **Emits:** SSE events (status, log, resource, page_schema).
    """
    raise NotImplementedError(
        "phase_figma_deterministic_map: contract locked in Phase 1d; body "
        "lifts from routers.generate lines 3722-4011 during Phase 1e."
    )
    yield {}


async def phase_figma_schema_refine(
    state: PipelineState,
    plan: dict,
    *,
    output_dir: str,
    deterministic_pages: set[str],
    figma_url: str,
    figma_token: Optional[str],
    project_id: Any = None,
) -> AsyncIterator[dict]:
    """LLM restructures each deterministic-mapper schema into responsive layout.

    **Lift source (Phase 1e):** ``routers.generate._run_figma_relay_pipeline``
    lines 3949-4003 (post-Phase-2 drift; the contract stub's original
    4013-4067 reference is from before subsequent edits shifted the file).

    Gated on ``FIGMA_SCHEMA_REFINE`` env flag. For each page schema
    the mapper emitted, calls ``run_figma_schema_refiner`` which
    reshapes the raw Figma tree into a responsive component tree with
    proper Row/Stack/Card semantics.

    ``pages_with_nodes`` was a local of the legacy caller (built from
    ``plan.pages`` with ``figma_node_id``); the lift recomputes it
    locally so this phase is pure over its inputs.

    **Emits:** SSE events (status, log). No new files — mutates existing
    schema files in place.
    """
    # Recompute locally — same expression the caller used to build it
    # (routers.generate:3682-3684). Keeping this here means the phase
    # is a pure function of its inputs and doesn't depend on prior-phase
    # local state.
    plan_pages = (plan or {}).get("pages") or []
    pages_with_nodes = [
        p for p in plan_pages
        if isinstance(p, dict) and p.get("figma_node_id")
    ]

    if os.environ.get("FIGMA_SCHEMA_REFINE", "1").strip().lower() not in ("0", "false", "no", "off") and deterministic_pages:
        try:
            from agents.figma_schema_refiner import run_figma_schema_refiner
            from services.schema_prompt import _format_library_descriptor
            from services.figma_client import fetch_figma_image_urls
            from services.figma_asset_downloader import download_figma_assets
            from services.figma_client import parse_figma_url
            descriptor = _format_library_descriptor()
            _parsed_ref = parse_figma_url(figma_url)
            ref_file_key = _parsed_ref.get("file_key") if _parsed_ref else None
            refine_pages = [
                p for p in pages_with_nodes[:50]
                if (p.get("route") in deterministic_pages) and p.get("figma_node_id")
            ]
            for p in refine_pages:
                route = p.get("route")
                node_id = p.get("figma_node_id")
                slug = route.strip("/").replace("/", "-") or "home"
                schema_path = Path(output_dir) / p.get("file", f"src/schemas/{slug}.json")
                if not schema_path.exists():
                    continue
                # Best-effort: fetch the frame PNG as visual reference.
                shot_path = None
                try:
                    if ref_file_key:
                        urls = await fetch_figma_image_urls(ref_file_key, [node_id], figma_token, format="png")
                        png_url = (urls or {}).get(node_id)
                        if png_url:
                            url_to_path = await download_figma_assets(
                                [png_url], output_dir, project_id=Path(output_dir).name
                            )
                            shot_path = (url_to_path or {}).get(png_url)
                except Exception as _shot_ex:
                    yield sse_event("log", {"text": f"[Refiner] {route} screenshot fetch failed ({_shot_ex}) — text-only"})
                try:
                    det_schema = json.loads(schema_path.read_text())
                    yield sse_event("status", {"message": f"Refining {route} into a responsive layout..."})
                    refined = await run_figma_schema_refiner(det_schema, shot_path, descriptor)
                    if refined is not None:
                        refined["id"] = det_schema.get("id", slug)
                        refined.setdefault("schemaVersion", det_schema.get("schemaVersion", "2"))
                        schema_path.write_text(json.dumps(refined, indent=2))
                        yield sse_event("log", {"text": f"[Refiner] ✓ {route} → responsive schema"})
                    else:
                        yield sse_event("log", {"text": f"[Refiner] {route} kept deterministic (refine rejected)"})
                except Exception as _ref_ex:
                    yield sse_event("log", {"text": f"[Refiner] {route} error: {_ref_ex} — kept deterministic"})
        except Exception as _refblk_ex:
            yield sse_event("log", {"text": f"[Refiner] block skipped: {_refblk_ex}"})


async def phase_figma_mcp(
    state: PipelineState,
    plan: dict,
    *,
    output_dir: str,
    figma_url: str,
    project_id: Any = None,
) -> AsyncIterator[dict]:
    """Overlay per-page JSX from the local Figma Dev Mode MCP.

    **Lift source (Phase 1e):** ``routers.generate._run_figma_relay_pipeline``
    lines 3966-4083 (post-drift; contract stub's 4069-4186 was pre-drift).

    Probes for a running Dev Mode MCP endpoint. If reachable, for each
    page: ``fetch_jsx_via_mcp`` → ``build_schema_from_jsx`` → overwrites
    the deterministic schema on success. Skipped silently when MCP
    isn't available (no Dev Mode running in the current environment).

    **Emits:** SSE events (status, log).
    """
    try:
        import asyncio as _asyncio
        import urllib.request as _urllib_request
        from agents.figma_mcp_agent import FIGMA_MCP_URL, fetch_jsx_via_mcp
        from services.figma_mcp_pipeline import build_schema_from_jsx
        from services.figma_client import parse_figma_url

        # ── reachability probe ──
        # For localhost URLs a plain GET tells us the server is alive; any
        # HTTP response (even 400/405) means it's there — only a connection
        # refusal / timeout means unreachable. Figma's local Dev Mode MCP
        # returns 400 to bare GETs (it wants JSON-RPC POST) which used to
        # falsely mark it "unreachable" and silently skip this whole block.
        # For remote hosts skip the probe entirely and let the real MCP
        # session speak for itself.
        _is_local = "127.0.0.1" in FIGMA_MCP_URL or "localhost" in FIGMA_MCP_URL
        _mcp_available = True  # optimistic default; probe only overrides for local
        if _is_local:
            _mcp_available = False
            try:
                _req = _urllib_request.Request(FIGMA_MCP_URL, method="GET")
                _urllib_request.urlopen(_req, timeout=2)
                _mcp_available = True
            except _urllib_request.HTTPError:
                # Server responded with an error status — it IS there.
                _mcp_available = True
            except Exception:
                # URLError, timeout, connection refused → truly unreachable.
                pass

        if not _mcp_available:
            yield sse_event("log", {"text": f"[FigmaMCP] MCP server not reachable at {FIGMA_MCP_URL} — skipping MCP block"})
        else:
            plan_pages = (plan or {}).get("pages") or []
            figma_file_key = (plan or {}).get("figma_file_key", "")
            pages_with_nodes = [
                p for p in plan_pages
                if isinstance(p, dict) and p.get("figma_node_id")
            ]

            if not pages_with_nodes:
                yield sse_event("log", {"text": "[FigmaMCP] No pages with figma_node_id — skipping"})
            else:
                yield sse_event("log", {
                    "text": f"[FigmaMCP] MCP available — upgrading {len(pages_with_nodes)} page(s) from get_design_context"
                })

                _mcp_sem = _asyncio.Semaphore(3)

                async def _fetch_mcp_for_page(page: dict) -> tuple[str, str | None]:
                    """Returns (route, jsx_or_None)."""
                    route = page.get("route", "?")
                    node_id = page.get("figma_node_id", "")
                    # Build per-page URL with node-id query param
                    node_id_url = node_id.replace(":", "-")
                    _parsed_base = parse_figma_url(figma_url)
                    _fk = figma_file_key or _parsed_base.get("file_key", "")
                    page_url = f"https://www.figma.com/design/{_fk}/frame?node-id={node_id_url}"
                    async with _mcp_sem:
                        jsx = await fetch_jsx_via_mcp(page_url)
                    return route, jsx

                tasks = [_fetch_mcp_for_page(p) for p in pages_with_nodes]
                results = await _asyncio.gather(*tasks, return_exceptions=True)

                mcp_success = 0
                for page, result in zip(pages_with_nodes, results):
                    route = page.get("route", "?")
                    if isinstance(result, Exception):
                        yield sse_event("log", {
                            "text": f"[FigmaMCP] ⚠ {route}: {result} — keeping deterministic schema"
                        })
                        continue
                    _route, jsx = result
                    if not jsx:
                        yield sse_event("log", {
                            "text": f"[FigmaMCP] ⚠ {route}: no JSX returned — keeping deterministic schema"
                        })
                        continue
                    try:
                        schema, asset_paths = await build_schema_from_jsx(
                            jsx, output_dir, project_id=str(project_id)
                        )
                        # Use the SAME filename convention as the deterministic mapper
                        slug = route.strip("/").replace("/", "-") or "home"
                        file_path = Path(output_dir) / page.get(
                            "file",
                            f"src/schemas/{slug}.json"
                        )
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(json.dumps(schema, indent=2))
                        mcp_success += 1
                        _asset_count = len(asset_paths)
                        yield sse_event("log", {
                            "text": (
                                f"[FigmaMCP] ✓ {route}"
                                + (f" ({_asset_count} asset(s) cached)" if _asset_count else "")
                            )
                        })
                    except Exception as _page_ex:
                        yield sse_event("log", {
                            "text": f"[FigmaMCP] ⚠ {route}: {_page_ex} — keeping deterministic schema"
                        })

                total_pages = len(pages_with_nodes)
                yield sse_event("log", {
                    "text": f"[FigmaMCP] ✓ {mcp_success}/{total_pages} pages upgraded from MCP"
                })

    except Exception as _mcp_block_ex:
        yield sse_event("log", {"text": f"[FigmaMCP] block error: {_mcp_block_ex} — deterministic schemas intact"})


async def phase_figma_binding_pass(
    state: PipelineState,
    plan: dict,
    *,
    output_dir: str,
    registry: dict,
) -> AsyncIterator[dict]:
    """Per-page ``apply_bindings`` pass + spec reconciliation.

    **Lift source (Phase 1e):** ``routers.generate._run_figma_relay_pipeline``
    lines 4085-4150 (post-drift; contract stub's 4188-4253 was pre-drift).

    For every page-schema file the previous three phases produced,
    merges the deterministic CRUD actions into it and runs
    ``apply_bindings`` (the same binding pass the text pipeline runs
    through its own ``save_binding_contract`` flow). Then
    ``aggregate_spec.reconcile_page_file`` for each page, and finally
    emits ``binding-report.json``.

    Figma has no ``save_binding_contract`` call — that's text-only.
    This phase is the Figma equivalent of the text pipeline's binding
    infrastructure.

    **Emits:** SSE events (status, log, binding_report).
    """
    try:
        from services.schema_binding import apply_bindings
        import json as _json
        binding_reports = []
        for p in (plan.get("pages") or []):
            slug = (p.get("route", "/").strip("/").replace("/", "-") or "home")
            schema_path = Path(output_dir) / p.get("file", f"src/schemas/{slug}.json")
            if not schema_path.exists():
                continue
            try:
                page_schema = _json.loads(schema_path.read_text())
            except Exception:
                continue
            # Merge deterministic CRUD actions + thread workflow set / page-type /
            # route so apply_bindings can wire nav/delete buttons and Form submit.
            from services.crud_actions import (
                merge_crud_into_page, build_workflow_index, resolvable_workflow_names,
            )
            # Every string the RUNTIME resolves to a workflow — its declared id
            # and name, not just the filename stem.
            #
            # This used to be `{f[:-5] for f in listdir(workflows)}`, i.e. file
            # stems. The runtime caches by `definition.id` AND `definition.name`
            # (KT Part 8), so a workflow whose file name differs from its
            # declared name was invisible here and the Delete button was never
            # emitted — even though dispatching it would have worked (BA-1).
            _exwf = resolvable_workflow_names(output_dir)
            p = merge_crud_into_page(p, plan, _exwf)
            p["_existing_workflows"] = sorted(_exwf)
            p["_workflow_index"] = build_workflow_index(output_dir)
            from services.workflow_action_mapper import index_status_workflows as _isw
            p["_status_index"] = _isw(output_dir)
            p["_page_type"] = p.get("type")
            p["_route"] = p.get("route")
            bound_schema, report = apply_bindings(page_schema, p, plan)
            schema_path.write_text(_json.dumps(bound_schema, indent=2))
            # Aggregate-spec floor: ensure MetricTile bindings to op:aggregate sources
            # resolve to real numbers (never literal {{…}}). Idempotent.
            try:
                from services.aggregate_spec import reconcile_page_file
                _agg_report = reconcile_page_file(schema_path, registry)
                if _agg_report.get("synthesised") or _agg_report.get("demoted"):
                    yield sse_event("log", {"text": (
                        f"[Aggregate] {p.get('route')}: "
                        f"{_agg_report['synthesised']} metric(s) synthesised, "
                        f"{_agg_report['demoted']} demoted")})
            except Exception as _agg_err:
                yield sse_event("log", {"text": f"[Aggregate] floor skipped: {_agg_err}"})
            binding_reports.append(report)
            if report.get("list_bound") or report.get("buttons_bound"):
                yield sse_event("log", {"text": (
                    f"[Binding] {p.get('route')} → list={report.get('list_bound')} "
                    f"buttons={report.get('buttons_bound')}")})
            elif report.get("reverted"):
                yield sse_event("log", {"text": f"[Binding] {p.get('route')} reverted (invalid) — kept unbound"})
        (Path(output_dir) / "binding-report.json").write_text(_json.dumps(binding_reports, indent=2))
        yield sse_event("log", {"text": f"[Binding] applied to {len(binding_reports)} page(s)"})
    except Exception as _bind_ex:
        yield sse_event("log", {"text": f"[Binding] phase skipped: {_bind_ex}"})
