"""Single naming authority for entities.

For every entity, ``derive_names`` returns a frozen tuple of ALL the name
variants downstream code needs — kebab route slug, camelCase list
dataSource, `{{binding}}` name, human labels. Every pluralization,
kebab-case-ification, and capitalization decision lives here, computed
ONCE per entity, referenced everywhere.

The historical failure mode is 4+ local helpers (``form_scaffold._plural``,
``deterministic_pages._entity_list_source``, ``scheduler_pass._plural``,
``stub_page_backfill._pluralize``) that each re-derived variants from the
raw PascalCase name and disagreed — one produced ``assessmentDaies``,
another ``assessmentDays``, a third ``assessment-days``. The result was
dangling ``{{binding}}`` references, 404ing detail links, and empty
tables. This module ends that class by being the single source of truth.

Read pattern
------------
Downstream code should either:

* Look up the entity in ``registry.entities[name]["names"]`` — enriched
  by :func:`enrich_entity_names` (re-exported as
  ``services.registry.enrich_entity_names``) at registry-build
  time — and use ``names.sourceName`` / ``names.routeSlug`` verbatim, OR
* Call ``derive_names(entity_name)`` directly when no registry is at
  hand (unit tests, template generators). The two paths return
  byte-identical results.

NEVER re-derive a name variant locally. If the variant you need is not
on :class:`EntityNames`, ADD IT HERE. Five modules ignored that rule and
grew private pluralizers that disagreed with this one on 4–17 of every
20 entity names; the fallout was findings CRUD-1, STATUS-3, BA-5 and
TG-2 in the bug register. Those helpers are gone — do not reintroduce
the shape.

Failure policy
--------------
This module RAISES :class:`EntityNameError` on input it cannot name.
It used to substitute ``'record'`` for unusable input and return
successfully, which meant a planner that emitted a nameless entity
silently generated CRUD against a ``records`` table nobody declared.
An entity with no name is a pipeline bug and must stop the run.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

_log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class EntityNameError(ValueError):
    """Raised when an entity name cannot be turned into name variants.

    Carries the offending value so the log names the actual input rather
    than the symptom two stages downstream."""

    def __init__(self, value: object, reason: str) -> None:
        self.value = value
        self.reason = reason
        super().__init__(f"cannot derive entity names from {value!r}: {reason}")


# --------------------------------------------------------------------------- #
# Public type
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class EntityNames:
    """Every name variant an entity needs. Every field is derived
    deterministically from the entity's PascalCase name — no external
    input, no environment, no I/O — so two callers on the same name
    ALWAYS get the same values."""

    entity: str          # PascalCase — 'AssessmentDay'
    tableSnake: str      # snake_case DB table — 'assessment_days'
    routeSlug: str       # kebab-case URL slug — 'assessment-days'
    sourceName: str      # camelCase dataSource / binding variable — 'assessmentDays'
    binding: str         # what goes inside {{...}} — same as sourceName
    label: str           # human plural label — 'Assessment Days'
    labelSingular: str   # human singular label — 'Assessment Day'
    pluralSlug: str      # separator-free lowercase plural — 'assessmentdays'
    entityKey: str       # separator-free lowercase SINGULAR join key — 'assessmentday'

    def as_dict(self) -> dict[str, str]:
        return {
            "entity":        self.entity,
            "tableSnake":    self.tableSnake,
            "routeSlug":     self.routeSlug,
            "sourceName":    self.sourceName,
            "binding":       self.binding,
            "label":         self.label,
            "labelSingular": self.labelSingular,
            "pluralSlug":    self.pluralSlug,
            "entityKey":     self.entityKey,
        }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def derive_names(entity: str) -> EntityNames:
    """Compute every name variant for ``entity``. See :class:`EntityNames`.

    ``entity`` is a PascalCase model name (``'AssessmentDay'``,
    ``'RecruitmentDrive'``, ``'User'``).

    Raises :class:`EntityNameError` when ``entity`` is not a string, is
    blank, or contains no alphanumeric characters to name. Callers that
    can legitimately continue without a name must catch it explicitly —
    see :func:`try_derive_names`. There is deliberately no silent
    default: substituting one used to turn a nameless planner entity
    into CRUD against a phantom ``records`` table."""
    src = _normalize_entity_name(entity)
    if not src:
        if not isinstance(entity, str):
            raise EntityNameError(entity, f"expected str, got {type(entity).__name__}")
        raise EntityNameError(entity, "blank after normalization")

    words = _split_pascal_case(src)          # ['Assessment', 'Day']
    if not words:
        raise EntityNameError(entity, "no alphanumeric word to name")
    singular_low = "".join(w.lower() for w in words)                  # 'assessmentday'
    # Plural: apply the English y→ies rule ONLY when preceded by a consonant.
    plural_words = words[:-1] + [_pluralize_word(words[-1])]          # ['Assessment', 'Days']
    plural_pascal = "".join(plural_words)                              # 'AssessmentDays'

    # camelCase: lowercase the FIRST word entirely (handles leading
    # acronyms so 'URLShortener' → 'urlShorteners', not 'uRLShorteners').
    first_word_lower = plural_words[0].lower()
    source_name = first_word_lower + "".join(plural_words[1:])         # 'assessmentDays'
    route_slug = "-".join(w.lower() for w in plural_words)             # 'assessment-days'
    table_snake = "_".join(w.lower() for w in plural_words)            # 'assessment_days'
    label = " ".join(plural_words)                                     # 'Assessment Days'
    label_singular = " ".join(words)                                   # 'Assessment Day'

    return EntityNames(
        entity=src,
        tableSnake=table_snake,
        routeSlug=route_slug,
        sourceName=source_name,
        binding=source_name,
        label=label,
        labelSingular=label_singular,
        pluralSlug="".join(w.lower() for w in plural_words),           # 'assessmentdays'
        entityKey=singular_low,                                        # 'assessmentday'
    )


def try_derive_names(entity: str) -> EntityNames | None:
    """:func:`derive_names`, or ``None`` when the name is underivable.

    The ONLY sanctioned way to tolerate a bad entity name. Use it where
    skipping one entity is genuinely correct (e.g. iterating a registry
    that may carry a malformed record) — and log the skip. Anywhere the
    name is required for correctness, call :func:`derive_names` and let
    :class:`EntityNameError` stop the run."""
    try:
        return derive_names(entity)
    except EntityNameError:
        return None


def entity_key(value: object) -> str:
    """Canonical SINGULAR join key for an entity name *or* a table name.

    ``'Appointment'``, ``'appointments'`` and ``'appointment'`` all
    collapse to ``'appointment'``; crucially so do the irregular pairs
    that a naive "drop one trailing s" breaks — ``'Category'`` and
    ``'categories'`` both give ``'category'``, ``'Address'`` and
    ``'addresses'`` both give ``'address'``, ``'Status'`` and
    ``'statuses'`` both give ``'status'``.

    This is the key to use whenever entity-side and table-side names
    have to be matched. Getting it wrong silently drops the join, which
    is what made status workflows unreachable for every irregular plural
    (register findings STATUS-3 and BA-5).

    Raises :class:`EntityNameError` on input with nothing to key on —
    a lookup keyed on ``''`` matches the wrong thing rather than
    nothing, so it must not be reachable."""
    if not isinstance(value, str):
        raise EntityNameError(value, f"expected str, got {type(value).__name__}")
    flat = re.sub(r"[^a-z0-9]", "", value.lower())
    if not flat:
        raise EntityNameError(value, "no alphanumeric characters to key on")
    return singularize(flat)


def pluralize(word: str) -> str:
    """Single-word English pluralizer. Used by the derivation above and
    kept public so legacy call-sites can migrate incrementally. Applies:

    * ``day`` → ``days`` (vowel-y stays), ``story`` → ``stories``.
    * ``class`` → ``classes``, ``dish`` → ``dishes``, ``box`` → ``boxes``.
    * default → adds ``'s'``.

    Already-plural inputs pass through unchanged.
    """
    return _pluralize_word(word or "")


def singularize(word: str) -> str:
    """Exact inverse of :func:`pluralize` for the rules it applies.

    * ``stories`` → ``story``, ``categories`` → ``category``
    * ``addresses`` → ``address``, ``boxes`` → ``box``, ``classes`` → ``class``
    * ``days`` → ``day``, ``bookings`` → ``booking``
    * already-singular inputs pass through (``status``, ``class``, ``analysis``)

    The round-trip ``singularize(pluralize(w)) == singularize(w)`` holds
    for every word this module can produce, which is what lets
    :func:`entity_key` join an entity to its table without either side
    knowing how the other was spelled."""
    return _singularize_word(word or "")


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

_VOWELS = set("aeiouAEIOU")

# Every field on EntityNames, in declaration order. Used to rebuild an
# instance from a cached registry block; a block missing any of these is
# treated as stale and recomputed.
_NAME_FIELDS: tuple[str, ...] = (
    "entity", "tableSnake", "routeSlug", "sourceName",
    "binding", "label", "labelSingular", "pluralSlug", "entityKey",
)

# Match runs of upper→lower or all-lower to segment PascalCase.
# ``AssessmentDay`` → ['Assessment', 'Day']
# ``URLPath`` → ['URL', 'Path']  (acronym-aware)
# ``userID`` → ['user', 'ID']
_PASCAL_SPLIT_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z])"   # acronym boundary: URLPath → URL | Path
    r"|[A-Z]?[a-z]+"          # normal word: Assessment / assessment / Day
    r"|[A-Z]+"                # trailing acronym: someID → some | ID
    r"|\d+"                   # numbers: v1 → v | 1
)


def _normalize_entity_name(entity: str) -> str:
    if not isinstance(entity, str):
        return ""
    s = entity.strip()
    if not s:
        return ""
    # Accept snake_case and kebab-case inputs by capitalizing each word.
    if "_" in s or "-" in s:
        parts = re.split(r"[_\-]+", s)
        return "".join(p[:1].upper() + p[1:] for p in parts if p)
    # camelCase / lowercase → uppercase first letter.
    return s[:1].upper() + s[1:]


def _split_pascal_case(name: str) -> list[str]:
    words = _PASCAL_SPLIT_RE.findall(name)
    return [w for w in words if w]


def _pluralize_word(word: str) -> str:
    """Correct English pluralization for a single word.

    The ``y → ies`` rule ONLY applies when the y is preceded by a
    CONSONANT. ``story → stories`` ✓, but ``day → days`` (not
    ``daies``), ``boy → boys``, ``key → keys``. Missing this vowel
    guard is the exact bug that produced ``assessmentDaies`` from
    ``AssessmentDay`` and broke every downstream binding to it.
    """
    if not word:
        return word
    lower = word.lower()

    # Already plural — pass through to avoid double-pluralizing.
    # Heuristic: ends in 's' and not one of the tricky classes ('class',
    # 'bus') where the singular happens to end in 's'.
    if lower.endswith("s") and not lower.endswith(("ss", "us", "is")):
        return word

    if lower.endswith("y") and len(lower) >= 2 and lower[-2] not in _VOWELS:
        return word[:-1] + "ies"
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


# Stems that legitimately end in these — 'status', 'class', 'analysis' are
# SINGULAR despite the trailing 's', so they must never be stripped.
_SINGULAR_S_ENDINGS = ("ss", "us", "is")

# Stems that genuinely take '-es' in the plural, so 'X' + 'es' is the right
# parse for a word ending in '-ses'. Everything else ending in '-ses' is
# read as a regular '+s' on an '-e'-final stem ('warehouse' → 'warehouses').
# Matched with str.endswith so compounds work: 'orderstatuses' → 'orderstatus'.
_LATINATE_S_STEMS = (
    "bus", "status", "campus", "focus", "virus", "census", "bonus",
    "radius", "corpus", "genus", "lens", "gas", "atlas", "bias", "canvas",
)


def _singularize_word(word: str) -> str:
    """Inverse of :func:`_pluralize_word`. See :func:`singularize`.

    Order matters: ``ies`` before ``es`` before ``s``, and each rule
    checks the STEM it would leave behind so ``addresses`` unwinds to
    ``address`` (stem ends ``ss`` → the ``es`` was added) while
    ``analysis`` is left alone (nothing was added)."""
    if not word:
        return word
    lower = word.lower()

    if not lower.endswith("s") or lower.endswith(_SINGULAR_S_ENDINGS):
        return word            # already singular — 'day', 'status', 'class'

    # 'categories' → 'category'  (the y→ies rule run backwards)
    if lower.endswith("ies") and len(lower) > 4:
        return word[:-3] + "y"

    # 'addresses'/'boxes'/'classes'/'dishes' → the s/x/z/ch/sh stem.
    #
    # A word ending in 'ses' is genuinely ambiguous: 'buses' is 'bus' + es,
    # but 'warehouses' is 'warehouse' + s. Both parses are structurally
    # identical and both round-trip through the pluralizer, so no rule over
    # the letters alone can separate them.
    #
    # The old test — `stem.endswith("s")` — always chose the +es parse, so
    # 'warehouses' unwound to 'warehous' and the entity `Warehouse` could
    # never be matched to the table `warehouses`. That was 11 of the 39
    # quarantined bindings on pkiuqdrq.
    #
    # Regular English is the default (+s, so the stem keeps its 'e'), and
    # the handful of latinate stems that really do take '-es' are named.
    # Matched with endswith so compounds work: 'orderstatuses' → 'orderstatus'.
    if lower.endswith("es"):
        stem = lower[:-2]
        if stem.endswith(("ss", "x", "z", "ch", "sh")) or stem.endswith(_LATINATE_S_STEMS):
            return word[:-2]

    # 'bookings' → 'booking'
    return word[:-1]


# --------------------------------------------------------------------------- #
# Registry lookup — the preferred read path when a registry is available
# --------------------------------------------------------------------------- #

def names_from_registry(registry: dict | None, entity: str) -> EntityNames:
    """Read the canonical names for ``entity`` from ``registry`` if it
    carries them (populated by :func:`enrich_entity_names`
    at build time). Falls back to :func:`derive_names` when the registry
    is missing / stale / doesn't carry the enriched block."""
    if isinstance(registry, dict):
        ents = registry.get("entities")
        if isinstance(ents, dict):
            e = ents.get(entity)
            if isinstance(e, dict):
                cached = e.get("names")
                if isinstance(cached, dict) and cached.get("sourceName"):
                    try:
                        return EntityNames(**{f: cached[f] for f in _NAME_FIELDS})
                    except (KeyError, TypeError):
                        # A block written before a field was added, or one
                        # hand-edited into a bad shape. Recompute rather than
                        # crash — derive_names is deterministic, so a fresh
                        # derivation is byte-identical to a complete cache.
                        # Catching TypeError matters: registries persisted by
                        # an older build legitimately lack newer fields, and
                        # every caller of this function would otherwise fail
                        # on a registry that is merely older, not wrong.
                        _log.debug(
                            "names_from_registry: stale/incomplete names block for "
                            "%r — recomputing", entity,
                        )
    return derive_names(entity)


