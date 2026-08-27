"""IRF-M4-T5 (minimum-viable) — per-route shape reader for post-gen guards.

Broader guard-signature refactor (every guard accepts ``(plan, route)``) is
deferred: the vast majority of ~30 guards operate on app-global artifacts
(border tokens, next.config, seed sequencer) and don't need per-route
context. This module ships the seam the ~5 guards that DO need it use:

    from services.post_gen_route_shape import shape_for_route
    shape = shape_for_route(output_dir, route)

The helper reads ``plan.json`` from the standard contracts location and
delegates to ``route_context.route_context_for``. Silent-empty on any I/O
failure so guards stay resilient.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.route_context import RouteContext, route_context_for


def _plan_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "src" / "contracts" / "plan.json"


def _load_plan(output_dir: str | Path) -> dict:
    p = _plan_path(output_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def shape_for_route(output_dir: str | Path, route: str) -> dict[str, Any]:
    """Return the effective shape at ``route`` for a generated app.

    Empty dict when plan.json is missing / malformed / carries no
    ``app_shape`` — guards fall through to their pre-substrate behavior.
    """
    plan = _load_plan(output_dir)
    ctx = route_context_for(plan, route)
    return ctx.shape


def context_for_route(output_dir: str | Path, route: str) -> RouteContext:
    """Full RouteContext (shape + owning archetype + runtime_context).

    Empty-valued RouteContext when the plan is missing — never raises."""
    plan = _load_plan(output_dir)
    return route_context_for(plan, route)


__all__ = ["shape_for_route", "context_for_route"]
