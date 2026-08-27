"""Brief → shell bridge (Spec D Wave 6).

Wave 1's design-brief authors palette, visual stance, and layout
numerics into ``contracts/brief.json`` as the single design authority.
The shell layout agent used to read a legacy ``design_spec`` blob (via
:mod:`services.shell_templates`) built from the LLM design agent —
Wave 6 replaces the primary path with this thin bridge that reads
brief-authored fields directly.

The bridge is deliberately small: it does NOT re-implement the shell
frame builders (sidebar / topbar / rail / split / SideNav) or the
IA → frame selector. Those live in :mod:`services.shell_templates`
and have four test files pinning their behavior (structural identity,
guardrail invariants, SideNav width, byte-exact Figma). Instead the
bridge synthesizes a ``design_spec``-shaped dict from the brief and
delegates to ``build_shell_deterministic`` so every shell shape,
guardrail, and token-cleaning invariant is preserved verbatim.

When the brief is absent or malformed, the bridge falls through to
``build_shell_deterministic(...)`` with whatever ``design_spec`` the
caller had, so briefless projects (older generated apps, unit tests)
keep working.
"""
from __future__ import annotations

from typing import Any

from services.shell_templates import build_shell_deterministic


# ---------------------------------------------------------------------------
# Brief → sidebar palette derivation
# ---------------------------------------------------------------------------

# The shell frames paint the sidebar with dedicated tokens (sidebarBg,
# sidebarText, sidebarMuted) because a well-designed rail is rarely just
# the app's surface bg. The design-agent's spec used to carry these
# explicitly; the brief does not. We derive them deterministically from
# the brief's brand hex so both light and dark rails read as part of
# the app.


def _hex_to_rgb(hexc: str) -> tuple[int, int, int] | None:
    """Parse a ``#RRGGBB`` / ``#RGB`` string. Returns None on garbage."""
    try:
        s = hexc.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return None
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except (ValueError, AttributeError):
        return None


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)),
    )


def _luminance(hexc: str) -> float:
    """Relative luminance in [0, 1]. Matches shell_templates._is_dark."""
    rgb = _hex_to_rgb(hexc)
    if rgb is None:
        return 0.5
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _darken(hexc: str, factor: float) -> str:
    """Multiply RGB channels by ``factor`` (0..1)."""
    rgb = _hex_to_rgb(hexc)
    if rgb is None:
        return hexc
    r, g, b = rgb
    return _rgb_to_hex(int(r * factor), int(g * factor), int(b * factor))


def _sidebar_tokens_from_brief(palette: dict[str, Any]) -> dict[str, str]:
    """Derive ``sidebarBg`` / ``sidebarText`` / ``sidebarMuted`` from the
    brief's palette. Uses a dark sidebar rooted in the brand hue (the
    same shape the design-agent used to produce) so the rail feels of
    the brand without hardcoding slate."""
    brand = palette.get("brand") or "#2E4A6E"
    accent = palette.get("accent") or "#C47D0E"
    # Sidebar bg = brand darkened toward navy. This keeps hue continuity
    # with the primary CTA color (unlike a stock slate).
    sidebar_bg = _darken(brand, 0.55)
    return {
        "sidebarBg": sidebar_bg,
        "sidebarText": "#E5EAF0",
        "sidebarMuted": "#7C8BA0",
        "sidebarActive": accent,
        "brandTile": brand,
    }


def _visual_stance_to_nav_pref(stance: dict[str, Any] | None) -> str | None:
    """Very light heuristic: some ``visual_stance`` values suggest a
    specific shell shape. Returns ``None`` when nothing conclusive.

    This intentionally does not overreach — the IA selector in
    :mod:`shell_templates` already has judgment; we only fill in
    when the brief is explicit."""
    if not isinstance(stance, dict):
        return None
    shape = (stance.get("shape_vocab") or "").lower()
    principles = " ".join(str(p).lower() for p in (stance.get("principles") or []))
    blob = f"{shape} {principles}"
    if "dense" in blob or "workspace" in blob or "canvas" in blob:
        return "rail"
    if "editorial" in blob or "content" in blob or "public" in blob:
        return "topbar"
    return None


# ---------------------------------------------------------------------------
# Brief → design_spec synth
# ---------------------------------------------------------------------------

