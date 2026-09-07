"""Per-page LLM continuation for missing page schemas (working-app reliability).

The monolithic page agent emits ALL pages in one call and stalls/overflows on big apps,
leaving nav destinations with no schema -> blank/broken routes. Rather than re-run the
same monolithic agent (which stalls again) or stub pages deterministically (bland), this
fills each MISSING page with a focused, per-page LLM call (`run_page_schema_agent`, which
already retries internally) — small calls don't overflow, and it's naturally resumable
(only generates what's missing). A deterministic minimal schema is the LAST-RESORT floor
so every route still renders even if the LLM can't produce one.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def fill_missing_pages(output_dir: str, plan: dict, domain_context: dict | None = None) -> dict:
    """Generate any missing page schema via a per-page LLM continuation, then floor.

    Returns {"llm": [routes], "minimal": [routes], "failed": [routes]}.
    """
    from services.phase_gates import check_pages_coverage
    from services.route_slug import slugify_route
    from agents.page_schema_agent import run_page_schema_agent, _minimal_schema

    result: dict[str, list[str]] = {"llm": [], "minimal": [], "failed": []}

    cov = check_pages_coverage(output_dir, plan)
    if cov.get("passed"):
        return result

    plan_pages = {p.get("route"): p for p in (plan.get("pages") or []) if isinstance(p, dict)}

    # 1) per-page LLM continuation for each missing page
    for route in cov["missing"]:
        page = plan_pages.get(route)
        if not page:
            continue
        try:
            await run_page_schema_agent(output_dir, plan, page, domain_context=domain_context)
            result["llm"].append(route)
        except Exception:
            logger.exception("[Pages] continuation LLM failed for %s", route)

    # 2) deterministic minimal floor for anything STILL missing
    cov2 = check_pages_coverage(output_dir, plan)
    schemas_dir = Path(output_dir) / "src" / "schemas"
    for route in cov2["missing"]:
        page = plan_pages.get(route) or {}
        try:
            slug = slugify_route(route)
            out = schemas_dir / f"{slug}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            page_type = page.get("type") or page.get("archetype") or "generic"
            sch = _minimal_schema(slug, page_type)
            sch["id"] = slug
            sch.setdefault("schemaVersion", "2")
            out.write_text(json.dumps(sch, indent=2), encoding="utf-8")
            result["minimal"].append(route)
        except Exception:
            logger.exception("[Pages] minimal floor failed for %s", route)
            result["failed"].append(route)

    return result
