# backend/services/vision_evaluator/types.py
"""Pydantic models matching the spec's Critique JSON shape exactly."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["high", "medium", "low"]
Axis = Literal[
    "visualPolish",
    "domainFeel",
    "informationDensity",
    "componentCoherence",
    "brandReflection",
]


class Scores(BaseModel):
    visualPolish: float = Field(ge=0, le=10)
    domainFeel: float = Field(ge=0, le=10)
    informationDensity: float = Field(ge=0, le=10)
    componentCoherence: float = Field(ge=0, le=10)
    brandReflection: float = Field(ge=0, le=10)


class PatchOp(BaseModel):
    op: Literal["add", "replace", "remove", "move"]
    path: str
    value: object | None = None
    from_: str | None = Field(default=None, alias="from")


class Issue(BaseModel):
    severity: Severity
    axis: Axis
    nodeIdHint: str | None = None
    issue: str
    suggestion: str
    patchOp: PatchOp | None = None


class CompareToPrevious(BaseModel):
    improved: list[Axis] = Field(default_factory=list)
    regressed: list[Axis] = Field(default_factory=list)


class Critique(BaseModel):
    scores: Scores
    compositeScore: float = Field(ge=0, le=10)
    pass_: bool = Field(alias="pass")
    topIssues: list[Issue] = Field(default_factory=list, max_length=10)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    designerApprovalRecommended: bool = False
    compareToPrevious: CompareToPrevious | None = None

    model_config = ConfigDict(populate_by_name=True)


# Composite weighting from the spec:
COMPOSITE_WEIGHTS: dict[Axis, float] = {
    "visualPolish": 0.25,
    "domainFeel": 0.25,
    "informationDensity": 0.15,
    "componentCoherence": 0.20,
    "brandReflection": 0.15,
}


def compute_composite(scores: Scores) -> float:
    total = sum(getattr(scores, axis) * weight for axis, weight in COMPOSITE_WEIGHTS.items())
    return round(total, 2)


DOMAIN_COMPOSITE_WEIGHTS: dict[str, dict[Axis, float]] = {
    "default": COMPOSITE_WEIGHTS,  # the existing weights

    # HR / corporate admin — information density matters more
    "hr": {
        "visualPolish":       0.20,
        "domainFeel":         0.25,
        "informationDensity": 0.25,  # bumped from 0.15
        "componentCoherence": 0.20,
        "brandReflection":    0.10,  # dropped from 0.15
    },

    # Fintech — domain feel and brand reflection matter most
    "fintech": {
        "visualPolish":       0.20,
        "domainFeel":         0.30,  # bumped
        "informationDensity": 0.15,
        "componentCoherence": 0.20,
        "brandReflection":    0.15,
    },

    # Healthcare — visual polish + domain feel critical
    "healthcare": {
        "visualPolish":       0.30,  # bumped
        "domainFeel":         0.30,  # bumped
        "informationDensity": 0.15,
        "componentCoherence": 0.15,
        "brandReflection":    0.10,
    },

    # Content/wiki/blog — brand reflection + polish dominate
    "content": {
        "visualPolish":       0.30,  # bumped
        "domainFeel":         0.15,
        "informationDensity": 0.10,
        "componentCoherence": 0.20,
        "brandReflection":    0.25,  # bumped
    },
}


def compute_composite_for_domain(scores: Scores, domain: str) -> float:
    """Same as compute_composite but uses domain-specific weights when
    available. Falls back to the default weights for unknown domains."""
    weights = DOMAIN_COMPOSITE_WEIGHTS.get(domain.lower(), COMPOSITE_WEIGHTS)
    total = sum(getattr(scores, axis) * weight for axis, weight in weights.items())
    return round(total, 2)
