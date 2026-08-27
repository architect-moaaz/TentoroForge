"""A credit/billing rejection must HALT the run, not degrade to empty stubs.

Before this fix, a 400 "credit balance too low" from any agent was swallowed
(logged as text) and the pipeline shipped stubs while cheerfully reporting
success. These tests lock in that a terminal billing error now propagates as a
BillingError through both the single-agent and parallel consumers.
"""
import asyncio

import pytest

from services.agent_messages import AssistantMessage, TextBlock
from services import sdk_agent_runner as r
from services.parallel_runner import run_parallel_agents, stream_with_idle_timeout
from sse_helpers import BillingError


# ── terminal-billing phrase detection ──────────────────────────────────────
def test_detects_credit_balance_error():
    assert r._is_terminal_billing_error(
        "Error code: 400 - Your credit balance is too low to access the API"
    )


def test_detects_billing_error_marker():
    assert r._is_terminal_billing_error("billing_error")


@pytest.mark.parametrize("transient", [
    "Error code: 429 - rate limit exceeded",
    "Error code: 529 - overloaded_error",
    "connection reset by peer",
    "",
])
def test_transient_errors_are_not_terminal(transient):
    # Transient errors should degrade gracefully, NOT halt the run.
    assert not r._is_terminal_billing_error(transient)


# ── helpers: fake agents ────────────────────────────────────────────────────
async def _billing_agent():
    """An agent whose model call raises a credit error (as the real runner does)."""
    raise BillingError("Your credit balance is too low to access the API.")
    yield  # pragma: no cover — makes this an async generator


async def _ok_agent():
    yield AssistantMessage(content=[TextBlock(text="working")], model="m")


# ── single-agent path (schema/data-models phase) ────────────────────────────
def test_single_agent_billing_error_propagates(tmp_path):
    async def _drain():
        async for _ in stream_with_idle_timeout("Schema", str(tmp_path), _billing_agent()):
            pass

    with pytest.raises(BillingError):
        asyncio.run(_drain())


# ── parallel path (bizlogic + api phase) ────────────────────────────────────
def test_parallel_agent_billing_error_propagates(tmp_path):
    async def _drain():
        async for _ in run_parallel_agents(
            str(tmp_path),
            [("api", _ok_agent), ("bizlogic", _billing_agent)],
        ):
            pass

    with pytest.raises(BillingError):
        asyncio.run(_drain())
