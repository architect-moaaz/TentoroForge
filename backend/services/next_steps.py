"""Derive "What next?" suggestions from a freshly generated plan.

Purpose: after a build completes, the user is dropped in front of a
generated app with no clear entry point. This module reads the app's
plan.json and emits a small, ordered list of concrete next actions
(create a record, publish, build mobile, etc.) that Smith surfaces as
clickable chips in a NextStepsCard.

Design contract:
  * DETERMINISTIC — same plan → same suggestions. No LLM in this
    module; the LLM comes in later if we want personalized copy.
  * SMALL — target 4–6 suggestions max. The card is a nudge, not a
    control panel. Long-tail asks stay in the free-text input.
  * PLAN-DERIVED — every "add a X" chip names a real entity from the
    plan, every "explore /X" chip names a real route. No hallucinated
    features.
  * ACTIONABLE — each suggestion is either a chat message Smith knows
    how to route (``kind="send"``), a preview-iframe navigation
    (``kind="navigate"``), or a direct tool invocation (``kind="tool"``).

The frontend renders whatever this module emits — new suggestion kinds
require both a schema addition here and a renderer in NextStepsCard.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Suggestion shapes                                                            #
# --------------------------------------------------------------------------- #

# The three action kinds the frontend knows how to render.
_VALID_KINDS = {"send", "navigate", "tool"}


@dataclass
class NextStep:
    """One clickable chip in the NextStepsCard.

    ``kind`` picks the click behavior:
      * ``send``     → sends ``message`` to the chat as if the user
                       typed it (Smith routes it via his normal loop).
      * ``navigate`` → navigates the preview iframe to ``url``.
      * ``tool``     → sends ``message`` (Smith's routing prompts him to
                       call the matching tool — used for publish /
                       generate_mobile_app).

    ``label`` is what the user reads on the chip.
    ``icon`` is a lucide-react icon name the frontend maps. Optional.
    ``rationale`` is a one-line hover hint explaining WHY this chip
    exists ("This app has an Applicants entity").
    """
    label: str
    kind: str
    message: Optional[str] = None
    url: Optional[str] = None
    icon: Optional[str] = None
    rationale: Optional[str] = None

    def to_dict(self) -> dict:
        # Drop Nones so the payload stays tight and TypeScript can lean
        # on `key in obj` narrowing.
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return d


# --------------------------------------------------------------------------- #
# Plan reading                                                                 #
# --------------------------------------------------------------------------- #

_PLAN_CANDIDATES = (
    ("src", "contracts", "plan.json"),
    ("contracts", "plan.json"),
)


def load_plan(output_dir: str | Path) -> Optional[dict]:
    """Read the app's plan.json from either standard location. Returns
    None if the file is missing or unreadable — the caller falls back
    to a plan-less suggestion set."""
    root = Path(output_dir)
    for parts in _PLAN_CANDIDATES:
        p = root.joinpath(*parts)
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("next_steps: unreadable plan at %s: %s", p, exc)
                return None
    return None


# --------------------------------------------------------------------------- #
# Signals                                                                      #
# --------------------------------------------------------------------------- #

# Names we don't want to suggest as "add a X" targets — they either
# don't have a create page or are lifecycle-only. Kept small and
# conservative; add here only after seeing a specific bad chip in the
# wild.
_SKIP_ENTITY_NAMES = {
    "user",         # /users/new is auth, not a data-entry flow
    "session",
    "audit",
    "auditlog",
    "notification",
    "workflowtask",
    "workflow_task",
}


def _entity_name(entity: dict) -> str:
    """Best-effort display name — falls back through name/module_name/table."""
    for key in ("name", "displayName", "module_name", "table"):
        v = entity.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _slug_for(entity: dict) -> Optional[str]:
    """URL-slug for the entity's list/create routes. Prefers explicit
    route/slug fields; falls back to a snake→kebab of the name."""
    for key in ("slug", "route", "path"):
        v = entity.get(key)
        if isinstance(v, str) and v.strip("/"):
            return "/" + v.strip("/").split("/")[0]  # strip leading segment only
    name = _entity_name(entity)
    if not name:
        return None
    # Simple pluralize + lowercase — matches how the generator names
    # routes for singleton entities. Not perfect (matches "applicant" →
    # "/applicants" but also "person" → "/persons" not "/people") — the
    # navigate action is best-effort, and if it 404s the user still has
    # the chat as an escape hatch.
    lower = name[0].lower() + name[1:] if name else name
    # camelCase → kebab-case
    kebab = "".join("-" + c.lower() if c.isupper() else c for c in lower).lstrip("-")
    if not kebab.endswith("s"):
        kebab += "s"
    return "/" + kebab


def _iter_entities(plan: dict) -> Iterable[dict]:
    """Plans stash entities under several keys depending on generation
    era. Yield them all so the derivation works across versions."""
    for key in ("data_models", "entities", "modules", "resources"):
        items = plan.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    yield item


def _pick_primary_entity(plan: dict) -> Optional[dict]:
    """Choose the entity most likely to be the user's main object.
    Heuristic: first non-skipped entity with a create page. Registry
    order is roughly importance order in current planner output."""
    for e in _iter_entities(plan):
        name = _entity_name(e)
        if not name:
            continue
        if name.lower().replace(" ", "").replace("_", "") in _SKIP_ENTITY_NAMES:
            continue
        return e
    return None


def _has_dashboard(plan: dict) -> bool:
    """True if the plan declares a dashboard-y root page. Kept generous:
    root-route with dashboard-ish name counts, plus explicit
    archetype=dashboard."""
    pages = plan.get("pages") or []
    if not isinstance(pages, list):
        return False
    for p in pages:
        if not isinstance(p, dict):
            continue
        arch = (p.get("archetype") or "").lower()
        route = (p.get("route") or "").strip()
        name = (p.get("name") or "").lower()
        if arch == "dashboard":
            return True
        if route in ("/", "") and ("dashboard" in name or "overview" in name or "home" in name):
            return True
    return False


def _has_commerce(plan: dict) -> bool:
    """True if any entity is flagged as commerce (drives cart/checkout
    UI). We suggest "test a checkout" only when there's something to
    check out with."""
    for e in _iter_entities(plan):
        if e.get("commerce") is True:
            return True
    return False


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def derive_next_steps(
    plan: Optional[dict],
    *,
    include_publish: bool = True,
    include_mobile: bool = True,
    max_steps: int = 6,
) -> list[NextStep]:
    """Return an ordered list of chip suggestions.

    ``plan=None`` yields a minimal set (theme / publish / mobile) — safe
    fallback when the plan file is missing so the card still has value.

    Ordering rule of thumb:
      1. In-app exploration (add a record, view dashboard) — these are
         low-cost and answer "does this thing work?".
      2. Customization (theme, add a page).
      3. Ship (publish, mobile).
    """
    steps: list[NextStep] = []

    if plan:
        # 1a. Try-a-record chip when there's an entity to try.
        primary = _pick_primary_entity(plan)
        if primary:
            name = _entity_name(primary)
            slug = _slug_for(primary)
            if slug and name:
                # navigate — the create page for the entity. Much crisper
                # than "add an X" free-text which goes through Smith.
                steps.append(NextStep(
                    label=f"Add your first {name}",
                    kind="navigate",
                    url=f"{slug}/new",
                    icon="plus",
                    rationale=f"Your app has a {name} entity — try creating one.",
                ))

        # 1b. Dashboard visit — if the app has one, it's the natural
        # entry point.
        if _has_dashboard(plan):
            steps.append(NextStep(
                label="Explore the dashboard",
                kind="navigate",
                url="/",
                icon="layout-dashboard",
                rationale="See how the KPIs and widgets read against real data.",
            ))

        # 1c. Commerce chip — only when there's something to sell.
        if _has_commerce(plan):
            steps.append(NextStep(
                label="Test a checkout",
                kind="send",
                message="Walk me through testing a checkout in this app.",
                icon="shopping-cart",
                rationale="A commerce entity is wired up — try the cart flow.",
            ))

    # 1d. Verify & Fix — gated on the master self-verify flag. When
    # FORGE_SELF_VERIFY is off the whole verify pipeline is dead code, so
    # dangling the chip in front of the user would just error on click.
    # Operators toggle one env var to enable/disable the entire feature.
    from services.flag_profile import is_on
    if is_on("FORGE_SELF_VERIFY"):
        steps.append(NextStep(
            label="Verify & Fix",
            kind="tool",
            message="Verify the app and fix anything that's broken.",
            icon="shield-check",
            rationale="Walk every declared journey and auto-fix failures.",
        ))

    # 2. Customization — always useful.
    steps.append(NextStep(
        label="Change the theme",
        kind="send",
        message="I want to change the app's theme — make it more vibrant.",
        icon="palette",
        rationale="Colors, typography, and density are all in your control.",
    ))

    # 3. Ship it — put these last so the user tries the app first.
    if include_publish:
        steps.append(NextStep(
            label="Publish to the web",
            kind="tool",
            message="Publish the app.",
            icon="rocket",
            rationale="Deploy to Vercel and share a live URL.",
        ))
    if include_mobile:
        steps.append(NextStep(
            label="Build the mobile app",
            kind="tool",
            message="Generate the Android app.",
            icon="smartphone",
            rationale="Get an installable APK via Expo EAS.",
        ))

    return steps[:max_steps]


def derive_next_steps_from_output_dir(
    output_dir: str | Path,
    **kwargs,
) -> list[NextStep]:
    """Convenience wrapper for the pipeline hook: read the plan and
    derive steps in one call. Returns the fallback set if the plan is
    unreadable so the card always has SOMETHING."""
    plan = load_plan(output_dir)
    return derive_next_steps(plan, **kwargs)
