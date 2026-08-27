"""Python-side HTTP client for the 21st.dev MCP server.

The stdio integration in ``services.magic_mcp`` exposes the MCP to LLMs
running under the Claude Agent SDK. This module is complementary: it
lets *our own Python code* (Smith tool dispatch, design-agent pre-fetch,
future callers) call 21st.dev tools directly.

Endpoint: POST https://21st.dev/api/mcp with header ``x-api-key: <key>``.
Wire format: JSON-RPC 2.0 ``tools/call``.

All entry points fail closed — if the double-gate (flag + key) is off,
or the network call fails, or the response is unparseable, we return
an empty/falsy result. Callers must handle the empty case (this MCP
is inspiration, not a hard dependency).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from services import magic_mcp

logger = logging.getLogger(__name__)

_ENDPOINT = "https://21st.dev/api/mcp"
_TIMEOUT_SECONDS = 60.0
_MAX_TEXT_BYTES = 200_000  # per response — an insurance cap, not a real limit


class MagicMCPError(RuntimeError):
    """Raised only by callers that want to surface failure loudly.
    The top-level helpers never raise — they log and return empty.
    """


async def call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke a 21st.dev MCP tool. Returns the parsed JSON-RPC result payload
    (``{}`` on any failure — the double-gate off, missing key, network error,
    unparseable response). Never raises.
    """
    if not magic_mcp.is_enabled():
        return {}
    api_key = (os.environ.get("FORGE_21ST_API_KEY") or "").strip()
    if not api_key:
        return {}
    try:
        import httpx  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover — httpx is a fastapi dep, should be there
        logger.warning("[magic-mcp] httpx not installed; skipping tool call")
        return {}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {
        "x-api-key": api_key,
        "content-type": "application/json",
        "accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(_ENDPOINT, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[magic-mcp] tool_call %s failed: %s", tool_name, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("[magic-mcp] non-object response for %s", tool_name)
        return {}
    if data.get("error"):
        logger.warning("[magic-mcp] server error for %s: %s", tool_name, data["error"])
        return {}
    result = data.get("result")
    return result if isinstance(result, dict) else {}


def extract_text(result: dict[str, Any]) -> str:
    """Pull the primary text block out of an MCP result envelope.

    MCP results carry a ``content`` list of typed blocks. We concatenate
    every ``{"type": "text", "text": "..."}`` we find, capped at
    ``_MAX_TEXT_BYTES``. Returns ``""`` when no text is found.
    """
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if not isinstance(content, list):
        # Some responses put text under `result.text` directly.
        maybe = result.get("text")
        return str(maybe)[:_MAX_TEXT_BYTES] if isinstance(maybe, str) else ""
    parts: list[str] = []
    total = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        remaining = _MAX_TEXT_BYTES - total
        if remaining <= 0:
            break
        parts.append(text[:remaining])
        total += len(parts[-1])
    return "".join(parts)


async def search_components(query: str, *, limit: int = 3) -> list[dict]:
    """Search the 21st.dev catalog for components matching ``query``.

    FREE tier call. Returns a list of parsed component metadata dicts,
    each shaped like ``{"id": int, "name": str, "author": str,
    "description": str, "preview": str, "raw": <str>}``. Empty list on
    any failure or when no matches are found.

    The API returns human-formatted markdown text; we parse it into
    structured dicts so callers can pick an id programmatically.
    """
    result = await call_tool(
        "search",
        {"query": query, "type": "component", "limit": max(1, min(int(limit), 10))},
    )
    text = extract_text(result)
    if not text:
        return []

    import re as _re

    # Pattern anchors on the "[id: NNN]" tag every catalog row emits.
    header_re = _re.compile(r"###\s*\[component\]\s*(?P<name>.+?)\s*\[id:\s*(?P<id>\d+)\s*\]")
    author_re = _re.compile(r"^by\s+(?P<author>\S+)", _re.MULTILINE)
    preview_re = _re.compile(r"preview:\s*(?P<url>\S+)")

    entries: list[dict] = []
    # Split on the header, keeping the header text via the split's captures.
    positions = [(m.start(), m.group("name").strip(), int(m.group("id"))) for m in header_re.finditer(text)]
    for i, (start, name, cid) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        block = text[start:end]
        author_m = author_re.search(block)
        preview_m = preview_re.search(block)
        # Description is the paragraph AFTER the author line, before "preview:".
        desc = ""
        if author_m:
            after_author = block[author_m.end() :]
            desc_end = after_author.find("preview:")
            if desc_end != -1:
                desc = after_author[:desc_end].strip()
            else:
                desc = after_author.strip()
        entries.append({
            "id": cid,
            "name": name,
            "author": author_m.group("author") if author_m else "",
            "description": desc,
            "preview": preview_m.group("url") if preview_m else "",
            "raw": block.strip(),
        })
    return entries


async def get_component_code(component_id: int | str) -> str:
    """Fetch a component's real code by id (from ``search_components``).

    PAID call — uses the account's daily retrieval quota. Returns the raw
    text (JSX/TSX + supporting files, sometimes with prose framing), or
    ``""`` on any failure.
    """
    result = await call_tool("get_component", {"id": int(component_id)})
    return extract_text(result)


async def generate_component(description: str, hint: str | None = None) -> str:
    """Convenience: search → pick top match → get_component. Returns raw
    JSX/TSX text or ``""``.

    Uses ONE search call (free) plus ONE get_component call (paid). The
    ``hint`` (if given) is appended to the search query to steer style.
    For richer selection (LLM-pick over N candidates), use
    ``search_components`` + ``get_component_code`` directly.
    """
    query = description
    if hint:
        query = f"{description} {hint}"
    candidates = await search_components(query, limit=3)
    if not candidates:
        return ""
    # Simple heuristic: take the first hit — the API ranks by relevance
    # by default. Callers wanting LLM-based pick should compose their own.
    return await get_component_code(candidates[0]["id"])


def parse_json_from_text(text: str) -> Any | None:
    """Best-effort JSON extraction from a text blob. Returns None on failure.

    21st.dev tools sometimes wrap JSON in markdown fences or prose. This
    helper handles the common wrappers so callers can consume structured
    results without re-implementing extraction.
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        # ```json … ``` or ``` … ```
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Try to find the first { or [ and take the balanced span.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = stripped.find(opener)
            if start == -1:
                continue
            depth = 0
            for i, ch in enumerate(stripped[start:], start):
                if ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(stripped[start : i + 1])
                        except json.JSONDecodeError:
                            break
        return None
