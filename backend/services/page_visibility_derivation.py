"""Derive per-page ``visibleTo`` metadata from actors + route patterns.

Symptom this cures
------------------
Candidate signs up on a generated ATS, gets logged in, and sees the
FULL admin menu — every top-level route as a sidebar item. Root cause:
plans emit pages without ``visibleTo``/``roles``, so
:func:`services.shell_menu_sync.derive_shell_groups` treats every page
as public.

Fix scope
---------
Post-generate pass reads the actor list + nav-flow pages, then applies
a route-prefix heuristic to stamp ``visibleTo`` on each page. Runs
deterministically after :mod:`services.nav_flow_from_plan` and
:mod:`services.nav_flow_from_schemas` have emitted the file.

Heuristic
---------
Priority (first match wins):
  1. Route starts with ``/{actor_slug}`` where ``actor_slug`` matches
     any actor name in the plan (lowercase, spaces→hyphens). E.g.
     ``/candidate/apply`` → ``["candidate"]``,
     ``/recruiter/candidates`` → ``["recruiter"]``.
  2. Auth routes (``/login``, ``/signup``, etc.) are skipped — they're
     already ``shell: false`` (SP1.5-F1) so don't need role scoping.
  3. Otherwise the page is left ``visibleTo: null`` (public / all-roles),
     which is the correct default for shared shell pages (dashboard,
     settings, etc.).

Idempotent + never raises. A missing/malformed nav-flow or plan is a
silent no-op so a plan-agnostic app still passes through cleanly."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_AUTH_PREFIXES = (
    "/login", "/signin", "/sign-in", "/signup", "/sign-up", "/register",
)


def derive_visible_to(output_dir: str | Path) -> dict[str, Any]:
    """Stamp ``visibleTo`` on every nav-flow page whose route matches
    an actor slug. Returns a summary dict::

        {
          "actors_seen":    ["candidate", "recruiter", "admin"],
          "pages_scoped":   12,
          "pages_public":   8,
          "pages_skipped":  3,   # auth routes + already-scoped pages
        }
    """
    summary: dict[str, Any] = {
        "actors_seen":   [],
        "pages_scoped":  0,
        "pages_public":  0,
        "pages_skipped": 0,
    }

    root = Path(output_dir)
    plan = _load_plan(root)
    nav  = _load_nav_flow(root)

    actor_slugs = _slugify_actors(plan)
    summary["actors_seen"] = sorted(actor_slugs)

    if not isinstance(nav, dict):
        return summary
    pages = nav.get("pages")
    if not isinstance(pages, list):
        return summary

    for page in pages:
        if not isinstance(page, dict):
            summary["pages_skipped"] += 1
            continue
        route = page.get("route") or ""
        if not isinstance(route, str) or not route.startswith("/"):
            summary["pages_skipped"] += 1
            continue
        # Skip auth routes — they're already shell:false and don't
        # need role scoping. (SP1.5-F1 + this session's plan-driven fix.)
        if any(route.startswith(pfx) for pfx in _AUTH_PREFIXES):
            summary["pages_skipped"] += 1
            continue

        # Preserve any existing visibleTo (respect planner or a
        # previous run) — this pass is a BACKFILL, not a stomp.
        if "visibleTo" in page and page.get("visibleTo") is not None:
            summary["pages_scoped"] += 1
            continue

        matched = _match_route_to_actor(route, actor_slugs)
        if matched:
            page["visibleTo"] = [matched]
            summary["pages_scoped"] += 1
        else:
            # Explicit null so downstream can see the field was reasoned
            # about (vs. a page the pass never visited).
            page["visibleTo"] = None
            summary["pages_public"] += 1

    _write_nav_flow(root, nav)
    return summary


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _load_plan(root: Path) -> dict | None:
    # Try the canonical locations first, then fall back to the
    # generation-dossier's embedded plan — smith-arch runs don't
    # always persist plan.json to contracts/, but the dossier always
    # captures the plan under /plan.
    for candidate in (root / "contracts" / "plan.json",
                      root / "plan.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
    dossier = root / "contracts" / "generation-dossier.json"
    if dossier.exists():
        try:
            d = json.loads(dossier.read_text(encoding="utf-8"))
            embedded = (d or {}).get("plan")
            if isinstance(embedded, dict):
                return embedded
        except Exception:  # noqa: BLE001
            return None
    return None


def _load_nav_flow(root: Path) -> dict | None:
    for candidate in (root / "src" / "contracts" / "nav-flow.json",
                      root / "contracts" / "nav-flow.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
    return None


def _write_nav_flow(root: Path, nav: dict) -> None:
    """Write back to whichever location we loaded from — src/contracts
    is where nav_flow_from_plan writes; contracts/ is the alt location
    some earlier flows used."""
    for candidate in (root / "src" / "contracts" / "nav-flow.json",
                      root / "contracts" / "nav-flow.json"):
        if candidate.exists():
            try:
                candidate.write_text(
                    json.dumps(nav, indent=2), encoding="utf-8",
                )
                return
            except Exception:  # noqa: BLE001
                logger.exception("[page-visibility] write failed")
                return


def _slugify_actors(plan: dict | None) -> set[str]:
    """Return the set of actor slugs (name lower-cased, spaces→hyphens).

    Reads both ``plan['actors']`` (canonical for smith-arch) and any
    ``plan['roles']`` / ``plan['data_models'][*].role_enum`` shape the
    planner may have used for role scoping.
    """
    if not isinstance(plan, dict):
        return set()
    slugs: set[str] = set()
    for a in (plan.get("actors") or []):
        if isinstance(a, dict):
            name = a.get("name") or a.get("role")
            if isinstance(name, str) and name.strip():
                slugs.add(_slugify(name))
        elif isinstance(a, str):
            slugs.add(_slugify(a))
    for r in (plan.get("roles") or []):
        if isinstance(r, str) and r.strip():
            slugs.add(_slugify(r))
        elif isinstance(r, dict):
            n = r.get("name")
            if isinstance(n, str) and n.strip():
                slugs.add(_slugify(n))
    return slugs


def _slugify(name: str) -> str:
    """``"Recruitment Administrator"`` → ``"recruitment-administrator"``.
    Also handles PascalCase and preserves alnum only."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _match_route_to_actor(route: str, actor_slugs: set[str]) -> str | None:
    """Return the actor slug whose name matches the first non-empty
    segment of ``route``, if any. Otherwise None (page is public).

    Comparison is fuzzy — an actor named "Candidate" matches routes
    starting with ``/candidate`` OR ``/candidates`` (plural). This
    tolerates the planner's inconsistent singular/plural choices.
    """
    segments = [s for s in route.split("/") if s]
    if not segments:
        return None
    first = segments[0].lower()
    # exact match
    if first in actor_slugs:
        return first
    # depluralize the segment and try again (candidates → candidate)
    if first.endswith("s") and first[:-1] in actor_slugs:
        return first[:-1]
    # or add a plural to the actor (candidate ↔ candidates)
    for slug in actor_slugs:
        if first == slug or first == slug + "s":
            return slug
    return None
