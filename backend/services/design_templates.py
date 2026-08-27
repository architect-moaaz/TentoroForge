"""Design templates — pick a visual look before generation.

A DesignTemplate is a COMPACT, capability-bounded description of an app's visual
language (palette + type + density + radius + shell). It can only ever express
values the design system already renders, so a picked look is guaranteed
buildable. `template_to_design_spec` expands it into the `design_spec` that
`design_compiler.compile` consumes; `guard_template` clamps any (web-researched)
template to renderable ranges.

Compact schema:
    {
      "id", "name", "vibe", "provenance",
      "palette":    {"primary": "#hex", "accent": "#hex", "mode": "light"|"dark",
                     # optional explicit overrides, else derived from mode:
                     "background", "surface", "sidebarBg", "sidebarText"},
      "typography": {"headingFont", "bodyFont", "scale": "compact"|"balanced"|"airy"},
      "tokens":     {"density", "radiusScale", "elevation", "motionLevel"},
      "shell":      {"frame": "sidebar"|"topbar"|"rail", "tone": "light"|"dark"},
    }
"""
from __future__ import annotations

import re

# --- Capability vocabulary (the "buildable" allowlist) -----------------------
DENSITIES = ("compact", "comfortable", "spacious")
FRAMES = ("sidebar", "topbar", "rail")
TONES = ("light", "dark")
RADIUS_SCALES = ("sharp", "soft", "rounded", "pill")
ELEVATIONS = ("flat", "soft", "raised")
MOTION_LEVELS = ("none", "subtle", "expressive")
SCALES = ("compact", "balanced", "airy")

# Self-hostable / Google-Fonts-allowlisted families only (no arbitrary web fonts).
FONT_ALLOWLIST = {
    "Inter", "Roboto", "Open Sans", "Lato", "Montserrat", "Poppins", "Work Sans",
    "Source Sans 3", "Nunito", "IBM Plex Sans", "Manrope", "DM Sans",
    "Space Grotesk", "Plus Jakarta Sans", "Figtree", "Playfair Display",
    "Merriweather", "Lora", "Fraunces", "JetBrains Mono", "IBM Plex Mono",
    "system-ui",
}

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

_RADIUS = {
    "sharp":   {"sm": "0.125rem", "md": "0.25rem", "lg": "0.375rem", "xl": "0.5rem",  "full": "9999px"},
    "soft":    {"sm": "0.25rem",  "md": "0.5rem",  "lg": "0.75rem",  "xl": "1rem",    "full": "9999px"},
    "rounded": {"sm": "0.375rem", "md": "0.625rem","lg": "0.875rem", "xl": "1.25rem", "full": "9999px"},
    "pill":    {"sm": "0.5rem",   "md": "0.875rem","lg": "1.25rem",  "xl": "1.75rem", "full": "9999px"},
}
_SHADOW = {
    "flat":   {"sm": "none", "md": "none", "lg": "none", "xl": "none"},
    "soft":   {"sm": "0 1px 2px rgba(0,0,0,.05)", "md": "0 2px 6px rgba(0,0,0,.07)",
               "lg": "0 8px 24px rgba(0,0,0,.08)", "xl": "0 16px 40px rgba(0,0,0,.10)"},
    "raised": {"sm": "0 1px 3px rgba(0,0,0,.10)", "md": "0 4px 12px rgba(0,0,0,.12)",
               "lg": "0 12px 32px rgba(0,0,0,.16)", "xl": "0 24px 56px rgba(0,0,0,.20)"},
}
_MOTION = {"none": "0ms", "subtle": "150ms, 250ms", "expressive": "220ms, 400ms"}
_TYPE_SCALE = {
    "compact":  {"h1": "1.5rem",   "h2": "1.25rem",  "h3": "1.05rem", "body": "0.875rem", "caption": "0.75rem"},
    "balanced": {"h1": "1.875rem", "h2": "1.5rem",   "h3": "1.25rem", "body": "1rem",     "caption": "0.8125rem"},
    "airy":     {"h1": "2.5rem",   "h2": "1.875rem", "h3": "1.5rem",  "body": "1.0625rem","caption": "0.875rem"},
}
_SCALE_TO_DENSITY = {"compact": "compact", "balanced": "comfortable", "airy": "spacious"}

# BACKFILL ONLY. A selected look that names these wins; this table exists so a
# sparse template (an older cached one, or a researcher response that returned
# just two hues) still renders. It is not the source of truth for any app whose
# chosen design direction speaks for itself.
_NEUTRALS = {
    "light": {"background": "#FFFFFF", "surface": "#F8FAFC", "surfaceHover": "#F1F5F9",
              "textPrimary": "#0F172A", "textSecondary": "#475569", "textTertiary": "#94A3B8"},
    "dark":  {"background": "#0F172A", "surface": "#1E293B", "surfaceHover": "#334155",
              "textPrimary": "#F1F5F9", "textSecondary": "#CBD5E1", "textTertiary": "#94A3B8"},
}

