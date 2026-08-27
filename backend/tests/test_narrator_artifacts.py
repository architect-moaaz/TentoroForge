"""Narrator-mode artifact contracts.

Spec §10.4: internal agents (discovery, planner, generator) emit
structured JSON only. Smith reads the artifact and speaks in his
own voice. No agent produces user-facing prose.

This slice defines the artifact shapes as dataclasses so agent
adapters have a target to normalize to, and Smith has a stable
shape to summarize from. Full prompt rewrites of each agent land
in S6; this slice just fixes the contract.
"""
from __future__ import annotations

import pytest

from services.narrator_artifacts import (
    DiscoveryArtifact,
    PlannerArtifact,
    GeneratorArtifact,
    ProposedEntity,
    ProposedWorkflow,
    ProposedPage,
    NarratorArtifactError,
)


# --------------------------------------------------------------------------- #
# DiscoveryArtifact
# --------------------------------------------------------------------------- #

def test_discovery_artifact_requires_domain_name():
    with pytest.raises(NarratorArtifactError):
        DiscoveryArtifact.from_dict({"domain_name": "", "actors": [], "verbs": []})


def test_discovery_artifact_round_trips_the_dossier():
    d = DiscoveryArtifact.from_dict({
        "domain_name": "Cabin Crew ATS",
        "actors": ["recruiter", "candidate"],
        "verbs": ["apply", "schedule"],
        "distinctive_shape": "kanban pipeline",
        "proposed_entities": [{"name": "Candidate", "why": "the applicant"}],
        "open_questions": ["how do assessments work?"],
        "confidence": 0.85,
    })
    assert d.domain_name == "Cabin Crew ATS"
    assert d.actors == ["recruiter", "candidate"]
    assert d.proposed_entities[0].name == "Candidate"
    assert d.open_questions == ["how do assessments work?"]
    assert 0 <= d.confidence <= 1


def test_discovery_artifact_narrator_summary_reads_like_architect():
    """The prose Smith would say to the user, generated from the
    dossier. Deterministic (no model call) — this is Smith's own
    voice, produced by the module rather than by the agent."""
    d = DiscoveryArtifact.from_dict({
        "domain_name": "Cabin Crew ATS",
        "actors": ["recruiter", "candidate"],
        "verbs": ["apply", "schedule"],
        "distinctive_shape": "kanban pipeline",
        "proposed_entities": [
            {"name": "Candidate", "why": "the applicant"},
            {"name": "AssessmentDay", "why": "batched interviews"},
        ],
        "open_questions": ["how do assessments work?"],
        "confidence": 0.85,
    })
    prose = d.narrator_summary()
    assert "Cabin Crew ATS" in prose
    assert "recruiter" in prose and "candidate" in prose
    assert "Candidate" in prose and "AssessmentDay" in prose
    # Should end with the open question so the user has something to
    # respond to.
    assert "how do assessments work?" in prose


# --------------------------------------------------------------------------- #
# PlannerArtifact
# --------------------------------------------------------------------------- #

def test_planner_artifact_requires_at_least_one_entity_or_page():
    """A plan with zero entities AND zero pages is meaningless — refuse."""
    with pytest.raises(NarratorArtifactError):
        PlannerArtifact.from_dict({
            "entities": [], "workflows": [], "pages": [],
        })


def test_planner_artifact_records_full_plan_and_summary():
    p = PlannerArtifact.from_dict({
        "entities": [
            {"name": "Candidate", "table": "candidates",
             "purpose": "applicant", "key_fields": ["email"],
             "why_shaped_this_way": "MVP"},
        ],
        "workflows": [
            {"name": "CreateCandidate", "purpose": "capture applicant",
             "trigger": "form submit", "why": "manual entry"},
        ],
        "pages": [
            {"route": "/candidates", "schema_path": "src/schemas/candidates/index.json",
             "role": "list view"},
        ],
    })
    assert p.entities[0].name == "Candidate"
    assert p.workflows[0].name == "CreateCandidate"
    assert p.pages[0].route == "/candidates"


def test_planner_narrator_summary_names_each_group_with_counts():
    p = PlannerArtifact.from_dict({
        "entities": [
            {"name": "A", "table": "as", "purpose": "", "key_fields": [],
             "why_shaped_this_way": ""},
            {"name": "B", "table": "bs", "purpose": "", "key_fields": [],
             "why_shaped_this_way": ""},
        ],
        "workflows": [],
        "pages": [
            {"route": "/a", "schema_path": "s/a.json", "role": "list"},
        ],
    })
    prose = p.narrator_summary()
    assert "2 entit" in prose  # entity or entities
    assert "1 page" in prose
    # Workflows section is present-tense-mentioned as none.
    assert "no workflow" in prose.lower() or "0 workflow" in prose.lower()


# --------------------------------------------------------------------------- #
# GeneratorArtifact
# --------------------------------------------------------------------------- #

def test_generator_artifact_records_files_warnings_notes():
    g = GeneratorArtifact.from_dict({
        "generated_files": [
            "src/schemas/candidates/new.json",
            "src/db/schema.ts",
        ],
        "warnings": ["form_scaffold: added 2 fields to /candidates/new"],
        "notes": ["seed_synthesizer: 60 rows across 6 tables"],
    })
    assert len(g.generated_files) == 2
    assert g.warnings[0].startswith("form_scaffold")


def test_generator_narrator_summary_is_concise():
    """The generator produces lots of file paths; the narrator summary
    stays to the punchline so Smith doesn't dump 100 paths at the user."""
    g = GeneratorArtifact.from_dict({
        "generated_files": [f"src/schemas/p{i}.json" for i in range(50)],
        "warnings": [],
        "notes": [],
    })
    prose = g.narrator_summary()
    assert "50" in prose or "fifty" in prose.lower()
    # Never dump every path — cap at a small preview.
    assert prose.count("src/schemas/p") <= 6
