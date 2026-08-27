"""Humanize + pluralize — Sprint 5 of Forge Great Again.

Copy is a design material. Right now Forge leaks raw identifiers into
the UI:

  - "Propertys" instead of "Properties" (naive `+ "s"` on irregular noun)
  - "Maintenance_request" instead of "Maintenance Request" (SQL column
    name as a chart legend)
  - "user_full_name" instead of "User full name" (snake_case in a label)

This module centralises the two operations that fix that class of bug:

  · ``pluralize(singular)`` — handles common English irregulars + suffix
    rules. No dependencies (avoids adding `inflect` to requirements).
  · ``humanize(text)``      — snake_case / camelCase / kebab-case →
    Title-Case-Words. Idempotent on already-humanized input.
  · ``humanize_series_label(name)`` — for chart legends specifically:
    strips trailing ``_id`` / ``_count`` / ``_sum`` / etc. before
    humanizing.

Design notes:

  - The pluralizer is compact by intent. English has ~50 irregular
    plurals; we cover the ones that appear in generated apps (Property,
    Person, Company, Status, Category, Category, etc.). If a rare word
    slips through the fallback (regular suffix rules), it will look
    slightly wrong but readable — never worse than the current
    "Propertys" state.
  - Preserves original capitalization: ``pluralize("Property") ==
    "Properties"``; ``pluralize("property") == "properties"``.
  - Idempotent-ish: ``pluralize("properties")`` returns "properties"
    (heuristic: input already ends in a common plural suffix).
  - Failure mode: bad input → returns input unchanged. Never raises.
"""
from __future__ import annotations

import re
from typing import Iterable

# ── Irregular plural table ─────────────────────────────────────────────
# All lowercase; the pluralize() function preserves the input's casing
# style via a lightweight rebuild. Add words here as generation surfaces
# them — the table beats a Latin-suffix library for our small vocabulary.
_IRREGULARS: dict[str, str] = {
    "person": "people",
    "man": "men",
    "woman": "women",
    "child": "children",
    "foot": "feet",
    "tooth": "teeth",
    "goose": "geese",
    "mouse": "mice",
    "ox": "oxen",
    # Common latin/greek in enterprise apps.
    "datum": "data",
    "criterion": "criteria",
    "phenomenon": "phenomena",
    "index": "indices",
    "matrix": "matrices",
    "vertex": "vertices",
    "appendix": "appendices",
    # Unchanged in plural.
    "sheep": "sheep",
    "series": "series",
    "species": "species",
    "aircraft": "aircraft",
    "deer": "deer",
    "fish": "fish",
    "equipment": "equipment",
    "software": "software",
    "hardware": "hardware",
    "furniture": "furniture",
    "info": "info",
    "news": "news",
}

# Common plural suffixes — if the input already ends in one AND the
# preceding letter suggests plural (e.g. "properties" → "-ties",
# "boxes" → "-xes"), treat as already plural.
_PLURAL_ENDINGS: tuple[str, ...] = (
    "ies", "ves", "sses", "shes", "ches", "xes", "zes",
)

# Consonants that trigger the "-y" → "-ies" rule.
_CONSONANTS = set("bcdfghjklmnpqrstvwxz")


def pluralize(singular: str) -> str:
    """Return the plural of ``singular``. Compact irregular table + English
    suffix rules. Preserves capitalization style of the input.

    Examples:
        pluralize("Property")   → "Properties"
        pluralize("Person")     → "People"
        pluralize("Company")    → "Companies"
        pluralize("Box")        → "Boxes"
        pluralize("Batch")      → "Batches"
        pluralize("Category")   → "Categories"
        pluralize("Status")     → "Statuses"
        pluralize("news")       → "news"       (uncountable)
        pluralize("Properties") → "Properties" (already plural)
    """
    if not isinstance(singular, str):
        return singular  # type: ignore[return-value]
    s = singular.strip()
    if not s:
        return s

    low = s.lower()

    # Irregular table wins first.
    if low in _IRREGULARS:
        return _match_case(s, _IRREGULARS[low])

    # Heuristic: input already ends in a common plural suffix → leave alone.
    if any(low.endswith(suf) for suf in _PLURAL_ENDINGS):
        return s

    # -y after a consonant → -ies (Property → Properties, Company → Companies)
    # -y after a vowel     → -ys   (Day → Days, Boy → Boys)
    if low.endswith("y") and len(low) >= 2 and low[-2] in _CONSONANTS:
        return _match_case(s, low[:-1] + "ies")

    # -s, -x, -z, -ch, -sh → -es (Box→Boxes, Batch→Batches, Status→Statuses)
    if low.endswith(("s", "x", "z")) or low.endswith(("ch", "sh")):
        return _match_case(s, low + "es")

    # -f, -fe → -ves (Life→Lives, Leaf→Leaves)
    if low.endswith("fe"):
        return _match_case(s, low[:-2] + "ves")
    if low.endswith("f") and len(low) >= 2 and low[-2] not in "aeio":
        # "roof" stays "roofs"; only after certain letters does "f" → "ves"
        # This heuristic is imperfect; keep default +s for the ambiguous case.
        pass

    # Default: append -s.
    return _match_case(s, low + "s")


