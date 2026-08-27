"""Figma Schema Refiner.

Restructure a deterministic Figma-mapped Page schema (content-faithful but
fixed-pixel, non-responsive) into a responsive, component-library Page schema
while PRESERVING its content.

Design: docs/superpowers/specs/2026-06-04-figma-schema-refiner-design.md

The public entry point is `run_figma_schema_refiner(...)`. It returns the
refined schema dict, or **None** on any failure — the caller falls back to the
deterministic schema, so the refiner can never make things worse.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path

# Reuse the schema agent's JSON extraction, normalisation, and authoritative
# Zod validation so the refiner's output obeys the same contract the renderer
# trusts. `_validate_schema_json` degrades to None when pnpm/node is absent.
from agents.feature_slice_schema_agent import _extract_json, _validate_schema_json
from services.schema_normalizer import normalize_v2_schema

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("FORGE_REFINER_MODEL", "claude-sonnet-4-6")

_BINDING_RE = re.compile(r"\{\{.*?\}\}")
_IMG_EXT = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")

# Keys whose string values are layout/metadata, not human content — excluded
# from the content-preservation check (the refiner is *expected* to rewrite
# className/style; it must NOT drop content like labels, ids, bindings).
_NON_CONTENT_KEYS = {"className", "class", "style", "type", "id", "schemaVersion", "layout"}

_SYSTEM_PROMPT = """You are a senior frontend engineer. You are given a UI Page \
schema that was auto-generated from a Figma frame. It captured the CONTENT \
correctly but its layout is locked to fixed pixel widths and does not reflow.

Rewrite it into a clean, RESPONSIVE Page schema. Hard rules:

1. PRESERVE CONTENT EXACTLY. Keep every text value, every binding (the \
`{{ ... }}` mustache expressions), every `dataSources` entry, and every image / \
photo URL from the input. Do not invent, translate, or drop content.

2. RESTRUCTURE LAYOUT to be responsive and well grouped:
   - Wrap each logical group (e.g. an entry card, a stat, a section) in a real \
container with border, padding and subtle shadow.
   - Page sections: use `w-full max-w-[<design-width>px] mx-auto` — never a bare \
fixed `w-[Npx]`. Remove fixed `w-[Npx]` and `h-[Npx]` everywhere; use `min-h-` \
only when needed.
   - Rows of fields: `flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center` \
so they stack on mobile and flow on desktop. Add `min-w-0` so children can shrink.
   - Mobile-first; use `sm:` / `md:` / `lg:` prefixes for larger screens.

3. VOCABULARY: use ONLY component `type` values from the "Available components" \
list below. Keep the same top-level schema shape as the input (same \
`schemaVersion`, and a `children` array under the root).

4. OUTPUT: a SINGLE JSON object — the refined Page schema — and NOTHING else. No \
markdown fences, no prose.

The attached screenshot is the intended visual design; match its grouping, \
spacing and hierarchy."""

_USER_TEMPLATE = """Available components (use only these `type` values):
{descriptor}

Here is the deterministic Page schema to refine (preserve its content, fix its \
layout):

```json
{schema}
```

Return ONLY the refined Page schema JSON."""


# ---------------------------------------------------------------------------
# Content extraction + preservation guard (pure Python — works everywhere)
# ---------------------------------------------------------------------------
def _walk_content_strings(node):
    """Yield string values that represent human/content data — skipping
    className / style / type / id metadata."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _NON_CONTENT_KEYS:
                continue
            yield from _walk_content_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_content_strings(v)
    elif isinstance(node, str):
        yield node


def _content_tokens(schema: dict) -> tuple[set[str], set[str], list[str]]:
    """Return (bindings, image_urls, text_tokens) from a schema's content."""
    bindings: set[str] = set()
    urls: set[str] = set()
    texts: list[str] = []
    for s in _walk_content_strings(schema):
        for b in _BINDING_RE.findall(s):
            bindings.add(b)
        low = s.lower()
        if (s.startswith("http") or s.startswith("/")) and (low.endswith(_IMG_EXT) or "/static/" in low or s.startswith("http")):
            if "{{" not in s:
                urls.add(s)
            continue
        stripped = _BINDING_RE.sub("", s).strip()
        if len(stripped) >= 3 and re.search(r"[A-Za-z0-9]", stripped) and "{{" not in stripped:
            texts.append(stripped)
    return bindings, urls, texts


