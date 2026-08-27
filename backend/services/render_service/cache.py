"""File-system cache for rendered PNGs, keyed by SHA-256 of the render request."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RenderCache:
    def __init__(self, root: Path | str):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(payload: dict[str, Any]) -> str:
        """Deterministic SHA-256 of a JSON-stable payload."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> bytes | None:
        path = self._root / f"{key}.png"
        if not path.exists():
            return None
        return path.read_bytes()

    def set(self, key: str, value: bytes) -> None:
        path = self._root / f"{key}.png"
        path.write_bytes(value)

    def invalidate(self, key: str) -> None:
        path = self._root / f"{key}.png"
        if path.exists():
            path.unlink()

    def clear(self) -> None:
        for p in self._root.glob("*.png"):
            p.unlink()
