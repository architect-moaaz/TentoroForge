"""design.md — the company's design language, written for whoever builds next.

GENERATED, NEVER AUTHORED BESIDE THE STRUCTURE. The profile holds `identity`
and `design` as data because code reads them — the projection writes colour
roles from `design`, Smith's question names `company_name`. This renders the
same facts as the prose a designer would have been handed, and it is
regenerated on every edit, so the two cannot drift. A document typed
independently of the structure is a document that is wrong the first time
somebody corrects a colour.

WHO READS IT. Two audiences, and the shape serves both:

* The agents. `services.blueprint.brand_language` puts it in front of the
  nodes that can act on it, the way a supplied specification reaches the
  requirements agent. That is why the colours are stated as roles with
  hexes rather than described — "our primary is #1B7F5A" is actionable and
  "a deep confident green" is an invitation to pick a different green.
* The person. It is shown in Settings and it is the thing they check when an
  app comes out the wrong colour. So every number says where it came from:
  a palette nobody can argue with is a palette nobody can correct.

DETERMINISTIC. Same profile in, same bytes out — no model, no timestamp, no
dict ordering luck. The document is stored in the database and copied into
every build, and a renderer that produced a slightly different file each time
would make every project's diff noise.
"""
from __future__ import annotations

from typing import Any

#: The order roles are presented in — most load-bearing first, so an agent
#: reading top-down gets the brand before the border. Sorted output would put
#: `accent` above `primary`, which reads as though it mattered more.
_COLOR_ORDER: tuple[str, ...] = (
    "primary", "primaryForeground", "accent", "secondary",
    "background", "foreground", "card", "border", "input", "ring",
    "muted", "mutedForeground", "destructive",
)

_ROLE_MEANING: dict[str, str] = {
    "primary": "the brand colour — primary buttons, active states, emphasis",
    "primaryForeground": "text and icons on top of the brand colour",
    "accent": "a second voice — highlights, selected rows, secondary emphasis",
    "secondary": "supporting fills that are not the brand",
    "background": "the page's ground",
    "foreground": "body text",
    "card": "raised surfaces sitting on the ground",
    "border": "hairlines and dividers",
    "input": "field outlines",
    "ring": "the focus ring",
    "muted": "quiet fills",
    "mutedForeground": "secondary text",
    "destructive": "delete and other irreversible actions",
}

_IDENTITY_HEADINGS: tuple[tuple[str, str], ...] = (
    ("who_you_are", "Who they are"),
    ("what_you_do", "What they do"),
    ("how_you_do_it", "How they do it"),
)


