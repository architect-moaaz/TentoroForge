"""Portal endpoints — aggregated dashboard data, export, and monitoring."""

import json
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from textwrap import dedent

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMember, InviteStatus, Department
from models.project import Project, ProjectStatus, AgentJob, Version
from schemas.portal import (
    PortalApp,
    PortalAppBadges,
    PortalTask,
    PortalActivity,
    PortalDashboard,
    PortalStats,
    SuggestedApp,
    ExportRequest,
    ProjectCostSummary,
    CostEntry,
    ErrorLogEntry,
)
from services.project_service import get_project_with_auth

router = APIRouter(tags=["portal"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_org_member(
    org_id: uuid.UUID,
    user: PlatformUser,
    db: AsyncSession,
) -> OrgMember:
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return membership


# ---------------------------------------------------------------------------
# Portal dashboard
# ---------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/portal/dashboard")
async def get_portal_dashboard(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate portal data: apps, pending tasks, activity feed."""
    await _require_org_member(org_id, user, db)

    # Fetch all org projects
    result = await db.execute(
        select(Project).where(
            Project.org_id == org_id,
            Project.status != ProjectStatus.archived,
        )
    )
    projects = result.scalars().all()

    apps: list[dict] = []
    tasks: list[dict] = []
    activity: list[dict] = []

    for project in projects:
        # Count pending agent jobs as "tasks"
        job_count_result = await db.execute(
            select(func.count(AgentJob.id)).where(
                AgentJob.project_id == project.id,
                AgentJob.status.in_(["pending", "running"]),
            )
        )
        pending_tasks = job_count_result.scalar() or 0

        # Count recent versions as activity
        version_result = await db.execute(
            select(Version)
            .where(Version.project_id == project.id)
            .order_by(Version.created_at.desc())
            .limit(5)
        )
        recent_versions = version_result.scalars().all()

        apps.append(
            PortalApp(
                id=str(project.id),
                name=project.name,
                description=project.description,
                status=project.status.value if hasattr(project.status, "value") else str(project.status),
                preview_port=project.preview_port,
                badges=PortalAppBadges(
                    pending_tasks=pending_tasks,
                    alerts=0,
                    new_items=len(recent_versions),
                ),
            ).model_dump()
        )

        # Add pending jobs as tasks
        pending_result = await db.execute(
            select(AgentJob)
            .where(
                AgentJob.project_id == project.id,
                AgentJob.status.in_(["pending", "running"]),
            )
            .order_by(AgentJob.created_at.desc())
            .limit(5)
        )
        for job in pending_result.scalars().all():
            tasks.append(
                PortalTask(
                    id=str(job.id),
                    app_id=str(project.id),
                    app_name=project.name,
                    title=f"{job.agent_type} job",
                    description=job.instruction,
                    status="pending" if job.status.value == "pending" else "claimed",
                    assignee_type="person",
                    created_at=job.created_at.isoformat() if job.created_at else "",
                ).model_dump()
            )

        # Add recent versions as activity
        for version in recent_versions:
            activity.append(
                PortalActivity(
                    id=str(version.id),
                    app_id=str(project.id),
                    app_name=project.name,
                    type="data_change",
                    title=version.message or "Code update",
                    created_at=version.created_at.isoformat() if version.created_at else "",
                ).model_dump()
            )

    # Sort activity by date descending
    activity.sort(key=lambda a: a.get("created_at", ""), reverse=True)

    return PortalDashboard(
        apps=apps,
        tasks=tasks[:20],
        activity=activity[:30],
    ).model_dump()


# ---------------------------------------------------------------------------
# Portal — Apps list
# ---------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/portal/apps")
async def list_portal_apps(
    org_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all apps in the org with optional search/filter."""
    await _require_org_member(org_id, user, db)

    query = select(Project).where(
        Project.org_id == org_id,
        Project.status != ProjectStatus.archived,
    )
    if status:
        try:
            query = query.where(Project.status == ProjectStatus(status))
        except ValueError:
            pass
    query = query.order_by(Project.updated_at.desc())

    result = await db.execute(query)
    projects = result.scalars().all()

    apps: list[dict] = []
    for project in projects:
        if search:
            term = search.lower()
            name_match = term in project.name.lower()
            desc_match = project.description and term in project.description.lower()
            if not name_match and not desc_match:
                continue

        job_count_result = await db.execute(
            select(func.count(AgentJob.id)).where(
                AgentJob.project_id == project.id,
                AgentJob.status.in_(["pending", "running"]),
            )
        )
        pending_tasks = job_count_result.scalar() or 0

        version_count_result = await db.execute(
            select(func.count(Version.id)).where(
                Version.project_id == project.id,
            )
        )
        version_count = version_count_result.scalar() or 0

        apps.append(
            PortalApp(
                id=str(project.id),
                name=project.name,
                description=project.description,
                status=project.status.value if hasattr(project.status, "value") else str(project.status),
                preview_port=project.preview_port,
                badges=PortalAppBadges(
                    pending_tasks=pending_tasks,
                    alerts=0,
                    new_items=version_count,
                ),
            ).model_dump()
        )

    return {"apps": apps, "total": len(apps)}


# ---------------------------------------------------------------------------
# Portal — Unified task inbox
# ---------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/portal/tasks")
async def list_portal_tasks(
    org_id: uuid.UUID,
    app_id: str | None = None,
    status: str | None = None,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unified task inbox across all apps."""
    await _require_org_member(org_id, user, db)

    # Get org projects, optionally filtered by app_id
    proj_query = select(Project).where(
        Project.org_id == org_id,
        Project.status != ProjectStatus.archived,
    )
    if app_id:
        try:
            proj_query = proj_query.where(Project.id == uuid.UUID(app_id))
        except ValueError:
            pass

    result = await db.execute(proj_query)
    projects = result.scalars().all()

    tasks: list[dict] = []
    for project in projects:
        job_statuses = ["pending", "running"]
        if status == "completed":
            job_statuses = ["completed"]
        elif status == "failed":
            job_statuses = ["failed"]

        pending_result = await db.execute(
            select(AgentJob)
            .where(
                AgentJob.project_id == project.id,
                AgentJob.status.in_(job_statuses),
            )
            .order_by(AgentJob.created_at.desc())
            .limit(50)
        )
        for job in pending_result.scalars().all():
            tasks.append(
                PortalTask(
                    id=str(job.id),
                    app_id=str(project.id),
                    app_name=project.name,
                    title=f"{job.agent_type} job",
                    description=job.instruction,
                    status="pending" if job.status.value == "pending" else "claimed",
                    assignee_type="person",
                    created_at=job.created_at.isoformat() if job.created_at else "",
                ).model_dump()
            )

    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return {"tasks": tasks[:100], "total": len(tasks)}


# ---------------------------------------------------------------------------
# Portal — Activity feed
# ---------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/portal/activity")
async def list_portal_activity(
    org_id: uuid.UUID,
    app_id: str | None = None,
    limit: int = 50,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cross-app activity feed."""
    await _require_org_member(org_id, user, db)

    proj_query = select(Project).where(
        Project.org_id == org_id,
        Project.status != ProjectStatus.archived,
    )
    if app_id:
        try:
            proj_query = proj_query.where(Project.id == uuid.UUID(app_id))
        except ValueError:
            pass

    result = await db.execute(proj_query)
    projects = result.scalars().all()

    activity: list[dict] = []
    per_project_limit = max(10, limit // max(len(projects), 1))

    for project in projects:
        # Recent versions as activity
        version_result = await db.execute(
            select(Version)
            .where(Version.project_id == project.id)
            .order_by(Version.created_at.desc())
            .limit(per_project_limit)
        )
        for version in version_result.scalars().all():
            activity.append(
                PortalActivity(
                    id=str(version.id),
                    app_id=str(project.id),
                    app_name=project.name,
                    type="data_change",
                    title=version.message or "Code update",
                    created_at=version.created_at.isoformat() if version.created_at else "",
                ).model_dump()
            )

        # Completed jobs as activity
        job_result = await db.execute(
            select(AgentJob)
            .where(
                AgentJob.project_id == project.id,
                AgentJob.status.in_(["completed", "failed"]),
            )
            .order_by(AgentJob.created_at.desc())
            .limit(per_project_limit)
        )
        for job in job_result.scalars().all():
            activity.append(
                PortalActivity(
                    id=str(job.id),
                    app_id=str(project.id),
                    app_name=project.name,
                    type="task_completed" if job.status.value == "completed" else "alert",
                    title=f"{job.agent_type} job {'completed' if job.status.value == 'completed' else 'failed'}",
                    description=job.instruction,
                    created_at=job.created_at.isoformat() if job.created_at else "",
                ).model_dump()
            )

    activity.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return {"activity": activity[:limit], "total": len(activity)}


# ---------------------------------------------------------------------------
# Portal — Dashboard stats
# ---------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/portal/stats")
async def get_portal_stats(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard summary stats."""
    await _require_org_member(org_id, user, db)

    # Total apps (non-archived)
    total_apps_result = await db.execute(
        select(func.count(Project.id)).where(
            Project.org_id == org_id,
            Project.status != ProjectStatus.archived,
        )
    )
    total_apps = total_apps_result.scalar() or 0

    # Active apps (ready status)
    active_apps_result = await db.execute(
        select(func.count(Project.id)).where(
            Project.org_id == org_id,
            Project.status == ProjectStatus.ready,
        )
    )
    active_apps = active_apps_result.scalar() or 0

    # Pending tasks across all projects
    project_ids_result = await db.execute(
        select(Project.id).where(
            Project.org_id == org_id,
            Project.status != ProjectStatus.archived,
        )
    )
    project_ids = [r for r in project_ids_result.scalars().all()]

    pending_tasks = 0
    total_versions = 0
    if project_ids:
        pending_result = await db.execute(
            select(func.count(AgentJob.id)).where(
                AgentJob.project_id.in_(project_ids),
                AgentJob.status.in_(["pending", "running"]),
            )
        )
        pending_tasks = pending_result.scalar() or 0

        versions_result = await db.execute(
            select(func.count(Version.id)).where(
                Version.project_id.in_(project_ids),
            )
        )
        total_versions = versions_result.scalar() or 0

    # Suggested apps: departments without associated projects
    dept_result = await db.execute(
        select(Department).where(Department.org_id == org_id)
    )
    departments = dept_result.scalars().all()

    # Get all project names for simple matching
    proj_names_result = await db.execute(
        select(Project.name).where(
            Project.org_id == org_id,
            Project.status != ProjectStatus.archived,
        )
    )
    project_names = {n.lower() for n in proj_names_result.scalars().all()}

    suggestions: list[dict] = []
    for dept in departments:
        # Simple heuristic: if no project name contains the department name
        dept_lower = dept.name.lower()
        has_app = any(dept_lower in pname for pname in project_names)
        if not has_app:
            suggestions.append(
                SuggestedApp(
                    department_id=str(dept.id),
                    department_name=dept.name,
                    suggestion=f"Create an app for the {dept.name} department",
                ).model_dump()
            )

    return {
        "stats": PortalStats(
            total_apps=total_apps,
            active_apps=active_apps,
            pending_tasks=pending_tasks,
            total_versions=total_versions,
            recent_activity_count=0,
        ).model_dump(),
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Export — ZIP with README
# ---------------------------------------------------------------------------

def _generate_readme(project_name: str, project_desc: str | None) -> str:
    return dedent(f"""\
        # {project_name}

        {project_desc or "Generated with Tentoro Forge."}

        ## Getting Started

        ### Prerequisites
        - Node.js 18+
        - PostgreSQL 15+
        - pnpm (or npm)

        ### Setup

        1. Install dependencies:
           ```bash
           pnpm install
           ```

        2. Copy environment variables:
           ```bash
           cp .env.example .env
           ```

        3. Update `.env` with your database credentials.

        4. Run database migrations:
           ```bash
           pnpm db:push
           ```

        5. Start the development server:
           ```bash
           pnpm dev
           ```

        ### Environment Variables

        | Variable | Description | Default |
        |----------|-------------|---------|
        | `DATABASE_URL` | PostgreSQL connection string | — |
        | `NEXTAUTH_SECRET` | Auth secret (generate with `openssl rand -base64 32`) | — |
        | `NEXTAUTH_URL` | App URL | `http://localhost:3000` |

        ## Project Structure

        ```
        src/
        ├── app/          # Next.js App Router pages
        ├── components/   # React components
        ├── db/           # Drizzle schema and migrations
        ├── lib/          # Utility functions
        └── styles/       # Global styles
        ```

        ## Deployment

        ### Docker

        ```bash
        docker compose up -d
        ```

        ### Manual

        ```bash
        pnpm build
        pnpm start
        ```

        ---
        Generated by [Tentoro Forge](https://tentoroforge.dev)
    """)


def _generate_env_example() -> str:
    return dedent("""\
        # Database
        DATABASE_URL=postgresql://user:password@localhost:5432/myapp

        # Auth
        NEXTAUTH_SECRET=change-me-to-a-random-string
        NEXTAUTH_URL=http://localhost:3000

        # Optional: AI features
        ANTHROPIC_API_KEY=sk-ant-...

        # Optional: Embeddings for semantic search
        OPENAI_API_KEY=sk-...
    """)


def _generate_dockerfile() -> str:
    return dedent("""\
        FROM node:20-alpine AS base

        # Install dependencies
        FROM base AS deps
        WORKDIR /app
        COPY package.json pnpm-lock.yaml* ./
        RUN corepack enable && pnpm install --frozen-lockfile

        # Build
        FROM base AS builder
        WORKDIR /app
        COPY --from=deps /app/node_modules ./node_modules
        COPY . .
        ENV NEXT_TELEMETRY_DISABLED=1
        RUN corepack enable && pnpm build

        # Production
        FROM base AS runner
        WORKDIR /app
        ENV NODE_ENV=production
        ENV NEXT_TELEMETRY_DISABLED=1

        RUN addgroup --system --gid 1001 nodejs
        RUN adduser --system --uid 1001 nextjs

        COPY --from=builder /app/public ./public
        COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
        COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

        USER nextjs
        EXPOSE 3000
        ENV PORT=3000
        ENV HOSTNAME="0.0.0.0"

        CMD ["node", "server.js"]
    """)


def _generate_docker_compose(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-").replace("_", "-")
    return dedent(f"""\
        version: "3.8"

        services:
          app:
            build: .
            ports:
              - "3000:3000"
            environment:
              - DATABASE_URL=postgresql://postgres:postgres@db:5432/{slug}
              - NEXTAUTH_SECRET=${{NEXTAUTH_SECRET}}
              - NEXTAUTH_URL=http://localhost:3000
            depends_on:
              db:
                condition: service_healthy

          db:
            image: pgvector/pgvector:pg16
            environment:
              POSTGRES_DB: {slug}
              POSTGRES_USER: postgres
              POSTGRES_PASSWORD: postgres
            ports:
              - "5432:5432"
            volumes:
              - pgdata:/var/lib/postgresql/data
            healthcheck:
              test: ["CMD-SHELL", "pg_isready -U postgres"]
              interval: 5s
              timeout: 5s
              retries: 5

        volumes:
          pgdata:
    """)


@router.post("/api/projects/{project_id}/export")
async def export_project(
    project_id: uuid.UUID,
    req: ExportRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export a project as ZIP with optional README, Dockerfile, docker-compose."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no generated code")

    project_dir = Path(project.output_dir)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    if req.format == "dockerfile":
        # Return just the Dockerfile content
        dockerfile = _generate_dockerfile()
        compose = _generate_docker_compose(project.name) if req.include_docker_compose else None
        return {
            "format": "dockerfile",
            "dockerfile": dockerfile,
            "docker_compose": compose,
        }

    # ZIP export
    buf = BytesIO()
    slug = project.name.lower().replace(" ", "-").replace("_", "-") or "app"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add all project files
        for path in sorted(project_dir.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(project_dir))
                # Skip node_modules, .git, .next
                if any(part in rel.split("/") for part in ["node_modules", ".git", ".next", "__pycache__"]):
                    continue
                zf.write(path, f"{slug}/{rel}")

        # Add README
        if req.include_readme:
            readme = _generate_readme(project.name, project.description)
            zf.writestr(f"{slug}/README.md", readme)

        # Add .env.example
        if req.include_env_example:
            env_example = _generate_env_example()
            zf.writestr(f"{slug}/.env.example", env_example)

        # Add Dockerfile + docker-compose
        if req.include_docker_compose:
            zf.writestr(f"{slug}/Dockerfile", _generate_dockerfile())
            zf.writestr(f"{slug}/docker-compose.yml", _generate_docker_compose(project.name))

        # Add .gitignore
        gitignore = "node_modules/\n.next/\n.env\n.env.local\n*.log\n"
        zf.writestr(f"{slug}/.gitignore", gitignore)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={slug}.zip"},
    )


# ---------------------------------------------------------------------------
# Monitoring — Cost tracking
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/monitoring/costs")
async def get_project_costs(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get cost tracking data for a project."""
    project = await get_project_with_auth(project_id, user, db)

    # Aggregate costs from completed agent jobs
    result = await db.execute(
        select(AgentJob)
        .where(
            AgentJob.project_id == project.id,
            AgentJob.status == "completed",
        )
        .order_by(AgentJob.created_at.desc())
    )
    jobs = result.scalars().all()

    total_cost = 0.0
    total_input = 0
    total_output = 0
    by_agent: dict[str, dict] = {}
    daily: dict[str, dict] = {}

    for job in jobs:
        meta = job.result or {}
        cost = float(meta.get("cost_usd", 0))
        inp = int(meta.get("input_tokens", 0))
        out = int(meta.get("output_tokens", 0))

        total_cost += cost
        total_input += inp
        total_output += out

        agent_type = job.agent_type or "unknown"
        if agent_type not in by_agent:
            by_agent[agent_type] = {"cost_usd": 0, "calls": 0}
        by_agent[agent_type]["cost_usd"] += cost
        by_agent[agent_type]["calls"] += 1

        if job.created_at:
            day = job.created_at.strftime("%Y-%m-%d")
            if day not in daily:
                daily[day] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0}
            daily[day]["input_tokens"] += inp
            daily[day]["output_tokens"] += out
            daily[day]["cost_usd"] += cost

    daily_list = [
        CostEntry(
            date=d,
            input_tokens=v["input_tokens"],
            output_tokens=v["output_tokens"],
            cost_usd=v["cost_usd"],
        ).model_dump()
        for d, v in sorted(daily.items())
    ]

    return ProjectCostSummary(
        project_id=str(project.id),
        total_cost_usd=round(total_cost, 4),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        daily=daily_list,
        by_agent=by_agent,
    ).model_dump()


# ---------------------------------------------------------------------------
# Monitoring — Error logs
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/monitoring/errors")
async def get_project_errors(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get error logs for a project (failed agent jobs, build failures)."""
    project = await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(AgentJob)
        .where(
            AgentJob.project_id == project.id,
            AgentJob.status == "failed",
        )
        .order_by(AgentJob.created_at.desc())
        .limit(50)
    )
    jobs = result.scalars().all()

    errors = []
    for job in jobs:
        errors.append(
            ErrorLogEntry(
                id=str(job.id),
                project_id=str(project.id),
                type="agent_failure",
                message=job.error_message or "Unknown error",
                agent_type=job.agent_type,
                resolved=False,
                created_at=job.created_at.isoformat() if job.created_at else "",
            ).model_dump()
        )

    return {"errors": errors, "total": len(errors)}
