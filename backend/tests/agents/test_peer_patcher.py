"""Tests for the peer_patcher agent."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.peer_patcher import run_peer_patcher


def _make_response(artifacts_input: dict | None, *, with_text: str = ""):
    """Build a mocked Anthropic response object."""
    resp = MagicMock()
    blocks = []
    if with_text:
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = with_text
        blocks.append(text_block)
    if artifacts_input is not None:
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "writeArtifacts"
        tool_block.input = artifacts_input
        blocks.append(tool_block)
    resp.content = blocks
    return resp


VALID_ARTIFACTS = {
    "pageSchemas": {
        "home": {
            "schemaVersion": "2", "id": "home", "route": "/",
            "root": {"id": "h1", "type": "Stack",
                     "children": [{"id": "t1", "type": "Text", "props": {"text": "Hello"}}]},
        }
    },
    "navFlow": {
        "version": "1.0", "initialPage": "home",
        "pages": [{"id": "home", "route": "/", "title": "Home",
                   "schemaFile": "src/schemas/home.json", "params": []}],
        "transitions": [], "guards": {},
    },
    "tokens": {
        "color": {}, "typography": {}, "spacing": {},
        "radius": {}, "shadow": {}, "motion": {}, "breakpoints": {},
    },
}


@pytest.mark.asyncio
async def test_peer_patcher_emits_artifacts_on_valid_tool_use():
    with patch("agents.peer_patcher.AsyncAnthropic") as Mock:
        client = Mock.return_value
        client.messages.create = AsyncMock(
            return_value=_make_response(VALID_ARTIFACTS, with_text="Built the home page.")
        )

        events = []
        async for evt in run_peer_patcher(
            user_prompt="Build a notes app",
            current_artifacts=None,
            registry_digest="Stack [...children]  { gap:enum, padding:enum }",
        ):
            events.append(evt)

        # The terminal event must be artifacts
        assert events[-1]["event"] == "artifacts"
        assert events[-1]["data"]["artifacts"] == VALID_ARTIFACTS
        assert "Built the home page" in events[-1]["data"]["rationale"]


@pytest.mark.asyncio
async def test_peer_patcher_retries_on_missing_tool_call():
    with patch("agents.peer_patcher.AsyncAnthropic") as Mock:
        client = Mock.return_value
        client.messages.create = AsyncMock(side_effect=[
            _make_response(None, with_text="I will think about it"),  # no tool call
            _make_response(VALID_ARTIFACTS),                            # retry succeeds
        ])

        events = []
        async for evt in run_peer_patcher(
            user_prompt="Build a notes app",
            current_artifacts=None,
            registry_digest="Stack [...children]",
        ):
            events.append(evt)

        # Should have retried; terminal event is artifacts
        assert events[-1]["event"] == "artifacts"
        # Two attempts logged
        logs = [e for e in events if e["event"] == "log" and "Attempt" in e["data"]["text"]]
        assert len(logs) == 2


@pytest.mark.asyncio
async def test_peer_patcher_retries_on_validation_failure():
    invalid = {"pageSchemas": "not a dict"}
    with patch("agents.peer_patcher.AsyncAnthropic") as Mock:
        client = Mock.return_value
        client.messages.create = AsyncMock(side_effect=[
            _make_response(invalid),
            _make_response(VALID_ARTIFACTS),
        ])

        events = []
        async for evt in run_peer_patcher(
            user_prompt="Build a notes app",
            current_artifacts=None,
            registry_digest="Stack",
            max_retries=2,
        ):
            events.append(evt)

        assert events[-1]["event"] == "artifacts"


@pytest.mark.asyncio
async def test_peer_patcher_emits_error_after_exhausting_retries():
    with patch("agents.peer_patcher.AsyncAnthropic") as Mock:
        client = Mock.return_value
        # Three failures in a row → no success
        client.messages.create = AsyncMock(side_effect=[
            _make_response(None),
            _make_response(None),
            _make_response(None),
        ])

        events = []
        async for evt in run_peer_patcher(
            user_prompt="Build a notes app",
            current_artifacts=None,
            registry_digest="Stack",
            max_retries=2,
        ):
            events.append(evt)

        assert events[-1]["event"] == "error"
        assert "Exhausted retries" in events[-1]["data"]["text"]


@pytest.mark.asyncio
async def test_peer_patcher_retries_on_domain_validation_failure():
    """When registry kwarg is provided, unknown components trigger retry."""
    REGISTRY = {"Stack": {"props": {"gap": {}}}, "Text": {"props": {"text": {}}}}
    invalid_artifacts = {
        "pageSchemas": {
            "home": {
                "schemaVersion": "2", "id": "home", "route": "/",
                "root": {"id": "n1", "type": "TotallyMadeUp", "props": {}},
            }
        },
        "navFlow": {
            "version": "1.0", "initialPage": "home",
            "pages": [{"id": "home", "route": "/", "title": "Home",
                       "schemaFile": "x", "params": []}],
            "transitions": [], "guards": {},
        },
        "tokens": {"color":{},"typography":{},"spacing":{},"radius":{},
                   "shadow":{},"motion":{},"breakpoints":{}},
    }
    valid_artifacts = {
        **invalid_artifacts,
        "pageSchemas": {
            "home": {
                **invalid_artifacts["pageSchemas"]["home"],
                "root": {"id": "n1", "type": "Stack",
                         "children": [{"id":"n2","type":"Text","props":{"text":"ok"}}]},
            }
        }
    }

    with patch("agents.peer_patcher.AsyncAnthropic") as Mock:
        client = Mock.return_value
        client.messages.create = AsyncMock(side_effect=[
            _make_response(invalid_artifacts),
            _make_response(valid_artifacts),
        ])

        events = []
        async for evt in run_peer_patcher(
            user_prompt="Build a notes app",
            current_artifacts=None,
            registry_digest="Stack, Text",
            registry=REGISTRY,
            max_retries=2,
        ):
            events.append(evt)

        assert events[-1]["event"] == "artifacts"
