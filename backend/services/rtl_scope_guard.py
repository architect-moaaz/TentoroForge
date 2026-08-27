"""Keep `direction: rtl` from mirroring left-to-right copy.

The design agent writes `globals.css`. When an app has an Arabic name it
tends to commit to an "Arabic-first (RTL)" stylesheet and emits

    html { direction: rtl }
    body { direction: rtl }
    textarea, table, label { … direction: rtl }

unconditionally. Meanwhile `layout.tsx` emits ``<html lang="en">`` with no
``dir`` attribute and every generated string is English. The two disagree,
and the browser believes the CSS: an English sentence renders right-to-left,
so "The numbers moved while you were out." displays as ".The numbers moved
while you were out" and every form label is pushed to the wrong edge.

The direction of a document belongs to the ``dir`` attribute, which is what
assistive tech and the bidi algorithm actually key on — not to a blanket CSS
rule. So this guard rewrites the unconditional selectors to
``[dir="rtl"] …``. An app that really is RTL sets ``dir="rtl"`` on the root
and gets exactly the same styling; an app whose copy is English stops being
mirrored. Nothing is deleted — the RTL intent survives, it just becomes
conditional on the fact it was always predicated on.

Deliberately does NOT decide the locale. Which direction an app should be is
a product question (the copy language, the audience), and no artifact in the
pipeline records it today. Making `lang` and `direction` stop contradicting
each other is the part that is unambiguously right.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Selectors that set direction for the WHOLE document. Scoping these is the
# fix; a `.arabic-text { direction: rtl }` helper class is already opt-in and
# is left alone.
_GLOBAL_SELECTORS = {"html", "body", "html, body", "body, html", ":root", "*"}

_RULE = re.compile(
    r"(?P<sel>^[^{}/@]+?)\s*\{(?P<body>[^{}]*?direction\s*:\s*rtl\s*;?[^{}]*?)\}",
    re.MULTILINE | re.DOTALL,
)


def _is_global(selector: str) -> bool:
    return selector.strip().strip(",").lower() in _GLOBAL_SELECTORS


def scope_rtl_rules(css: str) -> tuple[str, int]:
    """Return ``(css, rewritten)`` with document-wide RTL rules scoped.

    Only selectors that style the entire document are touched. Element
    selectors (``textarea``, ``table``) are scoped too — they are just as
    unconditional — but anything already qualified by ``[dir=…]`` or a class
    is left exactly as authored.
    """
    if "direction" not in css:
        return css, 0

    count = 0

    def _rewrite(m: re.Match) -> str:
        nonlocal count
        sel = m.group("sel").strip()
        if "[dir=" in sel or "[dir =" in sel:
            return m.group(0)          # already conditional
        parts = [p.strip() for p in sel.split(",") if p.strip()]
        if not parts:
            return m.group(0)
        # A class/id selector is an opt-in helper (.arabic-text) — leave it.
        if all(p.startswith(".") or p.startswith("#") for p in parts):
            return m.group(0)
        scoped = ", ".join(
            p if p.startswith("[dir") else
            (f'[dir="rtl"]' if _is_global(p) else f'[dir="rtl"] {p}')
            for p in parts
        )
        count += 1
        return f'{scoped} {{{m.group("body")}}}'

    out = _RULE.sub(_rewrite, css)
    return out, count


def apply_rtl_scope_guard(output_dir: str | Path) -> dict[str, Any]:
    """Scope every unconditional RTL rule in the app's globals.css.

    Idempotent: a second run finds every rule already qualified and rewrites
    nothing. Never raises — a stylesheet tweak must not fail a build.
    """
    path = Path(output_dir) / "src" / "app" / "globals.css"
    if not path.is_file():
        return {"scoped": 0, "reason": "no globals.css"}
    try:
        css = path.read_text(encoding="utf-8")
        out, n = scope_rtl_rules(css)
        if n:
            path.write_text(out, encoding="utf-8")
            logger.info("rtl_scope_guard: scoped %d unconditional RTL rule(s) in %s",
                        n, output_dir)
        return {"scoped": n}
    except Exception as exc:  # noqa: BLE001
        logger.warning("rtl_scope_guard failed: %s", exc)
        return {"scoped": 0, "error": str(exc)}
