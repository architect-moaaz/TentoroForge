"""The native app's typefaces: the design system's fonts, as files the phone can load.

The web app loads its fonts from Google Fonts by name (`Fraunces`, `Inter`). A phone has no stylesheet:
a typeface is a font FILE, and each weight is a file of its own (`Inter_700Bold`, not "Inter, bold"). So
the Blueprint's two typefaces (`designSystem.typography`: heading and base) are mapped to the
`@expo-google-fonts/*` package that carries each, the app's `package.json` gets those packages, and two
generated modules say what the kit loads and which family name is which weight:

* `src/fonts.generated.ts` imports the files and exports `FONT_FILES` (what `useFonts` loads);
* `src/theme.generated.ts` carries `fonts`: `{ body: { regular, medium, semibold, bold }, heading: {…} }`.

A family this table does not know is the system font: the app is never blocked on a typeface.
"""
from __future__ import annotations

import re
from typing import Any

#: Weight number -> the suffix `@expo-google-fonts` gives it.
_WEIGHT_NAME = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold",
                700: "Bold", 800: "ExtraBold", 900: "Black"}

#: The four slots the kit asks for.
SLOTS = (("regular", 400), ("medium", 500), ("semibold", 600), ("bold", 700))

_STANDARD = (400, 500, 600, 700)

#: family (lower case) -> (package slug, export prefix, weights the package carries among 300-900).
GOOGLE: dict[str, tuple[str, str, tuple[int, ...]]] = {
    "inter": ("inter", "Inter", _STANDARD),
    "fraunces": ("fraunces", "Fraunces", _STANDARD),
    "poppins": ("poppins", "Poppins", _STANDARD),
    "dm sans": ("dm-sans", "DMSans", _STANDARD),
    "playfair display": ("playfair-display", "PlayfairDisplay", _STANDARD),
    "lora": ("lora", "Lora", _STANDARD),
    "manrope": ("manrope", "Manrope", _STANDARD),
    "nunito": ("nunito", "Nunito", _STANDARD),
    "roboto": ("roboto", "Roboto", (400, 500, 700)),
    "open sans": ("open-sans", "OpenSans", _STANDARD),
    "montserrat": ("montserrat", "Montserrat", _STANDARD),
    "work sans": ("work-sans", "WorkSans", _STANDARD),
    "merriweather": ("merriweather", "Merriweather", (400, 700)),
    "plus jakarta sans": ("plus-jakarta-sans", "PlusJakartaSans", _STANDARD),
    "outfit": ("outfit", "Outfit", _STANDARD),
    "source sans 3": ("source-sans-3", "SourceSans3", _STANDARD),
    "source sans pro": ("source-sans-3", "SourceSans3", _STANDARD),
    "libre baskerville": ("libre-baskerville", "LibreBaskerville", (400, 700)),
}

#: The version of every `@expo-google-fonts/*` package this table was written against.
PACKAGE_RANGE = "^0.4.0"


def family_of(spec: Any) -> str | None:
    """The first family of a CSS font stack: `"Fraunces", serif` -> `fraunces`."""
    if not isinstance(spec, str) or not spec.strip():
        return None
    first = spec.split(",")[0].strip().strip("'\"").strip()
    return first.lower() or None


def design_fonts(doc: dict) -> dict[str, str]:
    """`{"heading": family, "body": family}` for the ones the design names and this table has."""
    typo = (doc.get("designSystem") or {}).get("typography") or {}
    head = family_of(typo.get("fontFamilyHeading") or typo.get("fontFamilyDisplay") or typo.get("headingFontFamily"))
    body = family_of(typo.get("fontFamilyBase") or typo.get("fontFamily") or typo.get("fontFamilyBody"))
    out: dict[str, str] = {}
    if body in GOOGLE:
        out["body"] = body
    if head in GOOGLE:
        out["heading"] = head
    elif head is None and "body" in out:
        out["heading"] = out["body"]
    return out


def _nearest(weight: int, have: tuple[int, ...]) -> int:
    return min(have, key=lambda w: (abs(w - weight), -w))


def file_name(family: str, weight: int) -> str:
    """`Inter_700Bold`: the export of the package, and the family name the phone knows it by."""
    _, prefix, _ = GOOGLE[family]
    return f"{prefix}_{weight}{_WEIGHT_NAME[weight]}"


def font_set(family: str) -> dict[str, str]:
    """`{regular, medium, semibold, bold}` -> the family name of the nearest weight the package has."""
    _, _, have = GOOGLE[family]
    return {slot: file_name(family, _nearest(weight, have)) for slot, weight in SLOTS}


def theme_fonts(doc: dict) -> dict[str, dict[str, str]]:
    return {face: font_set(family) for face, family in design_fonts(doc).items()}


def packages(doc: dict) -> dict[str, str]:
    """`{"@expo-google-fonts/inter": "^0.4.0", …}`: what the app's `package.json` must carry."""
    return {f"@expo-google-fonts/{GOOGLE[f][0]}": PACKAGE_RANGE for f in sorted(set(design_fonts(doc).values()))}


def fonts_module(doc: dict) -> str:
    """`src/fonts.generated.ts`: the font files, keyed by family name, for `useFonts`."""
    header = ("// Generated from the Living Blueprint (designSystem.typography) - the native app's own half. Edit the\n"
              "// Blueprint, not this file. One font FILE per weight; `theme.generated.ts` says which family is which.\n\n")
    lines: list[str] = []
    names: list[str] = []
    for family in sorted(set(design_fonts(doc).values())):
        slug, _, _ = GOOGLE[family]
        used = sorted(set(font_set(family).values()))
        lines.append(f"import {{ {', '.join(used)} }} from \"@expo-google-fonts/{slug}\";")
        names += used
    body = "\n".join(lines) + ("\n\n" if lines else "")
    items = ",\n".join(f"  {n}" for n in names)
    return (header + body + "export const FONT_FILES: Record<string, number> = {"
            + (f"\n{items},\n" if names else "") + "};\n")
