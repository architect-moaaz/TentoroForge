"""Action dispatcher registry for workflow service tasks."""

from sqlalchemy.ext.asyncio import AsyncSession

from runtime.actions.base import ActionDispatcher
from runtime.actions.custom import CustomActionDispatcher
from runtime.actions.http_call import HttpCallDispatcher
from runtime.actions.db_query import DbQueryDispatcher
from runtime.actions.send_email import SendEmailDispatcher
from runtime.actions.not_simulated import NotSimulatedDispatcher
from runtime.actions.send_notification import SendNotificationDispatcher
from runtime.actions.simulated import (
    AiClassifyDispatcher,
    AiDecideDispatcher,
    AiExtractDispatcher,
    AiGenerateDispatcher,
    DbDeleteDispatcher,
    DbInsertDispatcher,
    DbUpdateDispatcher,
    GenerateDocumentDispatcher,
    SetVariableDispatcher,
    TransformDispatcher,
)

ACTION_DISPATCHERS: dict[str, type[ActionDispatcher]] = {
    "custom": CustomActionDispatcher,
    "http_call": HttpCallDispatcher,
    "api_call": HttpCallDispatcher,
    "db_query": DbQueryDispatcher,
    "send_email": SendEmailDispatcher,
    "send_notification": SendNotificationDispatcher,
    # The other ten action types the editor can author (register A8-1).
    # Each returns the SHIPPED handler's output shape so downstream
    # bindings resolve in simulation exactly as they will in production.
    "db_insert": DbInsertDispatcher,
    "db_update": DbUpdateDispatcher,
    "db_delete": DbDeleteDispatcher,
    "set_variable": SetVariableDispatcher,
    "transform": TransformDispatcher,
    "generate_document": GenerateDocumentDispatcher,
    "ai_generate": AiGenerateDispatcher,
    "ai_classify": AiClassifyDispatcher,
    "ai_extract": AiExtractDispatcher,
    "ai_decide": AiDecideDispatcher,
}


def get_dispatcher(
    action_type: str,
    db: AsyncSession,
    variables: dict,
) -> ActionDispatcher:
    """Factory: return an ActionDispatcher instance for the given action_type.

    An action type with no dispatcher gets :class:`NotSimulatedDispatcher`, NOT
    the custom one.

    The fallback used to be ``CustomActionDispatcher``, which logs a line and
    returns ``{"result": "success"}`` — so every action type this registry does
    not implement (db_insert, db_update, db_delete, set_variable, transform,
    generate_document, the ai_* family) was reported as a SUCCESSFUL step in
    the in-editor Simulator while doing nothing (register A8-1). The Simulator
    is what an author uses to confirm an edit is correct, so a false green is a
    confidently wrong answer, not a missing feature. `custom` still resolves to
    the custom dispatcher because for `custom` that IS the correct behaviour.
    """
    cls = ACTION_DISPATCHERS.get(action_type)
    if cls is None:
        inst = NotSimulatedDispatcher(db=db, variables=variables)
        inst.action_type = action_type
        return inst
    return cls(db=db, variables=variables)
