"""Empty-state library — domain-voiced copy for empty collections.

Every generated app hits empty states first (nothing seeded yet).
Today those empty states ship the mechanical TXT-1 templates: "No X
yet. New one to get started." That prose reads as generator output
regardless of domain — a wellness app and a project-management app
speak identically.

Slice 2-3: this module picks copy from the archetype's vocabulary
first, falling back to TXT-1 templates only when the vocabulary is
silent. When a booking app hits an empty schedule, the composer
uses "No sessions this day. Try another date — new sessions are
added weekly." rather than "No class-sessions yet."

Design contract:

  - Pure functions. No I/O. No LLM. Takes vocabulary + entity slug
    + route hint + page kind; returns a dict of empty-state props
    (headline/subhead/cta_label/cta_action).

  - Every field is optional in the returned dict. Callers merge with
    what they already have — the library never overwrites a maquette-
    authored empty state, only fills in the blanks.

  - Match key resolution runs in order: page-specific → screen-kind
    → entity-name → route-slug. The first match wins. Falls back to
    None for every field when nothing matches, so the caller keeps
    its legacy behaviour.

Called from :func:`services.apply_collection_maquette._apply_empty_slot`
(and, later, dashboard / list composers that also emit empty states).
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── canonical screen keys ────────────────────────────────────────────


# Maps a route segment / entity slug / page name to the canonical
# empty-state key the vocabulary uses. Kept small + explicit — a new
# key only needs adding here when a real generated app hits an empty
# state that doesn't match one of these.
#
# Order matters: a route like ``/my-bookings`` should match
# ``empty_bookings`` before it matches the generic ``empty_state``.
# The resolver walks this dict top-to-bottom.
_ROUTE_TO_STATE_KEY: tuple[tuple[str, str], ...] = (
    # Booking-app screens (member view)
    ("schedule",         "empty_schedule"),
    ("today",            "empty_today"),
    ("this-week",        "empty_this_week"),
    ("this_week",        "empty_this_week"),
    ("my-bookings",      "empty_bookings"),
    ("my_bookings",      "empty_bookings"),
    ("bookings",         "empty_bookings"),
    ("upcoming",         "empty_upcoming"),
    ("past",             "empty_past"),
    ("reviews",          "empty_reviews"),
    # Booking-app screens (instructor view)
    ("upcoming-classes", "empty_upcoming_classes"),
    ("upcoming_classes", "empty_upcoming_classes"),
    ("availability",     "empty_availability"),
    ("attendance",       "empty_attendance"),
    # Booking-app screens (admin view)
    ("classes",          "empty_classes"),
    ("instructors",      "empty_instructors"),
    ("rooms",            "empty_rooms"),
    ("plans",            "empty_plans"),
    ("analytics",        "empty_analytics"),
    # Filtered "no matches" — distinct from empty-collection.
    ("results",          "no_results"),
)


def _extract_route_slug(route: str | None) -> str:
    """Return the first non-empty path segment of a route, lowercased.

    ``/my-bookings`` → ``my-bookings``.  ``/admin/classes`` →
    ``admin`` (parent scope wins; per-role empty copy is applied by
    the caller via the parent slug).
    """
    if not isinstance(route, str) or not route.strip():
        return ""
    parts = [p for p in route.strip().strip("/").split("/") if p]
    if not parts:
        return ""
    return parts[0].strip().lower()


def _resolve_state_key(entity_slug: str, route: str | None,
                       explicit_key: str | None) -> str | None:
    """Pick the vocabulary key that best matches this empty state.

    Order:
    1. ``explicit_key`` if provided (composer knows the moment name)
    2. Route slug lookup (``/schedule`` → ``empty_schedule``)
    3. Entity slug lookup (``bookings`` → ``empty_bookings``)

    Returns None when no match — caller falls back to its own default.
    """
    if isinstance(explicit_key, str) and explicit_key.strip():
        return explicit_key.strip()

    route_slug = _extract_route_slug(route)
    for probe_slug, state_key in _ROUTE_TO_STATE_KEY:
        if route_slug == probe_slug:
            return state_key

    entity_norm = re.sub(r"[^a-z0-9]+", "-", (entity_slug or "").lower()).strip("-")
    for probe_slug, state_key in _ROUTE_TO_STATE_KEY:
        if entity_norm == probe_slug:
            return state_key

    return None


# ── main resolver ────────────────────────────────────────────────────


def resolve_empty_state(vocabulary: Any,
                        entity_slug: str,
                        route: str | None = None,
                        *,
                        explicit_key: str | None = None) -> dict[str, str]:
    """Return an empty-state prop dict from the archetype vocabulary.

    Returns an empty dict when the vocabulary is missing, or when no
    matching key is found. Callers merge the returned dict into their
    existing props — an empty return means "use your existing default,"
    a populated return means "prefer this over the mechanical template."

    Shape of the returned dict:

        {"headline": "No sessions this day. …",
         "subhead":  "Try another date — new sessions are added weekly.",
         # Optional:
         "cta_label":  "Browse this week",
         "cta_action": "/schedule?range=week"}

    ``vocabulary.signature_states`` today stores a single copy string
    per key. This resolver splits on the first ``. `` boundary to give
    ``headline`` (the punchy first sentence) + ``subhead`` (the rest).
    Vocabularies can grow to structured entries (dict per key) later
    without breaking callers — the resolver checks both shapes.
    """
    if vocabulary is None:
        return {}
    states = getattr(vocabulary, "signature_states", None)
    if not isinstance(states, dict) or not states:
        return {}

    key = _resolve_state_key(entity_slug, route, explicit_key)
    if not key or key not in states:
        return {}

    raw = states[key]

    # Future-proof: a vocabulary might store {"headline":…, "subhead":…,
    # "cta_label":…, "cta_action":…} per key. Accept both shapes.
    if isinstance(raw, dict):
        out: dict[str, str] = {}
        for k in ("headline", "subhead", "cta_label", "cta_action"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
        return out

    if isinstance(raw, str) and raw.strip():
        return _split_headline_subhead(raw.strip())

    return {}


def _split_headline_subhead(copy: str) -> dict[str, str]:
    """Split a single copy string into (headline, subhead).

    The convention in the reference booking-platform vocabulary is
    "punchy sentence. Explanatory follow-up sentence." — so we split
    on the first ``. `` boundary. Copy with only one sentence goes
    entirely into ``headline`` (subhead absent, not empty).

    Trailing punctuation on the headline is preserved ("No sessions
    this day." — the period reads more emphatic than "No sessions this
    day"). Leading whitespace on the subhead is stripped.
    """
    # Split on the FIRST sentence terminator followed by whitespace.
    match = re.search(r"(?<=[.!?])\s+", copy)
    if match is None:
        return {"headline": copy}
    headline = copy[:match.start()].rstrip()
    subhead = copy[match.end():].strip()
    out: dict[str, str] = {"headline": headline}
    if subhead:
        out["subhead"] = subhead
    return out


__all__ = [
    "resolve_empty_state",
]
