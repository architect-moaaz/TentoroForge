"""Base action dispatcher for workflow service tasks."""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from runtime.variable_resolver import VariableResolver


class ActionDispatcher(ABC):
    """Abstract base class for workflow action dispatchers."""

    def __init__(self, db: AsyncSession, variables: dict):
        self.db = db
        self.variables = variables
        self.resolver = VariableResolver(variables)

    @abstractmethod
    async def execute(self, config: dict) -> dict:
        """Execute the action and return output data."""
        ...
