"""Derived functions over ShapeProfile — the ONE place cross-primitive
logic lives.

Every downstream stage that needs to answer "does this app need a
<Toaster /> at root?" or "should this workflow submit fire-and-forget?"
calls a function here — NEVER branches on ``plan.app_shape.label``
(labels are for humans; the pipeline reads primitives). See spec P1
"Derived properties".

The functions here are pure: dict-in, decision-out. No I/O. This is
what makes them cheap to unit-test and cheap to compose from any stage.

Also owns ``resolve_shape(plan, route)`` — the per-page shape resolver
that merges the outer ``plan.app_shape`` with the owning
``ArchetypeInstance.local_shape`` override for a specific route.
Multi-module apps (Uber, Workday, Swiggy) rely on this to have per-route
shape decisions (Uber's ``/pay`` route flips ``layout.shell`` to
``none`` locally while the outer stays ``map-canvas``).

Not owned here: the vocabulary loaders (shape_profile.py), the planner
emission (planner.py), the downstream stage integrations (various
service files in M3/M4).
"""
from __future__ import annotations

from typing import Any


# ══════════════════════════════════════════════════════════════════
# resolve_shape — the per-route shape resolver
# ══════════════════════════════════════════════════════════════════


def resolve_shape(plan: dict[str, Any], route: str) -> dict[str, Any]:
    """Effective shape for a specific route.

    ``effective = plan.app_shape`` merged with the ``local_shape`` of
    whichever ``ArchetypeInstance`` in ``plan.archetypes`` owns
    ``route``. Instance wins on overlap (partial override).

    Callers that don't care about per-route variation pass ``route=""``
    or read ``plan.app_shape`` directly. Callers that DO care (page
    schema agent, build_form_page, translate_workflow, signature moves
    guard) always route through here so their behavior stays coherent
    across single-module and multi-module apps.

    Returns a fresh dict; safe to mutate.
    """
    outer = plan.get("app_shape") or {}
    if not isinstance(outer, dict):
        return {}
    if not route:
        return _deep_copy(outer)
    owner = _find_owning_module(plan.get("archetypes") or [], route)
    if owner is None:
        return _deep_copy(outer)
    override = owner.get("local_shape")
    if not isinstance(override, dict) or not override:
        return _deep_copy(outer)
    return _merge(outer, override)


def _find_owning_module(archetypes: list, route: str) -> dict[str, Any] | None:
    """Return the ArchetypeInstance dict whose routes list contains
    ``route``. Deterministic — first-match wins if multiple instances
    claim the same route (the plan validator M1-T3 could flag this in
    a future coherence check; for now first-match is safest)."""
    if not route:
        return None
    for instance in archetypes:
        if not isinstance(instance, dict):
            continue
        for r in instance.get("routes") or []:
            if _route_matches(r, route):
                return instance
    return None


def _route_matches(declared: str, actual: str) -> bool:
    """Exact match OR the declared route is a dynamic-segment parent
    of the actual (``/products/[slug]`` matches ``/products/foo``).
    Deliberately conservative — no wildcards, no regex; a route
    declaration is a specific path, and dynamic segments use the
    standard ``[slug]`` convention this codebase already uses
    elsewhere."""
    if declared == actual:
        return True
    dparts = [p for p in declared.split("/") if p]
    aparts = [p for p in actual.split("/") if p]
    if len(dparts) != len(aparts):
        return False
    for d, a in zip(dparts, aparts):
        if d.startswith("[") and d.endswith("]"):
            continue  # dynamic segment matches anything
        if d != a:
            return False
    return True


