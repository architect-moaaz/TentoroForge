"""Typography register catalogue + domain-based selector."""
from __future__ import annotations
from pathlib import Path
import json
from functools import lru_cache

_DATA_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "typography_registers.json"


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    return json.loads(_DATA_PATH.read_text())["registers"]


def list_registers() -> list[dict]:
    return list(_load())


def get_register(register_id: str) -> dict | None:
    return next((r for r in _load() if r["id"] == register_id), None)


def pick_register_for_domain(domain: str) -> dict:
    """Pick the most-fitting register for a domain. Falls back to
    modern-minimal when no register's best_for list contains the domain."""
    domain = domain.lower().strip()
    for reg in _load():
        if domain in [b.lower() for b in reg.get("best_for", [])]:
            return reg
    return next(r for r in _load() if r["id"] == "modern-minimal")
