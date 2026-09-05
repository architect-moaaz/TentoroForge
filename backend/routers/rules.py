"""Rules & access control endpoints — CRUD for rules, app access policies, field access."""

import json
import uuid
from typing import Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgRole
from models.project import (
    AgentJob,
    AgentJobStatus,
    AgentType,
    Conversation,
    MessageRole,
    MessageType,
    Version,
)
from models.rules import AppAccessPolicy, FieldAccessPolicy, ProjectRule
from schemas.rules import (
    AccessPolicyCreate,
    AccessPolicyResponse,
    FieldAccessCreate,
    FieldAccessMatrixResponse,
    FieldAccessMatrixCell,
    FieldAccessResponse,
    FieldAccessUpdate,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
)
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from services.registry import load_registry
from services.validate_rules import validate_rules, format_rule_errors
from sse_helpers import sse_event, stream_agent_messages

router = APIRouter(tags=["rules"])

# The authoritative accept-list for a rule's `rule_type`. Two families:
#  - legacy / AI-authored: validation, access, business, computed, state_machine,
#    trigger + the 4 AI types;
#  - Business Rules editor (Power-Apps style): condition_action, decision_table.
# Dropping either editor type here silently breaks saving from the editor, so it
# is pinned by tests/test_rule_taxonomy.py. (The runtime engine's own type list
# and the agent's VALID_TYPES are narrower by design — see the plan doc.)
VALID_RULE_TYPES = {
    "validation", "access", "business", "computed", "state_machine", "trigger",
    "content_moderation", "similarity_check", "ai_validation", "ai_enrichment",
    "condition_action", "decision_table",
    # Row-level read access. `access` decides which COLUMNS come back;
    # `row_access` decides which ROWS the query returns at all, and the data
    # engine compiles its condition into the WHERE clause rather than filtering
    # afterwards — so the rows it hides are also absent from the count.
    "row_access",
}


# ---------------------------------------------------------------------------
# Rules CRUD
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/rules", response_model=list[RuleResponse])
async def list_rules(
    project_id: uuid.UUID,
    rule_type: str | None = None,
    model_name: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every rule for a project — the Blueprint's, then any authored by hand.

    THE BLUEPRINT IS THE LIVING DOCUMENT. `project_rules` is a table the
    Blueprint engine has never written, so a generated application answered
    `200 []` here while its Blueprint held thirteen business rules. The panel
    rendered an empty state, which is what an application with no rules also
    looks like, so nothing anywhere reported a problem.

    Read rather than synced. Copying the Blueprint into this table would give
    rules two homes and let them drift apart the moment either changed, which
    is the divergence §76 forbids — and `_sync_pages_from_app_model` next door
    is what that costs: a legacy bridge reachable from one router, leaving rows
    that are correct only until the Blueprint moves.

    Rows still answer for anything a person authored through POST. They come
    second so a hand-written rule can never be hidden by a generated one.
    """
    project = await get_project_with_auth(project_id, user, db)

    blueprint_rules: list[dict] = []
    if project.output_dir:
        try:
            from services.blueprint.service import BlueprintService
            from services.blueprint_to_editor import rules_from_blueprint
            svc = BlueprintService.load(output_dir=str(project.output_dir))
            blueprint_rules = rules_from_blueprint(
                svc.doc, project_id, project.output_dir)
        except FileNotFoundError:
            # No Blueprint — a legacy project, and the rows below are all it
            # ever had.
            pass
        # Filters apply to both sources or they mean different things
        # depending on where a rule came from.
        if rule_type:
            blueprint_rules = [r for r in blueprint_rules
                               if r["rule_type"] == rule_type]
        if model_name:
            blueprint_rules = [r for r in blueprint_rules
                               if r["model_name"] == model_name]

    stmt = select(ProjectRule).where(ProjectRule.project_id == project_id)
    if rule_type:
        stmt = stmt.where(ProjectRule.rule_type == rule_type)
    if model_name:
        stmt = stmt.where(ProjectRule.model_name == model_name)
    stmt = stmt.order_by(ProjectRule.created_at.desc())

    result = await db.execute(stmt)
    return blueprint_rules + [
        RuleResponse.model_validate(r) for r in result.scalars().all()
    ]


@router.post("/api/projects/{project_id}/rules", response_model=RuleResponse, status_code=201)
async def create_rule(
    project_id: uuid.UUID,
    req: RuleCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new rule for a project."""
    await get_project_with_auth(project_id, user, db)

    if req.rule_type not in VALID_RULE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid rule_type. Must be one of: {VALID_RULE_TYPES}",
        )

    rule = ProjectRule(
        project_id=project_id,
        name=req.name,
        rule_type=req.rule_type,
        model_name=req.model_name,
        field_name=req.field_name,
        config=req.config,
        is_active=req.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/api/projects/{project_id}/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single rule by ID."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(ProjectRule).where(
            ProjectRule.id == rule_id,
            ProjectRule.project_id == project_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


def _blueprint_rule(project: Any, project_id: Any,
                    rule_id: uuid.UUID) -> str | None:
    """The Blueprint rule this id stands for, or None if it is a real row.

    Writing to `project_rules` cannot change a rule the Blueprint owns: the
    row does not exist, so a PUT would 404 and read as "that rule is gone"
    rather than "that rule lives somewhere else". §76 asks for divergence to
    be named rather than silently resolved, and a 404 names nothing.
    """
    if not getattr(project, "output_dir", None):
        return None
    try:
        from services.blueprint.service import BlueprintService
        from services.blueprint_to_editor import derived_ids
        svc = BlueprintService.load(output_dir=str(project.output_dir))
        return derived_ids(svc.doc, project_id, "businessRules").get(rule_id)
    except FileNotFoundError:
        return None


def _refuse_blueprint_edit(artifact_id: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            f"{artifact_id} is defined in the Blueprint, which is the living "
            f"record of what this application is. Editing it here would write "
            f"a copy that the next generation overwrites. Ask Smith to change "
            f"it instead — the change lands in the Blueprint and the "
            f"application is rebuilt from it."
        ),
    )

