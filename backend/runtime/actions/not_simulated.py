"""Dispatcher for action types the Simulator cannot actually perform.

The registry used to fall back to :class:`CustomActionDispatcher` for ANY
unrecognised action type, and that dispatcher logs a line and returns
``{"result": "success"}``. So `db_insert`, `db_update`, `db_delete`,
`set_variable`, `transform`, `generate_document` and the `ai_*` types were all
painted GREEN in the in-editor Simulator while performing no work at all
(register A8-1).

That is the worst possible failure for this component specifically: the
Simulator is the tool an author uses to CONFIRM an edit is correct, so a false
green is not a missing feature, it is a wrong answer delivered confidently.

This dispatcher reports honestly instead. It never claims success, names the
action type, and says why — so the Simulator can surface "not simulated" rather
than a tick.
"""

import logging

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class NotSimulatedDispatcher(ActionDispatcher):
    """Reports that an action type has no simulator implementation."""

    #: Set by the factory so the message can name the real action type.
    action_type: str = "unknown"

    async def execute(self, config: dict) -> dict:
        at = getattr(self, "action_type", None) or config.get("actionType") or "unknown"
        reason = (
            f"'{at}' has no Simulator implementation — this step was NOT executed. "
            f"The shipped runtime does implement it; run the workflow for real to "
            f"exercise this step."
        )
        logger.warning("Simulator: %s", reason)
        return {
            "action_type": at,
            "result": "not_simulated",
            "simulated": False,
            "ok": False,
            "warning": reason,
        }
