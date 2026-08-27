"""Pydantic schemas for decision table endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Decision Table CRUD
# ---------------------------------------------------------------------------

class DecisionTableCreate(BaseModel):
    name: str
    description: str | None = None
    definition: dict  # Full DecisionTableDefinition


class DecisionTableUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict | None = None


class DecisionTableResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    definition: dict
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Decision Table Evaluation
# ---------------------------------------------------------------------------

class DecisionEvaluateRequest(BaseModel):
    inputs: dict


class DecisionEvaluateResponse(BaseModel):
    hit_policy: str
    matched_rule_ids: list[str]
    outputs: Any  # dict for single result, list[dict] for collect/rule-order
    result: Any


# ---------------------------------------------------------------------------
# Decision Table Testing
# ---------------------------------------------------------------------------

class DecisionTestCase(BaseModel):
    inputs: dict
    expected_outputs: dict | None = None


class DecisionTestCaseResult(BaseModel):
    test_case_id: int
    passed: bool
    actual: Any
    expected: Any | None = None
    error_message: str | None = None


class DecisionTestRequest(BaseModel):
    test_cases: list[DecisionTestCase]


class DecisionTestResponse(BaseModel):
    results: list[DecisionTestCaseResult]


# ---------------------------------------------------------------------------
# Decision Table Versions
# ---------------------------------------------------------------------------

class DecisionTableVersionResponse(BaseModel):
    id: uuid.UUID
    decision_table_id: uuid.UUID
    version: int
    definition: dict
    created_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Decision Execution Logs
# ---------------------------------------------------------------------------

class DecisionExecutionLogResponse(BaseModel):
    id: uuid.UUID
    decision_table_id: uuid.UUID
    workflow_instance_id: uuid.UUID | None
    inputs: dict | None
    outputs: dict | None
    matched_rule_ids: list | None
    hit_policy: str | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
