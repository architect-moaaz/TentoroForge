"""Generation profile — Fast vs Complete mode chosen at DiscoveryApprove.

The profile bundles several time-vs-quality levers behind one named
choice so the UI stays simple ("Fast (~15 min)" or "Complete (~40 min)")
and we can add or remove levers later without breaking the chip contract.

Levers today:
  * ``narrative_expansion`` — the 500-line domain-doc LLM call (2-3 min).
  * ``decomposition`` — parallel per-page authoring (saves 3-5 min).
  * ``full_post_generate`` — run every guard vs a slim "critical only" set.

Persistence: :func:`persist_profile` writes ``contracts/generation-profile.json``
at DiscoveryApprove time, and each downstream phase reads it back via
:func:`load_profile`. Env vars remain the fallback when no file exists —
so nothing breaks for older projects or command-line runs.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Profile shape + registry
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Profile:
    """One row in the profile registry.

    ``id`` is the wire identifier the frontend sends on the approve chip.
    Every downstream phase reads flag fields (``narrative_expansion``,
    etc.) — never the id — so adding/renaming profiles doesn't require
    touching every consumer."""

    id: str
    label: str
    description: str
    eta_minutes: int
    narrative_expansion: bool = False
    decomposition: bool = True
    full_post_generate: bool = True
    # ── Speed levers (the profile is the SINGLE source of truth for them) ──
    # These used to be hardcoded and profile-blind, so "Fast" only skipped a
    # 30-180s narrative call while the 10-20 min variance (planner revise/V2
    # retries, the 5× build loop) was identical for both — which is why Fast
    # could take LONGER than Complete. Now the profile controls them.
    #
    # review_cycles: max coder↔reviewer build-fix cycles (each can run a real
    #   npm build + LLM fix, minutes each).
    review_cycles: int = 5
    # planner_revise: allow the completeness-revise turn (re-streams a full 24K
    #   plan, +4-8 min). Fast trusts the first plan.
    planner_revise: bool = True
    # planner_v2_retry: allow the V2-gate to re-stream a full plan on violation.
    planner_v2_retry: bool = True
    # planner_critic: allow the Actor-Critic multi-turn planner loop.
    planner_critic: bool = True
    # ── Scope caps (Fast profile — MVP contract) ──
    # A large plan gets sparse pages because the per-page authoring budget
    # is spread thin. Fast trades scope for richness: fewer entities/pages,
    # each authored to a proper standard. 0 disables the cap.
    max_entities: int = 0
    max_pages: int = 0
    # ── Richness contract (both profiles — but Fast is the strictest) ──
    # These flip on the dashboard-maquette step + require its outputs. When
    # a required section is missing after authoring, the page fails the
    # invariant and gets deterministically composed from the maquette.
    require_kpi_row: bool = False        # dashboard MUST have ≥3 KPI tiles
    require_primary_chart: bool = False  # dashboard MUST have ≥1 series chart
    require_activity_feed: bool = False  # dashboard MUST have an activity feed
    require_hero: bool = False           # dashboard MUST have a hero header

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROFILES: dict[str, Profile] = {
    "fast": Profile(
        id="fast",
        label="Fast",
        description="~10 min · Quick build with rich dashboard authoring — same domain entities as Complete, faster loop. Best for iteration.",
        eta_minutes=10,
        narrative_expansion=False,
        # Fast uses the quick ONE-SHOT planner, not the decomposition path.
        # Decomposition (skeleton + per-unit page authoring = many LLM calls) is
        # the THOROUGH route; on small/medium apps it's SLOWER and less
        # predictable than a single lean plan — the opposite of what Fast
        # promises (observed live: a 3-entity app got mis-classified "large" and
        # crawled). Reserve decomposition for Complete.
        decomposition=False,
        full_post_generate=True,
        review_cycles=2,
        planner_revise=False,
        planner_v2_retry=False,
        planner_critic=False,
        # Scope caps DISABLED — the naive ranker over-trimmed and dropped
        # domain-essential entities (e.g. a Yoga Studio lost ClassSession /
        # Instructor / MembershipPlan in favor of generic User / Booking).
        # Re-enable when the ranker knows domain-essential entities.
        # See n5uacbrt for the mangled-plan case.
        max_entities=0,
        max_pages=0,
        # Full richness contract — every dashboard MUST have KPIs + chart +
        # activity + hero. When authoring falls short, the deterministic
        # maquette-driven composer fills the gap so the floor is real content,
        # not "≥3 nodes of any type".
        require_kpi_row=True,
        require_primary_chart=True,
        require_activity_feed=True,
        require_hero=True,
    ),
    "complete": Profile(
        id="complete",
        label="Complete",
        description="~30 min · Full domain research + richer plan with completeness passes. Best for the first build of a serious app.",
        eta_minutes=30,
        narrative_expansion=True,
        decomposition=True,
        full_post_generate=True,
        review_cycles=5,
        planner_revise=True,
        planner_v2_retry=True,
        planner_critic=True,
        # No scope caps on Complete — big apps are allowed.
        max_entities=0,
        max_pages=0,
        # Same richness contract applies — a "complete" app still ships rich
        # dashboards; only the SCOPE differs from Fast.
        require_kpi_row=True,
        require_primary_chart=True,
        require_activity_feed=True,
        require_hero=True,
    ),
}


PROFILE_IDS: list[str] = list(_PROFILES.keys())


_DEFAULT_ID = "fast"


def get_profile(profile_id: Optional[str]) -> Profile:
    """Return the profile for ``profile_id``, defaulting to Fast on any
    unknown/missing value. Never raises — a bad frontend payload can't
    take generation down."""
    if isinstance(profile_id, str) and profile_id in _PROFILES:
        return _PROFILES[profile_id]
    return _PROFILES[_DEFAULT_ID]


def list_profiles() -> list[dict[str, Any]]:
    """Serialized registry the frontend renders as the chip choices."""
    return [p.to_dict() for p in _PROFILES.values()]


# --------------------------------------------------------------------------- #
# Persistence  (contracts/generation-profile.json)
# --------------------------------------------------------------------------- #

_REL_PATH = Path("contracts") / "generation-profile.json"


def persist_profile(output_dir: str, profile: Profile) -> None:
    """Write the profile choice to ``<output_dir>/contracts/generation-profile.json``.

    Idempotent + best-effort — a write failure is logged and swallowed
    so the caller (the approve handler) doesn't fail user-visibly."""
    try:
        path = Path(output_dir) / _REL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("[generation-profile] persist failed")


def load_profile(output_dir: str) -> Optional[Profile]:
    """Read the persisted profile back, or None when missing/malformed.

    Downstream phases (planner narrative gate, generator decomposition,
    post-generate guard set) call this to know what the user picked."""
    try:
        path = Path(output_dir) / _REL_PATH
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            return None
        return get_profile(doc.get("id"))
    except Exception:  # noqa: BLE001
        logger.warning("[generation-profile] load failed — falling back", exc_info=True)
        return None