# The palette roles a design option may own outright, beyond primary/accent.
# `sidebarBg`/`sidebarText` are chrome, kept separate from the seven core roles.
_NEUTRAL_ROLES = ("background", "surface", "surfaceHover",
                  "textPrimary", "textSecondary", "textTertiary")
_PALETTE_ROLES = _NEUTRAL_ROLES + ("sidebarBg", "sidebarText")


def _pick(value, allowed, default):
    return value if value in allowed else default


def _font(value, default="Inter"):
    return value if value in FONT_ALLOWLIST else default


def _hex(value, default):
    return value if isinstance(value, str) and _HEX.match(value) else default


def guard_template(t: dict) -> tuple[dict, list[str]]:
    """Clamp a (possibly web-researched) template to renderable values.
    Returns (clean_template, warnings). Never raises."""
    t = t if isinstance(t, dict) else {}
    warn: list[str] = []
    pal = t.get("palette") or {}
    typo = t.get("typography") or {}
    tok = t.get("tokens") or {}
    shell = t.get("shell") or {}

    mode = _pick(pal.get("mode"), TONES, "light")
    primary = _hex(pal.get("primary"), "#3B82F6")
    if primary != pal.get("primary"):
        warn.append("primary color clamped")
    accent = _hex(pal.get("accent"), primary)

    clean = {
        "id": str(t.get("id") or t.get("name") or "template").strip().lower().replace(" ", "-"),
        "name": str(t.get("name") or "Untitled look"),
        "vibe": str(t.get("vibe") or ""),
        "provenance": str(t.get("provenance") or ""),
        "palette": {
            "primary": primary,
            "accent": accent,
            "mode": mode,
            # Every role the SELECTED look names survives. Previously only
            # background/surface/sidebar* were kept, so a template that named
            # its own text colours silently lost them here and fell back to
            # the shared _NEUTRALS table — which is why two deliberately
            # different looks shipped identical backgrounds and type colours.
            **{k: _hex(pal.get(k), None) for k in _PALETTE_ROLES
               if _hex(pal.get(k), None)},
        },
        "typography": {
            "headingFont": _font(typo.get("headingFont"), "Inter"),
            "bodyFont": _font(typo.get("bodyFont"), "Inter"),
            "scale": _pick(typo.get("scale"), SCALES, "balanced"),
        },
        "tokens": {
            "density": _pick(tok.get("density"), DENSITIES, "comfortable"),
            "radiusScale": _pick(tok.get("radiusScale"), RADIUS_SCALES, "soft"),
            "elevation": _pick(tok.get("elevation"), ELEVATIONS, "soft"),
            "motionLevel": _pick(tok.get("motionLevel"), MOTION_LEVELS, "subtle"),
        },
        "shell": {
            "frame": _pick(shell.get("frame"), FRAMES, "sidebar"),
            "tone": _pick(shell.get("tone"), TONES, mode),
        },
    }
    return clean, warn


def template_to_design_spec(t: dict) -> dict:
    """Expand a (guarded) template into a design_spec fragment consumable by
    design_compiler.compile."""
    t, _ = guard_template(t)
    pal, typo, tok, shell = t["palette"], t["typography"], t["tokens"], t["shell"]
    mode = pal["mode"]
    # The user's chosen look owns every role it names; the mode table only
    # fills the gaps it left.
    neut = dict(_NEUTRALS[mode])
    for k in _NEUTRAL_ROLES:
        if pal.get(k):
            neut[k] = pal[k]

    frame, tone = shell["frame"], shell["tone"]
    dark_side = frame == "sidebar" or tone == "dark"
    sidebar_bg = pal.get("sidebarBg") or ("#0B1220" if dark_side else neut["surface"])
    sidebar_text = pal.get("sidebarText") or ("#CBD5E1" if dark_side else neut["textSecondary"])

    color_palette = {
        "primary": pal["primary"],
        "accent": pal["accent"],
        "background": neut["background"],
        "surface": neut["surface"],
        "surfaceHover": neut["surfaceHover"],
        "textPrimary": neut["textPrimary"],
        "textSecondary": neut["textSecondary"],
        "textTertiary": neut["textTertiary"],
        "sidebarBg": sidebar_bg,
        "sidebarText": sidebar_text,
        "sidebarActiveItem": pal["accent"],
    }

    return {
        "colorPalette": color_palette,
        "typography": {
            "fontFamily": f"{typo['bodyFont']}, system-ui, sans-serif",
            "headingFontFamily": f"{typo['headingFont']}, system-ui, sans-serif",
            "scale": _TYPE_SCALE[typo["scale"]],
            "lineHeight": "1.6" if typo["scale"] == "airy" else "1.5",
        },
        "layout": {
            "density": tok["density"] if tok["density"] != "comfortable" else _SCALE_TO_DENSITY[typo["scale"]],
            "navigation": f"{frame}-{tone}",
        },
        "borderRadius": _RADIUS[tok["radiusScale"]],
        "shadows": _SHADOW[tok["elevation"]],
        "animation": {"duration": _MOTION[tok["motionLevel"]]},
        "_designTemplate": {"id": t["id"], "name": t["name"], "provenance": t["provenance"]},
    }