def _content_diff(src: dict, out: dict, *, text_threshold: float = 0.85) -> dict:
    """Compare content of `src` vs `out`. Returns a dict with the missing
    bindings / image URLs / text tokens, the text survival rate, and an `ok`
    flag (all bindings + URLs kept AND text rate >= threshold)."""
    s_bind, s_url, s_text = _content_tokens(src)
    out_blob = "\n".join(_walk_content_strings(out))
    missing_bind = [b for b in s_bind if b not in out_blob]
    missing_url = [u for u in s_url if u not in out_blob]
    missing_text = [t for t in s_text if t not in out_blob]
    text_rate = 1.0 if not s_text else (len(s_text) - len(missing_text)) / len(s_text)
    ok = (not missing_bind) and (not missing_url) and (text_rate >= text_threshold)
    return {
        "ok": ok,
        "missing_bindings": missing_bind,
        "missing_urls": missing_url,
        "missing_texts": missing_text,
        "text_rate": text_rate,
    }


def _preserves_content(src: dict, out: dict, *, text_threshold: float = 0.85) -> bool:
    """True when the refined `out` keeps the source's bindings, image URLs, and
    at least `text_threshold` of its significant text tokens."""
    return _content_diff(src, out, text_threshold=text_threshold)["ok"]


def _content_feedback(diff: dict, *, limit: int = 40) -> str:
    """A corrective instruction listing the dropped content, for a retry."""
    missing = (diff["missing_bindings"] + diff["missing_urls"] + diff["missing_texts"])[:limit]
    return (
        "Your previous output DROPPED required content. You MUST reproduce EVERY "
        "text value, binding, and image URL from the input schema verbatim. These "
        "items were missing and MUST appear exactly in your next output: "
        + "; ".join(repr(m) for m in missing)
        + ". Re-output the COMPLETE refined schema with all content included."
    )


def _structurally_valid(schema) -> bool:
    """Cheap structural sanity check that works without the Node toolchain."""
    if not isinstance(schema, dict):
        return False
    if "children" not in schema and "root" not in schema:
        return False
    ok = True

    def _chk(n):
        nonlocal ok
        if isinstance(n, dict):
            if "type" in n and not (isinstance(n["type"], str) and n["type"]):
                ok = False
            for v in n.values():
                _chk(v)
        elif isinstance(n, list):
            for v in n:
                _chk(v)

    _chk(schema)
    return ok


