"""Tests for workflow variable-provenance analysis (Part B / Task B1).

A gateway/condition that branches on a variable no upstream node produces is a
dead branch (the expression can never be true). `analyze_workflow` detects it.
"""
from __future__ import annotations

from services.workflow_variable_contract import (
    analyze_workflow,
    producers,
    referenced_vars,
)


# ---------------------------------------------------------------------------
# referenced_vars
# ---------------------------------------------------------------------------

def test_referenced_vars_single_comparison_strips_string_literal():
    assert referenced_vars("overallRecommendation = 'Hire'") == {"overallRecommendation"}


def test_referenced_vars_and_expression_two_vars():
    assert referenced_vars("score >= 80 and status = 'open'") == {"score", "status"}


def test_referenced_vars_dotted_path_uses_root():
    assert referenced_vars("application.stage = 'Offer'") == {"application"}


def test_referenced_vars_drops_keywords_booleans_numbers():
    # keywords (and/or/not), booleans (true/false/null), numbers, and the
    # double-quoted literal are all excluded — only `flag`, `qty`, `x` remain.
    assert referenced_vars('flag = true and qty > 3 and not (x = "y")') == {
        "flag",
        "qty",
        "x",
    }


def test_referenced_vars_string_function_not_a_var():
    # `contains` is a FEEL string function, not a referenced variable.
    got = referenced_vars("contains(name, 'Ada')")
    assert "contains" not in got
    assert got == {"name"}


def test_referenced_vars_empty():
    assert referenced_vars("") == set()
    assert referenced_vars(None) == set()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixtures (f4pw5y5k-shaped)
# ---------------------------------------------------------------------------

def _f4pw5y5k_shaped() -> dict:
    """A workflow shaped like output/f4pw5y5k/feedbackscoringworkflow.json:
    trigger db_change on InterviewFeedback, a set_variable producing only
    `compute_aggregate_score_done`, an ai_generate with NO declared output, and
    two exclusive_gateways branching on `overallRecommendation`."""
    return {
        "id": "feedbackscoringworkflow",
        "definition": {
            "trigger": {"type": "api_event"},
            "nodes": [
                {
                    "id": "trigger",
                    "type": "trigger",
                    "data": {
                        "nodeType": "trigger",
                        "config": {
                            "entity": "InterviewFeedback",
                            "triggerType": "db_change",
                        },
                    },
                },
                {
                    "id": "compute_aggregate_score",
                    "type": "action",
                    "data": {
                        "config": {
                            "actionType": "set_variable",
                            "variableName": "compute_aggregate_score_done",
                            "value": True,
                        }
                    },
                },
                {
                    "id": "generate_recommendation_summary",
                    "type": "action",
                    "data": {
                        "config": {
                            "actionType": "ai_generate",
                            "prompt": "generate a recommendation summary",
                            # NOTE: no outputVariable / outputParams — nothing is
                            # written back, so overallRecommendation is unproduced.
                        }
                    },
                },
                {
                    "id": "recommendation_gateway",
                    "type": "exclusive_gateway",
                    "data": {
                        "config": {"expression": "overallRecommendation = 'Hire'"}
                    },
                },
                {
                    "id": "hold_or_reject_gateway",
                    "type": "exclusive_gateway",
                    "data": {
                        "config": {"expression": "overallRecommendation = 'Hold'"}
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [],
        },
    }


# ---------------------------------------------------------------------------
# producers
# ---------------------------------------------------------------------------

def test_producers_includes_set_variable_and_excludes_ai_without_output():
    prod = producers(_f4pw5y5k_shaped(), None)
    assert "compute_aggregate_score_done" in prod
    assert "overallRecommendation" not in prod


def test_producers_includes_ai_declared_output_variable():
    defn = _f4pw5y5k_shaped()
    for n in defn["definition"]["nodes"]:
        if n["id"] == "generate_recommendation_summary":
            n["data"]["config"]["outputVariable"] = "overallRecommendation"
    assert "overallRecommendation" in producers(defn, None)


def test_producers_includes_output_params():
    defn = _f4pw5y5k_shaped()
    for n in defn["definition"]["nodes"]:
        if n["id"] == "generate_recommendation_summary":
            n["data"]["outputParams"] = [
                {"name": "raw", "target": "overallRecommendation"}
            ]
    assert "overallRecommendation" in producers(defn, None)


def test_producers_includes_trigger_entity_columns_from_registry():
    registry = {
        "entities": {
            "InterviewFeedback": {
                "fields": {"overallRecommendation": {"type": "varchar"}}
            }
        }
    }
    prod = producers(_f4pw5y5k_shaped(), registry)
    assert "overallRecommendation" in prod


# ---------------------------------------------------------------------------
# analyze_workflow
# ---------------------------------------------------------------------------

def test_analyze_flags_unproduced_gateway_var():
    findings = analyze_workflow(_f4pw5y5k_shaped())
    variables = {f["variable"] for f in findings}
    assert "overallRecommendation" in variables
    for f in findings:
        assert f["type"] == "unproduced_gateway_var"
        assert "expression" in f and "node" in f
    # Both gateways branch on it.
    nodes = {f["node"] for f in findings}
    assert "recommendation_gateway" in nodes
    assert "hold_or_reject_gateway" in nodes


def test_analyze_no_finding_when_set_variable_produces_the_var():
    defn = _f4pw5y5k_shaped()
    for n in defn["definition"]["nodes"]:
        if n["id"] == "compute_aggregate_score":
            n["data"]["config"]["variableName"] = "overallRecommendation"
    findings = analyze_workflow(defn)
    assert all(f["variable"] != "overallRecommendation" for f in findings)
    assert findings == []


def test_analyze_no_finding_when_registry_entity_column_supplies_var():
    registry = {
        "entities": {
            "InterviewFeedback": {
                "fields": {"overallRecommendation": {"type": "varchar"}}
            }
        }
    }
    findings = analyze_workflow(_f4pw5y5k_shaped(), registry)
    assert findings == []


def test_analyze_handles_step_style_condition_key():
    # Some definitions store the branch expression under config.condition instead
    # of config.expression; both must be read.
    defn = {
        "definition": {
            "nodes": [
                {"id": "trigger", "type": "trigger", "data": {"config": {}}},
                {
                    "id": "gw",
                    "type": "exclusive_gateway",
                    "data": {"config": {"condition": "missingVar = 'x'"}},
                },
            ],
            "edges": [],
        }
    }
    findings = analyze_workflow(defn)
    assert any(f["variable"] == "missingVar" for f in findings)