def seed_design_spec(existing: dict | None, t: dict) -> dict:
    """Merge a template's look onto an existing design_spec (template wins on the
    visual keys; everything else in `existing` is preserved)."""
    out = dict(existing or {})
    frag = template_to_design_spec(t)
    for key, val in frag.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            merged.update(val)
            out[key] = merged
        else:
            out[key] = val
    return out


# --- House presets (deterministic MVP + web-research fallback) ----------------
HOUSE_TEMPLATES: list[dict] = [
    {
        "id": "calm-clinical", "name": "Calm clinical", "vibe": "Soft, trustworthy, airy",
        "provenance": "house preset",
        "palette": {"primary": "#2563EB", "accent": "#3B82F6", "mode": "light",
                    "background": "#FBFDFF", "surface": "#F2F7FD", "surfaceHover": "#E6EFF9",
                    "textPrimary": "#0C1E33", "textSecondary": "#42607F", "textTertiary": "#8AA3BC"},
        "typography": {"headingFont": "Inter", "bodyFont": "Inter", "scale": "airy"},
        "tokens": {"density": "spacious", "radiusScale": "rounded", "elevation": "soft", "motionLevel": "subtle"},
        "shell": {"frame": "sidebar", "tone": "light"},
    },
    {
        "id": "data-console", "name": "Data console", "vibe": "Dense, dark, analytical",
        "provenance": "house preset",
        "palette": {"primary": "#14B8A6", "accent": "#2DD4BF", "mode": "dark",
                    "background": "#07120F", "surface": "#0E1F1B", "surfaceHover": "#173029",
                    "textPrimary": "#E8FBF6", "textSecondary": "#9DC7BE", "textTertiary": "#5E857D"},
        "typography": {"headingFont": "IBM Plex Sans", "bodyFont": "IBM Plex Sans", "scale": "compact"},
        "tokens": {"density": "compact", "radiusScale": "sharp", "elevation": "flat", "motionLevel": "subtle"},
        "shell": {"frame": "topbar", "tone": "dark"},
    },
    {
        "id": "warm-retail", "name": "Warm retail", "vibe": "Bright, friendly, rounded",
        "provenance": "house preset",
        "palette": {"primary": "#F97316", "accent": "#FB923C", "mode": "light",
                    "background": "#FFFBF5", "surface": "#FDF3E7", "surfaceHover": "#F8E6D2",
                    "textPrimary": "#2B1B0E", "textSecondary": "#6B5741", "textTertiary": "#A08B72"},
        "typography": {"headingFont": "Poppins", "bodyFont": "DM Sans", "scale": "balanced"},
        "tokens": {"density": "comfortable", "radiusScale": "pill", "elevation": "raised", "motionLevel": "expressive"},
        "shell": {"frame": "rail", "tone": "light"},
    },
    {
        "id": "editorial-minimal", "name": "Editorial minimal", "vibe": "Quiet, premium, spacious",
        "provenance": "house preset",
        "palette": {"primary": "#111111", "accent": "#6B7280", "mode": "light",
                    "background": "#FCFCFC", "surface": "#F4F4F4", "surfaceHover": "#EAEAEA",
                    "textPrimary": "#111111", "textSecondary": "#525252", "textTertiary": "#9A9A9A"},
        "typography": {"headingFont": "Fraunces", "bodyFont": "Inter", "scale": "airy"},
        "tokens": {"density": "spacious", "radiusScale": "sharp", "elevation": "flat", "motionLevel": "subtle"},
        "shell": {"frame": "topbar", "tone": "light"},
    },
]


def house_templates(n: int = 3) -> list[dict]:
    """Deterministic fallback / MVP catalog — first `n` guarded house presets."""
    return [guard_template(t)[0] for t in HOUSE_TEMPLATES[:max(1, n)]]
