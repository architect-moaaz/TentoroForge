"""LLM-based converter from React/Tailwind JSX to our schemaVersion:2 JSON.

Complements the deterministic parser in :mod:`services.jsx_to_schema`,
which is narrowly scoped to Figma MCP's restricted JSX subset. Real
React JSX from 21st.dev's `generate` tool includes function components,
hooks, imports, TypeScript types, and shadcn/ui components — the
deterministic parser would choke on the first ``useState``.

This module hands the whole blob to Claude with strict instructions:
map to our library primitives, drop hooks/state/imports, extract inline
literals as props, return schemaVersion:2 JSON only. Non-deterministic
but works today; the deterministic parser can replace this later under
the same API without breaking callers.

Public API::

    result = await convert_jsx_to_schema(jsx, hint="Wellness dashboard header")
    if result:
        page["root"]["children"].append(result)   # merge fragment into a page

Return shape is a schema NODE (``{"type", "props", "children"}``), not a
full page — the caller decides where to splice it. On any failure
(missing API key, LLM error, no valid JSON in the response), returns
None. Never raises.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


# The list of library components the converter is allowed to emit. Keep it
# small and stable — the LLM does better with a closed vocabulary than with
# a 100-item registry it might hallucinate against. When a source component
# doesn't map to any of these, the converter must fall back to the closest
# primitive rather than invent a new type.
ALLOWED_COMPONENT_TYPES: tuple[str, ...] = (
    # Layout primitives
    "Stack", "Row", "Grid", "Section", "Card",
    # Content
    "Heading", "Text", "Image", "Icon", "Badge", "Tag",
    # Actions
    "Button", "IconButton", "NavLink",
    # Data displays
    "Table", "List", "MetricTile", "Stat", "DescriptionList",
    # Forms
    "Input", "Textarea", "Select", "Combobox", "Switch", "Checkbox",
    "RadioGroup", "DatePicker", "NumberInput", "FileUpload",
    # Charts + visualization
    "Chart", "Gauge", "SplitArc", "Heatmap", "Progress",
    # Feedback
    "Banner", "Spinner", "IllustratedEmpty", "EmptyState",
    # Nav
    "Breadcrumbs", "Tabs", "Pagination",
)


class JSXConversionError(RuntimeError):
    """Optional — raised only by callers that want failures to be loud."""


def _build_system_prompt() -> str:
    """The converter prompt. Kept as a single string for cache-friendliness."""
    allowed = ", ".join(ALLOWED_COMPONENT_TYPES)
    return f"""\
You convert React/Tailwind JSX into schemaVersion:"2" JSON for a low-code renderer.

OUTPUT CONTRACT — you MUST emit exactly one JSON object with this shape:
  {{"type": "<component>", "props": {{...}}, "children": [<node>, ...]}}

The top level is a single node — a fragment, not a full page.

RULES
1. Only these component types are allowed:
{allowed}
   If the source uses a component that doesn't map here, use the closest
   primitive: shadcn Card → Card; shadcn Button → Button; div → Stack (if
   flex/grid) or Card (if bordered) or Section (if outer); h1/h2/h3 → Heading;
   p / span → Text; img → Image; svg icon → Icon; input → Input; select →
   Select; textarea → Textarea; nav → Row.

2. DROP entirely: imports, exports, hooks (useState/useEffect/etc), event
   handlers (onClick/onChange callbacks), refs, className strings that only
   affect visual style (color/border/shadow — the renderer applies the theme).
   KEEP className hints that convey semantic layout (justify-between,
   flex-col, gap-4) — translate them to props (e.g. gap="tokens.spacing.4",
   align="between") when a matching prop exists; otherwise drop.

3. LITERALS: inline text like "Total Revenue" → {{"type":"Text","props":{{"content":"Total Revenue"}}}}.
   Never invent bindings like "{{{{revenue}}}}" — extract only what's in the JSX.
   Icon references (<Icon name="Home"/>, <HomeIcon/>) → {{"type":"Icon","props":{{"name":"home"}}}}.

4. NESTING: keep the JSX tree structure. Each JSX element becomes one node.
   Text-only children collapse into a single Text child, not multiple.

5. HINTS: when the caller gives a hint like "wellness dashboard metric row",
   use it to disambiguate — e.g. a shadcn Card wrapping a large number is a
   MetricTile, not a plain Card.

