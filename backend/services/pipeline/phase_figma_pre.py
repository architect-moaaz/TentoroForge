"""Figma-only pre-frontend phase: the plan-driven binding pass.

The three phases that used to sit beside it — the REST node-tree mapper,
the schema refiner and the Dev Mode MCP block — are the Figma adapter's
``markup`` (``services.design_source.figma``) and the shared import phase
(``services.pipeline.phase_design_import``) now. What remains here is the
per-page ``apply_bindings`` pass the design pipeline runs after import.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from sse_helpers import sse_event
from services.pipeline.state import PipelineState


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
