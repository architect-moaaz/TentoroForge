"""Feature Slice Schema Agent — generates JSON Page schemas for a slice entity.

Produces one schema file per page type per entity:
  - src/schemas/<entity_slug>/<page_type>.json

Default page types (when entity.pages is absent): list, detail, form.
Custom page types: set entity.pages = ["dashboard", "settings", ...].

The schemas validate against @tentoroforge/schema Page Zod schema.

Follows the same conventions as other agents in this codebase:
  - Async generator (async def … -> AsyncIterator[Message])
  - Signature: run_*(output_dir, plan, domain_context=None)
  - Uses claude_agent_sdk.query(prompt, options)
  - Pops CLAUDECODE env var to prevent sub-agent recursion
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message

from services.schema_prompt import build_schema_prompt, load_default_tokens
from services.schema_validator import (
    validate_token_refs,
    invalid_ref_pct,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)

# Repo root — two levels up from backend/agents/
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Default page types generated when entity.pages is absent
DEFAULT_PAGES = ["list", "detail", "form"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_feature_slice_schema_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
) -> None:
    """Generate list/detail/form JSON schemas for a single entity.

    Writes three files to <output_dir>/src/schemas/<entity_slug>/.
    Does NOT yield SSE messages (call site handles that) — the agent runs
    synchronously from the caller's perspective because schema generation is
    fast (one LLM call per page type).

    Args:
        output_dir: Absolute path to the app output directory.
        plan: Dict with keys:
              - 'entity': {name: str, fields: list[dict]}
              - 'feature_description': str  (optional but recommended)
              - 'workflows': list[str]       (optional)
        domain_context: Optional domain-specific context injected into prompts.
    """
    os.environ.pop("CLAUDECODE", None)

    entity = plan.get("entity", {})
    entity_name = entity.get("name", "Unknown")
    entity_slug = _to_slug(entity_name)

    # Phase 4: support arbitrary page types per entity (defaults to list/detail/form).
    # The LLM-path planner stores `pages` as a list of TSX file paths
    # (e.g. ["src/app/(dashboard)/users/page.tsx", ...]) — those are not page
    # types we can use here. Only honour `pages` if every entry is a short
    # identifier; otherwise fall back to the defaults.
    raw_pages = entity.get("pages")
    if (
        isinstance(raw_pages, list)
        and raw_pages
        and all(isinstance(p, str) and "/" not in p and "." not in p for p in raw_pages)
    ):
        pages = raw_pages
    else:
        pages = DEFAULT_PAGES

    output_path = Path(output_dir) / "src" / "schemas" / entity_slug
    output_path.mkdir(parents=True, exist_ok=True)

    for page_type in pages:
        page_plan = {**plan, "page_type": page_type}
        schema_json = await _generate_page_schema(page_plan, entity_slug, domain_context)
        out_file = output_path / f"{page_type}.json"
        out_file.write_text(json.dumps(schema_json, indent=2))

    # Update/create the registry.ts in src/schemas/
    _update_schema_registry(output_dir, entity_slug, pages)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _generate_page_schema(
    plan: dict,
    entity_slug: str,
    domain_context: dict | None,
    max_retries: int = 2,
) -> dict:
    """Call the LLM to produce one validated Page schema dict.

    Retries up to max_retries times on validation failure, appending the
    error message to the prompt each time.
    """
    page_type = plan.get("page_type", "list")

    # Extract per-page brief + domain so build_schema_prompt can load
    # archetype-keyed enterprise patterns + reference exemplars.
    page_brief = {
        "route": plan.get("route") or f"/{entity_slug}/{page_type}",
        "role": plan.get("page_role") or plan.get("role") or "",
        "archetype": plan.get("archetype") or plan.get("page_archetype") or page_type,
    }
    # Domain comes from domain_context, plan, or registry — fallback to "general"
    domain = (
        plan.get("domain")
        or (domain_context or {}).get("domain")
        or "general"
    )

    prompt = build_schema_prompt(plan, page_brief=page_brief, domain=domain)
    if domain_context:
        prompt = f"Domain context: {json.dumps(domain_context)}\n\n{prompt}"

    last_error: str | None = None
    for attempt in range(max_retries + 1):
        retry_suffix = (
            f"\n\nPrevious attempt failed validation:\n{last_error}\nFix the issue and output the corrected JSON."
            if last_error
            else ""
        )
        full_prompt = prompt + retry_suffix

        raw_text = await _collect_llm_text(full_prompt)
        schema_dict = _extract_json(raw_text)
        if schema_dict is None:
            last_error = f"Could not parse JSON from LLM response: {raw_text[:200]}"
            continue

        # Ensure mandatory fields are set correctly
        schema_dict.setdefault("schemaVersion", "1")
        schema_dict.setdefault("id", f"{entity_slug}/{page_type}")

        # Normalise LLM-emitted v1-style prop shapes (Button.content,
        # Link.href, validators.minLength, Tabs.defaultValue, etc.) to v2
        # contracts BEFORE Zod validation so the schemas on disk are clean.
        # See services/schema_normalizer.py for the full transform list.
        from services.schema_normalizer import normalize_v2_schema
        schema_dict = normalize_v2_schema(schema_dict)

        error = _validate_schema_json(schema_dict)
        if error is not None:
            last_error = error
            continue

        # Token-path validation (Task 28-29)
        output_dir = plan.get("_output_dir")
        valid, invalid = _validate_token_paths(schema_dict, output_dir)
        pct = invalid_ref_pct(valid, len(invalid))
        logger.info(
            "[Schema] entity=%s page=%s: %d valid token refs, %d invalid (%.1f%% invalid)",
            entity_slug, page_type, valid, len(invalid), pct,
        )
        if pct > 50.0:
            # Systematic failure — fail fast rather than retry-looping
            msg = (
                f"Design context not reaching LLM: {pct:.1f}% of token refs "
                f"are invalid ({len(invalid)} of {valid + len(invalid)}). "
                f"First few invalid refs: {invalid[:5]}"
            )
            logger.error("[Schema] %s", msg)
            raise SchemaValidationError(msg)
        elif invalid:
            logger.warning(
                "[Schema] %d invalid token refs in %s/%s (will retry): %s",
                len(invalid), entity_slug, page_type, invalid[:5],
            )
            last_error = (
                f"Token-path validation: {len(invalid)} refs not found in design tokens: "
                f"{invalid[:5]}. Use only paths from the Available design tokens list."
            )
            continue

        return schema_dict

    # Return last parsed attempt even if validation failed (fallback)
    if schema_dict is not None:
        return schema_dict
    # Last resort: return a minimal valid schema
    return _minimal_schema(entity_slug, page_type)


async def _collect_llm_text(
    prompt: str,
    mcp_servers: dict | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 1,
) -> str:
    """Run claude_agent_sdk.query and collect all text content blocks.

    Optional kwargs let callers (e.g. page_schema_agent) register in-process
    MCP servers and whitelist the tools the LLM may invoke. When MCP tools
    are exposed, max_turns must be > 1 so the LLM can call a tool and then
    finish its JSON output in a subsequent turn.
    """
    options = ClaudeAgentOptions(
        system_prompt="You generate JSON schemas. Output ONLY a single JSON object.",
        allowed_tools=allowed_tools or [],
        mcp_servers=mcp_servers or {},
        permission_mode="default",
        max_turns=max_turns,
        model="claude-sonnet-4-6",
    )
    parts: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
    return "".join(parts)


def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object from text (strips markdown fences)."""
    # Strip ```json ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Find first { … }
    start = text.find("{")
    if start == -1:
        return None
    # Walk to find the matching closing brace
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _merge_dicts(base: dict, overlay: dict) -> dict:
    """Deep merge two dicts; overlay wins on leaf collisions."""
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge_dicts(out[k], v)
        else:
            out[k] = v
    return out