6. VALID JSON ONLY: no prose, no markdown fences. Just the object.
   If the JSX is unparseable or has no visible UI, return {{"type":"Text","props":{{"content":""}}}}.

Common shadcn → our-library mappings:
  <Card><CardHeader><CardTitle>X</CardTitle></CardHeader><CardContent>Y</CardContent></Card>
    → {{"type":"Card","props":{{"title":"X"}},"children":[{{"type":"Text","props":{{"content":"Y"}}}}]}}
  <Button variant="outline">Save</Button>
    → {{"type":"Button","props":{{"label":"Save","variant":"outline"}}}}
  <Badge>New</Badge>
    → {{"type":"Badge","props":{{"label":"New"}}}}
"""


def _extract_json_object(text: str) -> dict | None:
    """Extract the first balanced JSON object from ``text``. None on failure."""
    if not text:
        return None
    stripped = text.strip()
    # Strip common LLM wrappers first.
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Balance-scan for the first {...} span.
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(stripped[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _validate_node(obj: Any) -> dict | None:
    """Ensure ``obj`` looks like a schema node. Prunes unknown top-level fields.

    A valid node has ``type`` (str) and may have ``props`` (dict) and
    ``children`` (list of nodes or strings). Anything that fails the shape
    check yields None so the caller falls back gracefully.
    """
    if not isinstance(obj, dict):
        return None
    node_type = obj.get("type")
    if not isinstance(node_type, str) or not node_type:
        return None
    # Not enforcing allowed-types strictly here — the LLM sometimes emits
    # a legitimate less-common name and we prefer to accept it. A separate
    # validator downstream can reject unknowns if needed.
    out: dict = {"type": node_type}
    props = obj.get("props")
    if isinstance(props, dict):
        out["props"] = props
    children = obj.get("children")
    if isinstance(children, list):
        kept: list = []
        for c in children:
            if isinstance(c, str):
                kept.append(c)
            elif isinstance(c, dict):
                child = _validate_node(c)
                if child is not None:
                    kept.append(child)
        if kept:
            out["children"] = kept
    return out


async def convert_jsx_to_schema(
    jsx: str,
    hint: str | None = None,
    *,
    model: str = "claude-sonnet-4-6",
    timeout_seconds: float = 45.0,
    query_fn: Any | None = None,
) -> dict | None:
    """Convert ``jsx`` into a schemaVersion:2 node fragment. None on failure.

    Args:
        jsx: React/Tailwind source. Any well-formed JSX blob is accepted;
            imports, hooks, and unresolved variables are OK — the converter
            drops them.
        hint: Optional one-line context ("wellness dashboard header",
            "pricing card with monthly toggle"). Steers ambiguous mappings.
        model: Claude model id. Sonnet is a good speed/quality tradeoff;
            override to opus if quality matters more than latency.
        timeout_seconds: Hard cap on the LLM call.
        query_fn: Optional injectable async callable ``(system, user) -> str``
            for tests. When None (default) uses the Anthropic SDK.

    Never raises. Returns None when ``ANTHROPIC_API_KEY`` is missing, the
    LLM errors, or the response has no valid JSON node.
    """
    if not jsx or not jsx.strip():
        return None
    system_prompt = _build_system_prompt()
    hint_line = f"\n\nContext hint: {hint}" if hint else ""
    user_prompt = f"Convert this JSX into one schemaVersion:2 node:{hint_line}\n\n```jsx\n{jsx}\n```"

    if query_fn is not None:
        try:
            text = await query_fn(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jsx→schema] injected query_fn failed: %s", exc)
            return None
    else:
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            logger.warning("[jsx→schema] no ANTHROPIC_API_KEY; skipping conversion")
            return None
        try:
            from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        except ImportError:  # pragma: no cover
            logger.warning("[jsx→schema] anthropic SDK unavailable")
            return None
        try:
            client = llm_client.AsyncAnthropic(api_key=api_key)
            msg = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=8000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ),
                timeout=timeout_seconds,
            )
            text = "".join(getattr(b, "text", "") for b in msg.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jsx→schema] LLM call failed: %s", exc)
            return None

    raw = _extract_json_object(text)
    if raw is None:
        logger.warning("[jsx→schema] no valid JSON object in LLM response")
        return None
    validated = _validate_node(raw)
    if validated is None:
        logger.warning("[jsx→schema] response doesn't look like a schema node: %r", raw)
        return None
    return validated