def _lines_for_identity(identity: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key, heading in _IDENTITY_HEADINGS:
        value = str(identity.get(key) or "").strip()
        if value:
            out += [f"### {heading}", "", value, ""]
    facts = [
        ("Industry", identity.get("industry")),
        ("Who it is for", identity.get("audience")),
        ("Values", identity.get("values")),
    ]
    stated = [(label, str(v).strip()) for label, v in facts if str(v or "").strip()]
    if stated:
        out.append("| | |")
        out.append("|---|---|")
        out += [f"| {label} | {value} |" for label, value in stated]
        out.append("")
    return out


def _lines_for_voice(identity: dict[str, Any]) -> list[str]:
    tone = str(identity.get("tone") or "").strip()
    voice = str(identity.get("voice") or "").strip()
    if not tone and not voice:
        return []
    out = ["## Voice", ""]
    if tone:
        out += [f"The writing sounds: **{tone}**.", ""]
    if voice:
        out += [voice, ""]
    out += [
        "Every label, empty state, confirmation and error message in an "
        "application built for this company should sound like this. Use their "
        "words for their own things.",
        "",
    ]
    return out


def _lines_for_colors(colors: dict[str, str], evidence: dict[str, Any]) -> list[str]:
    if not colors:
        return []
    out = ["### Colour", "",
           "| Role | Value | What it is for |", "|---|---|---|"]
    named = [k for k in _COLOR_ORDER if colors.get(k)]
    named += sorted(k for k in colors if k not in _COLOR_ORDER and colors.get(k))
    for role in named:
        meaning = _ROLE_MEANING.get(role, "")
        out.append(f"| `{role}` | `{colors[role]}` | {meaning} |")
    out.append("")
    source = str(evidence.get("brandFrom") or "").strip()
    if source:
        out += [f"The brand colour was read from {source}.", ""]
    out += [
        "These are the application's colours. Do not introduce a hue that is "
        "not derived from them — a second blue beside the brand is the single "
        "most common way a generated application stops looking like the "
        "company it was built for.",
        "",
    ]
    return out


def _lines_for_type(typography: dict[str, str]) -> list[str]:
    if not typography:
        return []
    body = typography.get("fontFamilyBase")
    heading = typography.get("fontFamilyHeading")
    out = ["### Type", ""]
    if body:
        out.append(f"- Body: **{body}**")
    if heading and heading != body:
        out.append(f"- Headings: **{heading}**")
    elif heading:
        out.append("- Headings are set in the same face as body text.")
    out.append("")
    return out


def _lines_for_shape(design: dict[str, Any]) -> list[str]:
    out: list[str] = []
    radius = design.get("radius") or {}
    if isinstance(radius, dict) and radius.get("md"):
        corner = radius["md"]
        how = ("square — this company does not round its corners"
               if corner in ("0px", "0")
               else f"rounded to {corner}")
        out.append(f"- Corners: {how}.")
    elevation = design.get("elevation") or {}
    if isinstance(elevation, dict) and elevation.get("md"):
        flat = elevation["md"] == "none"
        out.append("- Surfaces: flat, separated by hairlines rather than shadow."
                   if flat else
                   "- Surfaces: lifted off the ground by a soft shadow.")
    density = design.get("informationDensity")
    if density:
        out.append(f"- Density: **{density}**.")
    return (["### Shape and density", ""] + out + [""]) if out else []


def render(profile: dict[str, Any]) -> str:
    """The design.md for one company profile.

    `profile` is the row's readable shape — `company_name`, `source_url`,
    `identity`, `design`, `evidence` — rather than the ORM object, so this
    renders from a dict in a test with no database in the process.
    """
    name = str(profile.get("company_name") or "").strip() or "This company"
    url = str(profile.get("source_url") or "").strip()
    identity = profile.get("identity") or {}
    design = profile.get("design") or {}
    evidence = profile.get("evidence") or {}
    colors = design.get("colors") or {}
    typography = design.get("typography") or {}

    out: list[str] = [f"# {name} — design language", ""]
    origin = f"Read from {url}." if url else "Entered by hand."
    if evidence.get("rendered") is False and url:
        origin += (" The page could only be read as source, not rendered, so "
                   "the colours below are what the markup states outright.")
    out += [origin,
            "",
            "This is the design language of the company this application is "
            "being built for. It is not a suggestion and it is not a theme to "
            "start from: where it states a value, use that value.",
            "",
            "---",
            ""]

    identity_lines = _lines_for_identity(identity)
    if identity_lines:
        out += ["## The company", ""] + identity_lines

    out += _lines_for_voice(identity)

    design_lines = (_lines_for_colors(colors, evidence)
                    + _lines_for_type(typography)
                    + _lines_for_shape(design))
    if design_lines:
        out += ["## The design language", ""] + design_lines
    else:
        out += ["## The design language", "",
                "Nothing could be read from the site. The application's design "
                "is open — decide it from the product, as usual.", ""]

    out += [
        "---",
        "",
        "## How to use this",
        "",
        "- The colours, type and corners above are the application's, "
        "wherever the application does not have a stated reason of its own.",
        "- The voice above is the application's copy — labels, empty states, "
        "confirmations, errors.",
        "- This says nothing about what the application DOES. Layout, pages "
        "and workflows come from the requirements; this only says what they "
        "look and sound like.",
        "",
    ]
    return "\n".join(out).rstrip() + "\n"