def _validate_token_paths(schema_dict: dict, output_dir: str | None) -> tuple[int, list[tuple[str, str]]]:
    """Run token-path validation. Returns (valid_count, invalid_refs).

    Loads the union of defaultTokens + tokens.custom.json (if present at
    output_dir/src/theme/tokens.custom.json).
    """
    tokens = load_default_tokens()
    if output_dir:
        custom_path = Path(output_dir) / "src" / "theme" / "tokens.custom.json"
        if custom_path.exists():
            try:
                custom = json.loads(custom_path.read_text())
                tokens = _merge_dicts(tokens, custom)
            except Exception as e:
                logger.warning("validator: failed to load tokens.custom.json: %s", e)
    return validate_token_refs(schema_dict, tokens)


def _validate_schema_json(schema_dict: dict) -> str | None:
    """Validate the schema dict via the Zod Page schema (Node subprocess).

    Returns None if valid, or an error string if invalid.
    """
    schema_str = json.dumps(schema_dict)
    script = (
        "import('./dist/index.js').then(m=>{"
        "try{"
        f"m.Page.parse({schema_str});"
        "console.log('OK');"
        "}catch(e){"
        "console.error('FAIL:'+e.message);"
        "process.exit(1);"
        "}"
        "})"
    )
    try:
        result = subprocess.run(
            ["pnpm", "--filter", "@tentoroforge/schema", "exec", "node", "-e", script],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=20,
        )
        if result.returncode == 0:
            return None
        return result.stderr or result.stdout or "Unknown validation error"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # If pnpm/Node isn't available (CI, test env), skip Zod validation
        return None


