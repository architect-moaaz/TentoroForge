"""AI resilience — fallback chain with retry logic and model degradation."""

import logging
import asyncio
from typing import AsyncIterator, Callable, Awaitable

from services.agent_messages import Message

logger = logging.getLogger(__name__)

# Model fallback chain: most capable → cheapest
MODEL_CHAIN = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 2


async def with_fallback(
    agent_func: Callable[..., AsyncIterator[Message]],
    *,
    sse_callback: Callable[[str, dict], Awaitable[None]] | None = None,
    **kwargs,
) -> AsyncIterator[Message]:
    """Wrap an agent function with retry and model fallback logic.

    Tries the original model first, then falls back to cheaper models.
    Emits SSE retry status events if sse_callback is provided.

    Usage:
        async for msg in with_fallback(run_code_generator, output_dir=..., description=...):
            yield msg
    """
    last_error = None

    for model_idx, model in enumerate(MODEL_CHAIN):
        for attempt in range(MAX_RETRIES):
            try:
                # Override model in kwargs if the function accepts it
                call_kwargs = dict(kwargs)
                if "model" in call_kwargs or model_idx > 0:
                    call_kwargs["model"] = model

                if model_idx > 0 or attempt > 0:
                    status_msg = f"Retrying with {model} (attempt {attempt + 1})"
                    logger.info(status_msg)
                    if sse_callback:
                        await sse_callback("retry_status", {
                            "message": status_msg,
                            "model": model,
                            "attempt": attempt + 1,
                        })

                async for message in agent_func(**call_kwargs):
                    yield message

                # If we get here without error, the agent completed successfully
                return

            except Exception as e:
                last_error = e
                logger.warning(
                    "Agent failed (model=%s, attempt=%d): %s",
                    model, attempt + 1, e,
                )

                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))

    # All retries exhausted
    if last_error:
        raise last_error


async def with_simple_retry(
    func: Callable[..., Awaitable],
    *args,
    max_retries: int = 3,
    delay: float = 1.0,
    **kwargs,
):
    """Simple retry wrapper for any async function."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            logger.warning("Retry %d/%d for %s: %s", attempt + 1, max_retries, func.__name__, e)
            if attempt < max_retries - 1:
                await asyncio.sleep(delay * (attempt + 1))

    raise last_error  # type: ignore[misc]
