"""Parallel agent runner — executes multiple agents concurrently.

Uses asyncio.gather() to run agents in parallel while interleaving their
SSE events with agent-name prefixes. All agents share the same output_dir
(filesystem is shared memory).
"""

import asyncio
import json
import logging
import os
import time
from typing import AsyncIterator, Callable, Awaitable

from services.agent_messages import Message

from sse_helpers import sse_event, stream_agent_messages

logger = logging.getLogger(__name__)


# Per-agent timeout (seconds). Agents that don't complete in this time
# are cancelled and the pipeline continues without their output.
AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "600"))

# When STREAM_TIMEOUT_DIAG=1, each event observed by stream_with_idle_timeout
# is appended to /tmp/timeout-diag-<name>.log so we can post-mortem what kept
# the queue drained during otherwise-silent pipeline phases.
_STREAM_TIMEOUT_DIAG = os.environ.get("STREAM_TIMEOUT_DIAG", "0") == "1"


def _diag_log(name: str, evt: dict, *, started_at: float, last_at: float) -> None:
    """Append a single-line diagnostic record for an observed event.

    Active only when STREAM_TIMEOUT_DIAG=1. Captures event type, age since
    start, gap since previous event, and an 80-char summary of any text
    payload — enough to spot a chatty heartbeat that's silently resetting
    the idle timer.
    """
    if not _STREAM_TIMEOUT_DIAG:
        return
    try:
        now = time.monotonic()
        event_type = evt.get("event", "?")
        raw = evt.get("data", "")
        summary = ""
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            data = {}
        if isinstance(data, dict):
            if "text" in data:
                summary = str(data["text"])[:80].replace("\n", "\\n")
            elif "tool" in data:
                summary = f"tool={data.get('tool')}"
            elif "path" in data:
                summary = f"path={data.get('path')}"
        line = (
            f"{time.strftime('%H:%M:%S')} "
            f"age={now - started_at:7.2f}s "
            f"gap={now - last_at:6.2f}s "
            f"evt={event_type:<14} "
            f"{summary}\n"
        )
        # Filename-safe agent name
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        with open(f"/tmp/timeout-diag-{safe}.log", "a") as f:
            f.write(line)
    except Exception:
        # Diagnostics must never break the pipeline.
        pass


class AgentTimeoutError(Exception):
    """Raised when a single agent phase exceeds its wall-clock timeout."""

    def __init__(self, name: str, timeout_seconds: int):
        self.name = name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Agent {name} timed out after {timeout_seconds}s with no completion"
        )


