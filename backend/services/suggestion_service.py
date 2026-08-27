"""Template suggestion engine — scores templates against org departments."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.org import Department, Organization
from models.project import Project
from models.template import AppTemplate


def _normalize(name: str) -> str:
    """Lowercase, strip whitespace for fuzzy matching."""
    return name.lower().strip()


def _dept_match_score(dept_name: str, relevant_departments: list[str]) -> float:
    """Score how well a department name matches a template's relevant departments.

    Returns 1.0 for exact match, 0.5 for partial/substring match, 0 otherwise.
    """
    norm_dept = _normalize(dept_name)
    for rd in relevant_departments:
        norm_rd = _normalize(rd)
        if norm_dept == norm_rd:
            return 1.0
        if norm_dept in norm_rd or norm_rd in norm_dept:
            return 0.5
    return 0.0


async def get_suggested_templates(
    org_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 8,
) -> list[dict]:
    """Score and rank templates based on the org's departments.

    Scoring:
    - Each template gets a score from matching its relevant_departments against org departments
    - Templates already used (have a project with same name in the org) are deprioritized
    - Higher score = more relevant suggestion

    Returns list of dicts: {template, score, matching_departments, reason}
    """
    # Fetch org departments
    dept_result = await db.execute(
        select(Department).where(Department.org_id == org_id)
    )
    departments = dept_result.scalars().all()
    dept_names = [d.name for d in departments]

    # Fetch all published templates
    tmpl_result = await db.execute(
        select(AppTemplate).where(AppTemplate.is_published == True)
    )
    templates = tmpl_result.scalars().all()

    # Fetch existing project names to detect already-covered areas
    proj_result = await db.execute(
        select(Project.name).where(Project.org_id == org_id)
    )
    existing_names = {_normalize(row[0]) for row in proj_result.all()}

    scored: list[dict] = []

    for tmpl in templates:
        relevant = tmpl.relevant_departments or []
        if not relevant:
            continue

        # Score against each department
        best_matches: list[tuple[str, float]] = []
        for dept_name in dept_names:
            score = _dept_match_score(dept_name, relevant)
            if score > 0:
                best_matches.append((dept_name, score))

        if not best_matches:
            continue

        # Total score is sum of match scores
        total_score = sum(s for _, s in best_matches)
        matching_depts = [d for d, _ in best_matches]

        # Deprioritize if a project with a similar name already exists
        if _normalize(tmpl.name) in existing_names:
            total_score *= 0.2

        reason = f"Relevant for {', '.join(matching_depts)}"

        scored.append({
            "template": tmpl,
            "score": round(total_score, 2),
            "matching_departments": matching_depts,
            "reason": reason,
        })

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
