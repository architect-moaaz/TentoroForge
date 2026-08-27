"""Pre-fetch 21st.dev component references for the design agent.

Runs BEFORE the design agent, calling 21st.dev's Magic MCP for 2–3
domain-shaped component patterns and materializing the converted schema
fragments to ``<output_dir>/src/contracts/references/<slug>.json``.

The design agent's prompt then points at that directory. Because the
LLM inside the CLI subprocess would need to spend tool-call turns to
fetch inspiration via the stdio MCP (Slice 1 wiring), materializing
references up-front:
  - guarantees usage regardless of what the agent decides
  - keeps the tool-call budget available for other things
  - lets us log & inspect what 21st sent before generation runs

Gated behind the same ``FORGE_21ST_MCP`` + ``FORGE_21ST_API_KEY``
double-gate. Failures are non-fatal — an empty list means the design
agent proceeds with its existing signals.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

from services import magic_jsx_to_schema, magic_mcp, magic_mcp_client

logger = logging.getLogger(__name__)


# Cap on how many references we materialize per generation. Two is the
# floor that gives the design agent variety; three is a mild upgrade.
# Beyond that the cost/quality curve flattens.
_DEFAULT_MAX_REFERENCES = 3

# Domain-specific query patterns. Each entry is ``(slug, query_template)``.
# Missing-domain fallback is a small, sturdy set that fits any app.
_DOMAIN_QUERIES: dict[str, list[tuple[str, str]]] = {
    "wellness": [
        ("dashboard_header", "wellness studio dashboard header with class overview"),
        ("metric_row", "wellness studio metric tiles row (bookings, members, revenue)"),
        ("session_list", "wellness class schedule list with time and instructor"),
    ],
    "healthcare": [
        ("dashboard_header", "healthcare provider dashboard header with patient overview"),
        ("metric_row", "healthcare metric tiles row (patients, appointments, revenue)"),
        ("record_list", "patient list with status badges and clinician assigned"),
    ],
    "commerce": [
        ("dashboard_header", "ecommerce store dashboard header with revenue snapshot"),
        ("metric_row", "ecommerce metric tiles (revenue, orders, conversion, AOV)"),
        ("product_card", "ecommerce product card with image, price, and add-to-cart"),
    ],
    "ecommerce": [
        ("dashboard_header", "ecommerce store dashboard header with revenue snapshot"),
        ("metric_row", "ecommerce metric tiles (revenue, orders, conversion, AOV)"),
        ("product_card", "ecommerce product card with image, price, and add-to-cart"),
    ],
    "saas": [
        ("dashboard_header", "SaaS admin dashboard header with usage summary"),
        ("metric_row", "SaaS metric tiles (MAU, MRR, churn, retention)"),
        ("data_table", "SaaS admin data table with filters and row actions"),
    ],
    "finance": [
        ("dashboard_header", "finance dashboard header with account overview"),
        ("metric_row", "finance metric tiles (balance, spend, income, savings)"),
        ("transaction_list", "finance transaction list with categorized rows"),
    ],
    "recruitment": [
        ("dashboard_header", "recruitment ATS dashboard header with pipeline overview"),
        ("kanban_column", "recruitment candidate kanban column (screening, interview, offer)"),
        ("candidate_card", "recruitment candidate card with name, role, and match score"),
    ],
    "education": [
        ("dashboard_header", "education platform dashboard header with course progress"),
        ("course_card", "online course card with instructor, duration, and enrollment"),
        ("progress_row", "student progress row with modules completed indicator"),
    ],
}

_DEFAULT_QUERIES: list[tuple[str, str]] = [
    ("dashboard_header", "modern admin dashboard header with page title and primary action"),
    ("metric_row", "row of four metric tiles with label, value, and trend indicator"),
    ("data_table", "clean data table with column headers, row hover, and action column"),
]


def _slugify_domain(domain: str | None) -> str:
    """Normalize a domain string for the query lookup. Empty → ''."""
    if not domain:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(domain).lower())


def _queries_for_domain(domain: str | None) -> list[tuple[str, str]]:
    """Pick the query set for ``domain``. Substring match against known
    buckets, then falls back to the generic default set."""
    slug = _slugify_domain(domain)
    if not slug:
        return list(_DEFAULT_QUERIES)
    if slug in _DOMAIN_QUERIES:
        return list(_DOMAIN_QUERIES[slug])
    for key, queries in _DOMAIN_QUERIES.items():
        if key in slug:
            return list(queries)
    return list(_DEFAULT_QUERIES)


def _hint_from_brief(brief: dict | None) -> str:
    """Extract a compact style hint from the design brief (if any).

    Returns a short comma-separated string like "warm terracotta palette,
    editorial serif headings" for steering the converter. Empty when brief
    is missing or has no relevant fields.
    """
    if not isinstance(brief, dict):
        return ""
    parts: list[str] = []
    palette = brief.get("palette")
    if isinstance(palette, dict):
        brand = palette.get("brand")
        neutrals = palette.get("neutrals_tint_free")
        if isinstance(brand, str) and brand:
            parts.append(f"brand color {brand}")
        if isinstance(neutrals, str) and neutrals:
            parts.append(f"neutral tone: {neutrals}")
    identity = brief.get("identity")
    if isinstance(identity, dict):
        voice = identity.get("voice_free")
        if isinstance(voice, str) and voice:
            parts.append(f"voice: {voice}")
    return ", ".join(parts)


async def prefetch_references(
    output_dir: str,
    *,
    domain: str | None = None,
    brief: dict | None = None,
    max_refs: int = _DEFAULT_MAX_REFERENCES,
) -> list[Path]:
    """Fetch, convert, and materialize domain-shaped reference fragments.

    Returns a list of written file paths (may be empty on failure or when
    the double-gate is off). Never raises. Files are written to
    ``<output_dir>/src/contracts/references/<slug>.json`` with shape::

        {
          "slug": "dashboard_header",
          "query": "wellness studio dashboard header ...",
          "fragment": {"type": "...", "props": {...}, "children": [...]},
          "source": "21st.dev"
        }

    An accompanying ``index.json`` lists every successful entry so the
    design agent can enumerate references in one Read.
    """
    if not magic_mcp.is_enabled():
        return []

    out_dir = Path(output_dir) / "src" / "contracts" / "references"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("[magic-prefetch] cannot create references dir: %s", exc)
        return []

    queries = _queries_for_domain(domain)[:max_refs]
    hint = _hint_from_brief(brief)
    written: list[Path] = []
    index_rows: list[dict] = []

    # Fetch + convert one at a time to keep MCP+LLM cost linear and errors
    # scoped. Sequential also lets us short-circuit if the first call is
    # empty (signals credential / connectivity problem — no point retrying
    # against the same failure two more times).
    for slug, query in queries:
        try:
            jsx = await magic_mcp_client.generate_component(query, hint=hint or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[magic-prefetch] %s generate failed: %s", slug, exc)
            jsx = ""
        if not jsx:
            if not written:
                # First fetch empty → likely misconfig or vendor outage.
                # Abort the rest to avoid burning tokens on nothing.
                logger.warning("[magic-prefetch] first fetch empty; aborting prefetch")
                return []
            continue
        try:
            fragment = await magic_jsx_to_schema.convert_jsx_to_schema(jsx, hint=query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[magic-prefetch] %s convert failed: %s", slug, exc)
            fragment = None
        if fragment is None:
            continue
        entry = {
            "slug": slug,
            "query": query,
            "source": "21st.dev",
            "fragment": fragment,
        }
        path = out_dir / f"{slug}.json"
        try:
            path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("[magic-prefetch] write %s failed: %s", path, exc)
            continue
        written.append(path)
        index_rows.append({"slug": slug, "query": query, "path": str(path.relative_to(Path(output_dir)))})

    if written:
        try:
            (out_dir / "index.json").write_text(
                json.dumps({"references": index_rows}, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("[magic-prefetch] write index.json failed: %s", exc)

    return written


def prompt_hint(reference_paths: list[Path], output_dir: str) -> str:
    """Compose a prompt block naming the pre-fetched reference files.

    Empty string when nothing was pre-fetched. The block instructs the
    design agent to read the references as STRUCTURAL inspiration — the
    fragments show component composition, hierarchy, and token usage
    that we can't derive from the brief alone.
    """
    if not reference_paths:
        return ""
    root = Path(output_dir)
    listing = []
    for p in reference_paths:
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = p
        listing.append(f"  - {rel}")
    return (
        "## 21st.dev reference fragments (pre-fetched)\n"
        "The following schema fragments were fetched from 21st.dev's curated "
        "catalog and pre-converted to our schema format. Read them BEFORE "
        "authoring the design spec — they encode structural composition + "
        "token usage patterns for this domain that will inform your palette, "
        "spacing, and layout choices:\n"
        + "\n".join(listing)
        + "\n\nRules for using them:\n"
        "  - EXTRACT decisions (component hierarchy, spacing rhythm, structural "
        "moves) into your design-spec.json. Don't just copy — synthesize.\n"
        "  - The fragments are references, not requirements. If a fragment's "
        "choices conflict with the brief's palette/typography, the brief wins.\n"
    )
