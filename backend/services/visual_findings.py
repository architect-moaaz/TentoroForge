"""Turn a vision critique into findings the pipeline can act on.

Fidelity scoring (``services/fidelity_scorer``) compares a generated page
against a curated reference and returns four scores plus prose. The prose
is unroutable: ``"cards lack elevation"`` names no seam, so nothing
downstream can do anything with it and the whole pass stays advisory.

This module is the adapter. It turns the critique into the same
``{type, route, ...}`` finding shape ``services/repair_dispatcher`` already
routes for functional defects, using types that each map to a real fixer.

Two rules do the load-bearing work:

1. **A type with no fixer is not a finding.** A vision model will happily
   invent categories. Anything outside the taxonomy is dropped here rather
   than surfaced as an unactionable "issue" the user can't act on and the
   pipeline can't repair.

2. **Page-scoped and global findings are separated, and only page-scoped
   ones may be repaired mid-build.** ``design`` runs once per app, so
   acting on ``palette_mismatch`` at feature 4 would repaint features 1-3
   that the user already reviewed. Global findings are collected and
   surfaced, never auto-applied per phase.
"""
from __future__ import annotations

# Page-scoped — safe to repair for one page without touching any other.
# Each maps to an existing deterministic pass:
#   density_off      → services.density_frames.apply_density_frames
#   bare_surface     → services.surface_wrap_guard.wrap_bare_data_displays
#   weak_hierarchy   → services.page_anatomy.apply_page_anatomy
#   flat_composition → services.composition_recipes (selector)
PAGE_TYPES: frozenset[str] = frozenset({
    "density_off",
    "bare_surface",
    "weak_hierarchy",
    "flat_composition",
})

# Global — one authority owns these for the whole app, and it runs once.
# Collected for reporting; never repaired inside a phase.
GLOBAL_TYPES: frozenset[str] = frozenset({
    "palette_mismatch",
    "type_scale_off",
})

KNOWN_TYPES: frozenset[str] = PAGE_TYPES | GLOBAL_TYPES


def parse_findings(raw: dict | None, route: str) -> list[dict]:
    """Vision-model output → typed findings for one page.

    ``raw`` is the parsed JSON the scorer got back. Older responses carry
    only ``qualitative_notes``; those yield nothing rather than raising, so
    this can be dropped in ahead of the prompt change.
    """
    if not isinstance(raw, dict):
        return []
    out: list[dict] = []
    for item in raw.get("findings") or []:
        if not isinstance(item, dict):
            continue                      # a bare string, a list, junk
        ftype = item.get("type")
        if ftype not in KNOWN_TYPES:
            continue                      # no fixer → not actionable → not a finding
        out.append({
            "type":   ftype,
            "route":  route,
            "detail": str(item.get("detail") or ""),
            "source": "fidelity",
        })
    return out


def partition(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split findings into (page_scoped, global_).

    Callers repair the first list and only report the second. Anything
    already filtered by ``parse_findings`` cannot appear here, so the two
    lists together account for every finding passed in.
    """
    page = [f for f in findings or [] if f.get("type") in PAGE_TYPES]
    glob = [f for f in findings or [] if f.get("type") in GLOBAL_TYPES]
    return page, glob


def _default_fixers() -> dict:
    """Finding type → a callable that runs the matching deterministic pass.

    Imported lazily so this module stays cheap to import and unit-testable
    without dragging in the guard suite.

    ``flat_composition`` is deliberately absent: ``composition_recipes``
    *selects* a recipe at authoring time, it cannot retrofit one onto an
    already-written page. Listing it here would let the disposition claim a
    fix that never happened.
    """
    from services.density_frames import apply_density_frames
    from services.page_anatomy import apply_page_anatomy
    from services.surface_wrap_guard import wrap_bare_data_displays

    def _density(app_dir):
        return int(apply_density_frames(app_dir).get("framed", 0) or 0)

    def _surface(app_dir):
        return int(wrap_bare_data_displays(app_dir).get("wrapped", 0) or 0)

    def _anatomy(app_dir):
        # apply_page_anatomy reports what it repaired under "findings".
        return len(apply_page_anatomy(app_dir).get("findings") or [])

    return {
        "density_off":    _density,
        "bare_surface":   _surface,
        "weak_hierarchy": _anatomy,
    }


def route_visual_findings(app_dir, findings: list[dict],
                          *, fixers: dict | None = None) -> dict:
    """Repair the page-scoped findings; report everything else unhandled.

    Mirrors ``repair_dispatcher.dispatch_repairs``' disposition shape so a
    caller can fold visual and functional repairs into one report.

    The passes are app-wide and idempotent, so each distinct finding type
    runs its fixer exactly once no matter how many pages raised it. A fixer
    that raises is recorded as unhandled rather than aborting the rest —
    one broken guard must not strand the others.
    """
    findings = findings or []
    fixers = _default_fixers() if fixers is None else fixers

    page, glob = partition(findings)
    fixed, ran = 0, []
    unhandled: list[dict] = list(glob)     # global: correct to refuse here

    for ftype in dict.fromkeys(f["type"] for f in page):   # ordered, deduped
        fn = fixers.get(ftype)
        if fn is None:
            unhandled.extend(f for f in page if f["type"] == ftype)
            continue
        try:
            fixed += int(fn(app_dir) or 0)
            ran.append(ftype)
        except Exception:  # noqa: BLE001 — a broken guard must not strand the rest
            unhandled.extend(f for f in page if f["type"] == ftype)

    return {
        "fixed": fixed,
        "ran": ran,
        "unhandled": unhandled,
        "made_progress": fixed > 0,
    }