async def stream_with_idle_timeout(
    name: str,
    output_dir: str,
    messages: AsyncIterator[Message],
    timeout_seconds: int | None = None,
    as_messages: bool = False,
) -> AsyncIterator[dict]:
    """Wrap :func:`sse_helpers.stream_agent_messages` with an idle timeout.

    The wrapped iterator behaves exactly like ``stream_agent_messages`` — it
    yields the same SSE event dicts in the same order — but if no event
    arrives for ``timeout_seconds`` consecutive seconds the producer is
    cancelled and :class:`AgentTimeoutError` is raised. An agent that keeps
    streaming output (tool calls, text blocks) keeps the timer fresh.

    Used by single-agent pipeline phases that share their iterator with
    ``stream_agent_messages``; the parallel runner has its own equivalent
    inside :func:`run_parallel_agents`.
    """
    timeout = timeout_seconds if timeout_seconds is not None else AGENT_TIMEOUT_SECONDS
    sentinel: object = object()
    queue: asyncio.Queue[object] = asyncio.Queue()
    producer_error: list[BaseException] = []

    async def _produce() -> None:
        try:
            async for evt in stream_agent_messages(
                messages,
                output_dir=output_dir,
                event_prefix=f"[{name}] ",
                as_messages=as_messages,
            ):
                await queue.put(evt)
        except asyncio.CancelledError:
            # Producer was cancelled by the consumer (e.g. idle timeout).
            # Don't surface this as an error — the consumer already raised
            # AgentTimeoutError on its behalf.
            raise
        except Exception as exc:
            producer_error.append(exc)
        finally:
            # Always wake the consumer so it can observe the sentinel
            # instead of waiting forever for the next event.
            try:
                queue.put_nowait(sentinel)
            except Exception:
                pass

    producer = asyncio.create_task(_produce(), name=f"agent-{name}-producer")
    started_at = time.monotonic()
    last_at = started_at
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                logger.error(
                    "[parallel] Agent %s wedged — no events for %ss; cancelling",
                    name,
                    timeout,
                )
                if _STREAM_TIMEOUT_DIAG:
                    try:
                        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
                        with open(f"/tmp/timeout-diag-{safe}.log", "a") as f:
                            f.write(
                                f"{time.strftime('%H:%M:%S')} *** TIMEOUT after "
                                f"{timeout}s idle; total age "
                                f"{time.monotonic() - started_at:.2f}s ***\n"
                            )
                    except Exception:
                        pass
                producer.cancel()
                try:
                    await asyncio.wait_for(producer, timeout=10)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
                raise AgentTimeoutError(name, timeout) from exc
            if item is sentinel:
                break
            if _STREAM_TIMEOUT_DIAG and isinstance(item, dict):
                _diag_log(name, item, started_at=started_at, last_at=last_at)
            last_at = time.monotonic()
            yield item  # type: ignore[misc]
    finally:
        if not producer.done():
            producer.cancel()
            try:
                await asyncio.wait_for(producer, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass

    if producer_error:
        raise producer_error[0]


async def run_parallel_agents(
    output_dir: str,
    agents: list[tuple[str, Callable[[], AsyncIterator[Message]]]],
) -> AsyncIterator[dict]:
    """Run multiple agents in parallel, interleaving their SSE events.

    Args:
        output_dir: shared project directory
        agents: list of (agent_name, agent_coroutine_factory) tuples.
                Each factory returns an AsyncIterator[Message].

    Yields:
        SSE event dicts with agent-name prefixes on log messages.
        Agent results are accumulated and yielded as a combined result.

    Each agent has a hard timeout (default 600s). Timed-out or crashed
    agents log an error but do not abort the entire pipeline.
    """
    if not agents:
        return

    from sse_helpers import BillingError

    # Queue for interleaving events from all agents
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    total_cost = 0.0
    total_turns = 0
    total_duration = 0
    # A credit/billing rejection in any parallel agent is terminal for the whole
    # run — capture it here so the outer loop can re-raise instead of swallowing
    # it into a log line and shipping empty stubs.
    billing_error: list[BillingError] = []

    async def _consume_agent(name: str, agent_factory: Callable[[], AsyncIterator[Message]]) -> None:
        """Consume one agent's stream into the shared queue."""
        nonlocal total_cost, total_turns, total_duration
        import json

        async for evt in stream_agent_messages(
            agent_factory(),
            output_dir=output_dir,
            event_prefix=f"[{name}] ",
        ):
            if evt.get("event") == "agent_result":
                data = json.loads(evt["data"])
                total_cost += data.get("cost_usd", 0)
                total_turns += data.get("num_turns", 0)
                total_duration += data.get("duration_ms", 0)
            else:
                await queue.put(evt)

    async def _run_single(name: str, agent_factory: Callable[[], AsyncIterator[Message]]) -> None:
        """Run one agent with a hard timeout, pushing events to the shared queue."""
        try:
            logger.info(f"[parallel] Starting agent: {name} (timeout={AGENT_TIMEOUT_SECONDS}s)")
            await asyncio.wait_for(
                _consume_agent(name, agent_factory),
                timeout=AGENT_TIMEOUT_SECONDS,
            )
            logger.info(f"[parallel] Agent {name} completed")
        except asyncio.TimeoutError:
            logger.error(f"[parallel] Agent {name} timed out after {AGENT_TIMEOUT_SECONDS}s")
            await queue.put(sse_event("log", {
                "text": f"[{name}] ⚠ Timeout after {AGENT_TIMEOUT_SECONDS}s — continuing without output",
            }))
        except BillingError as be:
            # Terminal — record it so the run halts rather than degrading to stubs.
            logger.error(f"[parallel] Agent {name} hit a billing/credit error; aborting run")
            billing_error.append(be)
        except Exception as e:
            logger.exception(f"[parallel] Agent {name} failed: {e}")
            await queue.put(sse_event("log", {"text": f"[{name}] Error: {e}"}))

    async def _run_all() -> None:
        """Run all agents concurrently and signal completion."""
        tasks = [
            asyncio.create_task(_run_single(name, factory))
            for name, factory in agents
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)  # Sentinel to signal completion

    # Start all agents in background
    runner_task = asyncio.create_task(_run_all())

    # Yield events as they arrive
    while True:
        evt = await queue.get()
        if evt is None:
            break
        yield evt

    # Wait for runner to fully complete
    await runner_task

    # A billing/credit rejection in any agent is terminal for the whole run.
    if billing_error:
        raise billing_error[0]

    # Yield combined result
    yield sse_event("agent_result", {
        "num_turns": total_turns,
        "cost_usd": total_cost,
        "duration_ms": total_duration,
    })


async def stream_planner_with_retry(
    name: str,
    output_dir: str,
    make_messages: Callable[[], AsyncIterator[Message]],
    collected_text: list,
    max_attempts: int = 3,
    as_messages: bool = True,
) -> AsyncIterator[dict]:
    """Run a planner-style stream with retry on a wedge/transient failure.

    The bundled Claude CLI intermittently wedges mid-generation (streams for a
    while, then emits nothing — :func:`stream_with_idle_timeout` catches that and
    raises :class:`AgentTimeoutError`). Because the failure is intermittent, a
    fresh attempt usually completes. This reruns ``make_messages()`` up to
    ``max_attempts`` times.

    ``collected_text`` is cleared at the start of EACH attempt so a failed
    attempt's partial output is discarded and the caller is left with only the
    successful run's text. Yields the same SSE event dicts as
    ``stream_with_idle_timeout``; re-raises the last error if every attempt fails.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        collected_text.clear()
        try:
            async for evt in stream_with_idle_timeout(
                name, output_dir, make_messages(), as_messages=as_messages
            ):
                yield evt
            return  # stream completed cleanly
        except Exception as exc:  # wedge (AgentTimeoutError) or transient CLI error
            last_exc = exc
            logger.warning(
                "[%s] attempt %d/%d failed (%s); %s",
                name, attempt, max_attempts, type(exc).__name__,
                "retrying" if attempt < max_attempts else "giving up",
            )
            if attempt < max_attempts:
                yield sse_event("log", {
                    "text": f"[{name}] attempt {attempt} stalled — retrying ({attempt + 1}/{max_attempts})…"
                })
    raise last_exc if last_exc is not None else RuntimeError(
        f"{name} failed after {max_attempts} attempts"
    )
