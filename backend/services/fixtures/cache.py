"""On-disk cache for LLM-generated fixture records.

Fixtures are cached per project at
`output/<short_id>/.fixtures-cache/<entity-name>.json`. The cache directory is
prefixed with a dot so it stays out of the way of the normal generated app
output and is easy to filter from project listings.

Cache contract:
  - Hit: returns a list[dict] (no schema validation — caller treats it as
    an opaque record set, same shape the LLM/Faker layers produce).
  - Miss: returns None.
  - Write: best-effort, swallows IO errors so a transient disk problem
    never breaks the preview-data endpoint. The next request will retry.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache directory name relative to the project root. Dot-prefixed so it
# doesn't get picked up by Drizzle/Next/registry scanners that walk
# `output/<short_id>/src/`.
_CACHE_DIR_NAME = ".fixtures-cache"


def _cache_path(project_root: Path, entity_name: str) -> Path:
    """Resolve the cache file path for an entity. Sanitises the entity name
    so unusual values can't escape the cache directory."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", entity_name)
    return project_root / _CACHE_DIR_NAME / f"{safe_name}.json"


def read_cache(project_root: Path, entity_name: str) -> list[dict[str, Any]] | None:
    """Return cached records for the entity, or None if no cache exists or the
    cache file is malformed."""
    path = _cache_path(project_root, entity_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("fixtures.cache: malformed cache at %s — ignoring: %s", path, e)
        return None
    if not isinstance(data, list):
        logger.warning("fixtures.cache: non-list cache at %s — ignoring", path)
        return None
    return [item for item in data if isinstance(item, dict)]


def write_cache(
    project_root: Path,
    entity_name: str,
    records: list[dict[str, Any]],
) -> None:
    """Write records to the per-project cache. Best-effort — IO failures are
    logged but never raised, since the cache is a performance optimisation,
    not a correctness boundary."""
    path = _cache_path(project_root, entity_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("fixtures.cache: failed to write %s: %s", path, e)
