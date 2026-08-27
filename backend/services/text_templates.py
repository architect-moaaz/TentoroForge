"""Deterministic string synthesis for mechanical UI text.

Root cause this addresses: the LLM is asked to author hundreds of JSON schema
nodes per generation. Every text node (empty-state message, column header,
button label, section title) is a mini-inline-generation that gets fractional
attention. Even at ~0.5% per-string error rate, a 500-string schema ships
2-3 typos. The failure mode we saw in B-021.2 was "No plant batchs yet." —
LLM concatenated "batch"+"s" instead of using the correct "-es" plural.

Fix: strings that don't require domain judgement are NOT authored by the LLM.
They are computed deterministically from the entity name at build time.

Categories this module owns:
  * Plurals of entity labels (with correct English -ch/-sh/-x/-s/-y/-f rules)
  * Empty-state text for list/dashboard sections
  * Column headers from field names
  * Standard button labels (Create/Edit/Delete/Cancel/Save)
  * Standard section titles for known archetypes

The LLM is told (via the planner + schema prompts) NOT to author these; if
one leaks through, a post-gen backstop (see text_template_backstop.py)
overwrites it with the deterministic value.
"""

from __future__ import annotations

import re
from typing import Iterable

# ---------------------------------------------------------------------------
# Pluralization                                                              #
# ---------------------------------------------------------------------------

# Irregular plurals — hand-curated, only for words a generated app is likely
# to hit as an entity name. Keep the list SHORT; anything not here falls
# through to the rules below.
_IRREGULAR_PLURALS: dict[str, str] = {
    "child": "children",
    "person": "people",
    "man": "men",
    "woman": "women",
    "foot": "feet",
    "tooth": "teeth",
    "goose": "geese",
    "mouse": "mice",
    "louse": "lice",
    "ox": "oxen",
    # Zero-plurals (same word).
    "deer": "deer",
    "sheep": "sheep",
    "fish": "fish",
    "series": "series",
    "species": "species",
    "aircraft": "aircraft",
    "moose": "moose",
    "salmon": "salmon",
    "trout": "trout",
    "data": "data",
    "media": "media",
    "software": "software",
    "hardware": "hardware",
    "equipment": "equipment",
    "information": "information",
    "traffic": "traffic",
    # Non-English but common in enterprise domains.
    "criterion": "criteria",
    "phenomenon": "phenomena",
    "analysis": "analyses",
    "diagnosis": "diagnoses",
    "hypothesis": "hypotheses",
    "thesis": "theses",
    "crisis": "crises",
    "axis": "axes",
    "matrix": "matrices",
    "index": "indices",
    "vertex": "vertices",
    "appendix": "appendices",
    "curriculum": "curricula",
    "datum": "data",
    "medium": "media",
}

# Suffixes that always take -es (sibilant endings).
_SIBILANT_SUFFIXES = ("s", "ss", "sh", "ch", "x", "z")

# Consonants — used for the y→ies rule.
_CONSONANTS = "bcdfghjklmnpqrstvwxz"


def pluralize(word: str) -> str:
    """Return the English plural of ``word``.

    Preserves the original casing of the first letter (Product → Products,
    child → children, Person → People). Handles the endings that trip up LLM
    concatenation:

      * `-ch / -sh / -x / -s / -ss / -z` → append ``es``  (batch → batches)
      * consonant + `-y`                 → replace ``y`` with ``ies``  (city → cities)
      * `-fe`                            → replace with ``ves``  (knife → knives)
      * plain `-f`                       → replace with ``ves`` for a small
                                           irregular set (leaf → leaves),
                                           else append ``s``
      * everything else                  → append ``s``
    """
    if not word:
        return word
    lc = word.lower()

    # Irregular table wins.
    if lc in _IRREGULAR_PLURALS:
        return _match_case(word, _IRREGULAR_PLURALS[lc])

    # -f / -fe → -ves for the common English irregulars.
    _FE_TO_VES = {"knife", "life", "wife", "shelf", "leaf", "loaf", "wolf",
                  "self", "half", "calf", "thief", "elf"}
    if lc in _FE_TO_VES:
        stem = word[:-2] if lc.endswith("fe") else word[:-1]
        return stem + "ves"

    # -y after a consonant → -ies (city → cities, but NOT boy → boyies).
    if lc.endswith("y") and len(word) >= 2 and word[-2].lower() in _CONSONANTS:
        return word[:-1] + "ies"

    # -ch / -sh / -x / -s / -ss / -z → -es (batch → batches).
    for suf in _SIBILANT_SUFFIXES:
        if lc.endswith(suf):
            return word + "es"

    # Default: append -s (Plant → Plants).
    return word + "s"


