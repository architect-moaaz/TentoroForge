"""Pick a photo URL for a given (entity, domain) pair."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import random
from functools import lru_cache

from services.unsplash_client import UnsplashClient

_SEEDS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "unsplash_seeds.json"
_client = UnsplashClient()


def _client_photo_url(query: str, size: str = "1600x900") -> str:
    """Wrapped for testability — patched in tests."""
    return _client.photo_url_for_query(query, size)


@lru_cache(maxsize=1)
def _load_seeds() -> dict:
    return json.loads(_SEEDS_PATH.read_text(encoding="utf-8"))


def _query_for(entity_name: str, domain: str, project_seed: str | None = None) -> str:
    seeds = _load_seeds()
    entities = seeds.get("entities", {})
    domains = seeds.get("domains", {})

    # Use a deterministic RNG seeded by (entity, domain, project_seed) so
    # repeated calls for the same triple always resolve to the same query
    # string. Including project_seed rotates the choice among the existing
    # query list so two projects sharing an entity/domain get different photos.
    # We seed from a stable string hash, not Python's built-in hash() — the
    # latter is randomised per-process via PYTHONHASHSEED so it isn't actually
    # deterministic across runs.
    seed_suffix = f"|{project_seed}" if project_seed else ""
    digest = hashlib.sha1(f"{entity_name}|{domain}{seed_suffix}".encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))

    if entity_name in entities:
        return rng.choice(entities[entity_name])
    if domain in domains:
        return rng.choice(domains[domain])
    return rng.choice(domains.get("default", ["abstract gradient"]))


def pick_photo_for(
    entity_name: str, domain: str, size: str = "1600x900",
    project_seed: str | None = None,
) -> str:
    query = _query_for(entity_name, domain, project_seed=project_seed)
    return _client_photo_url(query, size)
