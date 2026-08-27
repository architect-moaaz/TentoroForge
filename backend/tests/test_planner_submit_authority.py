"""Tests for the SUBMIT-AUTHORITY normalizer additions in
:mod:`agents.planner._normalize_oneshot_plan`.

Slice A T2. The normalizer is a backward-compat gate: for plans that
don't declare page.submit or workflow.source (either because the
prompt-guided LLM missed it, or the plan came from an older gen), fill
in sensible defaults so the rest of the pipeline sees the contract
shape.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- #
# Backward-compat: form pages with entity get default submit
# --------------------------------------------------------------------------- #

def test_form_page_with_entity_defaults_to_data_api_submit():
    from agents.planner import _normalize_oneshot_plan

    plan = {
        "entities": {"Feedback": {"table": "feedback", "fields": []}},
        "pages": [
            {"name": "FeedbackForm", "type": "form", "entity": "Feedback"},
        ],
    }
    out = _normalize_oneshot_plan(plan)
    feedback_page = next(p for p in out["pages"] if p["name"] == "FeedbackForm")
    assert feedback_page["submit"] == {"kind": "data_api", "target": "Feedback"}


def test_form_page_with_existing_submit_is_preserved():
    from agents.planner import _normalize_oneshot_plan

    plan = {
        "entities": {"F": {"fields": []}},
        "pages": [{
            "name": "P", "type": "form", "entity": "F",
            "submit": {"kind": "workflow", "target": "SubmitFeedbackWorkflow"},
        }],
    }
    out = _normalize_oneshot_plan(plan)
    page = out["pages"][0]
    # Existing declaration wins — normalizer never overwrites.
    assert page["submit"]["kind"] == "workflow"
    assert page["submit"]["target"] == "SubmitFeedbackWorkflow"


def test_non_form_page_no_submit_added():
    from agents.planner import _normalize_oneshot_plan

    plan = {
        "entities": {"F": {"fields": []}},
        "pages": [
            {"name": "List", "type": "list", "entity": "F"},
            {"name": "Detail", "type": "detail", "entity": "F"},
        ],
    }
    out = _normalize_oneshot_plan(plan)
    # List/detail pages don't submit — normalizer skips them.
    assert "submit" not in out["pages"][0]
    assert "submit" not in out["pages"][1]


def test_form_page_without_entity_no_submit_added():
    from agents.planner import _normalize_oneshot_plan

    plan = {
        "entities": {},
        "pages": [{"name": "P", "type": "form"}],   # no entity
    }
    out = _normalize_oneshot_plan(plan)
    # No entity → no way to derive a data-api target → leave submit
    # unset so the validator (T3) surfaces it as a genuine plan gap.
    assert "submit" not in out["pages"][0]


# --------------------------------------------------------------------------- #
# Idempotent — running the normalizer twice yields the same plan
# --------------------------------------------------------------------------- #

def test_normalizer_is_idempotent_for_submit_defaults():
    from agents.planner import _normalize_oneshot_plan

    plan = {
        "entities": {"F": {"fields": []}},
        "pages": [{"name": "P", "type": "form", "entity": "F"}],
    }
    once = _normalize_oneshot_plan(plan)
    twice = _normalize_oneshot_plan(once)
    # Same shape both passes — critical because the normalizer runs on
    # every plan-load path (initial gen, chat approval, refine, revise).
    assert twice["pages"][0]["submit"] == once["pages"][0]["submit"]


# --------------------------------------------------------------------------- #
# Handles alternate page-shape (data_models list already present)
# --------------------------------------------------------------------------- #

def test_normalizer_handles_data_models_list_shape():
    from agents.planner import _normalize_oneshot_plan

    # Some plans arrive with data_models already listed (post-normalize
    # or hand-authored). The submit default should still apply.
    plan = {
        "data_models": [{"name": "F", "fields": []}],
        "pages": [{"name": "P", "type": "form", "entity": "F"}],
    }
    out = _normalize_oneshot_plan(plan)
    assert out["pages"][0]["submit"] == {"kind": "data_api", "target": "F"}
