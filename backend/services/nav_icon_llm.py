"""LLM-based nav-icon picker (Spec D Wave 5 skeleton).

Purpose
-------
``services/nav_icon_map.py`` maps nav labels ("People", "Payroll",
"Time Off") to Lucide icon names via HR-flavored keyword buckets. Fine
for HR apps, wrong for hospital / logistics / education / retail. This
module replaces those buckets with an LLM pick constrained to a closed
60-icon Lucide subset — infrastructure, not domain intelligence.

The LLM reads a nav label + its neighbours + optional domain hint and
picks ONE icon from :data:`LUCIDE_ICON_SET`. If the LLM returns
anything outside that vocabulary we fall back to ``"Folder"`` with
``confidence=0.0``. Same registry-safety property as
``intent_classifier``: the closed vocabulary wins.

This module is ADDITIVE. Nothing calls it yet — the current production
path stays on ``nav_icon_map``.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# The closed icon vocabulary                                                  #
# --------------------------------------------------------------------------- #
#
# 60 Lucide icons chosen for defensible cross-domain coverage: generic
# app-chrome (Home, Users, Settings), commerce, logistics, healthcare,
# education, science, transport, media, and celebration/reward icons.
# All names are the exact Lucide identifiers (PascalCase); the renderer
# already accepts Lucide names directly.

LUCIDE_ICON_SET: frozenset[str] = frozenset({
    # Generic app-chrome (10)
    "Home", "Users", "Settings", "Search", "Bell",
    "Calendar", "ClipboardList", "FileText", "Folder", "Inbox",
    # Dashboards / commerce (10)
    "LayoutDashboard", "Package", "BarChart", "MessageSquare", "ShoppingCart",
    "CreditCard", "Truck", "Map", "Wrench", "ShieldCheck",
    # Bookmark / social (5)
    "Bookmark", "Star", "Heart", "Camera", "Image",
    # Media (5)
    "Music", "Video", "Mic", "Play", "Pause",
    # File / IO (5)
    "Upload", "Download", "Link", "Globe", "Building",
    # Business / storefront (3)
    "Briefcase", "Store", "Hospital",
    # Healthcare / education / science (10)
    "GraduationCap", "Cross", "Stethoscope", "Pill", "Dna",
    "FlaskConical", "Beaker", "Microscope", "Compass", "Anchor",
    # Transport (5)
    "Plane", "Car", "Bike", "TrainFront", "Ship",
    # Reward / celebration (7)
    "Ticket", "Trophy", "Gift", "PartyPopper", "Sparkles",
    "Flame", "Target",
})

_FALLBACK_ICON = "Folder"

# Sanity check: this module owns the "60 items" contract. If someone
# edits the set above the assertion below flags it at import time.
assert len(LUCIDE_ICON_SET) == 60, (
    f"LUCIDE_ICON_SET must have exactly 60 icons, got {len(LUCIDE_ICON_SET)}"
)


# --------------------------------------------------------------------------- #
# Result shape                                                                #
# --------------------------------------------------------------------------- #

class NavIconChoice(BaseModel):
    """LLM-derived icon pick for one nav item.

    ``icon`` is guaranteed (post-validation) to be a member of
    :data:`LUCIDE_ICON_SET`. If the LLM misbehaves we degrade to
    ``"Folder"`` with ``confidence=0.0``.
    """

    icon: str = _FALLBACK_ICON
    confidence: float = 0.0

    @field_validator("icon")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        return v or _FALLBACK_ICON

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        if v is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


# LLM boundary — tests inject a stub; production wires a real Claude call.
QueryFn = Callable[[str, str], str]


_SYSTEM_PROMPT = """You pick the single best-fitting icon for a nav \
item in a no-code app. Emit STRICT JSON only — no prose, no code fences.

You are given:
  * label     : the nav item's user-visible label (e.g. "Patients").
  * neighbors : sibling nav labels for context.
  * domain    : optional short domain hint ("healthcare", "logistics", …).
  * lucide_set: the CLOSED list of icon names you may pick from.

