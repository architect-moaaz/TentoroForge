"""IRF-M4 shared read-path — per-route generation context.

Every per-page stage (page_schema_agent, build_form_page, translate_workflow,
signature_moves_guard enforce, route-aware post-gen guards) consumes the same
three pieces of information for a route:

  1. The effective shape (plan.app_shape merged with the owning module's
     local_shape override) — via ``shape_profile_derived.resolve_shape``.
  2. The owning ArchetypeInstance dict (if any) — for capability lookup,
     signature-move enforcement, and archetype-scoped policies.
  3. plan.runtime_context (list of platform capability slugs) — shape isn't
     the whole story; app-global runtime capabilities (geo, camera, push)
     drive prompt gating too.

This module bundles the three into one ``RouteContext`` so per-stage diffs
stay tiny — a stage receives ``plan`` and ``route`` and calls
``route_context_for(plan, route)`` once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.shape_profile_derived import _find_owning_module, resolve_shape


@dataclass(frozen=True)
class RouteContext:
    """Everything a per-page stage needs to reason about a specific route.

    Every field has a stable empty-value fallback so callers can consume the
    context uniformly whether or not the plan carries a shape. Passing an
    empty ``route`` returns the app-level shape (no per-route resolution).
    """
    route: str
    shape: dict[str, Any] = field(default_factory=dict)
    owning_archetype: dict[str, Any] | None = None
    runtime_context: tuple[str, ...] = ()

    @property
    def owning_module_name(self) -> str | None:
        """Convenience — ``ArchetypeInstance.name`` (used as the display key
        for signature-move enforcement, telemetry, gap logs)."""
        if not isinstance(self.owning_archetype, dict):
            return None
        name = self.owning_archetype.get("name")
        return str(name) if isinstance(name, str) and name.strip() else None


def route_context_for(plan: Any, route: str) -> RouteContext:
    """Build a ``RouteContext`` for one route from a plan.

    Always returns a valid RouteContext — never raises. When the plan
    carries no ``app_shape`` or the route matches no archetype, the empty
    defaults kick in and downstream stages fall through to their pre-
    substrate behavior (same seam every prior IRF task uses).
    """
    if not isinstance(plan, dict):
        return RouteContext(route=str(route or ""))

    shape = resolve_shape(plan, str(route or ""))
    if not isinstance(shape, dict):
        shape = {}

    archetypes = plan.get("archetypes") or []
    owner = _find_owning_module(archetypes, str(route or ""))

    rc_raw = plan.get("runtime_context")
    if isinstance(rc_raw, list):
        runtime_context = tuple(str(v) for v in rc_raw if isinstance(v, str) and v)
    else:
        runtime_context = ()

    return RouteContext(
        route=str(route or ""),
        shape=shape,
        owning_archetype=owner if isinstance(owner, dict) else None,
        runtime_context=runtime_context,
    )


__all__ = ["RouteContext", "route_context_for"]
