"""Signature moves guard — post-gen pass that ensures every
ArchetypeInstance's owning routes contain the signature-move
components its capabilities imply.

Reads ``plan.archetypes`` + ``archetypes/signature_moves.json`` +
``archetypes/recipes.json``. For each instance:

1. Resolve the instance's effective capabilities (recipe capabilities
   OR the LLM-composed ``capabilities`` block, or both merged).
2. Match those capabilities against every trigger in
   ``signature_moves.json``.
3. Emit a list of ``SignatureRequirement`` objects saying "route
   /foo/bar needs signature-move X because interactions contains
   drag-between-groups."

The guard itself returns requirements; it doesn't mutate schemas
(that's the injector's job — a follow-up wiring PR). This keeps the
compute testable and lets callers decide what to do (auto-inject the
template, revise-loop the page schema agent, or surface as a
finding).

Signatures attach to CAPABILITY PRIMITIVES, not recipe names — so a
novel LLM-composed module with ``interactions: [drag-between-groups]``
gets the same lane-swap animation as a recipe-picked ``kanban``. See
spec P3 "Layer 2: signature moves keyed by capability primitives".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


_ARCHETYPES_DIR = Path(__file__).resolve().parents[1] / "archetypes"


# ══════════════════════════════════════════════════════════════════
# Types
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SignatureRequirement:
    """One signature move that MUST appear on the given routes.

    The injector will look this up in the library's ``SignatureMoves.*``
    component set and materialize it as a schema node — but that
    materialization is a follow-up wiring PR; this guard just says
    what's required."""
    signature: str                 # e.g. "lane-swap-animation"
    module_name: str               # ArchetypeInstance.name
    routes: tuple[str, ...]        # every route on which the signature applies
    source: str                    # "primitive: interactions=drag-between-groups"
                                   # OR "recipe: kanban"


@dataclass(frozen=True)
class GuardReport:
    """Full output of the guard pass."""
    requirements: tuple[SignatureRequirement, ...]
    unmatched_modules: tuple[str, ...] = ()  # instances with 0 signatures
                                             # — informational, not an error


# ══════════════════════════════════════════════════════════════════
# Data loaders (cached)
# ══════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _recipes() -> dict[str, Any]:
    return _load_json(_ARCHETYPES_DIR / "recipes.json")


@lru_cache(maxsize=1)
def _signature_triggers() -> list[dict[str, Any]]:
    data = _load_json(_ARCHETYPES_DIR / "signature_moves.json")
    triggers = data.get("triggers") or []
    return triggers if isinstance(triggers, list) else []


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def clear_cache() -> None:
    """Test hook — reset the JSON caches."""
    _recipes.cache_clear()
    _signature_triggers.cache_clear()


# ══════════════════════════════════════════════════════════════════
# Capability resolution
# ══════════════════════════════════════════════════════════════════


def resolve_effective_capabilities(instance: dict[str, Any]) -> dict[str, Any]:
    """Return the fully-resolved capability dict for an ArchetypeInstance.

    - Recipe-only: read the recipe's ``capabilities`` block from
      recipes.json.
    - Capabilities-only: return the composed block as-is.
    - Both set: the LLM-composed capabilities override recipe defaults
      field-by-field (recipe as starting point + local twist).

    Returns an empty dict when no recipe and no capabilities. The
    guard treats that as "no signatures triggered" (informational)
    rather than an error — a planner check should have caught it
    already (M1-T3)."""
    recipe_name = instance.get("recipe")
    caps_override = instance.get("capabilities") or {}
    if not recipe_name and not caps_override:
        return {}

    base: dict[str, Any] = {}
    if recipe_name:
        recipes = _recipes().get("recipes") or {}
        entry = recipes.get(recipe_name)
        if entry:
            base = _deep_copy(entry.get("capabilities") or {})

    if not caps_override:
        return base

    if not base:
        return _deep_copy(caps_override)

    return _merge_caps(base, caps_override)


