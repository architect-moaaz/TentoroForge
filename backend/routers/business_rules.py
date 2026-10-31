"""The Business Rules tab's API — the Blueprint's `businessRules`, read and written.

Every route answers for the authorised project only, and every write goes
through `services.business_rules`: checked as the build checks a rule,
versioned in the definition's history, written into the running app at once.
A project without a Living Blueprint (built by the old pipeline) answers
``mode: "legacy"`` and the tab keeps using ``/rules``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.rules import ProjectRule
from services import business_rules as rules
from services.project_service import get_project_with_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["business-rules"])


class RulePayload(BaseModel):
    """What the tab sends. Every field is optional on an edit: what is not sent
    is kept."""
    kind: str | None = None
    name: str | None = Field(default=None, max_length=200)
    statement: str | None = Field(default=None, max_length=2000)
    entity: str | None = None
    when: str | None = Field(default=None, max_length=4000)
    then: list[dict[str, Any]] | None = None
    otherwise: list[dict[str, Any]] | None = None
    scope: str | None = None
    salience: int | None = None
    enabled: bool | None = None
    table: dict[str, Any] | None = None
    message: str | None = Field(default=None, max_length=1000)
    requirements: list[str] | None = None
    #: When it fires: ["create"], ["update"], or both (absent or both).
    on: list[str] | None = None

    def body(self) -> dict:
        return self.model_dump(exclude_unset=True)


class EditPayload(RulePayload):
    #: The rule's revision when the person opened it; an edit of a rule that
    #: has changed since is refused (409) instead of overwriting the change.
    revision: str | None = None


class TestPayload(BaseModel):
    """A sample save to run through the app's own engine. `rule` is the
    draft as the editor holds it (omit it to test the rules as they are);
    `rule_id` the rule it edits; `entity` the record when there is no draft."""
    rule: RulePayload | None = None
    rule_id: str | None = None
    entity: str | None = None
    record: dict[str, Any] = Field(default_factory=dict)
    previous: dict[str, Any] | None = None
    event: str = Field(default="create", pattern="^(create|update)$")

    @field_validator("record", "previous", mode="before")
    @classmethod
    def _a_record_is_a_record(cls, v: Any) -> Any:
        """A sample record is a record: a few levels deep, finite numbers.
        Walked without recursion, so the check cannot be the thing that breaks."""
        if v is None:
            return v
        stack, seen = [(v, 1)], 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if depth > 8 or seen > 5000:
                raise ValueError("a sample record is at most 8 levels deep and 5000 values")
            if isinstance(node, float) and (node != node or node in (float("inf"), float("-inf"))):
                raise ValueError("numbers in a sample record must be finite")
            if isinstance(node, dict):
                stack.extend((x, depth + 1) for x in node.values())
            elif isinstance(node, list):
                stack.extend((x, depth + 1) for x in node)
        return v


class AttachPayload(BaseModel):
    workflow: str = Field(min_length=1, max_length=40)
    #: The step it comes after; omitted, at the start.
    after: str | None = Field(default=None, max_length=120)
    on_refusal: str = Field(default="stop", pattern="^(stop|continue)$")
    #: After a yes/no step: its yes path (then) or its no path (else).
    path: str = Field(default="then", pattern="^(then|else)$")


class EnabledPayload(BaseModel):
    enabled: bool
    revision: str | None = None


def _dir(project: Any):
    from routers.blueprint_generate import _output_dir
    return _output_dir(project)


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, rules.RuleError):
        return HTTPException(status_code=exc.status, detail={"message": str(exc), "problems": exc.problems})
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"message": "This app has no definition yet.",
                                                      "problems": []})
    logger.exception("[business-rules] write failed")
    return HTTPException(status_code=400, detail={"message": f"The rule could not be saved: {exc}",
                                                  "problems": [str(exc)]})


async def _adopt_old_rows(project: Any, out: Any, db: AsyncSession) -> int:
    """Rules this tab saved to the old table, moved into the definition once."""
    rows = (await db.execute(select(ProjectRule).where(
        ProjectRule.project_id == project.id,
        ProjectRule.rule_type.in_(("condition_action", "decision_table"))))).scalars().all()
    if not rows:
        return 0
    plain = [{"id": str(r.id), "name": r.name, "rule_type": r.rule_type, "model_name": r.model_name,
              "config": r.config or {}, "is_active": r.is_active} for r in rows]
    adopted = await asyncio.to_thread(rules.adopt, out, plain)
    if adopted:
        await db.execute(delete(ProjectRule).where(ProjectRule.id.in_([uuid.UUID(a) for a in adopted])))
        await db.commit()
        logger.info("[business-rules] %s: %d rule(s) moved from the old table", out.name, len(adopted))
    return len(adopted)


@router.get("/api/projects/{project_id}/business-rules")
async def list_business_rules(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    project = await get_project_with_auth(project_id, user, db)
    out = _dir(project)
    if not rules.has_definition(out):
        return {"mode": "legacy", "rules": [], "catalogue": None, "building": False, "version": 0}
    try:
        await _adopt_old_rows(project, out, db)
    except Exception:  # noqa: BLE001 — the list is still read
        logger.exception("[business-rules] adopting old rows failed for %s", project_id)
    try:
        return await asyncio.to_thread(rules.read, out)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/projects/{project_id}/business-rules/use-rules-in-workflows")
async def use_rules_in_workflows(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    """The person's "Use the rules": workflow checks that say exactly what a
    rule says are handed to the rule, with a change record. Never on a read."""
    project = await get_project_with_auth(project_id, user, db)
    try:
        return {"linked": await asyncio.to_thread(rules.link_copies, _dir(project))}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/projects/{project_id}/business-rules", status_code=201)
async def create_business_rule(project_id: uuid.UUID, req: RulePayload,
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.create, _dir(project), req.body(), actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/projects/{project_id}/business-rules/check")
async def check_business_rule(project_id: uuid.UUID, req: RulePayload,
                              rule_id: str | None = Query(default=None),
                              user: PlatformUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Check a rule without saving it — what the editor shows as you type."""
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.try_rule, _dir(project), req.body(), rule_id=rule_id)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.put("/api/projects/{project_id}/business-rules/{rule_id}")
async def update_business_rule(project_id: uuid.UUID, rule_id: str, req: EditPayload,
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    project = await get_project_with_auth(project_id, user, db)
    body = req.body()
    expected = body.pop("revision", None)
    try:
        return await asyncio.to_thread(rules.update, _dir(project), rule_id, body,
                                       expected=expected, actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.patch("/api/projects/{project_id}/business-rules/{rule_id}/enabled")
async def toggle_business_rule(project_id: uuid.UUID, rule_id: str, req: EnabledPayload,
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.set_enabled, _dir(project), rule_id, req.enabled,
                                       expected=req.revision, actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.delete("/api/projects/{project_id}/business-rules/{rule_id}")
async def delete_business_rule(project_id: uuid.UUID, rule_id: str,
                               revision: str | None = Query(default=None),
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.remove, _dir(project), rule_id,
                                       expected=revision, actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/projects/{project_id}/business-rules/test")
async def test_business_rule(project_id: uuid.UUID, req: TestPayload,
                             user: PlatformUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """What the app would do with a sample save — by the app's own engine,
    with the draft among the record's other rules. Nothing is saved."""
    project = await get_project_with_auth(project_id, user, db)
    who = {"id": str(user.id), "email": user.email, "name": user.name or ""}
    try:
        return await asyncio.to_thread(
            rules.test_rule, _dir(project), req.rule.body() if req.rule else None, rule_id=req.rule_id,
            entity=req.entity, record=req.record, previous=req.previous, event=req.event, user=who)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.post("/api/projects/{project_id}/business-rules/{rule_id}/workflows")
async def attach_business_rule(project_id: uuid.UUID, rule_id: str, req: AttachPayload,
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Run the rule as a step of a workflow, after a step of it."""
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.attach, _dir(project), rule_id, workflow=req.workflow, path=req.path,
                                       after=req.after, on_refusal=req.on_refusal, actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.delete("/api/projects/{project_id}/business-rules/{rule_id}/workflows/{workflow_id}")
async def detach_business_rule(project_id: uuid.UUID, rule_id: str, workflow_id: str,
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.detach, _dir(project), rule_id, workflow=workflow_id,
                                       actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


class FollowPayload(BaseModel):
    step: str = Field(min_length=1, max_length=200)


@router.post("/api/projects/{project_id}/business-rules/{rule_id}/workflows/{workflow_id}/follow")
async def follow_business_rule(project_id: uuid.UUID, rule_id: str, workflow_id: str, req: FollowPayload,
                               user: PlatformUser = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    """Take a workflow's own check out, so the rule decides there."""
    project = await get_project_with_auth(project_id, user, db)
    try:
        return await asyncio.to_thread(rules.follow_rule, _dir(project), rule_id, workflow=workflow_id,
                                       step=req.step, actor=user.name or "")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@router.get("/api/projects/{project_id}/business-rules-links")
async def business_rule_links(project_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """For the workflow screens: the rules each save step of each workflow
    checks — ``{FLOW-id: {step key: [{rule, name}]}}``."""
    from services import rule_links
    from services.blueprint.service import BlueprintService
    project = await get_project_with_auth(project_id, user, db)
    out = _dir(project)
    if not rules.has_definition(out):
        return {"links": {}}
    try:
        svc = await asyncio.to_thread(BlueprintService.load, output_dir=str(out))
        return {"links": rule_links.workflow_links(svc.doc)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
