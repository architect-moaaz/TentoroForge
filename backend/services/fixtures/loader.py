"""Layer 1 fixture loader — reads hand-curated domain bank JSON files from
backend/fixtures/<domain>/<EntityName>.json. Falls through (returns None) when
a bank doesn't exist; callers fall back to Layer 2 (Faker) or Layer 3
(type-correct nonsense)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Bank root is backend/fixtures/, alongside this services/ tree
_BANK_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def load_domain_bank(domain: str, entity_name: str) -> list[dict[str, Any]] | None:
    """Load all records for `entity_name` in `domain`, or None if absent."""
    if not domain or not entity_name:
        return None
    path = _BANK_ROOT / domain / f"{entity_name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, list):
        return None
    return data


def available_domains() -> list[str]:
    """List domain directories present in the fixtures bank."""
    if not _BANK_ROOT.exists():
        return []
    return sorted(p.name for p in _BANK_ROOT.iterdir() if p.is_dir() and not p.name.startswith("."))
