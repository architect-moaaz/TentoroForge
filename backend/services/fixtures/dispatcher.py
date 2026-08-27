"""Top-level fixtures dispatcher — picks the best layer for each request.

Resolution order, best-quality first:
  Layer 1     — hand-curated domain bank in `backend/fixtures/<domain>/<entity>.json`.
                Highest quality but only seeded for a few (domain, entity) pairs.
  Layer 2-cache — per-project LLM-generated records cached to
                `output/<short_id>/.fixtures-cache/<entity>.json`. Fast read, no
                LLM cost on subsequent requests.
  Layer 2-llm — fresh LLM call (Sonnet) when no cache hit and a `project_root`
                was passed. Result is written to the cache so this only fires
                once per (project, entity).
  Layer 3     — Faker-generated records from `fields`. Realistic for ~20 known
                field names (name/email/phone/department/...), Lorem-ipsum-style
                fallback for unrecognised string fields.
  Layer 4     — empty dicts (last resort, when no fields are known).

Layers 2-cache and 2-llm only engage when the caller passes `project_root`.
That keeps the function backwards-compatible with call sites that don't have
project context (tests, generators run before output dirs exist).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .faker_gen import generate_records
from .loader import load_domain_bank
from .types import FieldHint


def provide_records(
    domain: str,
    entity_name: str,
    fields: list[FieldHint],
    count: int = 10,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Sync entry point — covers Layer 1 (bank), Layer 2-cache (cached LLM),
    Layer 3 (Faker), Layer 4 (empty). The LLM-generation Layer 2-llm is NOT
    invoked here, because the Claude Agent SDK requires an async context that
    shares the caller's event loop (its subprocess pipes can't be bridged
    through `asyncio.run` in a worker thread without deadlocking on
    stdin/stdout).

    Async callers that want the full ordering should use
    `provide_records_async` — it awaits the LLM helper directly on the
    caller's event loop, and writes the result through the cache so future
    sync calls hit Layer 2-cache.
    """
    bank = load_domain_bank(domain, entity_name)
    if bank is not None:
        return bank[:count]

    if project_root is not None:
        from .cache import read_cache
        cached = read_cache(project_root, entity_name)
        if cached is not None and len(cached) >= count:
            return cached[:count]

    if fields:
        return generate_records(entity_name, fields, count=count, domain=domain)

    return [dict() for _ in range(count)]


async def provide_records_async(
    domain: str,
    entity_name: str,
    fields: list[FieldHint],
    count: int = 10,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Async entry point — full layer ordering, including Layer 2-llm.

    Identical contract to `provide_records` except the LLM-generation layer
    actually runs on cache miss. Callers who can `await` (FastAPI route
    handlers, scripts, etc.) should prefer this entry point so first-time
    fixture generation gets Sonnet-quality content. Subsequent calls (sync
    or async) hit Layer 2-cache and return in <1ms.
    """
    bank = load_domain_bank(domain, entity_name)
    if bank is not None:
        return bank[:count]

    if project_root is not None:
        from .cache import read_cache
        cached = read_cache(project_root, entity_name)
        if cached is not None and len(cached) >= count:
            return cached[:count]

    if project_root is not None and fields:
        from .cache import write_cache
        from .llm_gen import generate_records_llm
        try:
            llm_records = await generate_records_llm(
                entity_name, fields, domain, count=count
            )
        except Exception:  # noqa: BLE001 — LLM never breaks the caller
            llm_records = None
        if llm_records is not None:
            write_cache(project_root, entity_name, llm_records)
            return llm_records[:count]

    if fields:
        return generate_records(entity_name, fields, count=count, domain=domain)

    return [dict() for _ in range(count)]
