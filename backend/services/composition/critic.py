"""Slice 7 — recipe-aware design critic.

Reads a rendered page schema (the tree written by `build_recipe_page`)
and checks it against the recipe's promises:

    - Every anchor the recipe named that has a v1 component present
      in the tree, in order.
    - Every anchor's *required* copy slots (per anchors.json) present
      with non-empty strings — i.e. the deterministic string synthesizer
      or LLM copy pass actually filled them in.
    - Every anchor's required binds (per anchors.json) present in the
      page's dataSources — otherwise the anchor will render as a
      skeleton in production.

The critic is a *reader* — never rewrites, never blocks. It returns a
`CriticReport` the caller can log, persist, or attach to telemetry. The
existing `page_critic` handles LLM-authored pages; this one runs on
recipe pages instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from services.composition.loader import CompositionLibraryError, load_library

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CriticFinding:
    """One defect. `severity` is 'low' | 'medium' | 'high'."""
    kind: str          # "anchor_missing" | "empty_copy" | "wrong_order" | "missing_binding"
    anchor: str        # anchor name from anchors.json
    detail: str
    severity: str = "medium"

    def __str__(self) -> str:
        return f"[{self.severity}/{self.kind}] {self.anchor}: {self.detail}"


@dataclass(frozen=True)
class CriticReport:
    recipe: str
    route: str
    findings: tuple[CriticFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def high(self) -> list[CriticFinding]:
        return [f for f in self.findings if f.severity == "high"]

    def summary(self) -> str:
        if self.ok:
            return f"recipe {self.recipe!r} at {self.route}: OK"
        return (
            f"recipe {self.recipe!r} at {self.route}: "
            f"{len(self.findings)} finding(s) "
            f"({len(self.high())} high)"
        )


# Copy slots that must not be empty for the anchor to be worth showing.
# Rendering with these empty produces a skeleton — better to catch it.
_REQUIRED_COPY_BY_COMPONENT: dict[str, tuple[str, ...]] = {
    # member_home v1
    "PinnedMomentHero":  ("headline",),
    "VitalsInContext":   ("tiles",),        # tiles[].label|value
    "ScanStrip":         ("cells",),        # cells[].top|main
    "RecsRailReasoned":  ("items",),        # items[].title
    "CommunityPulse":    ("items",),        # items[].body
    "StickyPrimaryCta":  ("label",),
    # operator_console v1
    "AttentionQueueHero":  ("headline", "items"),
    "SlaVitalsStrip":      ("tiles",),
    "LiveEventLog":        ("events",),
    "TeamStatusBoard":     ("members",),
    "ShiftMetricsRail":    ("metrics",),
    "EmergencyActionRail": ("actions",),
    # manager_overview v1
    "TeamGlanceHero":   ("headline", "vitals"),
    "PrioritiesStrip":  ("items",),
    "CalendarWeek":     ("days",),
    "EscalationsQueue": ("items",),
    "RecognitionFeed":  ("items",),
    # creator/field/learner/analyst/patron v1
    "DiscoveryRail":     ("categories",),
    "DraftFocusHero":    ("title",),
    "JobChecklist":      ("steps",),
    "CompletionCapture": ("submitLabel",),
    "NarrativeHeadline": ("headline", "thesis"),
}


def _flatten_types(node: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return [(type, props), ...] in preorder traversal."""
    out: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(node, dict):
        return out
    t = node.get("type")
    if isinstance(t, str):
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        out.append((t, props))
    kids = node.get("children")
    if isinstance(kids, list):
        for child in kids:
            out.extend(_flatten_types(child))
    return out


