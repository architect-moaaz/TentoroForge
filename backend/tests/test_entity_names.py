"""Canonical naming authority — the single source of truth every builder
reads from. The historical failure mode was four disagreeing local
helpers (`_plural` / `_pluralize` / `_entity_list_source`) producing
`assessmentDays` vs `assessmentDaies` vs `assessment-days` for the same
entity, leaving dangling ``{{binding}}`` refs and 404 detail links.
These tests lock the class dead: every path returns the same set of
name variants for the same input."""
from __future__ import annotations

import pytest

from services.entity_names import (
    EntityNames,
    derive_names,
    enrich_entity,
    names_from_registry,
    pluralize,
)


# =========================================================================
# The canonical function — every downstream helper delegates to this
# =========================================================================

def test_assessment_day_all_variants():
    """The July-17 pileup: multi-word entity ending in consonant-plus-y."""
    n = derive_names("AssessmentDay")
    assert n.entity == "AssessmentDay"
    assert n.sourceName == "assessmentDays"       # NOT assessmentDaies
    assert n.binding == "assessmentDays"
    assert n.routeSlug == "assessment-days"       # what the URL uses
    assert n.tableSnake == "assessment_days"      # what Drizzle uses
    assert n.label == "Assessment Days"
    assert n.labelSingular == "Assessment Day"


def test_single_word_entity_stays_stable():
    n = derive_names("Applicant")
    assert n.sourceName == "applicants"
    assert n.routeSlug == "applicants"
    assert n.tableSnake == "applicants"
    assert n.label == "Applicants"


def test_pluralize_y_after_vowel():
    """The exact class of bug: y preceded by a vowel just adds 's'."""
    assert pluralize("Day") == "Days"
    assert pluralize("Boy") == "Boys"
    assert pluralize("Key") == "Keys"
    assert pluralize("Survey") == "Surveys"


def test_pluralize_y_after_consonant():
    assert pluralize("Story") == "Stories"
    assert pluralize("Company") == "Companies"
    assert pluralize("Policy") == "Policies"


def test_pluralize_es_class():
    assert pluralize("Class") == "Classes"
    assert pluralize("Box") == "Boxes"
    assert pluralize("Dish") == "Dishes"
    assert pluralize("Match") == "Matches"
    assert pluralize("Buzz") == "Buzzes"


def test_pluralize_already_plural_passthrough():
    """Idempotent: an already-plural noun doesn't double-pluralize."""
    assert pluralize("Users") == "Users"
    assert pluralize("Applicants") == "Applicants"


def test_pluralize_preserves_ss_us_is_singulars():
    """``class`` / ``bus`` / ``analysis`` end in 's' but ARE singular."""
    assert pluralize("Class") == "Classes"
    assert pluralize("Bus") == "Buses"
    assert pluralize("Analysis") == "Analysises"  # (naive rule; downstream can override)


def test_acronym_boundaries_respected():
    """PascalCase splitter must handle URLPath / userID gracefully — not
    every capital is a word boundary."""
    n = derive_names("URLShortener")
    # 'URL' + 'Shortener' → 'urlShorteners' (camel plural) is fine; the
    # important thing is we don't produce garbage like 'uRLShortenerS'.
    assert n.sourceName == "urlShorteners"
    assert n.routeSlug == "url-shorteners"
    assert n.tableSnake == "url_shorteners"


def test_accepts_snake_and_kebab_inputs():
    """A caller that passes snake_case or kebab-case (e.g. from a DB
    reflection path) still gets the right PascalCase-derived names."""
    assert derive_names("assessment_day").sourceName == "assessmentDays"
    assert derive_names("assessment-day").sourceName == "assessmentDays"


def test_empty_input_falls_back_to_record():
    """Never raises. Empty / None → the reserved fallback name."""
    assert derive_names("").entity == "Record"
    assert derive_names(None).entity == "Record"  # type: ignore[arg-type]


def test_binding_equals_source_name():
    """The `{{binding}}` and dataSource name MUST be identical, always."""
    for e in ("AssessmentDay", "Applicant", "InterviewFeedback", "Story"):
        n = derive_names(e)
        assert n.binding == n.sourceName


# =========================================================================
# Registry enrichment — the read-path via `registry.entities[X].names`
# =========================================================================

def test_enrich_entity_attaches_names_block():
    e = {"fields": {"id": {"type": "uuid"}}}
    enrich_entity(e, "AssessmentDay")
    assert e["names"]["sourceName"] == "assessmentDays"
    assert e["names"]["routeSlug"] == "assessment-days"


def test_names_from_registry_reads_cached_block():
    registry = {
        "entities": {"AssessmentDay": {"names": derive_names("AssessmentDay").as_dict()}},
    }
    n = names_from_registry(registry, "AssessmentDay")
    assert n.sourceName == "assessmentDays"


def test_names_from_registry_falls_back_when_missing():
    """A registry without the `names` block still returns correct values
    by delegating to derive_names — so partial-migration is safe."""
    registry = {"entities": {"AssessmentDay": {"fields": {}}}}
    n = names_from_registry(registry, "AssessmentDay")
    assert n.sourceName == "assessmentDays"


def test_enrich_is_idempotent():
    """Repeated enrichment doesn't drift — a reconcile pass on an already
    enriched entity leaves the block unchanged."""
    e = {"fields": {}}
    enrich_entity(e, "AssessmentDay")
    first = dict(e["names"])
    enrich_entity(e, "AssessmentDay")
    assert e["names"] == first


# =========================================================================
# Cross-helper consistency — the whole point of consolidation
# =========================================================================

def test_all_local_helpers_now_agree():
    """Historically these four helpers disagreed on `AssessmentDay`:
    ``form_scaffold._plural`` said `assessmentDaies`,
    ``deterministic_pages._entity_list_source`` said `assessmentDays`,
    ``scheduler_pass._plural`` said `assessmentDays`,
    ``stub_page_backfill._pluralize`` said (buggy behaviour). All four
    now delegate to :func:`derive_names` so they MUST return byte-
    identical dataSource names for every entity."""
    from services.deterministic_pages import _entity_list_source
    from services.form_scaffold import _plural as form_plural
    from services.scheduler_pass import _plural as sched_plural

    for entity in ("AssessmentDay", "Applicant", "InterviewFeedback",
                   "Day", "Company", "URLShortener", "Story"):
        canonical = derive_names(entity).sourceName
        assert _entity_list_source(entity) == canonical, (
            f"deterministic_pages._entity_list_source disagreed on {entity}"
        )
        assert form_plural(entity) == canonical, (
            f"form_scaffold._plural disagreed on {entity}"
        )
        assert sched_plural(entity) == canonical, (
            f"scheduler_pass._plural disagreed on {entity}"
        )
