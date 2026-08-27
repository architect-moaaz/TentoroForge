"""Project lifecycle service — create, retrieve, authorize."""

import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import PlatformUser
from models.org import OrgMember, OrgMemberRole, InviteStatus
from models.project import Project, ProjectStatus, _generate_short_id

OUTPUT_BASE = Path(__file__).parent.parent.parent / "output"
OUTPUT_BASE.mkdir(exist_ok=True)


async def create_project(
    org_id: uuid.UUID,
    owner_id: uuid.UUID,
    name: str,
    description: str | None,
    db: AsyncSession,
) -> Project:
    """Create a new project with output directory and git init."""
    short_id = _generate_short_id()
    output_dir = str(OUTPUT_BASE / short_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    project = Project(
        org_id=org_id,
        owner_id=owner_id,
        name=name,
        description=description,
        short_id=short_id,
        output_dir=output_dir,
        status=ProjectStatus.draft,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    # Git init the output directory
    from services.git_service import git_init
    await git_init(output_dir)

    return project


# Matches a trailing " (Copy)" or " (Copy N)" so we can strip it before
# re-suffixing — otherwise duplicating a duplicate stacks "(Copy)(Copy)".
_COPY_SUFFIX_RE = re.compile(r"^(?P<base>.*?)\s*\(Copy(?:\s+(?P<n>\d+))?\)\s*$")


def _strip_copy_suffix(name: str) -> str:
    m = _COPY_SUFFIX_RE.match(name or "")
    return m.group("base").strip() if m else (name or "").strip()


async def _unique_copy_name(source: Project, db: AsyncSession) -> str:
    """BUG-007: build the duplicate's name without stacking "(Copy)(Copy)".

    Strips any existing "(Copy)"/"(Copy N)" suffix to get the base, then picks
    the first free "<base> (Copy)", "<base> (Copy 2)", … that no sibling project
    in the same org already uses. So:
      Notes App            -> Notes App (Copy)        (or (Copy 2) if that's taken)
      Notes App (Copy)     -> Notes App (Copy 2)
      Notes App (Copy 2)   -> Notes App (Copy 3)
    """
    base = _strip_copy_suffix(source.name)
    result = await db.execute(
        select(Project.name).where(Project.org_id == source.org_id)
    )
    existing = {row[0] for row in result.all()}
    candidate = f"{base} (Copy)"
    n = 1
    while candidate in existing:
        n += 1
        candidate = f"{base} (Copy {n})"
    return candidate


async def copy_project(
    source: Project,
    db: AsyncSession,
) -> Project:
    """Duplicate a project: copy metadata, files, and git-init the new dir."""
    short_id = _generate_short_id()
    output_dir = str(OUTPUT_BASE / short_id)
    copy_name = await _unique_copy_name(source, db)

    # Copy files, excluding heavy directories
    if source.output_dir and Path(source.output_dir).exists():
        shutil.copytree(
            source.output_dir,
            output_dir,
            ignore=shutil.ignore_patterns("node_modules", ".next", ".git"),
        )
    else:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    project = Project(
        org_id=source.org_id,
        owner_id=source.owner_id,
        name=copy_name,
        description=source.description,
        short_id=short_id,
        output_dir=output_dir,
        status=ProjectStatus.draft,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    # Git init the new output directory
    from services.git_service import git_init
    await git_init(output_dir)

    return project


async def get_project_with_auth(
    project_id: uuid.UUID,
    user: PlatformUser,
    db: AsyncSession,
) -> Project:
    """Fetch a project and verify the user has access via org membership."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify user is member of the project's org
    membership = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == project.org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    if not membership.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    return project