def _match_case(source: str, produced: str) -> str:
    """Copy the first-letter case of ``source`` onto ``produced``."""
    if not produced:
        return produced
    if source[:1].isupper():
        return produced[:1].upper() + produced[1:]
    return produced


# ---------------------------------------------------------------------------
# Humanization (field/entity → display label)                                #
# ---------------------------------------------------------------------------

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_ACRONYMS_UPPER = {"id", "url", "uri", "sku", "api", "ui", "css", "html",
                   "sql", "usd", "eur", "gbp", "utc", "gps", "vip"}


def humanize(word: str) -> str:
    """Convert a snake_case / camelCase identifier into a title-cased display
    label. `photoUrl` → `Photo URL`, `nursery_location_id` → `Nursery Location`.

    Trailing `_id` / `Id` is dropped since it's a machine artifact, not user-
    facing content (the FK label typically shows the target entity's label).
    """
    if not word:
        return word
    # snake_case → words.
    s = word.replace("_", " ").replace("-", " ")
    # camelCase → words at boundaries.
    s = _CAMEL_BOUNDARY.sub(" ", s)
    # Strip machine-artefact trailing "Id" / " id".
    s = re.sub(r"\s+id$", "", s, flags=re.IGNORECASE).strip()

    def _capitalise(w: str) -> str:
        if w.lower() in _ACRONYMS_UPPER:
            return w.upper()
        return w[:1].upper() + w[1:].lower()

    return " ".join(_capitalise(w) for w in s.split() if w)


# ---------------------------------------------------------------------------
# Public string factories                                                    #
# ---------------------------------------------------------------------------

def entity_label(entity_name: str) -> str:
    """Human-readable singular label. `PlantBatch` → `Plant Batch`."""
    return humanize(entity_name)


def entity_label_plural(entity_name: str) -> str:
    """Human-readable plural label. `PlantBatch` → `Plant Batches`."""
    singular = entity_label(entity_name)
    # Pluralize the LAST token so `Plant Batch` → `Plant Batches`, not
    # `Plants Batches`.
    parts = singular.split(" ")
    parts[-1] = pluralize(parts[-1])
    return " ".join(parts)


def empty_state_text(entity_name: str,
                     *, filter_note: str | None = None) -> str:
    """Standard "No X yet." string. Optional filter note (e.g. "matching
    your search") gets appended without changing the pluralization."""
    plural_lc = entity_label_plural(entity_name).lower()
    if filter_note:
        return f"No {plural_lc} {filter_note.strip()}."
    return f"No {plural_lc} yet."


def column_header(field_name: str) -> str:
    """Column-header label from a field name. `photoUrl` → `Photo URL`."""
    return humanize(field_name)


# Standard CRUD button labels — never LLM-authored.
def button_create(entity_name: str) -> str:
    return f"Create {entity_label(entity_name)}"


def button_edit(entity_name: str) -> str:
    return f"Edit {entity_label(entity_name)}"


def button_delete(entity_name: str) -> str:
    return f"Delete {entity_label(entity_name)}"


def button_save() -> str:
    return "Save changes"


def button_cancel() -> str:
    return "Cancel"


def button_open() -> str:
    return "Open"


# Standard section titles for known archetypes — deterministic so no
# "Overviw" typo can ever land.
_SECTION_TITLES = {
    "overview":     "Overview",
    "recent":       "Recent activity",
    "stats":        "Statistics",
    "details":      "Details",
    "history":      "History",
    "settings":     "Settings",
    "team":         "Team",
    "members":      "Members",
}

def section_title(kind: str) -> str | None:
    return _SECTION_TITLES.get(kind.lower().strip()) if kind else None


# ---------------------------------------------------------------------------
# Detection: is this string one the LLM should NOT have authored?           #
# ---------------------------------------------------------------------------

# Regexes that a backstop can use to identify LLM-generated strings that
# should be replaced with the deterministic version.
_MECHANICAL_STRING_KEYS: frozenset[str] = frozenset({
    "emptyStateText", "emptyState", "empty_state", "empty_state_text",
    "placeholderText", "placeholder_text",
})

def is_mechanical_key(key: str) -> bool:
    """True if a schema-node prop with this key should be treated as
    machine-authored (deterministic string), not LLM-authored."""
    return key in _MECHANICAL_STRING_KEYS
