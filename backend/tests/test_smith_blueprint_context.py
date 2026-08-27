"""Blueprint → Smith-system-prompt context rendering.

This is what actually reaches Smith's system prompt each turn: a
compact human-readable rendering of the blueprint that establishes
"you built this app, here's what and why."

Contract tests:
  * The renderer produces text that includes the domain, every
    entity name, every workflow name, every page route, and a short
    slice of the change_log (the most recent moves — Smith needs to
    know what just happened without re-reading git).
  * An empty blueprint renders a distinct "no app built yet" block
    so Smith knows he's in bootstrap territory.
  * The renderer never exceeds a soft budget when the input is huge;
    it truncates the least-useful sections first (older change_log
    entries) and marks the truncation explicitly.
  * ``pick_relevant_slice`` is the seam for the future LLM slicer
    (§6.4). For now, small blueprints pass through whole; the
    contract just makes sure the seam exists so S2b can slot in
    without changing callers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import (
    blueprint_to_context,
    pick_relevant_slice,
    ContextBudget,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _new(tmp_path: Path, project_id: str = "p1") -> Blueprint:
    bp = Blueprint.load(project_id=project_id, output_dir=str(tmp_path))
    return bp


# --------------------------------------------------------------------------- #
# blueprint_to_context — the main rendering path
# --------------------------------------------------------------------------- #

def test_empty_blueprint_renders_bootstrap_marker(tmp_path):
    bp = _new(tmp_path)
    ctx = blueprint_to_context(bp)
    assert "no app built yet" in ctx.lower()
    assert bp.project_id in ctx


def test_populated_blueprint_includes_domain_entities_workflows_pages(tmp_path):
    bp = _new(tmp_path)
    bp.set_domain(
        name="Cabin Crew ATS", primary_actors=["recruiter", "candidate"],
        core_verbs=["apply", "schedule"],
        distinctive_shape="kanban pipeline",
        why="airline recruitment",
    )
    bp.add_entity(name="Candidate", table="candidates", purpose="applicant",
                  key_fields=["fullName", "email"], why_shaped_this_way="MVP")
    bp.add_entity(name="Assessor", table="assessors", purpose="interviewer",
                  key_fields=["email"], why_shaped_this_way="needed to schedule")
    bp.add_workflow(name="CreateCandidate", purpose="capture applicant",
                    trigger="form submit", why="manual add before bulk import")
    bp.add_page(route="/candidates/new",
                schema_path="src/schemas/candidates/new.json",
                role="primary intake", notable_choices=[])

    ctx = blueprint_to_context(bp)

    assert "Cabin Crew ATS" in ctx
    assert "recruiter" in ctx and "candidate" in ctx
    assert "Candidate" in ctx and "Assessor" in ctx
    assert "CreateCandidate" in ctx
    assert "/candidates/new" in ctx


def test_change_log_recent_first_and_bounded(tmp_path):
    """Only the tail of the change_log is included — Smith needs
    'what just happened,' not a full history in every prompt."""
    bp = _new(tmp_path)
    for i in range(50):
        bp.append_change_log(
            at=f"2026-07-17 12:{i:02d}",
            user_ask=f"ask #{i}", smith_move=f"move #{i}",
            diff_summary=f"file{i}.json | 1 +", verified_by=[],
            why=f"reason #{i}",
        )
    ctx = blueprint_to_context(bp)

    # Recent entries present, oldest omitted.
    assert "ask #49" in ctx
    assert "ask #48" in ctx
    assert "ask #0" not in ctx
    # Truncation marker is loud, not silent.
    assert "older" in ctx.lower() and "omitted" in ctx.lower()


def test_context_respects_soft_budget_by_dropping_change_log_first(tmp_path):
    """Under a tight budget, change_log entries are the first casualty
    (they're the most easily re-fetched via git log). Domain / entities
    / workflows / pages survive because Smith reasons against them."""
    bp = _new(tmp_path)
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.add_entity(name="Candidate", table="candidates", purpose="",
                  key_fields=[], why_shaped_this_way="")
    for i in range(100):
        bp.append_change_log(
            at=f"2026-07-17 12:{i:02d}",
            user_ask=f"ask #{i}", smith_move="x", diff_summary="y",
            verified_by=[], why="z",
        )
    ctx = blueprint_to_context(bp, budget=ContextBudget(max_chars=500))
    assert len(ctx) <= 500
    # Entity survived even under tight budget.
    assert "Candidate" in ctx
    # At least the truncation notice is present.
    assert "omitted" in ctx.lower()


# --------------------------------------------------------------------------- #
# pick_relevant_slice — the S2b seam
# --------------------------------------------------------------------------- #

def test_pick_relevant_slice_returns_full_blueprint_for_small_apps(tmp_path):
    """Small apps: the whole blueprint fits and is returned unchanged.
    This is the S2 shipping behavior; S2b will layer an LLM slicer on
    top for large apps."""
    bp = _new(tmp_path)
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.add_entity(name="Candidate", table="candidates", purpose="",
                  key_fields=[], why_shaped_this_way="")

    sliced = pick_relevant_slice(bp, ask="change the CV field")
    assert sliced is bp  # same object; no wrapper allocated for small apps


def test_pick_relevant_slice_accepts_none_ask_for_bootstrap_turns(tmp_path):
    """New-app conversations may not have an ask yet (Smith is
    introducing himself); the slicer must not crash."""
    bp = _new(tmp_path)
    sliced = pick_relevant_slice(bp, ask=None)
    assert sliced is bp
