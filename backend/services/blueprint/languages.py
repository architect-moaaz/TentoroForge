"""The languages an application's interface is shown in.

`product.locale` is the language the interface is written in; `product.languages`
the others a person can switch it to. Test2 (2026-09-28) was asked for English
and Hindi and had nowhere to say so: every page rolled its own EN/हिं toggle,
none agreed with the next, and nothing loaded a font that draws Devanagari,
so the toggle's own label rendered broken.

Declared once, the application has ONE switch, in its frame (`@/sdk/i18n`'s
`LanguageSwitch`), and every page reads it through `useT()`; the design tokens
load a font for each script the languages need. This module is the single
reading of the two fields that the projection, the tokens and the page writer
share.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Scripts the platform's default fonts do not reliably draw, by base language,
#: and the Google Fonts family that does. A language not listed is written in
#: a script the body font already covers (Latin, Cyrillic, Greek).
SCRIPT_FONTS: dict[str, str] = {
    "hi": "Noto Sans Devanagari", "mr": "Noto Sans Devanagari", "ne": "Noto Sans Devanagari",
    "sa": "Noto Sans Devanagari",
    "bn": "Noto Sans Bengali", "as": "Noto Sans Bengali",
    "gu": "Noto Sans Gujarati", "pa": "Noto Sans Gurmukhi", "or": "Noto Sans Oriya",
    "ta": "Noto Sans Tamil", "te": "Noto Sans Telugu", "kn": "Noto Sans Kannada",
    "ml": "Noto Sans Malayalam", "si": "Noto Sans Sinhala",
    "ar": "Noto Sans Arabic", "fa": "Noto Sans Arabic", "ur": "Noto Nastaliq Urdu", "ps": "Noto Sans Arabic",
    "he": "Noto Sans Hebrew", "yi": "Noto Sans Hebrew",
    "th": "Noto Sans Thai", "lo": "Noto Sans Lao", "km": "Noto Sans Khmer", "my": "Noto Sans Myanmar",
    "am": "Noto Sans Ethiopic", "ti": "Noto Sans Ethiopic",
    "ka": "Noto Sans Georgian", "hy": "Noto Sans Armenian",
    "zh": "Noto Sans SC", "ja": "Noto Sans JP", "ko": "Noto Sans KR",
}

def _rtl() -> frozenset[str]:
    from services.runtime_injector import _RTL_LANGUAGES  # one RTL list
    return _RTL_LANGUAGES


def base(tag: str) -> str:
    return str(tag or "").strip().replace("_", "-").split("-")[0].lower()


def languages(doc: dict) -> list[str]:
    """The interface's languages, the primary first, each once."""
    prod = doc.get("product") or {}
    primary = str(prod.get("locale") or "").strip() or "en"
    out = [primary]
    for tag in prod.get("languages") or []:
        tag = str(tag or "").strip()
        if tag and base(tag) not in {base(t) for t in out}:
            out.append(tag)
    return out


def script_fonts(doc: dict) -> dict[str, str]:
    """`{base language: font family}` for the languages that need one."""
    return {base(t): SCRIPT_FONTS[base(t)] for t in languages(doc) if base(t) in SCRIPT_FONTS}


def project_languages(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """`src/lib/languages.ts` — what `@/sdk/i18n` reads."""
    tags = languages(doc)
    rows = [{"tag": t, "dir": "rtl" if base(t) in _rtl() else "ltr"} for t in tags]
    path = Path(app_root) / "src" / "lib" / "languages.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ("// Generated from the Living Blueprint (services/blueprint/languages.py):\n"
            "// product.locale and product.languages. Edit the Blueprint, not this file.\n\n"
            f"export const PRIMARY: string = {json.dumps(tags[0])};\n\n"
            "export const LANGUAGES: { tag: string; dir: \"ltr\" | \"rtl\" }[] = "
            f"{json.dumps(rows, indent=2, ensure_ascii=False)};\n")
    try:
        if path.read_text("utf-8") == text:
            return {"files": []}
    except OSError:
        pass
    path.write_text(text, "utf-8")
    return {"files": ["src/lib/languages.ts"]}


def page_rule(doc: dict) -> str:
    """What the page writer is told about language — nothing for an English
    application in one language, which is what it assumes anyway."""
    tags = languages(doc)
    if len(tags) > 1:
        shown = ", ".join(f"`{t}`" for t in tags)
        sample = ", ".join(f'{base(t)}: "…"' for t in tags)
        return (f"This application is shown in {len(tags)} languages — {shown}, the first the one it is "
                "written in — and the person switches between them with the switch in the application's "
                "frame. EVERY string a reader sees on the page is written in all of them: "
                f"`const t = useT()` from \"@/sdk/i18n\", then `t({{ {sample} }})` wherever text appears — "
                "headings, labels, buttons, empty states, placeholders, toasts. Never write a language "
                "switch, toggle or button of your own — the frame has the one switch, and two disagree. "
                "The sign-in and sign-up pages have no frame: they place `<LanguageSwitch />` from "
                "\"@/sdk/i18n\" in their own top corner, and nothing else does. "
                "Record values (names, notes people typed) are shown as they are.")
    if base(tags[0]) != "en":
        return (f"This application's interface is written in `{tags[0]}`: every string a reader sees is "
                "written in that language.")
    return ""


__all__ = ["SCRIPT_FONTS", "base", "languages", "script_fonts", "project_languages", "page_rule"]
