"""IRF-M4-T6 (action half) — verify substrate signature moves per route.

Reads ``signature_moves_guard.compute_requirements(plan)`` to know WHAT
signatures each route needs, then walks the generated app under
``output_dir`` to check WHAT'S actually applied. Produces an
``EnforcementReport`` naming missing signatures per route and unresolvable
signatures across the catalog.

**Report-only in this ship.** The plan doc's "inject template" step is
deferred to a follow-up wired through the same ``services.signature_moves``
renderer pattern used by the existing ``apply_signature_moves`` pass.
Injection is deferred because none of the substrate signature names
currently maps to a registered renderer — until the resolver's mapping
grows, "inject" would be a no-op anyway. This module ships the compute →
verify → gap-log spine so telemetry can drive the mapping fill order.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.signature_move_resolver import resolve as _resolve_signature
from services.signature_moves_guard import compute_requirements

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteEnforcementResult:
    route: str
    module_name: str
    required: tuple[str, ...] = ()      # substrate signature names
    resolvable: tuple[str, ...] = ()    # subset with a renderer available
    unresolvable: tuple[str, ...] = ()  # subset with no renderer (gap)
    missing_applied: tuple[str, ...] = ()   # resolvable but not applied on page
    applied: tuple[str, ...] = ()       # resolvable AND already applied


@dataclass(frozen=True)
class EnforcementReport:
    per_route: tuple[RouteEnforcementResult, ...] = ()
    unmatched_modules: tuple[str, ...] = ()
    unresolvable_across_app: tuple[str, ...] = ()

    @property
    def has_gaps(self) -> bool:
        return bool(self.unresolvable_across_app) or any(
            r.missing_applied or r.unresolvable for r in self.per_route
        )


# ── page schema helpers ─────────────────────────────────────────────────


def _iter_pages_for_route(output_dir: Path, route: str) -> list[dict]:
    """Return every page schema whose ``route`` field matches ``route``.

    Matches exact + trailing-slash normalized. Returns [] if the schemas
    directory isn't present (unit-test friendly)."""
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return []
    target = route.rstrip("/") or "/"
    hits: list[dict] = []
    for p in sorted(sdir.glob("**/*.json")):
        if p.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        r = data.get("route")
        if isinstance(r, str) and (r.rstrip("/") or "/") == target:
            hits.append(data)
    return hits


def _walk_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_nodes(item)


def _renderer_marker_prop(renderer_kind: str) -> tuple[str, Any] | None:
    """Return ``(prop_name, sentinel_value)`` that indicates the renderer
    was applied to a node. Mirrors what the renderers in
    ``services.signature_moves`` actually set. ``None`` when we don't have
    a marker for the kind (unknown to this checker — treated as absent)."""
    # Kept intentionally small; add entries as new renderers land in the
    # signature_moves package.
    markers = {
        "ledger_row": ("rowStyle", None),
        "velocity_sparkline": ("trendVariant", "sparkline"),
        "status_stripe": ("statusStripe", True),
        "card_elevation": ("variant", "elevated"),
    }
    return markers.get(renderer_kind)


def _renderer_applied(pages: list[dict], renderer_kind: str) -> bool:
    """Best-effort presence check: any node in any page carries the
    renderer's sentinel prop. Silent-false when we don't have a marker
    (the enforcer then reports it as missing → grows the map over time)."""
    marker = _renderer_marker_prop(renderer_kind)
    if marker is None:
        return False
    prop_name, expected = marker
    for page in pages:
        for node in _walk_nodes(page.get("root")):
            if not isinstance(node, dict):
                continue
            props = node.get("props")
            if not isinstance(props, dict):
                continue
            if prop_name in props and (expected is None or props[prop_name] == expected):
                return True
    return False


# ── public API ──────────────────────────────────────────────────────────


def enforce(plan: dict, output_dir: str | Path) -> EnforcementReport:
    """Compute + verify + report. Never raises; never mutates.

    Args:
        plan: the plan dict (must carry ``archetypes`` for anything to
            happen; empty plan → empty report).
        output_dir: generated app root (for reading page schemas).
    Returns:
        ``EnforcementReport`` — safe to log or surface in a build report.
    """
    report = compute_requirements(plan if isinstance(plan, dict) else {})
    if not report.requirements and not report.unmatched_modules:
        return EnforcementReport()

    root = Path(output_dir)

    # Bucket requirements per (module, route).
    by_route: dict[tuple[str, str], list[str]] = {}
    for req in report.requirements:
        for route in req.routes:
            by_route.setdefault((req.module_name, route), []).append(req.signature)

    results: list[RouteEnforcementResult] = []
    unresolvable_across: set[str] = set()

    for (module_name, route), signatures in sorted(by_route.items()):
        required = tuple(sorted(set(signatures)))
        resolvable: list[str] = []
        unresolvable: list[str] = []
        for sig in required:
            if _resolve_signature(sig) is not None:
                resolvable.append(sig)
            else:
                unresolvable.append(sig)
                unresolvable_across.add(sig)

        pages = _iter_pages_for_route(root, route) if root.is_dir() else []
        applied: list[str] = []
        missing: list[str] = []
        for sig in resolvable:
            renderer_kind = _resolve_signature(sig)
            if renderer_kind and _renderer_applied(pages, renderer_kind):
                applied.append(sig)
            else:
                missing.append(sig)

        results.append(RouteEnforcementResult(
            route=route,
            module_name=module_name,
            required=required,
            resolvable=tuple(resolvable),
            unresolvable=tuple(unresolvable),
            missing_applied=tuple(missing),
            applied=tuple(applied),
        ))

    return EnforcementReport(
        per_route=tuple(results),
        unmatched_modules=report.unmatched_modules,
        unresolvable_across_app=tuple(sorted(unresolvable_across)),
    )


def log_gaps(report: EnforcementReport, *, plan_id: str | None = None) -> None:
    """Emit a substrate_gap_log entry per unresolvable signature.

    No-op when the gap log isn't importable (keeps this helper safe to
    call from post-gen guards that shouldn't fail on missing telemetry)."""
    if not report.has_gaps:
        return
    try:
        from services.substrate_gap_log import append as _append
    except Exception:  # noqa: BLE001
        return
    for sig in report.unresolvable_across_app:
        try:
            _append({
                "kind": "signature-move-unresolvable",
                "signature": sig,
                "plan_id": plan_id,
            })
        except Exception:  # noqa: BLE001
            logger.debug("substrate_gap_log append failed for %s", sig, exc_info=True)


__all__ = [
    "EnforcementReport",
    "RouteEnforcementResult",
    "enforce",
    "log_gaps",
]
