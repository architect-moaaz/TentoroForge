"""Design montage → DesignBrief, so a reference screenshot reaches generation.

`attachment_ids` currently reaches only `_handle_smith_turn`: Smith can
SEE an attached image and act on it conversationally, but the generation
pipeline never reads it. A user who pastes the look they want gets a
brief authored from discovery prose ("deep navy and teal with warm amber
accents") rather than from the pixels they pointed at.

Figma already solved the second half of this. `brief_from_figma` is a
DETERMINISTIC aggregator over ``{colors, fonts, spacings, border_radii}``
— it assigns roles by frequency and lightness and knows nothing about
where the tokens came from. So a screenshot only needs the first half
replaced: vision instead of the Figma API. This module reuses those
helpers verbatim rather than reimplementing colour-role assignment,
which keeps one behaviour for both sources.

Two boundaries this module owns:

* **Untrusted extraction.** Vision returns prose as readily as JSON. Every
  value is validated before it can reach a brief — a malformed hex here
  becomes a broken custom property in globals.css.
* **Provenance + locking.** ``source="screenshot"`` and locked palette
  fields, so Smith's edit_brief refuses to silently overwrite evidence
  the user deliberately supplied — the same contract Figma gets.

Scope is SURFACE ONLY: palette, typography, density, radius. A montage
is strong evidence for how an app should look and weak evidence for how
it should be structured — the BizHub reference has no breadcrumbs and no
detail-page depth anywhere in it, so letting it drive IA would teach the
pipeline a flatness we deliberately fixed elsewhere.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from schemas.design_brief import (
    DesignBrief,
    Identity,
    Layout,
    Palette,
    SignatureMove,
    Typography,
)
from services.brief_from_figma import (
    BASE_ANTI_PATTERNS,
    _infer_neutrals_tint,
    _pick_palette,
    _pick_typography,
    _snap_density,
    _snap_radius,
)

logger = logging.getLogger(__name__)

_HEX_FULL = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX_SHORT = re.compile(r"^#[0-9a-fA-F]{3}$")
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

_EXTRACT_PROMPT = """You are reading one or more UI screenshots to extract DESIGN TOKENS.

Report only what you can actually see. Do not invent values.

Return STRICT JSON, no prose, with these keys:
{
  "colors": ["#RRGGBB", ...],   // every distinct colour you see, REPEATED
                                // in rough proportion to how much area it
                                // covers — frequency decides which colour
                                // becomes the brand
  "fonts": ["Family Name", ...],
  "border_radii": [8, 12],      // corner radii in px
  "spacings": [4, 8, 16]        // gaps/padding in px
}

Colours must be 6-digit hex. If you cannot read a value, omit it rather
than guessing."""


class ScreenshotBriefError(RuntimeError):
    """Screenshot input too sparse or unreadable to produce a brief."""


# ── extraction (vision, untrusted output) ───────────────────────────

def _norm_hex(v: Any) -> str | None:
    """A hex string or nothing. Shorthand is expanded; junk is dropped."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if _HEX_FULL.match(s):
        return s.upper()
    if _HEX_SHORT.match(s):
        return ("#" + "".join(c * 2 for c in s[1:])).upper()
    return None


def _norm_num(v: Any) -> float | None:
    if isinstance(v, bool):          # bool is an int subclass — reject first
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _parse_payload(raw: str) -> dict:
    """Vision output → dict. Prose (or anything unparseable) yields {}."""
    text = _FENCE.sub("", str(raw or "")).strip()
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001 - prose is an expected response shape
        logger.debug("screenshot extract: non-JSON response, treating as empty")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_screenshot_tokens(
    image_blocks: list[dict],
    *,
    llm: Callable[..., str] | None = None,
    domain: str = "",
) -> dict:
    """Vision-extract design tokens from attached image blocks.

    Returns the same shape ``brief_from_figma`` consumes:
    ``{colors, fonts, border_radii, spacings}``. Every value is validated —
    a bad hex here would propagate to globals.css.

    ``llm`` is injectable so this is testable without a network call.
    """
    if not image_blocks:
        raise ScreenshotBriefError("no image blocks supplied")

    if llm is None:  # pragma: no cover - exercised live, not in unit tests
        from services.llm_client import complete as _complete

        def llm(**kw):
            return _complete(**kw)

    raw = llm(
        system=_EXTRACT_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "text",
             "text": f"Extract design tokens from these screenshots. Domain: {domain or 'unknown'}."},
            *image_blocks,
        ]}],
    )
    payload = _parse_payload(raw)

    colors = [h for h in (_norm_hex(c) for c in (payload.get("colors") or [])) if h]
    fonts = [f.strip() for f in (payload.get("fonts") or [])
             if isinstance(f, str) and f.strip()]
    radii = [n for n in (_norm_num(r) for r in (payload.get("border_radii") or []))
             if n is not None]
    spacings = [n for n in (_norm_num(s) for s in (payload.get("spacings") or []))
                if n is not None]

    return {"colors": colors, "fonts": fonts,
            "border_radii": radii, "spacings": spacings}


# ── aggregation (deterministic, shared with Figma) ──────────────────

def brief_from_screenshot(tokens: dict, domain: str) -> DesignBrief:
    """Deterministic aggregator: screenshot tokens → DesignBrief.

    Role assignment is delegated to brief_from_figma's helpers so both
    sources behave identically — brand is the most-frequent non-neutral,
    neutrals are picked by lightness, radius/density snap to the scale.

    Raises:
        ScreenshotBriefError: the tokens carry no usable colour signal.
            Failing loudly beats inventing a brand hue the image never had.
    """
    colors = list((tokens or {}).get("colors") or [])
    if not colors:
        raise ScreenshotBriefError("screenshot tokens carry no colors")

    try:
        palette_kwargs = _pick_palette(colors)
    except Exception as exc:  # noqa: BLE001 - greyscale/monochrome input
        raise ScreenshotBriefError(
            f"could not derive a palette from the screenshot: {exc}") from exc

    palette = Palette(
        **palette_kwargs,
        neutrals_tint=_infer_neutrals_tint(palette_kwargs["brand"]),
        locked_fields={
            "brand", "accent", "surface_bg", "surface_elevated",
            "foreground_primary", "neutrals_base",
        },
    )

    typography = Typography(
        **_pick_typography(tokens.get("fonts") or []),
        locked_fields={"display_family", "body_family"},
    )

    layout = Layout(
        density=_snap_density(tokens.get("spacings") or []),
        radius=_snap_radius(tokens.get("border_radii") or []),
        grid="12col",
        locked_fields={"radius"},
    )

    identity = Identity(
        domain=domain,
        register=["structured"],
        voice="warm_precise",
        modes=["light", "dark"],
        source="screenshot",
    )

    return DesignBrief(
        identity=identity,
        palette=palette,
        typography=typography,
        layout=layout,
        signature_moves=[
            SignatureMove(
                kind="screenshot_source",
                detail="palette + type + radius extracted from a reference screenshot",
            ),
        ],
        anti_patterns=BASE_ANTI_PATTERNS,
    )


__all__ = [
    "ScreenshotBriefError",
    "brief_from_screenshot",
    "extract_screenshot_tokens",
]
