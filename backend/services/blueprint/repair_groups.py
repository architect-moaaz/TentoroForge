"""Failures that share a cause are repaired together.

The build's checks hand each failure to Smith on its own, one turn after
another. ToroCommerce's six customer processes all failed with "Your account
has been disabled" — one cause, a demo account seeded wrongly — and six
repair turns ran in a row, twenty minutes for one fault (memg8iw6,
2026-10-09). Failures whose reason reads the same once what names the
particular record, process or page is taken out go to Smith as one: the
cause is found once, fixed once, and each is tried again.

Grouping only decides how failures are handed over; nothing is dropped or
judged here — a group of one is the single repair it always was.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_REF = re.compile(r"\b[A-Z]+-\d{3,}\b")
_JSON = re.compile(r"\{[^{}]*\}")
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`")
_PATH = re.compile(r"(?<![\w])/[\w\-\[\]./?=&%]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

#: What one grouped repair is given beyond a single one, per extra failure,
#: and the most it is given — a cause found once is fixed in a few steps, but
#: each failure is tried again after it.
STEPS_PER_EXTRA = 3
MAX_STEPS = 26


def cause_key(text: str) -> str:
    """A failure's reason with what names its particular subject taken out:
    ids, references, inputs, quoted names, addresses and numbers."""
    t = _UUID.sub("<id>", str(text or ""))
    t = _REF.sub("<ref>", t)
    t = _JSON.sub("<input>", t)
    t = _QUOTED.sub("<v>", t)
    t = _PATH.sub("<path>", t)
    t = _NUMBER.sub("<n>", t)
    return " ".join(t.lower().split())[:240]


def by_cause(items: Iterable[T], reason: Callable[[T], str]) -> list[list[T]]:
    """`items` in groups that fail the same way, in the order first seen."""
    groups: dict[str, list[T]] = {}
    for item in items:
        groups.setdefault(cause_key(reason(item)), []).append(item)
    return list(groups.values())


def steps_for(base: int, size: int) -> int:
    """The step budget of one repair turn for `size` failures that share a cause."""
    return min(base + STEPS_PER_EXTRA * max(size - 1, 0), MAX_STEPS)


__all__ = ["cause_key", "by_cause", "steps_for", "STEPS_PER_EXTRA", "MAX_STEPS"]