def _is_empty_slot(value: Any) -> bool:
    """True when a copy slot value is empty enough that render will
    fall back to a skeleton placeholder."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def critique_recipe_page(
    page: dict[str, Any],
    *,
    library: Any = None,
) -> CriticReport:
    """Score a recipe-built page. See module docstring for the checks.

    Args:
        page: the schema dict written by `build_recipe_page`.
              Must have `meta.recipe` set — pages without it are
              non-recipe pages and get an OK report with no checks.
        library: optional Library override (test seam).

    Returns:
        CriticReport. `.ok` is True when nothing was flagged.
    """
    meta = page.get("meta") if isinstance(page.get("meta"), dict) else {}
    recipe_key = meta.get("recipe") if isinstance(meta, dict) else None
    route = page.get("route") or "/"
    if not recipe_key or not isinstance(recipe_key, str):
        # Not a recipe page — nothing to critique here.
        return CriticReport(recipe="", route=route, findings=())

    if library is None:
        try:
            library = load_library()
        except CompositionLibraryError as exc:
            logger.warning("[recipe-critic] library load failed: %s", exc)
            return CriticReport(
                recipe=recipe_key, route=route,
                findings=(CriticFinding(
                    kind="library_load_failed", anchor="*",
                    detail=str(exc), severity="high",
                ),),
            )

    recipe = library.recipes.get(recipe_key)
    if recipe is None:
        return CriticReport(
            recipe=recipe_key, route=route,
            findings=(CriticFinding(
                kind="unknown_recipe", anchor="*",
                detail=f"recipe {recipe_key!r} not in library",
                severity="high",
            ),),
        )

    findings: list[CriticFinding] = []
    rendered = _flatten_types(page.get("root"))
    # v1 anchors this recipe expected, in order:
    expected: list[tuple[str, str]] = []  # (anchor_name, component_name)
    for a_name in recipe.anchors:
        anchor = library.anchors.get(a_name)
        if anchor is None or anchor.impl_status != "v1":
            continue
        expected.append((a_name, anchor.component))

    # 1. Anchor presence + order.
    rendered_types = [t for (t, _) in rendered]
    seen_components: dict[str, dict[str, Any]] = {}
    for t, props in rendered:
        seen_components.setdefault(t, props)
    order_index = 0
    for a_name, comp in expected:
        if comp not in seen_components:
            findings.append(CriticFinding(
                kind="anchor_missing", anchor=a_name,
                detail=f"expected component {comp!r} not rendered",
                severity="high",
            ))
            continue
        # Order check — component must appear at or after the expected slot.
        try:
            idx = rendered_types.index(comp, order_index)
            order_index = idx + 1
        except ValueError:
            findings.append(CriticFinding(
                kind="wrong_order", anchor=a_name,
                detail=f"{comp!r} present but out of recipe order",
                severity="medium",
            ))

    # 2. Required copy slots per component.
    for a_name, comp in expected:
        props = seen_components.get(comp)
        if props is None:
            continue  # anchor_missing already reported
        for slot in _REQUIRED_COPY_BY_COMPONENT.get(comp, ()):
            if _is_empty_slot(props.get(slot)):
                findings.append(CriticFinding(
                    kind="empty_copy", anchor=a_name,
                    detail=f"{comp}.{slot} empty — will render as skeleton",
                    severity="medium",
                ))

    # 3. Required binds (dataSources) declared on the anchor.
    data_sources = page.get("dataSources") if isinstance(page.get("dataSources"), list) else []
    ds_names = {
        ds.get("name") for ds in data_sources
        if isinstance(ds, dict) and isinstance(ds.get("name"), str)
    }
    for a_name, _ in expected:
        anchor = library.anchors.get(a_name)
        if anchor is None:
            continue
        for bind in anchor.binds_required:
            if not isinstance(bind, dict):
                continue
            bind_name = bind.get("name")
            if not isinstance(bind_name, str):
                continue
            # We don't yet author binds in build_recipe_page — this check
            # will start firing once Slice 8 (data binding for recipes)
            # lands. Report as low-severity for now.
            if bind_name not in ds_names:
                findings.append(CriticFinding(
                    kind="missing_binding", anchor=a_name,
                    detail=f"required bind {bind_name!r} not in page.dataSources",
                    severity="low",
                ))

    return CriticReport(
        recipe=recipe_key, route=route,
        findings=tuple(findings),
    )


__all__ = ["CriticFinding", "CriticReport", "critique_recipe_page"]
