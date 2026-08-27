"""The built-in composition reference — a montage every app inherits.

Without this, the montage layer only helps a project that designates its own
reference, and nothing in the product does that yet. So the bar was set for
nobody: every generated app fell back to "however many columns the entity
happened to have", which is the density problem the reference layer exists
to fix.

The reference encoded here is read from the **BizHub Business Management**
montage — nine screens of a general-purpose business app (dashboard,
customers, projects board, invoices, tasks, reports, calendar, documents,
settings). It is deliberately a *general business* reference: the shapes it
describes (a greeting dashboard over a KPI strip, tables that carry seven
columns and a status pill, a detail screen with a summary rail) are the ones
almost every business app needs, so it raises the floor without pushing a
domain onto anything.

Two things it is not:

* **Not colour.** Same boundary as :mod:`services.montage_composition` — the
  palette belongs to the design option the user picks. Nothing here is a hex.
* **Not an override.** A project that designates its own montage wins; this
  only fills the silence. Set ``FORGE_DEFAULT_MONTAGE=0`` to fall back to the
  old behaviour of no reference at all.

Encoded as reviewable data rather than a per-build vision call: the montage
does not change between builds, so reading it once and writing the answer
down is both cheaper and auditable. Every typed value below is checked
against the maquette layer's live vocabularies by
``tests/services/test_default_composition.py`` — if someone renames a hero
kind, that test fails rather than this silently recommending a shape the
schema rejects.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── BizHub, read as shape ───────────────────────────────────────────────────
# Counts are the RICHEST screen of each kind, because the reference is a bar
# to reach rather than an average to hit:
#   • kpis_target 5      — the dashboard's KPI strip runs five tiles, each
#                          carrying icon + label + value + delta + comparison.
#   • sections_target 8  — the montage stacks twelve widget cards under that
#                          strip; eight is the schema's own ceiling, so the
#                          bar is "as dense as the maquette can express".
#   • columns_target 7   — Invoices is the widest table (Invoice #, Customer,
#                          Date, Due Date, Status, Amount, Balance). Customers,
#                          Tasks and Documents all run six.
#   • record 3 / 9       — Settings is the montage's only record-shaped screen:
#                          a page header, a profile form beside an account
#                          summary rail, nine fields across the two.
_BIZHUB = {
    "source": "BizHub Business Management montage (9 screens)",
    "layout": ("fixed left sidebar with grouped primary and admin sections; "
               "top bar carrying global search, a primary create action, "
               "notifications and account; wide content column"),
    "screens": {
        "dashboard": {
            "regions": [
                "greeting header with a date-range control",
                "kpi strip of 5 tiles, each with a delta and a comparison line",
                "primary trend chart beside a health gauge and an activity feed",
                "ranked customer list, project progress list and a due-today list",
                "category breakdown, cash-flow bars and an upcoming-events agenda",
            ],
            "density": ("dense — 5 KPIs above the fold, then three rows of "
                        "three cards mixing charts, ranked lists and feeds"),
            "hero_kind": "personalised-greeting",
            "rhythm": "tight",
            "kpis_target": 5,
            "sections_target": 8,
        },
        "collection": {
            "regions": [
                "title with a one-line subtitle",
                "search beside filter dropdowns and a primary create action",
                "table whose first column leads with an avatar or reference",
                "status pill column and a trailing owner or assignee",
                "pagination with a result count and a page-size control",
            ],
            "density": ("6-7 columns per row including a status pill; "
                        "identity column pairs an avatar with a name"),
            "shape": "table",
            "columns_target": 7,
        },
        "record": {
            "regions": [
                "page header with a one-line subtitle",
                "form sections in the main column",
                "summary rail beside the form carrying plan and usage rows",
                "destructive action at the foot of the rail",
            ],
            "density": "9-10 fields across a main form and a summary rail",
            "hero_kind": "page-header",
            "sections_target": 3,
            "fields_target": 9,
        },
    },
}

# Keyed so per-archetype references can be added later without touching any
# caller — today every app resolves to the general-business one.
DEFAULT_COMPOSITION_REFERENCES: dict[str, dict] = {"general-business": _BIZHUB}

_ENV_FLAG = "FORGE_DEFAULT_MONTAGE"


def default_montage_enabled() -> bool:
    """False only when explicitly switched off. On by default — a reference
    nobody opts into is a reference nobody gets."""
    return os.environ.get(_ENV_FLAG, "1").strip().lower() not in ("0", "false", "no")


def default_composition_reference(plan: dict | None = None) -> Optional[dict]:
    """The built-in reference for this app, or None when disabled.

    ``plan`` is accepted and currently unused: it is the hook for choosing a
    per-archetype reference once there is more than one, and taking it now
    means callers do not change when that happens.
    """
    if not default_montage_enabled():
        logger.info("[montage] built-in default disabled via %s", _ENV_FLAG)
        return None
    ref = DEFAULT_COMPOSITION_REFERENCES.get("general-business")
    # Deep-copied at the boundary: callers persist this and a shared mutable
    # default would leak one build's edits into the next.
    import copy
    return copy.deepcopy(ref) if ref else None