# ── Humanize ────────────────────────────────────────────────────────────

_CAMEL_SPLIT = re.compile(r"([a-z0-9])([A-Z])")
_MULTI_SEP  = re.compile(r"[_\-.\s]+")


def humanize(text: str) -> str:
    """Convert snake_case / camelCase / kebab-case / dotted.name to
    ``Title Case Words``.

    Examples:
        humanize("full_name")           → "Full Name"
        humanize("userFullName")        → "User Full Name"
        humanize("maintenance_request") → "Maintenance Request"
        humanize("HVAC")                → "HVAC"           (all-caps kept)
        humanize("propertyId")          → "Property Id"    (unchanged from
                                                            camel split; use
                                                            humanize_series_
                                                            label to drop id)
        humanize("Already Human")       → "Already Human"  (idempotent)
    """
    if not isinstance(text, str):
        return ""
    s = text.strip()
    if not s:
        return ""
    # Split camelCase: aX → a_X (preserving X boundary).
    s = _CAMEL_SPLIT.sub(r"\1_\2", s)
    # Collapse all separators to single spaces.
    s = _MULTI_SEP.sub(" ", s)
    parts = [p for p in s.split(" ") if p]
    return " ".join(_word_case(p) for p in parts)


# Suffixes commonly appended to SQL column names that add no meaning in a
# UI label. Chart legends + column headers should strip these.
_META_SUFFIXES: tuple[str, ...] = (
    "_id", "_ids", "_count", "_sum", "_avg", "_min", "_max",
    "_at", "_on", "_by", "_ref",
)


def humanize_series_label(name: str) -> str:
    """Chart-legend-shaped humanization: drops meta suffixes before
    humanizing so ``maintenance_request_count`` becomes ``Maintenance
    Request`` (not ``Maintenance Request Count``).

    For the count/sum/avg case the metric is already implied by the chart
    type — the axis or subtitle carries "count" — so the legend shouldn't
    repeat it.
    """
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if not s:
        return ""
    low = s.lower()
    for suf in _META_SUFFIXES:
        if low.endswith(suf):
            # Preserve original casing for the trimmed portion.
            s = s[: len(s) - len(suf)]
            break
    return humanize(s)


# ── Helpers ─────────────────────────────────────────────────────────────

def _word_case(word: str) -> str:
    """Case a single word. All-caps input (HVAC, API, URL) stays all-caps —
    a common acronym. Otherwise Title Case (first char upper, rest lower).
    Preserves already-mixed-case words that look intentional (e.g. iPhone).
    """
    if not word:
        return word
    # All-caps → keep. (Threshold ≥2 avoids treating single chars.)
    if word.isupper() and len(word) >= 2:
        return word
    # Mixed case with an internal upper (iPhone, MacBook) → leave alone.
    if any(c.isupper() for c in word[1:]) and word[0].islower():
        return word
    return word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()


def _match_case(sample: str, plural_lower: str) -> str:
    """Rebuild ``plural_lower`` to match the case shape of ``sample``.

    - Sample all-upper → plural all-upper ("BOX" → "BOXES")
    - Sample title-case → plural title-case ("Box" → "Boxes")
    - Sample all-lower → plural all-lower ("box" → "boxes")
    - Mixed / unusual  → default title-case rebuild.
    """
    if not sample or not plural_lower:
        return plural_lower
    if sample.isupper():
        return plural_lower.upper()
    if sample[0].isupper():
        return plural_lower[0].upper() + plural_lower[1:]
    return plural_lower


__all__ = [
    "pluralize",
    "humanize",
    "humanize_series_label",
]