@router.put("/api/projects/{project_id}/rules/{rule_id}", response_model=RuleResponse)
async def update_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    req: RuleUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing rule."""
    project = await get_project_with_auth(project_id, user, db)

    owned = _blueprint_rule(project, project_id, rule_id)
    if owned:
        raise _refuse_blueprint_edit(owned)

    result = await db.execute(
        select(ProjectRule).where(
            ProjectRule.id == rule_id,
            ProjectRule.project_id == project_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/api/projects/{project_id}/rules/{rule_id}", status_code=204)
async def delete_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a rule."""
    project = await get_project_with_auth(project_id, user, db)

    owned = _blueprint_rule(project, project_id, rule_id)
    if owned:
        raise _refuse_blueprint_edit(owned)

    result = await db.execute(
        select(ProjectRule).where(
            ProjectRule.id == rule_id,
            ProjectRule.project_id == project_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    await db.delete(rule)
    await db.commit()


@router.post("/api/projects/{project_id}/rules/{rule_id}/apply")
async def apply_rule(
    project_id: uuid.UUID,
    rule_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a rule to the generated app code via code_editor agent pipeline (SSE streaming)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    result = await db.execute(
        select(ProjectRule).where(
            ProjectRule.id == rule_id,
            ProjectRule.project_id == project_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Validate rule against registry before applying
    registry = load_registry(project.output_dir)
    if registry.get("entities"):
        rule_dict = {
            "name": rule.name,
            "rule_type": rule.rule_type,
            "model_name": rule.model_name,
            "field_name": rule.field_name,
            "config": rule.config,
        }
        rule_errors = validate_rules(registry["entities"], [rule_dict])
        blocking_errors = [e for e in rule_errors if e.severity == "error"]
        if blocking_errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Rule references invalid entities or fields",
                    "errors": [{"rule": e.rule_name, "error": e.error, "suggestion": e.suggestion} for e in blocking_errors],
                },
            )

    # Build instruction from rule
    instruction = _build_rule_instruction(rule)

    async def event_stream():
        yield sse_event("status", {"message": f"Applying rule: {rule.name}..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            from agents.code_editor import run_code_editor
            yield sse_event("status", {"message": "Editing code..."})

            async for evt in stream_agent_messages(
                run_code_editor(output_dir=project.output_dir, instruction=instruction),
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Validate
            from agents.validator import run_validator
            yield sse_event("status", {"message": "Validating build..."})

            async for evt in stream_agent_messages(
                run_validator(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Validator] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Index
            from agents.indexer import run_indexer
            yield sse_event("status", {"message": "Indexing application..."})

            async for evt in stream_agent_messages(
                run_indexer(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Indexer] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Git commit
            commit_hash = await git_commit(project.output_dir,
                f"rule: apply {rule.rule_type} rule '{rule.name}'",
            actor="editor")

            # Persist
            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction,
                    result={
                        "intent": "RULE_APPLY",
                        "rule_id": str(rule.id),
                        "rule_type": rule.rule_type,
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message=f"rule: apply {rule.rule_type} rule '{rule.name}'",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                assistant_msg = Conversation(
                    project_id=project.id,
                    role=MessageRole.assistant,
                    content=f"Applied {rule.rule_type} rule: {rule.name}",
                    message_type=MessageType.chat,
                    metadata_={
                        "intent": "RULE_APPLY",
                        "rule_id": str(rule.id),
                        "commit_hash": commit_hash,
                    },
                )
                sess.add(assistant_msg)
                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "rule_id": str(rule.id),
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


def _build_rule_instruction(rule: ProjectRule) -> str:
    """Convert a rule DB record to a natural language instruction for the code_editor agent."""
    config = rule.config or {}
    model = rule.model_name or "the relevant model"
    field = rule.field_name

    if rule.rule_type == "validation":
        condition = config.get("condition", {})
        error_msg = config.get("errorMessage", "Validation failed")
        enforcement = config.get("enforcement", ["api"])
        enforce_str = ", ".join(enforcement)
        parts = [f'Add a validation rule "{rule.name}" on model "{model}"']
        if field:
            parts.append(f'for field "{field}"')
        parts.append(f'with condition: {json.dumps(condition)}.')
        parts.append(f'Error message: "{error_msg}".')
        parts.append(f"Enforce at: {enforce_str}.")
        if "api" in enforcement:
            parts.append("Add server-side validation in the API route handler.")
        if "ui" in enforcement:
            parts.append("Add client-side validation in the form component.")
        if "db" in enforcement:
            parts.append("Add a database constraint or check.")
        return " ".join(parts)

    elif rule.rule_type == "access":
        actions = config.get("actions", {})
        parts = [f'Add access control rule "{rule.name}" on model "{model}".']
        for role_id, perms in actions.items():
            allowed = [a for a, v in perms.items() if v == "allow"]
            denied = [a for a, v in perms.items() if v == "deny"]
            if allowed:
                parts.append(f"Role {role_id}: allow {', '.join(allowed)}.")
            if denied:
                parts.append(f"Role {role_id}: deny {', '.join(denied)}.")
        parts.append("Add middleware or route guards to enforce these access rules.")
        return " ".join(parts)

    elif rule.rule_type == "business":
        trigger = config.get("triggerAction", "create/update")
        condition = config.get("condition", {})
        consequence = config.get("consequence", "")
        return (
            f'Add business rule "{rule.name}" on model "{model}". '
            f"Triggered on: {trigger}. "
            f"Condition: {json.dumps(condition)}. "
            f"Consequence: {consequence}. "
            f"Implement this logic in the API route handler for {trigger} operations."
        )

    elif rule.rule_type == "computed":
        target_field = field or config.get("targetField", "")
        expression = config.get("expression", "")
        return (
            f'Add computed field rule "{rule.name}" on model "{model}". '
            f'Field "{target_field}" should be computed as: {expression}. '
            f"Add a getter function or computed column. "
            f"Update the API to include this computed value in responses."
        )

    elif rule.rule_type == "state_machine":
        states = config.get("states", [])
        transitions = config.get("transitions", [])
        state_field = field or config.get("stateField", "status")
        parts = [f'Add state machine rule "{rule.name}" on model "{model}".']
        parts.append(f'State field: "{state_field}".')
        parts.append(f"States: {', '.join(states)}.")
        for t in transitions:
            cond = f" when {t.get('condition', '')}" if t.get("condition") else ""
            parts.append(f"Transition: {t['from']} -> {t['to']}{cond}.")
        parts.append("Add transition validation in the API update handler — reject invalid state transitions.")
        return " ".join(parts)

    elif rule.rule_type == "trigger":
        watch_field = field or config.get("watchField", "")
        condition = config.get("condition", {})
        action_desc = config.get("actionDescription", "")
        return (
            f'Add trigger rule "{rule.name}" on model "{model}". '
            f'Watch field: "{watch_field}". '
            f"Condition: {json.dumps(condition)}. "
            f"Action: {action_desc}. "
            f"Implement this as a post-save hook or event handler in the API."
        )

    elif rule.rule_type == "content_moderation":
        policy = config.get("policy", "No inappropriate content")
        action = config.get("moderationAction", "flag")
        enforcement = config.get("enforcement", ["api"])
        return (
            f'Add AI content moderation rule "{rule.name}" on model "{model}"'
            f'{f" field {field}" if field else ""}. '
            f"Policy: {policy}. "
            f"On violation: {action}. "
            f"Enforce at: {', '.join(enforcement)}. "
            f"Use the Anthropic SDK (claude-haiku) to evaluate content against the policy. "
            f"The LLM returns {{allowed: bool, reason: string, confidence: float}}. "
            f'If not allowed and action is "flag": mark record for review. '
            f'If "reject": return 400 with the reason. '
            f'If "redact": replace offending content with [REDACTED].'
        )

    elif rule.rule_type == "similarity_check":
        sim_fields = config.get("similarityFields", [])
        threshold = config.get("similarityThreshold", 0.85)
        action = config.get("similarityAction", "warn")
        return (
            f'Add AI similarity check rule "{rule.name}" on model "{model}". '
            f"Compare fields: {', '.join(sim_fields)}. "
            f"Threshold: {threshold}. "
            f"On duplicate: {action}. "
            f"On create, compute embedding of the new record's text fields, "
            f"query pgvector for records above the similarity threshold. "
            f'If found and action is "warn": return warning with similar records. '
            f'If "block": reject creation. '
            f'If "merge_suggest": return suggestion to merge with existing record.'
        )

    elif rule.rule_type == "ai_validation":
        prompt = config.get("aiValidationPrompt", "")
        val_fields = config.get("aiValidationFields", [])
        action = config.get("aiValidationAction", "flag")
        return (
            f'Add AI validation rule "{rule.name}" on model "{model}". '
            f"Validate fields: {', '.join(val_fields)}. "
            f"Validation prompt: {prompt}. "
            f"On failure: {action}. "
            f"Use the Anthropic SDK to evaluate the record data against the prompt. "
            f"The LLM returns {{valid: bool, reason: string, confidence: float}}. "
            f'If not valid: {"flag for review" if action == "flag" else "reject with reason"}.'
        )

    elif rule.rule_type == "ai_enrichment":
        trigger_field = config.get("aiEnrichTriggerField", "")
        enrich_fields = config.get("aiEnrichFields", [])
        prompt = config.get("aiEnrichPrompt", "")
        return (
            f'Add AI enrichment rule "{rule.name}" on model "{model}". '
            f'When field "{trigger_field}" is set/updated, automatically fill: {", ".join(enrich_fields)}. '
            f"Enrichment prompt: {prompt}. "
            f"Use the Anthropic SDK to generate the enriched values. "
            f"Run enrichment asynchronously (don't block the API response). "
            f"Update the record with the enriched values after computation."
        )

    return f"Apply rule '{rule.name}' of type '{rule.rule_type}' with config: {json.dumps(config)}"


# ---------------------------------------------------------------------------
# App Access Policies
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/access-policies", response_model=list[AccessPolicyResponse])
async def list_access_policies(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(AppAccessPolicy)
        .where(AppAccessPolicy.project_id == project_id)
        .order_by(AppAccessPolicy.created_at.desc())
    )
    return result.scalars().all()


@router.post("/api/projects/{project_id}/access-policies", response_model=AccessPolicyResponse, status_code=201)
async def create_access_policy(
    project_id: uuid.UUID,
    req: AccessPolicyCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)

    policy = AppAccessPolicy(
        project_id=project_id,
        target_type=req.target_type,
        target_id=req.target_id,
        access_level=req.access_level,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


@router.delete("/api/projects/{project_id}/access-policies/{policy_id}", status_code=204)
async def delete_access_policy(
    project_id: uuid.UUID,
    policy_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(AppAccessPolicy).where(
            AppAccessPolicy.id == policy_id,
            AppAccessPolicy.project_id == project_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Access policy not found")
    await db.delete(policy)
    await db.commit()


# ---------------------------------------------------------------------------
# Field Access Policies
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/field-access", response_model=list[FieldAccessResponse])
async def list_field_access(
    project_id: uuid.UUID,
    model_name: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    stmt = select(FieldAccessPolicy).where(FieldAccessPolicy.project_id == project_id)
    if model_name:
        stmt = stmt.where(FieldAccessPolicy.model_name == model_name)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/api/projects/{project_id}/field-access", response_model=FieldAccessResponse, status_code=201)
async def create_field_access(
    project_id: uuid.UUID,
    req: FieldAccessCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)

    # Upsert — update if exists for same project+model+field+target
    result = await db.execute(
        select(FieldAccessPolicy).where(
            FieldAccessPolicy.project_id == project_id,
            FieldAccessPolicy.model_name == req.model_name,
            FieldAccessPolicy.field_name == req.field_name,
            FieldAccessPolicy.target_type == req.target_type,
            FieldAccessPolicy.target_id == req.target_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.can_view = req.can_view
        existing.can_edit = req.can_edit
        existing.condition = req.condition
        await db.commit()
        await db.refresh(existing)
        return existing

    policy = FieldAccessPolicy(
        project_id=project_id,
        model_name=req.model_name,
        field_name=req.field_name,
        target_type=req.target_type,
        target_id=req.target_id,
        can_view=req.can_view,
        can_edit=req.can_edit,
        condition=req.condition,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


@router.put("/api/projects/{project_id}/field-access/{policy_id}", response_model=FieldAccessResponse)
async def update_field_access(
    project_id: uuid.UUID,
    policy_id: uuid.UUID,
    req: FieldAccessUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(FieldAccessPolicy).where(
            FieldAccessPolicy.id == policy_id,
            FieldAccessPolicy.project_id == project_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Field access policy not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)

    await db.commit()
    await db.refresh(policy)
    return policy


@router.delete("/api/projects/{project_id}/field-access/{policy_id}", status_code=204)
async def delete_field_access(
    project_id: uuid.UUID,
    policy_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(FieldAccessPolicy).where(
            FieldAccessPolicy.id == policy_id,
            FieldAccessPolicy.project_id == project_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Field access policy not found")
    await db.delete(policy)
    await db.commit()


@router.get("/api/projects/{project_id}/field-access/matrix", response_model=FieldAccessMatrixResponse)
async def get_field_access_matrix(
    project_id: uuid.UUID,
    model_name: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full field access matrix for a model: fields × roles."""
    project = await get_project_with_auth(project_id, user, db)

    # Get all org roles for the project's org
    roles_result = await db.execute(
        select(OrgRole).where(OrgRole.org_id == project.org_id)
    )
    roles = roles_result.scalars().all()
    targets = [{"id": str(r.id), "type": "role", "name": r.name} for r in roles]

    # Get field names from app-model.json
    from pathlib import Path
    import json as json_module
    fields: list[str] = []
    if project.output_dir:
        model_path = Path(project.output_dir) / "app-model.json"
        if model_path.exists():
            app_model = json_module.loads(model_path.read_text())
            for table in app_model.get("database", {}).get("tables", []):
                if table.get("name") == model_name:
                    fields = [col["name"] for col in table.get("columns", [])]
                    break

    # Get existing policies
    result = await db.execute(
        select(FieldAccessPolicy).where(
            FieldAccessPolicy.project_id == project_id,
            FieldAccessPolicy.model_name == model_name,
        )
    )
    policies = result.scalars().all()

    # Build cells
    cells: list[FieldAccessMatrixCell] = []
    policy_map = {
        (p.field_name, str(p.target_id), p.target_type): p for p in policies
    }
    for field_name in fields:
        for target in targets:
            key = (field_name, target["id"], target["type"])
            if key in policy_map:
                p = policy_map[key]
                cells.append(FieldAccessMatrixCell(
                    field_name=field_name,
                    target_id=uuid.UUID(target["id"]),
                    target_type=target["type"],
                    can_view=p.can_view,
                    can_edit=p.can_edit,
                ))
            else:
                # Default: full access
                cells.append(FieldAccessMatrixCell(
                    field_name=field_name,
                    target_id=uuid.UUID(target["id"]),
                    target_type=target["type"],
                    can_view=True,
                    can_edit=True,
                ))

    return FieldAccessMatrixResponse(
        model_name=model_name,
        fields=fields,
        targets=targets,
        cells=cells,
    )


@router.post("/api/projects/{project_id}/field-access/apply")
async def apply_field_access(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply field access policies as RBAC middleware in the generated app (SSE streaming)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    # Load all field access policies for this project
    result = await db.execute(
        select(FieldAccessPolicy).where(FieldAccessPolicy.project_id == project_id)
    )
    policies = result.scalars().all()

    if not policies:
        raise HTTPException(status_code=400, detail="No field access policies to apply")

    # Build RBAC instruction
    instruction = _build_field_access_instruction(policies)

    async def event_stream():
        yield sse_event("status", {"message": "Applying field access RBAC..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            from agents.code_editor import run_code_editor
            yield sse_event("status", {"message": "Generating RBAC middleware..."})

            async for evt in stream_agent_messages(
                run_code_editor(output_dir=project.output_dir, instruction=instruction),
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            from agents.validator import run_validator
            yield sse_event("status", {"message": "Validating build..."})

            async for evt in stream_agent_messages(
                run_validator(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Validator] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            from agents.indexer import run_indexer
            yield sse_event("status", {"message": "Indexing application..."})

            async for evt in stream_agent_messages(
                run_indexer(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Indexer] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            commit_hash = await git_commit(project.output_dir,
                "rbac: apply field-level access control",
            actor="editor")

            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "RBAC_APPLY",
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message="rbac: apply field-level access control",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


def _build_field_access_instruction(policies: list[FieldAccessPolicy]) -> str:
    """Convert field access policies to a natural language RBAC instruction."""
    # Group by model
    models: dict[str, list[FieldAccessPolicy]] = {}
    for p in policies:
        models.setdefault(p.model_name, []).append(p)

    parts = [
        "Implement field-level RBAC (Role-Based Access Control) middleware for the application.",
        "Create or update an RBAC middleware that filters API response fields based on the user's role.",
        "",
    ]

    for model_name, model_policies in models.items():
        parts.append(f'For model "{model_name}":')
        # Group by target
        by_target: dict[str, list[FieldAccessPolicy]] = {}
        for p in model_policies:
            key = f"{p.target_type}:{p.target_id}"
            by_target.setdefault(key, []).append(p)

        for target_key, target_policies in by_target.items():
            hidden = [p.field_name for p in target_policies if not p.can_view]
            readonly = [p.field_name for p in target_policies if p.can_view and not p.can_edit]
            if hidden:
                parts.append(f"  - {target_key}: hide fields {', '.join(hidden)}")
            if readonly:
                parts.append(f"  - {target_key}: read-only fields {', '.join(readonly)}")
        parts.append("")

    parts.extend([
        "Implementation requirements:",
        "1. Create a middleware function that checks the current user's role",
        "2. Filter out hidden fields from API responses (GET endpoints)",
        "3. Reject updates to read-only fields (PUT/PATCH endpoints)",
        "4. Create a /api/me/permissions endpoint that returns the current user's field permissions",
        "5. Export a useFieldPermissions React hook that fetches permissions for UI conditional rendering",
    ])

    return "\n".join(parts)
