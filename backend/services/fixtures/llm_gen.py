"""Layer 2-LLM fixture generator — produces realistic per-entity records via
the Anthropic HTTP API.

Sits between the curated domain bank (Layer 1) and the Faker fallback
(Layer 2-faker). Used when:
  - No curated bank exists for (domain, entity_name), AND
  - The caller passed a project_root so results can be cached, AND
  - `ANTHROPIC_API_KEY` is set in the environment.

If no API key is present, the helper returns `None` immediately so the caller
falls through to Faker — generation continues without LLM, just with weaker
content for unrecognised fields. Set `ANTHROPIC_API_KEY` in `backend/.env`
(see `backend/.env.example`) to enable LLM-quality fixture generation.

Why the regular `anthropic` SDK instead of `claude_agent_sdk`: the agent SDK
spawns a bundled Claude Code CLI subprocess and its stdout pipes don't
play well with uvicorn's asyncio loop — calls hang indefinitely from inside
FastAPI route handlers even though they work fine from a standalone shell.
The HTTP-only `anthropic` SDK (already used by `runtime/ai/base.py`) doesn't
have that problem and is faster anyway (~2-5s vs 7-25s for first SDK call).

Cost characteristics: one Sonnet call per (project, entity), cached to
`output/<short_id>/.fixtures-cache/<entity>.json`. First preview-data fetch
for a fresh project takes ~5-15s total (one Sonnet round-trip per entity);
every subsequent fetch is a cached read in <1ms.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from .types import FieldHint

logger = logging.getLogger(__name__)


# Hard ceiling so a stuck request doesn't pin the preview-data endpoint open.
# Sonnet typically returns in 5-30s for a 10-record request, depending on
# how many fields the entity has — wide entities (e.g. a workflow task with
# 17 fields × 10 records) can push past 30s. Because all entities fire
# CONCURRENTLY (asyncio.gather in the caller), the fixture phase's wall-clock
# equals the SLOWEST single call — so a generous per-call timeout is paid on
# every generation, not amortised. 40s covers the vast majority of observed
# entities; the rare straggler that exceeds it falls back to deterministic
# faker data (still `count` rows), so nothing is lost — we just cap the tail
# ~20s sooner. Result is cached per project, so it's a one-time cost anyway.
_LLM_TIMEOUT_SECONDS = 40.0
_LLM_MODEL = "claude-sonnet-4-6"
# 10 records × ~15 fields × realistic content ≈ 4-6 KB of JSON. 2048 tokens
# truncated responses mid-array (parser failed because the closing `]` was
# never emitted), so bump to a comfortable headroom. Sonnet only emits what
# it needs, so this is a ceiling, not a target.
_LLM_MAX_TOKENS = 8192


async def generate_records_llm(
    entity_name: str,
    fields: list[FieldHint],
    domain: str,
    count: int = 10,
) -> list[dict[str, Any]] | None:
    """Generate `count` realistic records for the given (domain, entity_name).

    Returns None when:
      - `fields` is empty (no shape to generate against)
      - `ANTHROPIC_API_KEY` is not set
      - the API call fails or times out
      - the response can't be parsed as a JSON array
      - the response is shorter than half the requested count

    Caller falls through to Faker on None; this function never raises.
    """
    if not fields:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Not an error — just means the LLM layer is disabled in this env.
        # Log once at debug level (would be too noisy at INFO since this
        # fires on every cache-miss preview-data request).
        logger.debug(
            "fixtures.llm: ANTHROPIC_API_KEY not set, skipping LLM generation "
            "for %s/%s — falling through to Faker",
            domain, entity_name,
        )
        return None

    prompt = _build_prompt(entity_name, fields, domain, count)
    try:
        text = await asyncio.wait_for(
            _call_anthropic(api_key, prompt),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "fixtures.llm: timeout after %.1fs for %s/%s",
            _LLM_TIMEOUT_SECONDS, domain, entity_name,
        )
        return None
    except Exception as e:  # noqa: BLE001 — auth, billing, network, etc.
        logger.warning("fixtures.llm: API failure for %s/%s: %s", domain, entity_name, e)
        return None

    parsed = _extract_json_array(text)
    if parsed is None:
        logger.warning(
            "fixtures.llm: could not parse JSON array for %s/%s — first 200 chars: %s",
            domain, entity_name, text[:200].replace("\n", " "),
        )
        return None

    if len(parsed) < count // 2:
        logger.warning(
            "fixtures.llm: short response (%d/%d) for %s/%s — falling through",
            len(parsed), count, domain, entity_name,
        )
        return None
    logger.info(
        "fixtures.llm: generated %d records for %s/%s",
        len(parsed), domain, entity_name,
    )
    return parsed[:count]


def _build_prompt(entity_name: str, fields: list[FieldHint], domain: str, count: int) -> str:
    """Render the user prompt. The system prompt (set in `_collect_llm_text`)
    pins JSON-only output; this prompt focuses on realism + field-by-field
    requirements."""
    field_list = "\n".join(
        f"  - {f.name} ({f.type})"
        for f in fields
    )
    return (
        f"Generate {count} realistic fixture records for the entity "
        f"`{entity_name}` in the `{domain}` domain.\n\n"
        f"Each record must include EXACTLY these fields (matching names "
        f"and types):\n{field_list}\n\n"
        "Requirements:\n"
        f"- Output a JSON array of exactly {count} objects, no wrapper, no commentary.\n"
        "- String fields should contain realistic, varied, domain-appropriate "
        "content (no Lorem ipsum, no placeholder text).\n"
        "- For 'reason' / 'description' / 'notes' fields, write 1-2 short, "
        "realistic phrases that a real user would type (\"Family medical leave\", "
        f"not \"Lorem ipsum\").\n"
        "- For 'name' fields, use realistic first+last names from diverse cultures.\n"
        "- For 'email' fields, derive from the name (e.g. sarah.chen@company.com).\n"
        "- For 'status' / enum-like fields, use plausible values "
        "('approved', 'pending', 'rejected', 'active', 'archived', etc.).\n"
        "- For dates, use ISO 8601 format and realistic relative timing.\n"
        "- For UUIDs, generate valid UUID-v4 strings.\n"
        "- For numeric fields, use plausible domain-appropriate values "
        "(e.g. daysRequested: 1-15 for leave; amount: $50-$5000 for orders).\n"
        "- Vary the records — avoid copy-paste repetition across rows.\n\n"
        f"Output ONLY the JSON array. Begin with `[` and end with `]`."
    )


async def _call_anthropic(api_key: str, prompt: str) -> str:
    """Send a single fixture-generation prompt to the Anthropic API and return
    the assistant message text. Mirrors the pattern in `runtime/ai/base.py`."""
    # Lazy import — keeps this module importable in environments without the
    # `anthropic` package installed (e.g. CI jobs that only run tests).
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=_LLM_MODEL,
        max_tokens=_LLM_MAX_TOKENS,
        system=(
            "You generate realistic JSON fixture data. Output ONLY a JSON array "
            "of objects. No markdown, no commentary, no surrounding prose."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    # `content` is a list of TextBlock | … — concat all text blocks.
    parts: list[str] = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


def _extract_json_array(text: str) -> list[dict[str, Any]] | None:
    """Extract the first JSON array from `text`. Tolerates markdown fences and
    leading/trailing prose. Returns None if no parseable array is found or if
    the parsed value isn't a list-of-objects."""
    # Strip markdown fences if present.
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()

    # Find the bounds of the outermost array.
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = cleaned[start : end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if not isinstance(value, list):
        return None
    # Filter to dict-shaped items (defensive — LLM occasionally emits a
    # mixed array).
    return [item for item in value if isinstance(item, dict)]
