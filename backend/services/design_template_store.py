"""Persist the design templates offered to the user + their selection.

Both the chat phase (offers templates, records the pick) and the generation
pipeline (seeds the picked look into the design_spec) share the project's
`output_dir/contracts/` dir, so selection survives the gap between "user picks"
and "pipeline builds".
"""
from __future__ import annotations

import json
import os

_OFFERED = "design-templates.json"
_SELECTED = "selected-design-template.json"


def _contracts(output_dir: str) -> str:
    d = os.path.join(str(output_dir), "contracts")
    os.makedirs(d, exist_ok=True)
    return d


def save_offered(output_dir: str, templates: list[dict]) -> None:
    with open(os.path.join(_contracts(output_dir), _OFFERED), "w", encoding="utf-8") as fh:
        json.dump({"templates": templates}, fh, indent=2)


def load_offered(output_dir: str) -> list[dict]:
    try:
        with open(os.path.join(str(output_dir), "contracts", _OFFERED), encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("templates") or []
    except Exception:
        return []


def save_selection(output_dir: str, template: dict) -> None:
    with open(os.path.join(_contracts(output_dir), _SELECTED), "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2)


def load_selection(output_dir: str) -> dict | None:
    try:
        with open(os.path.join(str(output_dir), "contracts", _SELECTED), encoding="utf-8") as fh:
            t = json.load(fh)
            return t if isinstance(t, dict) and t.get("id") else None
    except Exception:
        return None


def select_by_id(output_dir: str, template_id: str) -> dict | None:
    """Record the user's pick from the offered set. Returns the selected template
    (guarded) or None if the id isn't among the offers."""
    from services.design_templates import guard_template
    tid = str(template_id or "").strip()
    for t in load_offered(output_dir):
        if isinstance(t, dict) and str(t.get("id")) == tid:
            clean, _ = guard_template(t)
            save_selection(output_dir, clean)
            return clean
    return None
