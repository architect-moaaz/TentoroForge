"""Maps generated page metadata to reference page_type used by fidelity_scorer."""
from __future__ import annotations
from typing import Protocol

from services.page_type import infer_page_type


class _BriefLike(Protocol):
    route: str
    role: str | None


# Canonical fidelity page-types (what we curated references for)
FIDELITY_PAGE_TYPES = frozenset({"dashboard", "login", "list", "detail", "form", "calendar"})


def fidelity_page_type_for(route: str, role: str | None = None) -> str | None:
    """Return one of FIDELITY_PAGE_TYPES, or None if no reference exists.

    Login detection is explicit — infer_page_type doesn't surface a "login"
    bucket. Calendar detection is explicit too (admin domain references it
    via calendar.png; route patterns like /schedule or /calendar should map).
    """
    r = (route or "").lower()
    o = (role or "").lower()

    # Explicit login detection
    if any(seg in r for seg in ("/login", "/signin", "/sign-in", "/auth")) or \
       any(seg in o for seg in ("login", "sign in", "authentication")):
        return "login"

    # Explicit calendar detection
    if "/calendar" in r or "/schedule" in r or "calendar" in o:
        return "calendar"

    class _Brief:
        def __init__(self, route, role):
            self.route = route
            self.role = role
    inferred = infer_page_type(_Brief(route, role))

    # Only pass through the canonical set; everything else has no reference
    if inferred in FIDELITY_PAGE_TYPES:
        return inferred
    return None
