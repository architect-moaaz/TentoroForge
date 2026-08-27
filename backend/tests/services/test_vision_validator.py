# backend/tests/services/test_vision_validator.py
import json

import pytest

from services.vision_evaluator.validator import parse_critique_json, ValidationError


VALID_CRITIQUE = {
    "scores": {
        "visualPolish": 7, "domainFeel": 6, "informationDensity": 5,
        "componentCoherence": 7, "brandReflection": 6,
    },
    "compositeScore": 6.4,
    "pass": False,
    "topIssues": [
        {
            "severity": "medium",
            "axis": "informationDensity",
            "nodeIdHint": "stats-grid",
            "issue": "Only 2 MetricTiles — too sparse",
            "suggestion": "Add Avg Duration tile.",
        }
    ],
    "strengths": ["Hero structure is solid"],
    "designerApprovalRecommended": False,
}


def test_valid_payload_parses():
    c = parse_critique_json(json.dumps(VALID_CRITIQUE))
    assert c.compositeScore == 6.4
    assert c.pass_ is False
    assert len(c.topIssues) == 1


def test_missing_required_field_raises():
    bad = {**VALID_CRITIQUE}
    del bad["scores"]
    with pytest.raises(ValidationError):
        parse_critique_json(json.dumps(bad))


def test_score_out_of_range_raises():
    bad = json.loads(json.dumps(VALID_CRITIQUE))
    bad["scores"]["visualPolish"] = 11
    with pytest.raises(ValidationError):
        parse_critique_json(json.dumps(bad))


def test_invalid_json_raises():
    with pytest.raises(ValidationError):
        parse_critique_json("not json at all")


def test_extra_unknown_keys_are_tolerated():
    extra = {**VALID_CRITIQUE, "reasoning": "I think therefore"}
    c = parse_critique_json(json.dumps(extra))
    assert c.compositeScore == 6.4
