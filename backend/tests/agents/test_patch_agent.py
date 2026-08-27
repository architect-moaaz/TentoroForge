# backend/tests/agents/test_patch_agent.py
"""Patch agent tests use a stubbed Anthropic client so they run offline."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.patch_agent import propose_patches, PatchAgentContext
from services.vision_evaluator.types import Critique, Issue, Scores


VALID_PATCHES_RESPONSE = json.dumps([
    {"op": "replace", "path": "/root/children/0/props/headline", "value": "Track patient appointments"},
    {"op": "add", "path": "/root/children/-", "value": {"id": "extra", "type": "Card", "props": {}}}
])


def make_critique() -> Critique:
    return Critique.model_validate({
        "scores": {"visualPolish": 6, "domainFeel": 5, "informationDensity": 5,
                   "componentCoherence": 6, "brandReflection": 5},
        "compositeScore": 5.4,
        "pass": False,
        "topIssues": [{
            "severity": "high", "axis": "domainFeel", "nodeIdHint": "hero",
            "issue": "Hero headline is generic", "suggestion": "Use domain-specific copy",
        }],
        "strengths": [],
        "designerApprovalRecommended": False,
    })


def make_schema() -> dict:
    return {
        "schemaVersion": "2", "id": "x", "route": "/x", "meta": {"title": "X"},
        "dataSources": [],
        "root": {"id": "root", "type": "Stack", "props": {},
                 "children": [{"id": "hero", "type": "Hero", "props": {"headline": "Welcome"}, "children": []}]}
    }


def make_ctx() -> PatchAgentContext:
    return PatchAgentContext(domain="healthcare", app_name="Clinic", description="track patients", tone="trustworthy")


@pytest.mark.asyncio
async def test_propose_patches_returns_parsed_list():
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value=VALID_PATCHES_RESPONSE)):
        patches = await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())
        assert len(patches) == 2
        assert patches[0]["op"] == "replace"
        assert patches[0]["path"] == "/root/children/0/props/headline"


@pytest.mark.asyncio
async def test_propose_patches_strips_markdown_fence():
    fenced = "```json\n" + VALID_PATCHES_RESPONSE + "\n```"
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value=fenced)):
        patches = await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())
        assert len(patches) == 2


@pytest.mark.asyncio
async def test_propose_patches_invalid_json_raises():
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value="not json")):
        with pytest.raises(Exception):
            await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())


@pytest.mark.asyncio
async def test_propose_patches_caps_at_8_patches():
    too_many = json.dumps([{"op": "replace", "path": "/x", "value": i} for i in range(20)])
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value=too_many)):
        patches = await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())
        assert len(patches) == 8


@pytest.mark.asyncio
async def test_strict_mode_includes_validation_errors_in_prompt():
    """When strict=True, the validation_errors list should be passed to the
    prompt builder. We verify by checking _call_anthropic receives it via the
    user-prompt content."""
    captured = {}
    async def fake_call(*, system, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return VALID_PATCHES_RESPONSE
    with patch("agents.patch_agent._call_anthropic", new=fake_call):
        await propose_patches(
            schema=make_schema(), critique=make_critique(), app_ctx=make_ctx(),
            strict=True, validation_errors=["path_unresolved at /foo"],
        )
        assert "path_unresolved at /foo" in captured["user_prompt"]