def _merge(outer: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two shape dicts. Override wins on any leaf value.
    Both inputs are expected to be shape-shaped (nested slices with
    scalar leaves); we don't merge lists — override replaces entirely."""
    result = _deep_copy(outer)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = _deep_copy(value)
    return result


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


# ══════════════════════════════════════════════════════════════════
# Derived properties — the "if X then Y" logic that used to be
# scattered across guards and templates. Each function reads shape
# primitives; NEVER a shape label.
# ══════════════════════════════════════════════════════════════════


def needs_root_toaster(shape: dict[str, Any]) -> bool:
    """True when the app must mount ``<Toaster />`` at root layout
    (not inside the dashboard shell).

    Triggered when ANY surface bypasses the shell:
    - ``layout.shell == "none"`` — hero pages without any shell
    - ``auth.surface == "modal"`` — login modal renders outside shell
    - ``workflows.executionMode == "fire-and-forget"`` — dispatches
      need to toast from any page including pre-auth

    Fixes the AC10-copy "toaster only on dashboard-shell pages" class
    permanently — the derivation is stable, no per-app patch needed.
    """
    layout = shape.get("layout") or {}
    auth = shape.get("auth") or {}
    workflows = shape.get("workflows") or {}
    return (
        layout.get("shell") == "none"
        or auth.get("surface") == "modal"
        or workflows.get("executionMode") == "fire-and-forget"
    )


def should_generate_login_route(shape: dict[str, Any]) -> bool:
    """True when the pipeline should generate ``/login`` + ``/signup``
    route pages. False when auth is modal-only or absent — the
    ``<LoginModal>`` component covers the flow inline."""
    auth = shape.get("auth") or {}
    return auth.get("surface") == "route"


def form_submit_pattern(shape: dict[str, Any]) -> str:
    """Return the submit pattern name that ``build_form_page`` should
    apply. Reads ``workflows.executionMode`` — the same primitive that
    ``translate_workflow`` reads, so form and workflow stay coherent
    per-app.

    Returns one of:
    - ``fire-and-forget-with-toast-nav`` — dispatch, toast, navigate
    - ``await-with-spinner`` — spinner + block until complete
    - ``in-place-progress`` — streaming progress in-page
    - ``background-with-notification`` — dispatch, notify later
    """
    workflows = shape.get("workflows") or {}
    mode = workflows.get("executionMode")
    if mode == "fire-and-forget":
        return "fire-and-forget-with-toast-nav"
    if mode == "streaming":
        return "in-place-progress"
    if mode == "background-with-notification":
        return "background-with-notification"
    return "await-with-spinner"


def denorm_columns_needed(shape: dict[str, Any]) -> bool:
    """True when ``schema_builder`` should emit ``*Name`` denorm
    columns per FK. Reads ``data.denormalization``."""
    data = shape.get("data") or {}
    return data.get("denormalization") == "aggressive"


def synth_shell_menu(shape: dict[str, Any]) -> bool:
    """True when ``shell_menu_sync`` should synthesize a menu. False
    when the shape declares no menu surface — nothing for the sync to
    populate."""
    nav = shape.get("nav") or {}
    return nav.get("menu") not in ("none", None)


def shell_kind(shape: dict[str, Any]) -> str:
    """Convenience — return the value of ``layout.shell`` with a
    tolerant default of ``sidebar`` for missing/invalid input.
    Consumers that switch on the six shell values call this."""
    layout = shape.get("layout") or {}
    value = layout.get("shell")
    if value in ("none", "sidebar", "header", "three-pane", "bottom-tabs", "map-canvas"):
        return value
    return "sidebar"


# ══════════════════════════════════════════════════════════════════
# Coherence hints — small pure helpers the coherence check (M1-T9)
# and downstream stages both use.
# ══════════════════════════════════════════════════════════════════


def is_realtime_module(instance: dict[str, Any]) -> bool:
    """True when an ArchetypeInstance's capabilities declare
    ``state.realtime == 'stream'`` — used by translate_workflow to
    decide whether to emit polling or streaming dispatch."""
    caps = instance.get("capabilities") or {}
    state = caps.get("state") or {}
    return state.get("realtime") == "stream"


def module_interactions(instance: dict[str, Any]) -> tuple[str, ...]:
    """Tuple of declared interactions for an instance. Empty for
    recipe-only instances (unless the caller resolves the recipe's
    capabilities first — that's shape_profile.recipe_capabilities)."""
    caps = instance.get("capabilities") or {}
    interactions = caps.get("interactions") or []
    if not isinstance(interactions, list):
        return ()
    return tuple(str(i) for i in interactions)
