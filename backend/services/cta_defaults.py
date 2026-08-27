"""Per-register CTA hierarchy defaults.

Each register expresses a different visual rhythm for primary / secondary /
tertiary actions. This module owns the mapping. The design_agent reads
defaults from here when emitting design-spec.json; the user can override
per-project from the design panel later.

CTA hierarchy is a project-wide rule. Per-page exceptions (e.g. form pages
where the submit button is the implicit primary) live in the validator,
not here.
"""
from __future__ import annotations
from typing import Literal, TypedDict

RegisterName = Literal["default", "workday", "linear", "stripe", "notion", "figma"]

class CtaRule(TypedDict):
    variant: str
    max_per_page: int | None
    min_per_page: int

class CtaHierarchy(TypedDict):
    primary: CtaRule
    secondary: CtaRule
    tertiary: CtaRule


_BASE: CtaHierarchy = {
    "primary":   {"variant": "primary",   "max_per_page": 1,    "min_per_page": 1},
    "secondary": {"variant": "secondary", "max_per_page": 3,    "min_per_page": 0},
    "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
}


_PER_REGISTER: dict[RegisterName, CtaHierarchy] = {
    "default": _BASE,
    "linear":  {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 2, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    },
    "workday": {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 3, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    },
    "stripe": _BASE,
    "figma":  _BASE,
    "notion": {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 2, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    },
}


def defaults_for_register(register: str) -> CtaHierarchy:
    """Return the CTA hierarchy defaults for the given register. Unknown
    registers fall back to the base configuration."""
    return _PER_REGISTER.get(register, _BASE)  # type: ignore[arg-type]
