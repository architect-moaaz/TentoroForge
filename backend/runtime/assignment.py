"""Assignment resolver — resolves task assignees from assignment policies."""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.org import (
    OrgPerson,
    OrgRole,
    OrgPersonRole,
    OrgGroup,
    OrgGroupMember,
    Department,
)
from models.workflow import WorkflowAssignmentPolicy

logger = logging.getLogger(__name__)


class AssignmentResolver:
    """Resolves who should be assigned a workflow task based on assignment policies."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve(
        self,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        workflow_id: str,
        node_id: str,
        initiator_person_id: uuid.UUID | None = None,
    ) -> tuple[uuid.UUID | None, str | None]:
        """Resolve the assignee for a task node.

        Returns (assignee_id, assignee_type) where assignee_type is one of:
        person, role, group, department.
        """
        # Look up assignment policy for this node
        result = await self.db.execute(
            select(WorkflowAssignmentPolicy).where(
                WorkflowAssignmentPolicy.project_id == project_id,
                WorkflowAssignmentPolicy.workflow_id == workflow_id,
                WorkflowAssignmentPolicy.node_id == node_id,
            )
        )
        policy = result.scalar_one_or_none()
        if not policy:
            logger.info("No assignment policy for %s/%s — unassigned", workflow_id, node_id)
            return None, None

        assign_type = policy.assign_type
        assign_target = policy.assign_target

        if assign_type == "person":
            return assign_target, "person"

        elif assign_type == "role":
            # Find first active person with this role
            person_id = await self._first_person_with_role(org_id, assign_target)
            return person_id, "role"

        elif assign_type == "group":
            # Find first active person in this group
            person_id = await self._first_person_in_group(assign_target)
            return person_id, "group"

        elif assign_type == "department":
            # Find department head, or first person in dept
            person_id = await self._department_assignee(assign_target)
            return person_id, "department"

        elif assign_type == "manager_of_requester":
            if initiator_person_id:
                person_id = await self._manager_of(initiator_person_id)
                return person_id, "manager"
            return None, None

        elif assign_type == "department_head":
            if initiator_person_id:
                person_id = await self._department_head_of(initiator_person_id)
                return person_id, "department_head"
            return None, None

        elif assign_type == "team":
            # Team-based assignment — resolve to first person in the team
            if assign_target:
                person_id = await self._first_person_in_group(uuid.UUID(str(assign_target)))
                return person_id, "team"
            return None, None

        elif assign_type == "initiator":
            return initiator_person_id, "initiator"

        elif assign_type == "process_variable":
            # The task executor resolves the variable path to a concrete UUID
            # before calling the resolver, so assign_target is already a person ID
            if assign_target:
                return uuid.UUID(str(assign_target)), "process_variable"
            return None, None

        logger.warning("Unknown assign_type: %s", assign_type)
        return None, None

    # -----------------------------------------------------------------------
    # Internal resolution methods
    # -----------------------------------------------------------------------

    async def _first_person_with_role(
        self, org_id: uuid.UUID, role_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if not role_id:
            return None
        result = await self.db.execute(
            select(OrgPersonRole.person_id)
            .join(OrgPerson, OrgPerson.id == OrgPersonRole.person_id)
            .where(
                OrgPersonRole.role_id == role_id,
                OrgPerson.org_id == org_id,
                OrgPerson.is_active.is_(True),
            )
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    async def _first_person_in_group(
        self, group_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if not group_id:
            return None
        result = await self.db.execute(
            select(OrgGroupMember.person_id)
            .join(OrgPerson, OrgPerson.id == OrgGroupMember.person_id)
            .where(
                OrgGroupMember.group_id == group_id,
                OrgPerson.is_active.is_(True),
            )
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    async def _department_assignee(
        self, dept_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if not dept_id:
            return None
        # Try department head first
        result = await self.db.execute(
            select(Department.head_person_id).where(Department.id == dept_id)
        )
        row = result.first()
        if row and row[0]:
            return row[0]

        # Fall back to first active person in department
        result = await self.db.execute(
            select(OrgPerson.id)
            .where(
                OrgPerson.department_id == dept_id,
                OrgPerson.is_active.is_(True),
            )
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    async def _manager_of(self, person_id: uuid.UUID) -> uuid.UUID | None:
        result = await self.db.execute(
            select(OrgPerson.manager_id).where(OrgPerson.id == person_id)
        )
        row = result.first()
        return row[0] if row else None

    async def _department_head_of(self, person_id: uuid.UUID) -> uuid.UUID | None:
        result = await self.db.execute(
            select(OrgPerson.department_id).where(OrgPerson.id == person_id)
        )
        row = result.first()
        dept_id = row[0] if row else None
        if not dept_id:
            return None
        return await self._department_assignee(dept_id)
