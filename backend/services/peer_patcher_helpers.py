"""Helpers for the peer-patcher generation path: load/commit artifacts,
build the registry digest, surface the token vocabulary."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional


def _load_json_safe(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_current_artifacts(output_dir: str) -> Optional[dict]:
    """Reconstruct the {pageSchemas, navFlow, tokens} bundle from disk.

    Returns None when there are no page schemas yet (greenfield).
    """
    base = Path(output_dir)
    schemas_dir = base / "src" / "schemas"
    if not schemas_dir.exists():
        return None

    page_schemas: dict[str, dict] = {}
    for f in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        pid = data.get("id") or f.stem
        page_schemas[pid] = data
    if not page_schemas:
        return None

    nav = _load_json_safe(base / "src" / "contracts" / "nav-flow.json") or {
        "version": "1.0", "initialPage": "", "pages": [],
        "transitions": [], "guards": {},
    }
    tokens = _load_json_safe(base / "src" / "contracts" / "tokens.json") or {
        "color":{}, "typography":{}, "spacing":{}, "radius":{},
        "shadow":{}, "motion":{}, "breakpoints":{},
    }
    return {"pageSchemas": page_schemas, "navFlow": nav, "tokens": tokens}


def commit_artifacts(output_dir: str, artifacts: dict) -> None:
    """Write each page schema + nav-flow + tokens to disk."""
    base = Path(output_dir)
    (base / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    (base / "src" / "contracts").mkdir(parents=True, exist_ok=True)

    # Page schemas — one file per id
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        (base / "src" / "schemas" / f"{pid}.json").write_text(
            json.dumps(page, indent=2) + "\n",
            encoding="utf-8",
        )

    nav = artifacts.get("navFlow") or {}
    (base / "src" / "contracts" / "nav-flow.json").write_text(
        json.dumps(nav, indent=2) + "\n",
        encoding="utf-8",
    )

    tokens = artifacts.get("tokens") or {}
    (base / "src" / "contracts" / "tokens.json").write_text(
        json.dumps(tokens, indent=2) + "\n",
        encoding="utf-8",
    )


# ----- Registry snapshot — read from @forge/registry dist/starter.json -----
# The JSON is emitted by `packages/registry/scripts/export.mjs` as part of
# `npm run build` for the registry package, so it stays in sync automatically.

_REGISTRY_JSON_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages" / "registry" / "dist" / "starter.json"
)

# Compact fallback covering the core layout + input components — used when
# the registry package hasn't been built yet (e.g. fresh clone).
_FALLBACK_REGISTRY: dict = {
    "Container": {"props": {"direction":{}, "gap":{}, "padding":{}, "align":{}, "justify":{}, "wrap":{}}},
    "Stack":     {"props": {"gap":{}, "padding":{}, "align":{}, "justify":{}}},
    "Row":       {"props": {"gap":{}, "padding":{}, "align":{}, "justify":{}, "wrap":{}}},
    "Heading":   {"props": {"content":{}, "level":{}}},
    "Text":      {"props": {"content":{}, "text":{}}},
    "Button":    {"props": {"label":{}, "variant":{}, "size":{}, "disabled":{}, "onClick":{}}},
    "Input":     {"props": {"label":{}, "placeholder":{}, "type":{}, "binding":{}}},
    "Hero":      {"props": {"headline":{}, "subhead":{}, "eyebrow":{}, "layout":{}, "backgroundImage":{}, "ctas":{}}},
}


@lru_cache(maxsize=1)
def _load_registry_from_json() -> dict:
    if _REGISTRY_JSON_PATH.exists():
        return json.loads(_REGISTRY_JSON_PATH.read_text(encoding="utf-8"))
    return _FALLBACK_REGISTRY


def registry_snapshot() -> dict:
    return dict(_load_registry_from_json())


def registry_digest() -> str:
    """Compact text for the LLM system prompt."""
    reg = _load_registry_from_json()
    lines = []
    for name, entry in reg.items():
        props = ", ".join(entry.get("props", {}).keys())
        lines.append(f"{name}  {{ {props} }}")
    return "\n".join(lines)


def token_vocabulary(current: Optional[dict]) -> str:
    """If current artifacts have tokens, surface their keys as the vocab."""
    if not current:
        return ("(use sensible defaults: color.brand.primary, color.neutral.0-900, "
                "spacing.xs-2xl, radius.sm-full, etc.)")
    t = current.get("tokens") or {}
    keys: list[str] = []
    for category in ("color", "typography", "spacing", "radius"):
        sub = t.get(category) or {}
        for k in sub.keys():
            if isinstance(sub[k], dict):
                for kk in sub[k].keys():
                    keys.append(f"{category}.{k}.{kk}")
            else:
                keys.append(f"{category}.{k}")
    return "Tokens available: " + ", ".join(keys[:60])
