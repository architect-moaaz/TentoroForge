"""The brand a drawing is drawn in: the company's own, filled from the board.

A screen drawn in the Drafts Room is the person's page, not a reference's,
so it is drawn in the company's design language where the company has one
(`OrgBrandProfile`, read by discovery or entered in Settings) and in the
board's `look` where it has not. `source` says which, and the Screens tab
says it to the person.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Colour roles the drawer is handed, most load-bearing first (the order
#: `design_md` presents them in).
ROLES = ("primary", "primaryForeground", "accent", "secondary", "background", "foreground", "card",
         "border", "input", "ring", "muted", "mutedForeground", "destructive")


async def for_org(org_id: Any, db: Any) -> dict:
    """The company's brand, as the drawer needs it; `{}` when the company
    has none it can be drawn in (the profile's own `usable` rule)."""
    from sqlalchemy import select

    from models.brand_profile import OrgBrandProfile
    from services.brand_discovery.store import logo_file

    found = await db.execute(select(OrgBrandProfile).where(OrgBrandProfile.org_id == org_id))
    profile = found.scalar_one_or_none()
    if profile is None or not profile.usable:
        return {}
    design = profile.design or {}
    colors = {k: v for k, v in (design.get("colors") or {}).items() if isinstance(v, str) and v.strip()}
    typography = design.get("typography") or {}
    out: dict = {"source": "company", "company": str(profile.company_name or "").strip(),
                 "colors": colors,
                 "fonts": {k: v for k, v in (("body", typography.get("fontFamilyBase")),
                                             ("heading", typography.get("fontFamilyHeading"))) if v},
                 "radius": (design.get("radius") or {}).get("md") or "",
                 "elevation": (design.get("elevation") or {}).get("md") or "",
                 "density": design.get("informationDensity") or "",
                 "voice": str((profile.identity or {}).get("voice") or "")[:600],
                 "logo": None}
    logo = design.get("logo") or {}
    path = logo_file(str(org_id), logo)
    if path is not None:
        try:
            data = path.read_bytes()
            media = str(logo.get("mediaType") or "image/png")
            # Inlined: the drawing is a sandboxed document that cannot send a token.
            out["logo"] = {"media_type": media,
                           "data_uri": f"data:{media};base64,{base64.standard_b64encode(data).decode()}"}
        except OSError:
            logger.info("drafts room: the company's logo could not be read")
    return out


def merged(company: dict, board: dict) -> dict:
    """The company's brand where it has one; the board's `look` fills what
    the company does not state. With neither, the drawer chooses a restrained
    look of its own and the drawing says so."""
    look = (board or {}).get("look") or {}
    out = {k: v for k, v in (company or {}).items()}
    if not out.get("colors"):
        palette = [p for p in (look.get("palette") or []) if isinstance(p, dict) and p.get("hex")]
        if palette:
            out["colors"] = {str(p.get("name") or f"colour{i + 1}"): str(p["hex"]) for i, p in enumerate(palette)}
            out.setdefault("source", "board")
    if not out.get("fonts"):
        fonts = [str(f) for f in (look.get("fonts") or []) if f]
        if fonts:
            out["fonts"] = {"body": fonts[-1], "heading": fonts[0]}
            out.setdefault("source", "board")
    for key in ("mood", "layout", "avoid"):
        if look.get(key) and not out.get(key):
            out[key] = str(look[key])
            out.setdefault("source", "board")
    out.setdefault("source", "none")
    return out


def tokens(brand: dict) -> str:
    """A fingerprint of what a drawing is drawn in: a brand that changes is a
    drawing that is out of date."""
    body = {k: brand.get(k) for k in ("source", "company", "colors", "fonts", "radius", "elevation",
                                      "density", "mood", "layout", "avoid")}
    logo = (brand.get("logo") or {}).get("data_uri") or ""
    body["logo"] = hashlib.sha1(logo.encode()).hexdigest() if logo else ""
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def described(brand: dict) -> str:
    """The brand in words for the drawer, hexes and names included — stated
    values are used, described ones are an invitation to pick another."""
    if brand.get("source") == "none":
        return ("No brand is on record for this company and the board has no look yet: choose one restrained, "
                "modern palette and type pairing of your own and keep to it.")
    lines = []
    who = brand.get("company") or "the company"
    lines.append(f"Drawn in {who}'s own design language." if brand.get("source") == "company"
                 else "Drawn in the look agreed on the idea board.")
    colors = brand.get("colors") or {}
    if colors:
        named = [k for k in ROLES if colors.get(k)] + sorted(k for k in colors if k not in ROLES)
        lines.append("Colours (use these and only hues derived from them): "
                     + ", ".join(f"{k} {colors[k]}" for k in named))
    fonts = brand.get("fonts") or {}
    if fonts:
        lines.append("Type: " + "; ".join(f"{k} {v}" for k, v in fonts.items())
                     + " (name the family with a system fallback; load nothing).")
    for key, label in (("radius", "Corners"), ("elevation", "Elevation"), ("density", "Density"),
                       ("mood", "Mood"), ("layout", "Layout"), ("avoid", "Avoid")):
        if brand.get(key):
            lines.append(f"{label}: {brand[key]}")
    if brand.get("voice"):
        lines.append(f"Voice: {brand['voice']}")
    lines.append("The company's logo is supplied as an image; place it where a mark belongs."
                 if brand.get("logo") else "No logo is on record: set the app's name in type where a mark would go.")
    return "\n".join(lines)


__all__ = ["for_org", "merged", "tokens", "described", "ROLES"]
