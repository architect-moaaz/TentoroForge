"""The catalog and the vocabulary registry must agree.

The bug this exists to make impossible: two keyword tables, both named
``_ARCHETYPE_KEYWORDS``, one read by the prompt detector and one by the
candidate ranker. ``legislative-platform`` was added to the first only.
The detector named the domain, ``load_vocabulary`` resolved it, every
test passed — and the ranker, which is what actually decides which
vocabulary shapes the app, could not see it. A legislative council app
was matched to ``analytics-dashboard-platform``, whose dashboard recipe
names ``report_runs`` and ``datasets``; all six of its KPIs were dropped
on entity mismatch and the dashboard fell back to a generic bootstrap.

Nothing raised. So these assert the agreement directly.
"""
from __future__ import annotations

import pytest

from services.archetype_keywords import (
    ARCHETYPES, known_keyword_archetypes, plan_token_table,
    prompt_phrase_table,
)
from services.archetype_vocabulary import known_archetypes, load_vocabulary
from services.plan_directive_parser import detect_vocab_archetype
from services.product_brief import _ARCHETYPE_KEYWORDS as PLAN_TABLE
from services.vocab_ranker import rank_vocabs_by_keyword_hits


# ── the drift the catalog exists to prevent ────────────────────────

def test_every_registered_vocabulary_is_reachable_by_keyword():
    """The exact failure: a vocabulary on disk that no matcher can name.

    A vocabulary absent from this catalog is dead weight — it can never
    be detected from a prompt nor ranked into the candidate pool.
    """
    missing = sorted(set(known_archetypes()) - set(known_keyword_archetypes()))
    assert missing == [], (
        f"registered but unreachable — add a catalog entry: {missing}")


def test_every_catalog_entry_resolves_to_a_real_vocabulary():
    """The mirror: a keyword entry pointing at nothing routes an app to a
    vocabulary that will not load."""
    unresolved = [a.vocab_id for a in ARCHETYPES if load_vocabulary(a.vocab_id) is None]
    assert unresolved == [], f"catalog names unregistered vocabs: {unresolved}"


def test_both_matchers_see_the_same_archetypes():
    """Neither derived view may quietly cover fewer archetypes than the
    other — that asymmetry *was* the bug."""
    assert set(prompt_phrase_table()) == {s for s, _ in plan_token_table()}


def test_the_ranker_scores_every_catalog_archetype():
    """Guards the import path, not just the data: vocab_ranker reads the
    table through product_brief, so a stale re-export would show up here
    as a short ranking."""
    ranked = {slug for slug, _ in rank_vocabs_by_keyword_hits({"description": ""})}
    assert ranked == set(known_keyword_archetypes())


# ── the catalog is well-formed ─────────────────────────────────────

def test_ids_are_canonical_registry_ids():
    """Short slugs reached the registry only through a suffix fallback in
    load_vocabulary. Emitting real ids removes that bridge."""
    bad = [a.vocab_id for a in ARCHETYPES if not a.vocab_id.endswith("-platform")]
    assert bad == [], f"non-canonical ids: {bad}"


def test_no_archetype_is_half_registered():
    """Both keyword sets are required. An entry with one empty is the
    original bug wearing a different hat."""
    holes = [a.vocab_id for a in ARCHETYPES
             if not a.prompt_phrases or not a.plan_tokens]
    assert holes == [], f"entries missing a keyword set: {holes}"


def test_ids_are_unique():
    ids = [a.vocab_id for a in ARCHETYPES]
    assert len(ids) == len(set(ids))


def test_product_brief_reexport_is_the_catalog():
    """product_brief keeps the old name for its callers; it must be the
    derived view, not a second copy that can drift again."""
    assert PLAN_TABLE == plan_token_table()


# ── precedence the comments promise ────────────────────────────────

@pytest.mark.parametrize("earlier,later", [
    # A SaaS billing description must not be captured by legislative's
    # "bill" token, which is a substring of "billing".
    ("subscription-billing-platform", "legislative-platform"),
    # An SRE dashboard is dev-tools, not generic BI.
    ("dev-tools-platform", "analytics-dashboard-platform"),
    # analytics-dashboard's tokens are the vaguest in the catalog; it
    # must not outrank a real domain. This ordering is why a civic app
    # stopped being classified as a BI tool.
    ("legislative-platform", "analytics-dashboard-platform"),
])
def test_precedence_order_is_preserved(earlier, later):
    ids = known_keyword_archetypes()
    assert ids.index(earlier) < ids.index(later)


# ── it actually classifies the app that exposed this ───────────────

_LEGISLATIVE_ENTITIES = [
    "PoliticalBloc", "Member", "Committee", "CommitteeMembership", "Session",
    "Agenda", "AgendaItem", "Attendance", "VoteSession", "VoteRecord", "Bill",
    "Minutes", "Document", "AuditLog",
]


def test_the_council_app_now_ranks_legislative_first():
    """Reproduces l8vrakiw from its real entity list. Before the catalog,
    legislative scored nothing and analytics-dashboard was the sole
    candidate."""
    plan = {"entities": {n: {} for n in _LEGISLATIVE_ENTITIES},
            "description": "Palestinian Legislative Council management system"}
    ranked = rank_vocabs_by_keyword_hits(plan)
    top, score = ranked[0]
    assert top == "legislative-platform", f"ranked: {ranked[:3]}"
    assert score >= 2, "must clear select_candidate_pool's min_score"


def test_the_council_app_beats_the_vocabulary_that_captured_it():
    plan = {"entities": {n: {} for n in _LEGISLATIVE_ENTITIES}}
    scores = dict(rank_vocabs_by_keyword_hits(plan))
    assert scores["legislative-platform"] > scores["analytics-dashboard-platform"]


@pytest.mark.parametrize("prompt,expected", [
    ("a city council agenda management system", "legislative-platform"),
    ("bill tracking for the state legislature", "legislative-platform"),
    ("inventory management for a warehouse", "inventory-platform"),
    ("an executive dashboard of revenue analytics",
     "analytics-dashboard-platform"),
])
def test_prompt_detection_returns_canonical_ids(prompt, expected):
    assert detect_vocab_archetype(prompt) == expected


def test_an_unrelated_prompt_still_matches_nothing():
    """The catalog must not turn every sentence into an archetype."""
    assert detect_vocab_archetype("hello there") is None
