"""Chunked page-schema generation.

Large pages overflow the model's single-response output cap. Instead of one giant
LLM response, generate the page ROOT skeleton (region placeholders), then fill each
region's subtree in a separate bounded call, then assemble. Functions take an
injected ``call_llm`` so they are unit-testable without the network.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from agents.feature_slice_schema_agent import _extract_json

CallLLM = Callable[[str], Awaitable[str]]

# Substrings that identify the API output-token overflow (case-insensitive).
_OVERFLOW_MARKERS = ("output token", "max_tokens", "too long", "token limit", "token maximum")


def is_output_overflow_error(exc: BaseException | None) -> bool:
    """True when an exception looks like the LLM output-token cap being hit."""
    if exc is None:
        return False
    msg = str(exc).lower()
    return any(m in msg for m in _OVERFLOW_MARKERS)


SKELETON_DIRECTIVE = """

## OUTPUT OVERRIDE — SKELETON ONLY
IGNORE any earlier instruction to output the full page schema. This page is large and is
being generated in chunks. Output ONLY the page ROOT layout with REGION PLACEHOLDERS — do
NOT expand region contents.

Output a single JSON object EXACTLY of this shape:
{
  "schemaVersion": "2",
  "root": {
    "type": "Stack",
    "id": "root",
    "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.section" },
    "children": [
      { "type": "Region", "id": "<short-slug>", "brief": "<one sentence: what this region holds>" }
    ]
  }
}
Rules: 2-8 regions, one per top-level section of the page, in display order. Every child of
root MUST be a Region with a unique "id" and a "brief". No other top-level node types. No
nested children inside regions. Output ONLY the JSON object.
"""


def region_placeholders(skeleton: dict) -> list[dict]:
    """Extract [{id, brief}] for each Region child of the skeleton root."""
    root = (skeleton or {}).get("root") or {}
    out: list[dict] = []
    for child in (root.get("children") or []):
        if isinstance(child, dict) and child.get("type") == "Region" and child.get("id"):
            out.append({"id": child["id"], "brief": child.get("brief", "")})
    return out


async def generate_skeleton(base_prompt: str, call_llm: CallLLM) -> dict | None:
    """Pass 1 — emit the page root with region placeholders. None on failure."""
    # base_prompt (the big shared context) is identical across the skeleton + every
    # region fill — mark it cacheable so only the small directive is fresh input.
    from services.sdk_agent_runner import with_cache_prefix
    raw = await call_llm(with_cache_prefix(base_prompt, SKELETON_DIRECTIVE))
    skel = _extract_json(raw)
    if not isinstance(skel, dict):
        return None
    root = skel.get("root")
    if not isinstance(root, dict) or not isinstance(root.get("children"), list):
        return None
    if not region_placeholders(skel):
        return None
    return skel


REGION_DIRECTIVE = """

## OUTPUT OVERRIDE — SINGLE REGION ONLY
IGNORE any earlier instruction to output the full page schema. Output ONLY the subtree for
ONE region of this page. Use the design tokens, data bindings, components, and archetype
guidance from above.

Region id: {id}
Region brief: {brief}

Output a single JSON object: ONE node (e.g. {{"type":"Card"|"Stack"|"Grid", "id":"{id}",
"props":{{...}}, "children":[...]}}) that fully renders this region's content. Set the top
node's "id" to "{id}". Output ONLY the JSON object.
"""


async def fill_region(base_prompt: str, region: dict, call_llm: CallLLM) -> dict | None:
    """Pass 2 — emit one region's subtree. None on failure."""
    directive = REGION_DIRECTIVE.format(id=region.get("id", ""), brief=region.get("brief", ""))
    from services.sdk_agent_runner import with_cache_prefix
    raw = await call_llm(with_cache_prefix(base_prompt, directive))
    node = _extract_json(raw)
    if not isinstance(node, dict) or not node.get("type"):
        return None
    node["id"] = region.get("id") or node.get("id")
    return node


def _placeholder_node(region: dict) -> dict:
    """Minimal renderable node for a region whose fill failed."""
    rid = region.get("id") or "region"
    brief = (region.get("brief") or "Section").strip()[:80]
    return {
        "type": "Card",
        "id": rid,
        "children": [
            {"type": "Heading", "id": f"{rid}-h", "props": {"level": 2, "content": brief}},
        ],
    }


def assemble(skeleton: dict, filled: list, page_brief: dict) -> dict:
    """Replace each region placeholder in the skeleton root with its filled subtree
    (or a minimal placeholder when that region failed). Returns the final Page envelope."""
    regions = region_placeholders(skeleton)
    root = dict(skeleton.get("root") or {"type": "Stack", "id": "root"})
    children: list[dict] = []
    for i, region in enumerate(regions):
        node = filled[i] if i < len(filled) else None
        if isinstance(node, dict) and node.get("type"):
            children.append(node)
        else:
            children.append(_placeholder_node(region))
    root["children"] = children
    slug = page_brief.get("id") or "home"
    route = page_brief.get("route") or (f"/{slug}" if slug != "home" else "/")
    return {"schemaVersion": "2", "id": slug, "route": route, "layout": "main", "root": root}


async def generate_chunked_schema(base_prompt: str, page_brief: dict, call_llm: CallLLM) -> dict | None:
    """Two-pass chunked generation. Returns an assembled (un-normalized) Page dict, or
    None when the skeleton pass fails so the caller can fall back to _minimal_schema.
    Each region fill is isolated — a failing region degrades to a placeholder, never aborts."""
    try:
        skeleton = await generate_skeleton(base_prompt, call_llm)
    except Exception:
        skeleton = None
    if skeleton is None:
        return None

    regions = region_placeholders(skeleton)

    async def _safe_fill(region: dict) -> dict | None:
        try:
            return await fill_region(base_prompt, region, call_llm)
        except Exception:
            return None

    filled = await asyncio.gather(*[_safe_fill(r) for r in regions])
    return assemble(skeleton, list(filled), page_brief)
