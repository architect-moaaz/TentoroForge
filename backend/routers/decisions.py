"""Decision table endpoints — CRUD, evaluation, testing, versions, and execution logs."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.decision import DecisionExecutionLog, DecisionTable, DecisionTableVersion
from schemas.decision import (
    DecisionEvaluateRequest,
    DecisionEvaluateResponse,
    DecisionExecutionLogResponse,
    DecisionTableCreate,
    DecisionTableResponse,
    DecisionTableUpdate,
    DecisionTableVersionResponse,
    DecisionTestRequest,
    DecisionTestResponse,
    DecisionTestCaseResult,
)
from services.project_service import get_project_with_auth

router = APIRouter(tags=["decisions"])


# ---------------------------------------------------------------------------
# Decision Table CRUD
# ---------------------------------------------------------------------------

@router.get(
    "/api/projects/{project_id}/decisions",
    response_model=list[DecisionTableResponse],
)
async def list_decision_tables(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all decision tables for a project."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(DecisionTable)
        .where(DecisionTable.project_id == project_id)
        .order_by(DecisionTable.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/api/projects/{project_id}/decisions",
    response_model=DecisionTableResponse,
    status_code=201,
)
async def create_decision_table(
    project_id: uuid.UUID,
    req: DecisionTableCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new decision table."""
    await get_project_with_auth(project_id, user, db)

    dt = DecisionTable(
        project_id=project_id,
        name=req.name,
        description=req.description,
        definition=req.definition,
        version=1,
    )
    db.add(dt)
    await db.flush()

    # Create initial version snapshot
    version = DecisionTableVersion(
        decision_table_id=dt.id,
        version=1,
        definition=req.definition,
        created_by=user.id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(dt)
    return dt


@router.get(
    "/api/projects/{project_id}/decisions/{decision_id}",
    response_model=DecisionTableResponse,
)
async def get_decision_table(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single decision table by ID."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    dt = result.scalar_one_or_none()
    if not dt:
        raise HTTPException(status_code=404, detail="Decision table not found")
    return dt


@router.put(
    "/api/projects/{project_id}/decisions/{decision_id}",
    response_model=DecisionTableResponse,
)
async def update_decision_table(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    req: DecisionTableUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing decision table."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    dt = result.scalar_one_or_none()
    if not dt:
        raise HTTPException(status_code=404, detail="Decision table not found")

    update_data = req.model_dump(exclude_unset=True)

    # If definition changed, bump version and create version snapshot
    if "definition" in update_data and update_data["definition"] is not None:
        dt.version += 1
        version = DecisionTableVersion(
            decision_table_id=dt.id,
            version=dt.version,
            definition=update_data["definition"],
            created_by=user.id,
        )
        db.add(version)

    for field, value in update_data.items():
        setattr(dt, field, value)

    await db.commit()
    await db.refresh(dt)
    return dt


@router.delete(
    "/api/projects/{project_id}/decisions/{decision_id}",
    status_code=204,
)
async def delete_decision_table(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a decision table."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    dt = result.scalar_one_or_none()
    if not dt:
        raise HTTPException(status_code=404, detail="Decision table not found")

    await db.delete(dt)
    await db.commit()


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@router.post(
    "/api/projects/{project_id}/decisions/{decision_id}/evaluate",
    response_model=DecisionEvaluateResponse,
)
async def evaluate_decision(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    req: DecisionEvaluateRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate a decision table with the given inputs."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    dt = result.scalar_one_or_none()
    if not dt:
        raise HTTPException(status_code=404, detail="Decision table not found")

    from runtime.decision_evaluator import evaluate_decision_table

    eval_result = evaluate_decision_table(dt.definition, req.inputs)

    # Log execution
    log = DecisionExecutionLog(
        decision_table_id=dt.id,
        inputs=req.inputs,
        outputs=eval_result.get("outputs"),
        matched_rule_ids=eval_result.get("matched_rule_ids"),
        hit_policy=eval_result.get("hit_policy"),
        duration_ms=eval_result.get("duration_ms"),
    )
    db.add(log)
    await db.commit()

    return DecisionEvaluateResponse(
        hit_policy=eval_result["hit_policy"],
        matched_rule_ids=eval_result["matched_rule_ids"],
        outputs=eval_result["outputs"],
        result=eval_result["result"],
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@router.post(
    "/api/projects/{project_id}/decisions/{decision_id}/test",
    response_model=DecisionTestResponse,
)
async def test_decision(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    req: DecisionTestRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run test cases against a decision table."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    dt = result.scalar_one_or_none()
    if not dt:
        raise HTTPException(status_code=404, detail="Decision table not found")

    from runtime.decision_evaluator import evaluate_decision_table

    results: list[DecisionTestCaseResult] = []

    for i, test_case in enumerate(req.test_cases):
        try:
            eval_result = evaluate_decision_table(dt.definition, test_case.inputs)
            actual = eval_result.get("outputs") or eval_result.get("result")

            passed = True
            if test_case.expected_outputs is not None:
                # Check if actual outputs match expected
                if isinstance(actual, dict):
                    passed = all(
                        str(actual.get(k)) == str(v)
                        for k, v in test_case.expected_outputs.items()
                    )
                elif isinstance(actual, list) and actual:
                    # For collect/rule-order, check if any output matches
                    passed = any(
                        all(
                            str(out.get(k)) == str(v)
                            for k, v in test_case.expected_outputs.items()
                        )
                        for out in actual
                        if isinstance(out, dict)
                    )
                else:
                    passed = False

            results.append(DecisionTestCaseResult(
                test_case_id=i,
                passed=passed,
                actual=actual,
                expected=test_case.expected_outputs,
            ))
        except Exception as e:
            results.append(DecisionTestCaseResult(
                test_case_id=i,
                passed=False,
                actual=None,
                expected=test_case.expected_outputs,
                error_message=str(e),
            ))

    return DecisionTestResponse(results=results)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@router.get(
    "/api/projects/{project_id}/decisions/{decision_id}/versions",
    response_model=list[DecisionTableVersionResponse],
)
async def list_decision_versions(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of a decision table."""
    await get_project_with_auth(project_id, user, db)

    # Verify decision table exists and belongs to project
    dt_result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    if not dt_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Decision table not found")

    result = await db.execute(
        select(DecisionTableVersion)
        .where(DecisionTableVersion.decision_table_id == decision_id)
        .order_by(DecisionTableVersion.version.desc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Execution Logs
# ---------------------------------------------------------------------------

@router.get(
    "/api/projects/{project_id}/decisions/{decision_id}/logs",
    response_model=list[DecisionExecutionLogResponse],
)
async def list_decision_logs(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List execution logs for a decision table."""
    await get_project_with_auth(project_id, user, db)

    # Verify decision table exists and belongs to project
    dt_result = await db.execute(
        select(DecisionTable).where(
            DecisionTable.id == decision_id,
            DecisionTable.project_id == project_id,
        )
    )
    if not dt_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Decision table not found")

    result = await db.execute(
        select(DecisionExecutionLog)
        .where(DecisionExecutionLog.decision_table_id == decision_id)
        .order_by(DecisionExecutionLog.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
