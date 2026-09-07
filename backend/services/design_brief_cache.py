"""Design-brief cache with in-process store + optional disk persistence.

Spec A Slice 7 removed the per-domain hand-authored anchor pre-prime;
Slice 7b adds disk persistence so LLM-authored briefs survive process
restarts. Cache starts EMPTY per-process (no baked-in domain
intelligence); disk-backed entries are lazy-loaded on first ``get``.

Layout on disk (default: ``backend/cache/design_briefs/{slug}.json``):
one JSON file per domain, slug-sanitized. Directory is created on
first write. Read failures are silent (cache miss); write failures
are logged but never raise (caching is best-effort infrastructure,
must not fail a generation).

Env override: ``FORGE_BRIEF_CACHE_DIR`` picks a different root.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from threading import Lock

from schemas.design_brief import DesignBrief


logger = logging.getLogger(__name__)


_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "design_briefs"


def _cache_dir() -> Path:
    """Root directory for on-disk cache entries."""
    override = os.getenv("FORGE_BRIEF_CACHE_DIR")
    return Path(override) if override else _DEFAULT_CACHE_DIR


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(domain: str) -> str:
    """Filesystem-safe slug for a domain label. ``Property Management``
    → ``property-management``."""
    s = _SLUG_RE.sub("-", (domain or "").strip().lower()).strip("-")
    return s or "unknown"


def _path_for(domain: str) -> Path:
    return _cache_dir() / f"{_slug(domain)}.json"


_store: dict[str, DesignBrief] = {}
_lock = Lock()


def get(domain: str) -> DesignBrief | None:
    """Return the cached brief for a domain, or None if not cached.

    Checks the in-process store first, then falls back to disk. Disk-hit
    populates the in-process store so subsequent calls skip I/O.
    """
    b = _store.get(domain)
    if b is not None:
        return b
    # Disk lookup — silent failure = cache miss.
    path = _path_for(domain)
    if not path.exists():
        return None
    try:
        b = DesignBrief.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[brief-cache] disk read failed for %s: %s", domain, exc)
        return None
    with _lock:
        _store[domain] = b
    return b


def has(domain: str) -> bool:
    """Cheap check for cache presence (checks both memory + disk)."""
    return domain in _store or _path_for(domain).exists()


def put(domain: str, brief: DesignBrief) -> None:
    """Cache an authored brief in memory + write to disk.

    Disk write failures are logged and swallowed — the in-process
    cache still holds the brief for the current process, so behavior
    only degrades to legacy (re-author on restart).
    """
    with _lock:
        _store[domain] = brief
    path = _path_for(domain)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("[brief-cache] disk write failed for %s: %s", domain, exc)


def clear(domain: str | None = None) -> None:
    """Drop a single entry (in-memory + disk) or, when ``domain`` is
    None, empty the entire cache (in-memory + disk)."""
    with _lock:
        if domain is None:
            _store.clear()
            try:
                for p in _cache_dir().glob("*.json"):
                    p.unlink()
            except OSError:
                pass
        else:
            _store.pop(domain, None)
            try:
                _path_for(domain).unlink(missing_ok=True)
            except OSError:
                pass


def all_domains() -> list[str]:
    """Return sorted list of every cached domain (memory + disk)."""
    domains = set(_store.keys())
    try:
        for p in _cache_dir().glob("*.json"):
            # Read the brief to recover the original domain label
            # (slug is lossy — "Property Management" ↔ "property-management").
            try:
                b = DesignBrief.model_validate_json(p.read_text(encoding="utf-8"))
                domains.add(b.identity.domain)
            except Exception:  # noqa: BLE001
                continue
    except OSError:
        pass
    return sorted(domains)


__all__ = ["get", "has", "put", "clear", "all_domains"]
