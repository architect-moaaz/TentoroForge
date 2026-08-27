"""Background job for code generation — moves long-running agent work off the request thread."""

import uuid
import logging
from datetime import datetime, timezone

from jobs.worker import register_job

logger = logging.getLogger(__name__)


@register_job("generate_app")
async def generate_app_job(
    project_id: str,
    description: str,
    plan: dict | None = None,
    output_dir: str | None = None,
) -> dict:
    """Generate an app in the background. Stores results in the AgentJob table."""
    from database import async_session
    from models.project import (
        AgentJob,
        AgentJobStatus,
        AgentType,
        Version,
    )
    from agents.code_generator import run_code_generator
    from services.git_service import git_commit
    from services.agent_messages import ResultMessage

    pid = uuid.UUID(project_id)

    async with async_session() as db:
        # Create agent job record
        job = AgentJob(
            project_id=pid,
            agent_type=AgentType.code_generator,
            status=AgentJobStatus.running,
            instruction=description[:500],
            started_at=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

    result_msg = None
    try:
        async for message in run_code_generator(
            output_dir=output_dir or f"/app/output/{project_id}",
            description=description,
            plan=plan,
        ):
            if isinstance(message, ResultMessage):
                result_msg = message

        # Commit generated code
        commit_hash = await git_commit(
            output_dir or f"/app/output/{project_id}",
            "feat: generate application from description",
        )

        async with async_session() as db:
            # Update job as completed
            from sqlalchemy import update
            await db.execute(
                update(AgentJob)
                .where(AgentJob.id == job.id)
                .values(
                    status=AgentJobStatus.completed,
                    completed_at=datetime.now(timezone.utc),
                    result={
                        "cost_usd": result_msg.total_cost_usd if result_msg else 0,
                        "num_turns": result_msg.num_turns if result_msg else 0,
                        "duration_ms": result_msg.duration_ms if result_msg else 0,
                        "commit_hash": commit_hash,
                    },
                )
            )

            if commit_hash:
                version = Version(
                    project_id=pid,
                    commit_hash=commit_hash,
                    message="feat: generate application from description",
                    agent_job_id=job.id,
                )
                db.add(version)

            await db.commit()

        return {
            "status": "completed",
            "commit_hash": commit_hash,
            "cost_usd": result_msg.total_cost_usd if result_msg else 0,
        }

    except Exception as e:
        logger.exception("Generation job failed for project %s", project_id)
        async with async_session() as db:
            from sqlalchemy import update
            await db.execute(
                update(AgentJob)
                .where(AgentJob.id == job.id)
                .values(
                    status=AgentJobStatus.failed,
                    completed_at=datetime.now(timezone.utc),
                    error_message=str(e),
                )
            )
            await db.commit()

        return {"status": "failed", "error": str(e)}
