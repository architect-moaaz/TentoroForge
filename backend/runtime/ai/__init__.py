"""AI handler registry for workflow AI nodes."""

from runtime.ai.base import AINodeHandler
from runtime.ai.classify import ClassifyHandler
from runtime.ai.extract import ExtractHandler
from runtime.ai.decide import DecideHandler
from runtime.ai.generate import GenerateHandler

AI_HANDLERS: dict[str, type[AINodeHandler]] = {
    "ai_classify": ClassifyHandler,
    "ai_extract": ExtractHandler,
    "ai_decide": DecideHandler,
    "ai_generate": GenerateHandler,
}


def get_ai_handler(node_type: str, variables: dict) -> AINodeHandler:
    """Factory: return an AINodeHandler instance for the given node type."""
    cls = AI_HANDLERS.get(node_type)
    if cls is None:
        raise ValueError(f"Unknown AI node type: {node_type}")
    return cls(variables=variables)