def _design_spec_from_brief(
    brief: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the small ``design_spec`` slice ``shell_templates`` reads.

    Only fields shell_templates.extract_tokens + _nav_pref care about
    are populated. Anything the caller already had in ``fallback``
    (usually the legacy design_spec) wins for keys the brief doesn't
    speak to — so we never regress a spec that had richer info."""
    out: dict[str, Any] = dict(fallback or {})
    palette = brief.get("palette") if isinstance(brief.get("palette"), dict) else {}
    identity = brief.get("identity") if isinstance(brief.get("identity"), dict) else {}

    # Color palette — merge on top of the fallback's colorPalette (if any)
    # so brief-authored hexes win but any spec-only keys survive.
    cp: dict[str, Any] = dict(out.get("colorPalette") or {})
    brand = palette.get("brand")
    accent = palette.get("accent")
    canvas = palette.get("surface_bg") or palette.get("canvas")
    ink = palette.get("foreground_primary")
    muted = palette.get("foreground_muted")
    surface = palette.get("surface_elevated")
    border = palette.get("neutrals_base")

    if brand:
        cp["primary"] = brand
    if accent:
        cp["accent"] = accent
    if canvas:
        cp["background"] = canvas
    if surface:
        cp["surface"] = surface
    if ink:
        cp["textPrimary"] = ink
    if muted:
        cp["textSecondary"] = muted
    if border:
        cp.setdefault("border", border)

    # Sidebar tokens — derive from the brand when the fallback didn't
    # carry them explicitly.
    sb = _sidebar_tokens_from_brief(palette)
    for key in ("sidebarBg", "sidebarText", "sidebarMuted",
                "sidebarActive", "brandTile"):
        cp.setdefault(key, sb[key])

    out["colorPalette"] = cp

    # Navigation preference — brief.identity.visual_stance can nudge
    # the frame selector. Written as a dict-shaped nav ({style: ...}) so
    # downstream ``build_nav_groups`` (which does ``.get('groups')``
    # unconditionally) never trips on a bare string.
    pref = _visual_stance_to_nav_pref(identity.get("visual_stance"))
    if pref and "navigation" not in out:
        out["navigation"] = {"style": pref}

    return out


def _brand_from_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``brand`` dict shell_templates expects (appName +
    primaryColor). Falls back to safe defaults for missing fields."""
    palette = brief.get("palette") if isinstance(brief.get("palette"), dict) else {}
    identity = brief.get("identity") if isinstance(brief.get("identity"), dict) else {}
    brand: dict[str, Any] = {}
    if palette.get("brand"):
        brand["primaryColor"] = palette["brand"]
    if identity.get("app_name") or identity.get("product_name"):
        brand["appName"] = identity.get("app_name") or identity.get("product_name")
    return brand


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_shell_from_brief(
    brief: dict[str, Any] | None,
    ia: dict[str, Any],
) -> dict[str, Any]:
    """Author a renderable shell.json from a brief + information architecture.

    Args:
        brief: A brief-shaped dict (typically ``contracts/brief.json``
            deserialized, or ``DesignBrief.model_dump()``). When
            ``None`` or empty, this function delegates verbatim to
            :func:`services.shell_templates.build_shell_deterministic`
            so briefless callers keep working.
        ia: The information architecture bundle: ``{plan, nav_flow,
            brand?, design_spec?}``. ``nav_flow`` is required; the
            rest are optional and passed through to
            ``build_shell_deterministic`` after brief-synth merging.

    Returns:
        A shell.json dict (schemaVersion 2.0). Same shape as
        ``build_shell_deterministic`` — the guardrail + validator
        invariants are preserved because we delegate to the same
        renderer with a synthesized design_spec.
    """
    plan = ia.get("plan")
    nav_flow = ia.get("nav_flow") or {}
    caller_brand = ia.get("brand")
    caller_spec = ia.get("design_spec")

    if not isinstance(brief, dict) or not brief:
        return build_shell_deterministic(plan, nav_flow, caller_brand, caller_spec)

    synth_spec = _design_spec_from_brief(brief, caller_spec)
    synth_brand = caller_brand or _brand_from_brief(brief) or None
    return build_shell_deterministic(plan, nav_flow, synth_brand, synth_spec)


__all__ = ["build_shell_from_brief"]