Output JSON shape:
  {
    "icon":       "<one identifier from lucide_set>",
    "confidence": 0.0-1.0
  }

STRICT rules:
  * ``icon`` MUST be verbatim from ``lucide_set``. Never invent an \
icon name. Never return an icon that isn't in the list.
  * When several icons fit, prefer the more domain-specific one \
("Stethoscope" over "Users" for a Doctors nav in healthcare).
  * When nothing fits well, pick the most generic reasonable option \
(e.g. "Folder", "LayoutDashboard") from ``lucide_set`` and lower the \
confidence.

Confidence rubric:
  * 0.9+   : label matches an icon meaning directly
  * 0.7-0.9: strong domain-aware match
  * 0.5-0.7: plausible but generic
  * < 0.5  : forced generic choice

Do not narrate. Emit ONE JSON object. No code fences."""


def _default_query_fn(system_prompt: str, user_prompt: str) -> str:
    """Real LLM call — kept minimal so tests can stub cleanly."""
    try:
        from services.llm_edit import _default_llm_query  # type: ignore
        return _default_llm_query(system_prompt, user_prompt)  # type: ignore[misc]
    except Exception:
        logger.exception("choose_nav_icon_llm: default LLM query failed")
        return ""


def choose_nav_icon_llm(
    label: str,
    *,
    neighbors: Optional[list[str]] = None,
    domain: str = "",
    query_fn: Optional[QueryFn] = None,
) -> NavIconChoice:
    """Pick a Lucide icon for one nav label.

    Args:
        label: The nav item's user-visible label.
        neighbors: Sibling nav labels for context.
        domain: Optional short domain hint ("healthcare", "logistics").
        query_fn: LLM boundary — tests inject; ``None`` uses the real
            SDK call via :func:`_default_query_fn`.

    Returns:
        A :class:`NavIconChoice`. On any failure (malformed JSON, LLM
        raised, icon not in :data:`LUCIDE_ICON_SET`) returns
        ``NavIconChoice(icon="Folder", confidence=0.0)`` — never raises.
    """
    q = query_fn or _default_query_fn
    neighbor_list = list(neighbors or [])

    # We pass a sorted list to the LLM for deterministic prompt
    # ordering, but membership is still frozenset-checked.
    lucide_list = sorted(LUCIDE_ICON_SET)

    user_prompt = "\n\n".join([
        f"label:\n{label}",
        "neighbors:\n" + json.dumps(neighbor_list, ensure_ascii=False),
        f"domain:\n{domain or ''}",
        "lucide_set:\n" + json.dumps(lucide_list, ensure_ascii=False),
    ])

    try:
        raw = q(_SYSTEM_PROMPT, user_prompt) or ""
    except Exception:
        logger.exception("choose_nav_icon_llm: LLM boundary raised")
        raw = ""

    parsed = _extract_json(raw)
    if parsed is None:
        return NavIconChoice(icon=_FALLBACK_ICON, confidence=0.0)

    try:
        pick = NavIconChoice(**parsed)
    except ValidationError:
        return NavIconChoice(icon=_FALLBACK_ICON, confidence=0.0)

    # Registry-safety: icon MUST be in the closed set.
    if pick.icon not in LUCIDE_ICON_SET:
        return NavIconChoice(icon=_FALLBACK_ICON, confidence=0.0)
    return pick


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _extract_json(text: str) -> Optional[dict]:
    """Extract the first ``{...}`` object from a string. Handles pure
    JSON, code-fence wrappers, and leading/trailing prose. Returns None
    on any failure."""
    if not text or not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        try:
            body = stripped.split("\n", 1)[1]
            body = body.rsplit("```", 1)[0]
            stripped = body.strip()
        except Exception:
            pass
    try:
        v = json.loads(stripped)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    start = stripped.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(stripped)):
        c = stripped[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    v = json.loads(stripped[start:i + 1])
                    return v if isinstance(v, dict) else None
                except Exception:
                    return None
    return None
