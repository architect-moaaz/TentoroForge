# backend/agents/patch_agent.py
"""Patch agent — given a schema + critique, emits RFC 6902 patches.

Narrow, single-purpose: no refactoring, no restructuring, no inventing new
features. Just patches that target the issues in the critique.
"""
from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass
from typing import Any

from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)

from services.vision_evaluator.types import Critique


_MODEL = os.getenv("PATCH_AGENT_MODEL", "claude-sonnet-4-5-20250929")
_MAX_TOKENS = 2048
_MAX_PATCHES = 8


PATCH_AGENT_SYSTEM_PROMPT = r"""You are a precise code surgeon. Given a UI page schema and a design critique, you emit RFC 6902 JSON Patches that fix the issues.

HARD RULES — violating any of these is a failed response:
- Emit ONLY a JSON array of patch objects. No prose, no markdown fences, no explanations.
- Maximum 8 patches per response. If the critique has more issues, rank by severity (high > medium > low) and emit patches for the top-8.
- Each patch's `path` must resolve in the provided schema. Use JSON Pointer (RFC 6901) syntax.
- Each patch's `value` must match the v2 prop contract for the target component.
- When an issue has a `nodeIdHint`, prefer patches against that node.
- DO NOT change the page's route, id, or schemaVersion.
- DO NOT add, remove, or rename top-level keys (root, meta, dataSources).
- DO NOT remove existing nodes unless the critique explicitly asks for removal.
- Prefer minimal patches: change one prop at a time when that addresses the issue.

SCHEMA STRUCTURE
- Schemas use a tree where each node has {id, type, props, children?}.
- Paths are JSON pointers — to target Hero's headline at the root's first child, the path is "/root/children/0/props/headline".
- To insert at the end of a children array, use path "/parent/children/-" with op "add".

OUTPUT FORMAT (strict)
[
  {"op": "replace", "path": "/root/children/0/props/headline", "value": "Track patient appointments"},
  {"op": "add", "path": "/root/children/-", "value": {"id": "stats-extra", "type": "MetricTile", "props": {"label": "Avg Wait", "value": 23, "format": "duration"}}}
]

HIERARCHY ISSUES — when the critique mentions "no clear primary metric" or
"all tiles equal weight", emit patches that set MetricTile.importance:
  - One tile → primary (the headline metric)
  - Others → secondary or omit (default)

When the critique mentions "no breadcrumb / no page header", emit patches
that change Hero.role to "headline" or add a Section.role: "headline".

When the critique mentions "sparse" / "too much white space", emit patches
that change Card.density to "regular" or "tight" (or Section padding via
density-related props).
"""


@dataclass
class PatchAgentContext:
    domain: str
    app_name: str
    description: str
    tone: str


async def _call_anthropic(*, system: str, user_prompt: str, model: str = _MODEL, max_tokens: int = _MAX_TOKENS) -> str:
    """Single Anthropic call — returns the raw text. Mocked in tests."""
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = []
    for block in msg.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


def _strip_fence(text: str) -> str:
    """Strip ```json ... ``` fences if the model emitted them despite instructions."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text


def _build_user_prompt(*, schema: dict[str, Any], critique: Critique, app_ctx: PatchAgentContext, strict: bool, validation_errors: list[str] | None) -> str:
    """Assemble the user-prompt body. Schema and critique are inlined as JSON."""
    lines = [
        f"APP CONTEXT",
        f"  Domain: {app_ctx.domain}",
        f"  Name: {app_ctx.app_name}",
        f"  Description: {app_ctx.description}",
        f"  Tone: {app_ctx.tone}",
        "",
        "CURRENT SCHEMA:",
        json.dumps(schema, indent=2),
        "",
        "CRITIQUE:",
        critique.model_dump_json(by_alias=True, indent=2),
        "",
    ]
    if strict and validation_errors:
        lines.append("YOUR PREVIOUS ATTEMPT HAD THESE VALIDATION ERRORS:")
        for err in validation_errors:
            lines.append(f"  - {err}")
        lines.append("")
        lines.append("Emit corrected patches. Do not include any patch that touched paths from those errors.")
        lines.append("")
    lines.append("Emit the JSON array of patches now.")
    return "\n".join(lines)


async def propose_patches(
    *,
    schema: dict[str, Any],
    critique: Critique,
    app_ctx: PatchAgentContext,
    strict: bool = False,
    validation_errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Call the patch agent. Returns up to 8 RFC 6902 patches (caller validates + applies).

    Raises Exception on unparseable model output. Caller catches and treats as a
    failed iteration."""
    user_prompt = _build_user_prompt(
        schema=schema, critique=critique, app_ctx=app_ctx,
        strict=strict, validation_errors=validation_errors,
    )
    raw = await _call_anthropic(system=PATCH_AGENT_SYSTEM_PROMPT, user_prompt=user_prompt)
    text = _strip_fence(raw)
    patches = json.loads(text)  # raises JSONDecodeError if not JSON
    if not isinstance(patches, list):
        raise ValueError(f"patch agent returned non-array: {type(patches).__name__}")
    return patches[:_MAX_PATCHES]