# ---------------------------------------------------------------------------
# Prompt assembly + LLM call
# ---------------------------------------------------------------------------
def _image_block(screenshot_path: str | None) -> dict | None:
    if not screenshot_path:
        return None
    p = Path(screenshot_path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def _build_content_blocks(schema: dict, screenshot_path: str | None, registry_descriptor: str) -> list[dict]:
    blocks: list[dict] = []
    img = _image_block(screenshot_path)
    if img:
        blocks.append(img)
    blocks.append({
        "type": "text",
        "text": _USER_TEMPLATE.format(
            descriptor=(registry_descriptor or "").strip(),
            schema=json.dumps(schema, indent=2),
        ),
    })
    return blocks


async def _call_refiner_llm(system: str, content_blocks: list[dict], timeout_s: int, model: str) -> str:
    """One multimodal Anthropic call. Raises on missing key / API / timeout."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.AsyncAnthropic(api_key=api_key)
    # Refined schemas can be large (the input frame schema is often >100KB),
    # so we need a generous output budget or the JSON truncates and fails to
    # parse. A large max_tokens makes the request long enough that the SDK
    # *requires* streaming — so we stream and accumulate.
    max_tokens = int(os.environ.get("FORGE_REFINER_MAX_TOKENS", "32000"))

    async def _stream() -> str:
        parts: list[str] = []
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            async for chunk in stream.text_stream:
                parts.append(chunk)
            final = await stream.get_final_message()
        if getattr(final, "stop_reason", None) == "max_tokens":
            logger.warning("[Refiner] output hit max_tokens (%d) — JSON likely truncated", max_tokens)
        return "".join(parts)

    return await asyncio.wait_for(_stream(), timeout=timeout_s)


async def run_figma_schema_refiner(
    deterministic_schema: dict,
    screenshot_path: str | None,
    registry_descriptor: str,
    *,
    timeout_s: int = 600,
    model: str = _DEFAULT_MODEL,
    max_attempts: int = 2,
) -> dict | None:
    """Refine a deterministic Figma-mapped Page schema into a responsive,
    component-library Page schema. Returns the refined schema, or None on any
    failure (caller falls back to `deterministic_schema`).

    Retries up to `max_attempts` times: a recoverable failure (unparseable
    JSON, structurally invalid, dropped content, or a real Zod rejection) feeds
    the model a corrective instruction and tries again before falling back. An
    API error / timeout is not retried.
    """
    try:
        base_blocks = _build_content_blocks(deterministic_schema, screenshot_path, registry_descriptor)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[Refiner] prompt build failed: %s — falling back", e)
        return None

    feedback = ""
    for attempt in range(1, max_attempts + 1):
        blocks = base_blocks if not feedback else base_blocks + [{"type": "text", "text": feedback}]

        try:
            raw = await _call_refiner_llm(_SYSTEM_PROMPT, blocks, timeout_s, model)
        except Exception as e:
            logger.warning("[Refiner] LLM call failed/timeout: %s — falling back", e)
            return None  # API/timeout: not worth retrying

        refined = _extract_json(raw)
        if not isinstance(refined, dict):
            logger.warning("[Refiner] attempt %d/%d: no JSON parsed", attempt, max_attempts)
            feedback = "Your previous output was not valid JSON. Output ONLY the JSON object — no prose, no markdown fences."
            continue

        try:
            refined = normalize_v2_schema(refined)
        except Exception:
            pass

        if not _structurally_valid(refined):
            logger.warning("[Refiner] attempt %d/%d: structurally invalid", attempt, max_attempts)
            feedback = ("Your previous output was missing a root `children` array or had a node with a "
                        "non-string `type`. Output a valid Page schema with a `children` array of typed nodes.")
            continue

        diff = _content_diff(deterministic_schema, refined)
        if not diff["ok"]:
            logger.warning(
                "[Refiner] attempt %d/%d: content not preserved (text_rate=%.2f, missing b/u/t=%d/%d/%d)",
                attempt, max_attempts, diff["text_rate"],
                len(diff["missing_bindings"]), len(diff["missing_urls"]), len(diff["missing_texts"]),
            )
            feedback = _content_feedback(diff)
            continue

        # Authoritative Zod check, tolerant of toolchain noise (real rejection
        # is marked "FAIL:"; module-resolution / pnpm warnings are environment
        # issues and must not block an otherwise-good refine).
        try:
            err = _validate_schema_json(refined)
        except Exception as e:  # pragma: no cover - validator env issues never block
            err = None
            logger.warning("[Refiner] Zod validator raised (%s) — relying on structural+content checks", e)
        if err is not None and "FAIL:" in str(err):
            logger.warning("[Refiner] attempt %d/%d: Zod rejected: %s", attempt, max_attempts, str(err)[:160])
            feedback = f"Schema validation rejected your output: {str(err)[:300]}. Fix the issue and re-output valid JSON."
            continue
        if err is not None:
            logger.warning("[Refiner] Zod validator unavailable (toolchain) — accepting on structural+content checks")

        logger.info("[Refiner] refined schema accepted on attempt %d/%d", attempt, max_attempts)
        return refined

    logger.warning("[Refiner] all %d attempt(s) failed validation/content — falling back to deterministic", max_attempts)
    return None
