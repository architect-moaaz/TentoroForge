"""Semantic route-intent classifier for pages that are NOT ordinary CRUD.

Root causes this addresses (B-022.6, .7, .9):

  * `/profile` / `/settings` / `/account` render as generic "Add User"
    forms because the deterministic page builder treats every route ending
    in a noun as a CRUD landing page. But these are singletons scoped to
    the currently-signed-in user — no listing, no create, always the same
    record. (B-022.6)
  * `/home-cooks` / `/my-cooks` / `/team` render as generic user lists
    that show ALL rows regardless of scope. But the reader intent is
    "people I care about" — a filtered list. (B-022.7)
  * `/my-recipes` / `/my-orders` / `/my-*` render as ordinary list pages
    that show every row instead of the current user's rows. Adding a new
    recipe doesn't "show up" because the list is unfiltered. (B-022.9)

The fix: a small classifier that recognises these route patterns and
returns a structured intent — the deterministic page builder uses this
intent to shape the page differently (singleton vs list, scoped filter vs
unscoped, edit-in-place vs create+edit routes).

Contract (pure Python, deterministic, no LLM):

    RouteIntent(kind: "singleton_current_user"     # /profile, /settings
                     | "current_user_scope_list"   # /my-recipes, /favourites
                     | "role_scope_list"           # /home-cooks
                     | "crud",                     # (default — unchanged)
                entity: str | None,
                filter: dict | None)              # {"ownerId": "{{currentUser.id}}"}

The classifier is intentionally conservative — anything ambiguous falls
through to "crud" so existing behaviour is preserved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# ---------- vocabulary -----------------------------------------------------

# Routes that are ALWAYS a singleton view of the current user's record.
SINGLETON_ROUTES: frozenset[str] = frozenset({
    "profile", "myprofile", "my-profile",
    "settings", "mysettings", "my-settings",
    "account", "myaccount", "my-account",
    "preferences", "mypreferences", "my-preferences",
})

# Routes whose LIST is scoped to the current user's rows.
MY_X_PREFIXES: tuple[str, ...] = ("my-", "my", "mine-")

# Routes commonly meaning "list of users with role=X".
ROLE_LIST_PATTERNS: dict[str, str] = {
    # normalized-route stub → role literal to filter by. Case-insensitive match.
    "home-cooks":   "cook",
    "homecooks":    "cook",
    "cooks":        "cook",
    "chefs":        "chef",
    "instructors":  "instructor",
    "teachers":     "teacher",
    "students":     "student",
    "recruiters":   "recruiter",
    "reviewers":    "reviewer",
    "assessors":    "assessor",
    "admins":       "admin",
    "moderators":   "moderator",
    "interviewers": "interviewer",
    "candidates":   "candidate",
    "applicants":   "applicant",
    "customers":    "customer",
    "buyers":       "buyer",
    "sellers":      "seller",
    "vendors":      "vendor",
    "operators":    "operator",
    "managers":     "manager",
    "staff":        "staff",
    "employees":    "employee",
    "guests":       "guest",
    "members":      "member",
    "hosts":        "host",
    "drivers":      "driver",
    "riders":       "rider",
}


# ---------- data class -----------------------------------------------------

@dataclass(frozen=True)
class RouteIntent:
    kind: str                             # singleton_current_user | current_user_scope_list | role_scope_list | crud
    entity: str | None                    # inferred entity name (may be None)
    filter: dict | None                   # binding-shaped filter dict, or None


# ---------- helpers --------------------------------------------------------

def _normalize_route_segment(route: str) -> str:
    """`/My-Recipes/` → `my-recipes`. Strip lead/trailing slash + lowercase."""
    r = (route or "").strip("/").strip().lower()
    # We only classify by the top-level segment.
    return r.split("/")[0] if r else ""


def _strip_my_prefix(seg: str) -> str:
    """`my-recipes` → `recipes`. `my_orders` → `orders`. Anything else → seg."""
    for pref in MY_X_PREFIXES:
        if seg.startswith(pref) and len(seg) > len(pref):
            rest = seg[len(pref):]
            # Strip a leading dash if present after 'my'.
            return rest.lstrip("-_")
    return seg


def _entity_from_segment(seg: str, entities: Iterable[str] | None) -> str | None:
    """Try to match a route segment to a declared entity (case-insensitive,
    singular/plural aware)."""
    if not seg:
        return None
    lc = seg.lower()
    if not entities:
        return None
    ents = list(entities)
    lc_map = {e.lower(): e for e in ents}
    # exact
    if lc in lc_map:
        return lc_map[lc]
    # depluralise
    if lc.endswith("ies") and lc[:-3] + "y" in lc_map:
        return lc_map[lc[:-3] + "y"]
    if lc.endswith("es") and lc[:-2] in lc_map:
        return lc_map[lc[:-2]]
    if lc.endswith("s") and lc[:-1] in lc_map:
        return lc_map[lc[:-1]]
    # try dash-collapsed camelcase — `home-cooks` → `homecook`s → `HomeCook`
    joined = lc.replace("-", "").replace("_", "")
    for e in ents:
        if e.lower() == joined:
            return e
        # plural form of camelcase
        if e.lower() + "s" == joined:
            return e
    return None


# ---------- public API -----------------------------------------------------

def classify_route(route: str, entities: Iterable[str] | None = None) -> RouteIntent:
    """Return the RouteIntent for a page's route. Non-matches → `crud`.

    `entities` is the plan's entity map keys, used to resolve the target
    entity for scoped lists. If not supplied, `entity` in the returned
    intent may be `None` — the caller can still act on `kind` alone.
    """
    seg = _normalize_route_segment(route)
    if not seg:
        return RouteIntent(kind="crud", entity=None, filter=None)

    # 1. Singleton (profile / settings / account)
    if seg in SINGLETON_ROUTES:
        return RouteIntent(
            kind="singleton_current_user",
            entity=_entity_from_segment("user", entities),
            filter={"id": "{{currentUser.id}}"},
        )

    # 2. My-X — current-user-scoped list of X
    if any(seg.startswith(pref) for pref in MY_X_PREFIXES) and _strip_my_prefix(seg) != seg:
        target_seg = _strip_my_prefix(seg)
        entity = _entity_from_segment(target_seg, entities)
        return RouteIntent(
            kind="current_user_scope_list",
            entity=entity,
            filter={"ownerId": "{{currentUser.id}}"},
        )

    # 3. Role-scoped user lists — /home-cooks, /reviewers, ...
    for stub, role in ROLE_LIST_PATTERNS.items():
        if seg == stub or seg == stub.replace("-", "") or seg == stub.replace("-", "_"):
            entity = _entity_from_segment("user", entities)
            return RouteIntent(
                kind="role_scope_list",
                entity=entity,
                filter={"role": role},
            )

    # 4. Default — ordinary CRUD path, don't change behaviour.
    return RouteIntent(kind="crud", entity=None, filter=None)
