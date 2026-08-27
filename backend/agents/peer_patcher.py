"""LLM as peer patcher: one writeArtifacts tool call, full artifact bundle.

Replaces the multi-agent pipeline (design → contract → schema → page → ...)
with a single LLM invocation that returns all three artifacts (page schemas
map + nav-flow + tokens) at once. The output is committed via one
replaceArtifacts action so undo restores the prior project state exactly.
"""
from __future__ import annotations
import json
from typing import AsyncIterator, Optional

from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)

from agents.peer_patcher_schemas import artifacts_json_schema, Artifacts
from services.artifact_validator import validate_all


async def run_peer_patcher(
    *,
    user_prompt: str,
    current_artifacts: Optional[dict],
    registry_digest: str,
    registry: Optional[dict] = None,
    token_vocabulary: str = "",
    max_retries: int = 2,
) -> AsyncIterator[dict]:
    """Yield SSE-shaped events as the LLM produces its artifact bundle.

    Yields:
        {"event": "status", "data": {...}}
        {"event": "log",    "data": {"text": "..."}}
        {"event": "artifacts", "data": {"artifacts": <dict>, "rationale": "..."}}
            -- terminal on success
        {"event": "error", "data": {"text": "..."}}
            -- terminal on unrecoverable failure
    """
    yield {"event": "status",
           "data": {"message": "Generating artifacts via peer patcher..."}}

    system = _build_system_prompt(registry_digest, token_vocabulary, current_artifacts)
    tool_schema = artifacts_json_schema()

    client = AsyncAnthropic()
    last_error: Optional[str] = None
    prompt = user_prompt

    for attempt in range(1, max_retries + 2):  # initial + up to max_retries
        yield {"event": "log",
               "data": {"text": f"[PeerPatcher] Attempt {attempt}/{max_retries + 1}"}}

        try:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16_000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": "writeArtifacts",
                    "description":
                        "Commit a complete updated artifact bundle. "
                        "Call exactly once with the full {pageSchemas, navFlow, tokens}.",
                    "input_schema": tool_schema,
                }],
                tool_choice={"type": "tool", "name": "writeArtifacts"},
            )
        except Exception as e:
            yield {"event": "log",
                   "data": {"text": f"[PeerPatcher] API call failed: {e}"}}
            last_error = str(e)
            # API failures don't get retried — they're network/auth issues
            yield {"event": "error", "data": {"text": str(e)}}
            return

        # Extract tool_use block
        artifacts_input = None
        rationale_parts: list[str] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "tool_use" and getattr(block, "name", None) == "writeArtifacts":
                artifacts_input = block.input
            elif btype == "text":
                rationale_parts.append(getattr(block, "text", ""))

        if artifacts_input is None:
            last_error = "LLM did not call writeArtifacts"
            yield {"event": "log",
                   "data": {"text": f"[PeerPatcher] {last_error} (attempt {attempt})"}}
            prompt = (
                f"{user_prompt}\n\n"
                f"Previous attempt failed: did not call the writeArtifacts tool. "
                f"Call it now with the full artifact bundle."
            )
            continue

        # Validate against the Pydantic shape
        try:
            Artifacts.model_validate(artifacts_input)
        except Exception as e:
            last_error = f"Validation failed: {e}"
            yield {"event": "log",
                   "data": {"text": f"[PeerPatcher] {last_error} (attempt {attempt})"}}
            prompt = (
                f"{user_prompt}\n\n"
                f"Previous attempt failed validation:\n{str(e)[:1500]}\n\n"
                f"Fix the issues and call writeArtifacts again."
            )
            continue

        # NEW: domain validators (registry closure, token closure, ids, nav)
        if registry is not None:
            errs = validate_all(artifacts_input, registry)
            if errs:
                last_error = "Domain validation failed:\n  " + "\n  ".join(errs[:10])
                yield {"event": "log",
                       "data": {"text": f"[PeerPatcher] {last_error} (attempt {attempt})"}}
                prompt = (
                    f"{user_prompt}\n\n"
                    f"Previous attempt failed domain validation:\n{last_error}\n\n"
                    f"Fix every error and call writeArtifacts again."
                )
                continue

        # Success
        rationale = "\n".join(rationale_parts).strip()
        yield {"event": "log",
               "data": {"text": "[PeerPatcher] Artifacts validated"}}
        yield {"event": "artifacts",
               "data": {"artifacts": artifacts_input, "rationale": rationale}}
        return

    # Out of retries
    yield {"event": "error",
           "data": {"text": f"[PeerPatcher] Exhausted retries. Last error: {last_error}"}}


def _build_system_prompt(
    registry_digest: str,
    tokens: str,
    current: Optional[dict],
) -> str:
    """The constraint contract the LLM operates under."""
    current_repr = (
        json.dumps(current, indent=2)[:8000]  # cap to keep prompt manageable
        if current else "null"
    )
    tokens_repr = tokens or "(use sensible defaults)"

    return f"""You are Tentoro Forge's peer patcher. Produce an updated artifact bundle by calling the writeArtifacts tool exactly once.

# Component registry — ONLY use these components, ONLY these props

{registry_digest}

# Available tokens — every color/spacing/typography value MUST reference one of these

{tokens_repr}

# Current artifacts (null = greenfield)

{current_repr}

# Constraints (MANDATORY — failure to satisfy will trigger a retry with errors)

- Call writeArtifacts exactly once with the full bundle.
- Every node has a globally unique id across all page schemas.
- Every component name in pageSchemas exists in the registry above.
- Every prop on every node matches the registry descriptor (name + type).
- For enum props, value must be one of the listed options.
- Every visual value either references a token or is omitted (no raw hex, no raw px).
- pageSchemas keys match navFlow.pages[].id exactly.
- Any onClick navigate action's trigger matches a navFlow.transitions[].trigger.
- Tokens artifact has all 7 categories (color, typography, spacing, radius, shadow, motion, breakpoints) — empty dicts are fine but the keys must exist.
- For first-time generation: pick at least one page (route '/' with id 'home'), sensible navFlow with initialPage='home', and a reasonable default tokens set.
- For updates: PRESERVE node ids that already exist in current artifacts. Only re-mint ids for genuinely new nodes.
"""
