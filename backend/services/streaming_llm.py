"""Anthropic streaming helper with throttled per-chunk SSE emission.

Two planning-time LLM calls used to run as opaque awaits:

  * ``discovery_narrative.expand_prompt_to_narrative`` (30-90s)
  * ``agents.planner.run_planner_oneshot`` (2-5 min)

Between them the frontend saw nothing but a spinner. This helper wraps
Anthropic's ``client.messages.stream()`` so the caller can hand in an
``emit_fn`` and get typewriter-style progress events (throttled to
avoid SSE spam).

Contract
--------
``stream_and_emit(client, *, stage, model, max_tokens, system, messages,
                  timeout_seconds, emit_fn)`` returns the assembled text.

Events emitted (when ``emit_fn`` is supplied and non-None):

  * ``{stage}_started``   — one-time, on stream open. text = "Working…"
  * ``{stage}_chunk``     — throttled — every ~400ms OR every ~800 chars,
                            whichever comes first. Payload:
                              text = short human line
                              chars_so_far = int
                              preview = last ~60 chars of accumulated text
  * ``{stage}_complete``  — one-time, on final message. Payload:
                              chars = total count
                              lines = newline count

If ``emit_fn`` is None or raises, streaming still works — the helper
swallows emit errors so a broken UI hook never breaks generation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Throttle constants — tuned so a 30-second call emits ~15-25 chunks
# (roughly 1 event per 1-2 seconds of streaming). Loose enough that
# a fast burst doesn't spam SSE; tight enough that the user sees
# steady progress.
_CHUNK_MIN_INTERVAL_SEC = 0.4
_CHUNK_MIN_CHARS        = 800
_PREVIEW_TAIL_CHARS     = 60


async def stream_and_emit(
    client: Any,
    *,
    stage: str,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    timeout_seconds: float,
    emit_fn: Callable[[str, dict], None] | None = None,
    started_text: str = "Working…",
    semantic_watcher: Callable[[str], list[dict]] | None = None,
) -> str:
    """Stream from Anthropic and emit throttled progress events.

    Returns the full assembled text. Raises the underlying Anthropic
    error on API failure (billing / rate limit / bad request) — the
    caller decides what to do with a failed call.

    A ``None`` client (or a client without ``.messages.stream``) is
    treated as a signal to fall back to the non-streaming path; the
    caller supplies that fallback. This keeps the module testable
    without a live SDK.
    """
    if client is None or not hasattr(client, "messages"):
        raise RuntimeError(
            "stream_and_emit requires an Anthropic-like client with "
            ".messages.stream(...)"
        )

    _emit(emit_fn, f"{stage}_started", {"text": started_text})

    accumulated: list[str] = []
    last_emit_at   = time.monotonic()
    since_last_len = 0

    async def _consume() -> str:
        nonlocal last_emit_at, since_last_len
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            async for delta in stream.text_stream:
                if not delta:
                    continue
                accumulated.append(delta)
                since_last_len += len(delta)
                now = time.monotonic()
                if (since_last_len >= _CHUNK_MIN_CHARS
                        or (now - last_emit_at) >= _CHUNK_MIN_INTERVAL_SEC):
                    total = "".join(accumulated)
                    _emit(emit_fn, f"{stage}_chunk", {
                        # No thousand-separator: the frontend narrator
                        # extracts the count with a plain \d+ regex and
                        # a comma would truncate 8,432 to just "432",
                        # making the counter appear to reset every 1000.
                        "text":         f"streaming {len(total)} chars",
                        "chars_so_far": len(total),
                        "preview":      total[-_PREVIEW_TAIL_CHARS:],
                    })
                    # Semantic events layered on top of raw progress —
                    # the watcher inspects the accumulated text so far
                    # and returns any NEW landmark events it spotted
                    # since the previous chunk (e.g. "entered pages
                    # section", "authored entity Candidate"). Emit each
                    # as ``{stage}_semantic``.
                    if semantic_watcher is not None:
                        try:
                            for evt in semantic_watcher(total):
                                _emit(emit_fn, f"{stage}_semantic", evt)
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "[stream-emit] semantic_watcher failed"
                            )
                    last_emit_at   = now
                    since_last_len = 0
        return "".join(accumulated)

    try:
        text = await asyncio.wait_for(_consume(), timeout=timeout_seconds)
    finally:
        # Even on timeout / early failure, tell the UI we're done.
        pass

    total = text
    _emit(emit_fn, f"{stage}_complete", {
        "text":  f"done — {len(total)} chars",
        "chars": len(total),
        "lines": total.count("\n") + (1 if total else 0),
    })
    return total


def _emit(
    emit_fn: Callable[[str, dict], None] | None,
    stage: str,
    payload: dict,
) -> None:
    """Best-effort emit — a caller emit_fn that raises must NEVER break
    the LLM call."""
    if emit_fn is None:
        return
    try:
        emit_fn(stage, payload)
    except Exception:  # noqa: BLE001
        logger.exception("[stream-emit] %s failed", stage)
