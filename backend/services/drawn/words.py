"""The words a drawn design shows, and which of them a language lacks.

A screen converted from a drawing says its words as drawn; `product.words`
holds them in each of the application's other languages, and the frame's
`DrawnWords` shows them (`@/sdk/i18n`). This module reads what there is to
translate: every text the drawn screens, shells and parts show (`words.mjs`,
through the TypeScript parser, so nothing a comparison or a class name takes is
counted), the drawn menus' labels, and the values of the record types' choice
fields, which pages show as they are stored.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).with_name("words.mjs")


def squeeze(text: Any) -> str:
    """A text as the table keys it, and as `DrawnWords` looks it up."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _code_words(codes: list[str]) -> set[str]:
    items = [{"id": str(i), "code": c} for i, c in enumerate(codes) if c]
    if not items:
        return set()
    out = subprocess.run(["node", str(_SCRIPT)], input=json.dumps(items), capture_output=True, text=True,
                         check=True, cwd=str(_SCRIPT.parent))
    return {w for ws in json.loads(out.stdout or "{}").values() for w in ws}


def shown_words(doc: dict) -> list[str]:
    """Every text the drawn design shows, each once, sorted."""
    from services.drawn.project import _shells, nav_routes

    codes = [str(v.get("code") or "") for v in doc.get("drawnViews") or [] if isinstance(v, dict)]
    for row in doc.get("pageCode") or []:
        if isinstance(row, dict) and not row.get("deleted"):
            codes += [str(c or "") for c in (row.get("parts") or {}).values()]
    words = _code_words(codes)
    for shell in _shells(doc):
        words |= {squeeze(n.get("label")) for n in nav_routes(doc, shell)}
    data = doc.get("data") or {}
    for entity in (data.get("entities") if isinstance(data, dict) else data) or []:
        for field in entity.get("fields") or []:
            words |= {squeeze(v) for v in field.get("enumValues") or [] if isinstance(v, str)}
    return sorted(w for w in words if re.search(r"[^\W\d_]", w))


def untranslated(doc: dict, tag: str) -> list[str]:
    """The drawn words `product.words[tag]` does not hold yet."""
    have = ((doc.get("product") or {}).get("words") or {}).get(tag) or {}
    return [w for w in shown_words(doc) if w not in have]


__all__ = ["squeeze", "shown_words", "untranslated"]