def enrich_entity_names(registry: dict) -> dict:
    """Attach the canonical ``names`` block to EVERY entity in ``registry``.

    This is the integration path this module's own docstring has always
    described — and it did not exist (register EN-1). Callers reading the docs
    reached for ``services.registry.enrich_entity_names``, found nothing, and
    either hand-rolled the loop or skipped enrichment entirely, which is how
    the pipeline ended up with registries whose entities had no ``names`` block
    for downstream builders to read.

    Idempotent and safe to call repeatedly: derivation is deterministic, so
    re-enrichment is a no-op. One unnameable entity does not stop the others —
    it is marked ``namesError`` and logged, per :func:`enrich_entity`. Returns
    the same registry for chaining.
    """
    if not isinstance(registry, dict):
        return registry
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return registry
    for name, info in entities.items():
        enrich_entity(info, name)
    return registry


def enrich_entity(entity_dict: dict, entity_name: str) -> dict:
    """Attach the ``names`` block to a registry entity record in place.
    Safe to call repeatedly — the block is fully deterministic so
    re-enrichment is a no-op. Returns the same dict for chaining.

    Deliberately does NOT propagate :class:`EntityNameError`. This runs in
    a loop over every entity in the registry, and one unnameable entity
    must not destroy the naming of all the others — that is the failure
    shape of register finding CRUD-2. Instead the entity is left without
    a ``names`` block, marked with ``namesError``, and logged at ERROR.
    Downstream builders that require ``names`` will fail on that one
    entity, loudly, with the cause already recorded here."""
    if not isinstance(entity_dict, dict):
        _log.error(
            "enrich_entity: expected a dict for entity %r, got %s — no name "
            "variants attached", entity_name, type(entity_dict).__name__,
        )
        return entity_dict
    try:
        entity_dict["names"] = derive_names(entity_name).as_dict()
        entity_dict.pop("namesError", None)
    except EntityNameError as e:
        entity_dict["namesError"] = str(e)
        _log.error(
            "enrich_entity: %s — this entity has NO canonical names, so every "
            "builder that needs its table/slug/binding will fail on it. The "
            "other entities are unaffected.", e,
        )
    return entity_dict