def _update_schema_registry(
    output_dir: str,
    entity_slug: str,
    pages: list[str] | None = None,
) -> None:
    """Regenerate src/schemas/registry.ts from a scan of the schemas dir.

    The foundation template ships a registry.ts that exports `schemas` (a map of
    name → dynamic JSON loader) plus a `getSchema` helper that validates via
    `loadSchema`. This regenerator preserves that exact shape so schema-page.tsx
    keeps working — it just rewrites the `schemas` map to reflect every
    <entity>/<page>.json file currently on disk.
    """
    schemas_root = Path(output_dir) / "src" / "schemas"
    registry_path = schemas_root / "registry.ts"

    # Scan for every <entity>/<page>.json — that's the source of truth.
    entries: list[str] = []
    for entity_dir in sorted(p for p in schemas_root.iterdir() if p.is_dir()):
        for json_file in sorted(entity_dir.glob("*.json")):
            page_name = json_file.stem
            key = f"{entity_dir.name}/{page_name}"
            entries.append(
                f'  "{key}": () => import("./{entity_dir.name}/{page_name}.json"),'
            )

    body = "\n".join(entries) if entries else ""
    registry_path.write_text(
        '// Auto-generated by feature_slice_schema_agent — do not edit by hand.\n'
        '// Regenerated whenever any entity emits new schemas; mirrors the on-disk\n'
        '// src/schemas/<entity>/<page>.json layout.\n\n'
        'import { loadSchema } from "./load";\n\n'
        'export const schemas: Record<string, () => Promise<unknown>> = {\n'
        f'{body}\n'
        '};\n\n'
        'export async function getSchema(name: keyof typeof schemas): Promise<ReturnType<typeof loadSchema>> {\n'
        '  const loader = schemas[name as string];\n'
        '  if (!loader) throw new Error(`unknown schema \'${String(name)}\'`);\n'
        '  const raw = await loader();\n'
        '  return loadSchema(name as string, (raw as any).default ?? raw);\n'
        '}\n'
    )


def _to_slug(entity_name: str) -> str:
    """Convert entity name to lowercase plural slug: 'Product' -> 'products'."""
    name = entity_name.lower().strip()
    # Simple pluralisation: add 's' if not already plural
    if not name.endswith("s"):
        name += "s"
    return name


def _minimal_schema(entity_slug: str, page_type: str) -> dict:
    """Return the bare minimum valid Page schema as a fallback."""
    return {
        "schemaVersion": "1",
        "id": f"{entity_slug}/{page_type}",
        "route": f"/{entity_slug}",
        "layout": "DashboardLayout",
        "meta": {"title": entity_slug.capitalize()},
        "dataSources": [],
        "root": {
            "id": "page-root",
            "type": "Stack",
            "props": {"direction": "vertical", "gap": "spacing.6"},
            "children": [],
        },
    }
