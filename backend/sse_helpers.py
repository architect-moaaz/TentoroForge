"""Shared SSE event formatting utilities."""

import json
from typing import AsyncIterator

from services.agent_messages import Message, AssistantMessage, ResultMessage, TextBlock, ToolUseBlock


class BillingError(Exception):
    """Raised when the Claude API reports a billing/credit error."""
    pass


BILLING_ERROR_MSG = (
    "Your credit balance is too low to access the API. "
    "Please go to Plans & Billing to upgrade or purchase credits."
)


async def billing_safe_query(messages_iter: AsyncIterator[Message]) -> AsyncIterator[Message]:
    """Wrap a query() async iterator to detect billing errors from the SDK.

    The SDK returns billing errors as AssistantMessage(error='billing_error')
    before raising a generic Exception. This wrapper catches the billing error
    message and raises BillingError instead, so callers get a clear signal.
    """
    try:
        async for message in messages_iter:
            if isinstance(message, AssistantMessage):
                if getattr(message, "error", None) == "billing_error":
                    raise BillingError(BILLING_ERROR_MSG)
                # Also detect from text content with synthetic model marker
                for block in message.content:
                    if isinstance(block, TextBlock):
                        lower = block.text.lower()
                        if ("credit balance" in lower or "billing_error" in lower) and getattr(message, "model", "") == "<synthetic>":
                            raise BillingError(BILLING_ERROR_MSG)
            yield message
    except BillingError:
        raise
    except Exception as e:
        # If we saw a billing error before the exception, re-raise as BillingError
        raise


def sse_event(event: str, data: dict) -> dict:
    """Format an SSE event dict for EventSourceResponse."""
    return {"event": event, "data": json.dumps(data)}


# --------------------------------------------------------------------------- #
# Conversational Fix-Assistant SSE contract (consumed verbatim by the frontend,
# Task 1-E). These builders PIN the exact payload shapes — do not deviate.
# --------------------------------------------------------------------------- #

# The control chip the user sends back to approve a proposed fix.
FIX_APPLY_TOKEN = "[APPLY_FIX]"


def fix_proposal_event(diagnosis: dict, changes: list | None = None) -> dict:
    """Build the ``fix_proposal`` SSE event from a diagnoser Diagnosis.

    Shape (pinned):
        {"diagnosis": {symptom, feature, rootCause, explanation,
                       artifact:{kind,path}, locator, confidence},
         "changes": [...preview...],
         "applyToken": "[APPLY_FIX]"}
    """
    diag = diagnosis or {}
    artifact = diag.get("artifact") or {}
    locator = diag.get("locator") or {}
    payload = {
        "diagnosis": {
            "symptom": diag.get("symptom"),
            "feature": diag.get("feature"),
            "rootCause": diag.get("rootCause"),
            "explanation": diag.get("explanation"),
            "artifact": {
                "kind": artifact.get("kind"),
                "path": artifact.get("path"),
            },
            "locator": {
                "nodeId": locator.get("nodeId"),
                "jsonPointer": locator.get("jsonPointer"),
            },
            "confidence": diag.get("confidence"),
        },
        "changes": list(changes or []),
        "applyToken": FIX_APPLY_TOKEN,
    }
    return sse_event("fix_proposal", payload)


def fix_applied_event(result: dict, message: str) -> dict:
    """Build the ``fix_applied`` SSE event from a fix_applier result.

    Shape (pinned):
        {"applied": bool, "changes": [...],
         "verify": {"resolved": bool, "remaining": [...]},
         "committed": bool, "message": <plain-language result>}
    """
    res = result or {}
    verify = res.get("verify") or {}
    payload = {
        "applied": bool(res.get("applied")),
        "changes": list(res.get("changes") or []),
        "verify": {
            "resolved": bool(verify.get("resolved")),
            "remaining": list(verify.get("remaining") or []),
        },
        "committed": bool(res.get("committed")),
        "message": message,
    }
    return sse_event("fix_applied", payload)


def safe_serialize(obj: dict) -> str:
    """Serialize tool args, truncating long values."""
    truncated = {}
    for k, v in obj.items():
        s = str(v)
        if len(s) > 200:
            truncated[k] = s[:200] + "..."
        else:
            truncated[k] = v
    return json.dumps(truncated)


async def stream_agent_messages(
    messages: AsyncIterator[Message],
    output_dir: str,
    event_prefix: str = "",
    as_messages: bool = False,
) -> AsyncIterator[dict]:
    """Convert agent streaming messages to SSE events.

    Yields SSE event dicts and tracks the ResultMessage internally.
    The final ResultMessage is yielded as a 'result' event with cost/turn info.

    When as_messages is True, TextBlock content is emitted as 'message' events
    (shown in chat as assistant messages) instead of 'log' events (only shown in
    streaming overlay).
    """
    _billing_error_msg = (
        "Your credit balance is too low to access the API. "
        "Please go to Plans & Billing to upgrade or purchase credits."
    )
    # Usage accounting: remember the model from the stream's assistant
    # messages (ResultMessage doesn't carry it) so the terminal result's
    # token counts can be priced and written to the build-usage ledger.
    _seen_model: str | None = None
    async for message in messages:
        if isinstance(message, AssistantMessage):
            _m = getattr(message, "model", None)
            if _m and _m != "<synthetic>":
                _seen_model = _m
            # Check for billing/credit errors returned by the SDK
            if getattr(message, "error", None) == "billing_error":
                raise RuntimeError(_billing_error_msg)
            # Also detect billing errors from the text content itself
            for block in message.content:
                if isinstance(block, TextBlock):
                    lower = block.text.lower()
                    if ("credit balance" in lower or "billing" in lower) and getattr(message, "model", "") == "<synthetic>":
                        raise RuntimeError(_billing_error_msg)
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    event_type = "message" if as_messages else "log"
                    text = f"{event_prefix}{block.text}" if event_prefix else block.text
                    yield sse_event(event_type, {"text": text})
                elif isinstance(block, ToolUseBlock):
                    tool_name = block.name
                    if tool_name in ("Write", "Edit"):
                        file_path = block.input.get("file_path", "")
                        rel_path = file_path
                        if file_path.startswith(output_dir):
                            rel_path = file_path[len(output_dir):].lstrip("/")
                        yield sse_event("file_created", {"path": rel_path})
                    yield sse_event("tool_call", {
                        "tool": tool_name,
                        "args": safe_serialize(block.input),
                    })

        elif isinstance(message, ResultMessage):
            # Record tokens + cost for the admin usage dashboard. This is
            # the one choke point every pipeline agent streams through, so
            # one hook covers planner/schema/pages/QA/etc. Fail-open.
            try:
                import os as _os
                from services.build_usage import record_usage as _record_usage
                _record_usage(
                    project=_os.path.basename(str(output_dir).rstrip("/")) or "unknown",
                    agent=(event_prefix or "").strip("[] ") or "agent",
                    model=_seen_model,
                    usage=getattr(message, "usage", None),
                    sdk_cost_usd=message.total_cost_usd,
                    duration_ms=message.duration_ms,
                    num_turns=message.num_turns,
                )
            except Exception:  # noqa: BLE001 — accounting never breaks a build
                pass
            yield sse_event("agent_result", {
                "num_turns": message.num_turns or 0,
                "cost_usd": message.total_cost_usd or 0,
                "duration_ms": message.duration_ms or 0,
            })
