"""Dashboard Authority — Phase 3 of the pipeline cleanup.

One writer per artifact. On dashboards, that writer is
:func:`services.apply_dashboard_maquette.apply_maquette_to_dashboard`.
This module holds the SINGLE toggle + the SINGLE dashboard-page test all
four downstream sites use, so the pattern can't drift:

- :mod:`agents.page_schema_agent` — LLM SKIPS `type=dashboard` pages
  when the authority is on (composer will fill the gap).
- :mod:`services.apply_dashboard_maquette` — composer bootstraps a new
  dashboard schema from scratch (rather than only rewriting an existing
  one), and falls back to :mod:`services.dashboard_completeness` when
  the maquette JSON is missing.
- The four dashboard-touching guards
  (:mod:`services.dashboard_completeness`,
  :mod:`services.surface_wrap_guard`,
  :mod:`services.widget_data_source_guard`,
  :mod:`services.chart_data_source_guard`) — assert-only mode on
  dashboards the composer already wrote (marker
  ``meta.maquette_composed=True``). They log drift, they don't rewrite.

The gate defaults ON. It shipped off while the behaviour was unproven,
but leaving it off meant the dashboard maquette — the artifact that
carries the montage's KPI/chart/activity decisions — was authored on
every build and then thrown away: with the authority off the LLM writes
the dashboard page first, and the composer refuses to overwrite an
already-authored page, so the maquette never reached a screen. Turning
it on makes the composer the dashboard's sole writer, which is the whole
point of the phase. Opt out per-build with FORGE_DASHBOARD_AUTHORITY=0.
"""
from __future__ import annotations

import os
from typing import Any


# ─────────────────────────── env gate ──────────────────────────────────


_FLAG_ENV_NAME = "FORGE_DASHBOARD_AUTHORITY"


def is_dashboard_authority_enabled() -> bool:
    """Return True when the Phase 3 dashboard-authority behaviour is on.

    On by default. Opt out with ``FORGE_DASHBOARD_AUTHORITY=0`` (or
    ``false`` / ``no`` / ``off`` — case-insensitive). Reading the env
    per-call is intentional: it makes tests trivially controllable
    with :func:`monkeypatch.setenv` and lets the flag be toggled at
    runtime without a process restart.
    """
    raw = os.environ.get(_FLAG_ENV_NAME, "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


# ─────────────────────────── dashboard test ────────────────────────────


# Values plan.pages[*].type / archetype uses for a dashboard-shaped
# page. Kept as a set so a new synonym added to the planner can be
# picked up in ONE place. Empty strings are excluded.
#
# ``admin`` was added because planners routinely type the primary
# admin landing surface as ``admin`` (not ``dashboard``) even though
# semantically it is the dashboard for the admin actor. The result
# was that a plan with just ``/admin`` as the landing surface bypassed
# the composer entirely — the LLM authored the page and the
# responsive-Grid KPI layout, chart palette, etc. never applied.
_DASHBOARD_PAGE_TYPES = frozenset({
    "dashboard", "overview", "home",
    # Admin landing surfaces — often the ONLY dashboard in ops apps.
    "admin", "admin-dashboard", "adminhome",
    # Analytics/reports landings — same content shape (KPI + chart + list).
    "analytics", "reports", "insights",
    # Consumer-facing landing surfaces.
    "landing",
})

# Routes that are dashboard-shaped by convention even when the plan
# types them as a generic "page". Route-based detection is a defensive
# backstop: an app whose landing page mounts at ``/admin`` but is
# typed as ``page`` should still get composer authority. Matched by
# exact route or by stem ending (``/foo/dashboard``, ``/foo/overview``).
_DASHBOARD_LANDING_ROUTES = frozenset({
    "/", "/home", "/dashboard", "/overview", "/admin",
})
_DASHBOARD_ROUTE_SUFFIXES = ("/dashboard", "/overview", "/home", "/admin")


def is_dashboard_page(page: dict[str, Any] | None) -> bool:
    """Return True when a plan page is dashboard-shaped.

    Checks in order:

    1. ``page.type`` — the primary planner classifier.
    2. ``page.archetype`` — some planners emit this instead of ``type``.
    3. ``page.route`` — defensive backstop. A page whose route is
       ``/`` / ``/home`` / ``/dashboard`` / ``/overview`` / ``/admin``
       (or ends in ``/dashboard`` / ``/overview`` / ``/home`` /
       ``/admin``) is treated as dashboard-shaped even if its type
       field says something generic like ``page``. Prevents an entire
       class of misclassifications where the planner named the landing
       route right but forgot to type it.

    Case-insensitive; whitespace trimmed. ``None`` / missing keys /
    unexpected types safely return False.
    """
    if not isinstance(page, dict):
        return False
    for key in ("type", "archetype"):
        v = page.get(key)
        if isinstance(v, str) and v.strip().lower() in _DASHBOARD_PAGE_TYPES:
            return True
    # Route-based fallback.
    route = page.get("route")
    if isinstance(route, str) and route:
        r = route.strip().rstrip("/") or "/"
        r_lower = r.lower()
        if r_lower in _DASHBOARD_LANDING_ROUTES:
            return True
        for suffix in _DASHBOARD_ROUTE_SUFFIXES:
            if r_lower.endswith(suffix):
                return True
    return False


# ─────────────────────────── composed marker ──────────────────────────


# Marker the composer stamps on every schema it writes. Guards read this
# to know whether they should assert-only (composer's output is the
# authority) or rewrite (legacy behaviour on non-composed schemas).
#
# Kept synced with
# :data:`services.apply_dashboard_maquette._MARKER_META_KEY`. Duplicated
# here rather than imported so a guard that runs early in post-generate
# doesn't pay the import cost of the whole composer module — and so
# there's no circular-import risk between the composer and guards.
_COMPOSED_MARKER_KEY = "maquette_composed"


def is_composer_authored(schema: dict[str, Any] | None) -> bool:
    """Return True when a page schema was written by the maquette composer.

    Guards use this to decide whether to run in assert-only mode
    (composer output is authority — log drift, don't rewrite) or
    legacy rewrite mode.
    """
    if not isinstance(schema, dict):
        return False
    meta = schema.get("meta")
    if not isinstance(meta, dict):
        return False
    return meta.get(_COMPOSED_MARKER_KEY) is True


def should_assert_only(schema: dict[str, Any] | None) -> bool:
    """Convenience: return True when a guard should ASSERT (log drift) instead
    of REWRITING a schema.

    Combines the authority flag + composer marker into ONE check the guards
    can call before their mutation loop. Kept here so a follow-up (e.g.
    adding a per-guard opt-out env) has a single place to change.
    """
    return is_dashboard_authority_enabled() and is_composer_authored(schema)
