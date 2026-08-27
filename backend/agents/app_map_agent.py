"""App-map (skeleton) planner — the first pass of large-app decomposition (spec B2).

For enterprise-scale apps the whole plan does not fit one LLM context. This agent
runs a small, bounded FIRST pass that emits only the *skeleton*: entities (names +
one-line + field-name→type summary), pages (route + archetype + entity + one-line),
workflows (id + trigger + target entity), and roles. Per-page/per-form detail is
authored LATER, each in its own bounded registry-slice context.

This module is ADDITIVE. It does not touch the one-shot planner; a later task wires
the branch that chooses skeleton-vs-oneshot. The skeleton is normalized through the
SAME normalizer the one-shot uses (`planner._normalize_oneshot_plan`) so it is
plan-shaped (`data_models` list) and directly consumable by
`resource_registry.build_canonical_registry`.

The LLM boundary is INJECTABLE via the ``_query`` parameter of
``run_app_map_planner`` — the default hits the real Anthropic SDK, tests pass a
fake that returns a canned skeleton string (no network).
"""

from __future__ import annotations

import inspect
import os
from typing import Callable

from agents.planner import _extract_plan_object, _normalize_oneshot_plan


class AppMapError(Exception):
    """Raised when the app-map LLM response cannot be parsed into a skeleton.

    Callers catch this to fall back to the one-shot planner (or surface the
    failure) rather than proceeding with a malformed plan.
    """


APP_MAP_SYSTEM_PROMPT = r"""You are an application architect producing an app MAP
(a skeleton), not a full plan. This is the FIRST pass of a two-pass process for a
large application: you outline the whole app cheaply; per-page and per-form detail
is authored LATER in separate, focused passes. Emit LEAN structure only.

Output a SINGLE JSON object, no prose, no markdown fences, with these keys:

{
  "app_name": "<short name>",
  "domain": "<one-word domain>",
  "entities": {
    "<EntityName>": {
      "description": "<one line, what this entity is>",
      "fields": { "<fieldName>": "<sqlType>", ... }   // NAME:TYPE SUMMARY ONLY
    },
    ...
  },
  "pages": [
    {
      "route": "/<path>",
      "name": "<Page Name>",
      "entity": "<EntityName or null>",
      "archetype": "<list | detail | form | dashboard | auth | landing>",
      "description": "<one line, what the page is for>"
    },
    ...
  ],
  "workflows": [
    { "id": "<workflow-id>", "trigger": "<what fires it>", "entity": "<target EntityName>" },
    ...
  ],
  "roles": ["<role>", ...]
}

HARD RULES — skeleton only:
- entities.fields is a NAME->TYPE SUMMARY map (e.g. "status": "varchar"). Do NOT
  emit full field specs (no control, label, required, enum, validation, defaults).
- pages carry route + name + entity + archetype + a one-line description ONLY.
  Do NOT emit `fields`, `widgets`, `actions`, or any per-page detail — that is
  authored later, per page, in its own bounded context.
- workflows carry id + trigger + target entity ONLY. Do NOT emit steps/nodes.
- Cover the FULL app breadth (every module/entity/page) — breadth over depth.
- Every page.entity and workflow.entity MUST name an entity you listed.

Remember: skeleton only; per-page detail is authored later."""


def normalize_skeleton(raw: dict) -> dict:
    """Normalize a raw skeleton into a plan-shaped dict.

    Reuses the one-shot normalizer so the skeleton gets the same `entities`(dict)
    -> `data_models`(list) conversion, `relations` derivation from `depends_on`,
    and `module_name` default — making it directly consumable by
    `build_canonical_registry`. Idempotent; safe on an already-normalized dict.
    """
    if not isinstance(raw, dict):
        raise AppMapError(f"skeleton must be a dict, got {type(raw).__name__}")
    return _normalize_oneshot_plan(raw)


async def _default_query(system_prompt: str, user_prompt: str) -> str:
    """Default LLM boundary — a single headless Anthropic call (mirrors the
    one-shot planner's SDK usage). Returns the raw response text.

    Injected over in tests via the ``_query`` parameter; never hit there.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AppMapError(
            "run_app_map_planner requires ANTHROPIC_API_KEY (or an injected "
            "_query). Set it in the backend env or pass _query=..."
        )
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        # Bumped from 8000 → 16000: a 15-entity ATS skeleton exceeded 8k,
        # response truncated mid-object, JSON parser returned None, whole
        # decomposition path crashed with AppMapError and fell back to
        # one-shot. 16k is enough for ~25 entities × 10 pages skeleton
        # per empirical sizing.
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    # If the response hits max_tokens the tail is truncated; log so the
    # next bump is data-driven, not another guessed round.
    if getattr(msg, "stop_reason", None) == "max_tokens":
        import logging
        logging.getLogger(__name__).warning(
            "app_map_agent: response hit max_tokens (16000) — response "
            "may be truncated, consider bumping further"
        )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def run_app_map_planner(
    prompt: str,
    domain_context: dict | None = None,
    *,
    _query: Callable[[str, str], str] | None = None,
) -> dict:
    """Produce a normalized, plan-shaped skeleton from a prompt.

    The LLM call goes through ``_query(system_prompt, user_prompt) -> str`` — a
    seam that DEFAULTS to a real Anthropic call but is injected in tests with a
    fake returning canned skeleton JSON (sync or async fakes both work). The
    response is parsed (tolerating ```json fences), normalized to plan shape, and
    returned.

    Raises ``AppMapError`` on a malformed / unparseable response.
    """
    from services.domain_context import build_domain_profile

    query_fn = _query or _default_query

    system_prompt = APP_MAP_SYSTEM_PROMPT + build_domain_profile(domain_context, "planner")
    user_prompt = (
        f"App brief:\n{(prompt or '').strip()}\n\n"
        "Emit the app-map skeleton JSON now. Single object, no prose, no fences."
    )

    try:
        result = query_fn(system_prompt, user_prompt)
        if inspect.isawaitable(result):
            import asyncio

            result = asyncio.run(result)
    except AppMapError:
        raise
    except Exception as e:  # LLM/transport failure -> caller can fall back
        raise AppMapError(f"app-map query failed: {e}") from e

    if not isinstance(result, str) or not result.strip():
        raise AppMapError("app-map query returned empty/non-string response")

    raw = _extract_plan_object(result)
    if raw is None:
        # Log more context so we can tell truncation apart from shape issues.
        import logging
        logging.getLogger(__name__).error(
            "app_map_agent: JSON parse failed. len=%d, head=%r, tail=%r",
            len(result), result[:200], result[-200:],
        )
        raise AppMapError(
            f"app-map response did not contain parseable JSON. Head: {result[:200]!r}"
        )

    return normalize_skeleton(raw)