def _merge_caps(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge for capability slices; interactions list is a
    replace-not-append (LLM explicitly stated the interaction set)."""
    result = _deep_copy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_caps(result[key], value)
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
# Trigger matching
# ══════════════════════════════════════════════════════════════════


def _match_trigger(when: dict[str, Any], capabilities: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate a trigger's ``when`` clause against a capability dict.

    Returns ``(matched, source_description)`` — the source string
    describes WHY the trigger matched, useful for downstream logging
    and for the report the review page renders.
    """
    if not isinstance(when, dict):
        return (False, "")
    if "all" in when:
        sub_clauses = when.get("all") or []
        sources: list[str] = []
        for clause in sub_clauses:
            matched, src = _match_trigger(clause, capabilities)
            if not matched:
                return (False, "")
            sources.append(src)
        return (True, " AND ".join(sources))

    primitive = when.get("primitive")
    if not primitive:
        return (False, "")
    value = _lookup_primitive(capabilities, primitive)

    if "equals" in when:
        expected = when["equals"]
        matched = value == expected
        return (matched, f"primitive: {primitive}={expected}" if matched else "")
    if "contains" in when:
        needle = when["contains"]
        matched = isinstance(value, (list, tuple)) and needle in value
        return (matched, f"primitive: {primitive} contains {needle}" if matched else "")
    return (False, "")


def _lookup_primitive(capabilities: dict[str, Any], primitive: str) -> Any:
    """Resolve a dotted primitive path (``read.pattern``) inside a
    capability dict. Returns None if any segment missing."""
    node: Any = capabilities
    for segment in primitive.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(segment)
        if node is None:
            return None
    return node


# ══════════════════════════════════════════════════════════════════
# Guard entry point
# ══════════════════════════════════════════════════════════════════


def compute_requirements(plan: dict[str, Any]) -> GuardReport:
    """Read ``plan.archetypes`` and produce the list of
    SignatureRequirement objects the injector should honor.

    Deterministic — same plan → same requirements. Pure — no I/O
    beyond the cached JSON reads (which are effectively read-once
    per process). Safe to call from any downstream stage.

    An instance with no matching triggers is added to
    ``unmatched_modules`` for the report; not an error (many modules
    legitimately have no signature moves — a bare `crud` recipe, for
    instance).
    """
    archetypes = plan.get("archetypes") or []
    triggers = _signature_triggers()

    requirements: list[SignatureRequirement] = []
    unmatched: list[str] = []

    for instance in archetypes:
        if not isinstance(instance, dict):
            continue
        name = instance.get("name") or "<unnamed>"
        routes = tuple(str(r) for r in instance.get("routes") or [])
        caps = resolve_effective_capabilities(instance)
        if not caps:
            unmatched.append(name)
            continue

        matched_any = False
        for trigger in triggers:
            when = trigger.get("when") or {}
            matched, source = _match_trigger(when, caps)
            if not matched:
                continue
            matched_any = True
            for signature in trigger.get("signatures") or []:
                requirements.append(SignatureRequirement(
                    signature=str(signature),
                    module_name=str(name),
                    routes=routes,
                    source=source,
                ))

        # Also honor recipe-specific signatures declared on the recipe
        # entry itself. These bypass primitive matching; they always
        # apply when the recipe is used.
        recipe_name = instance.get("recipe")
        if recipe_name:
            recipe_entry = (_recipes().get("recipes") or {}).get(recipe_name) or {}
            for signature in recipe_entry.get("recipe_signatures") or []:
                requirements.append(SignatureRequirement(
                    signature=str(signature),
                    module_name=str(name),
                    routes=routes,
                    source=f"recipe: {recipe_name}",
                ))
                matched_any = True

        if not matched_any:
            unmatched.append(name)

    return GuardReport(
        requirements=tuple(requirements),
        unmatched_modules=tuple(unmatched),
    )


def requirements_for_route(report: GuardReport, route: str) -> tuple[SignatureRequirement, ...]:
    """Filter helper — return only requirements that apply to a
    specific route. Used by the page schema agent to know what
    signatures its output must include."""
    return tuple(r for r in report.requirements if route in r.routes)
