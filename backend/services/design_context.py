"""Design context persistence — which design a project was built from and
the tokens measured from it.

Written once at import time to ``src/contracts/design-context.json`` and
read by every later agent that must stay on the design's palette (refiner,
scaffolder, the brief aggregator). ``figma-context.json`` is the name the
Figma-only version of this file had; it is still read as a fallback so a
project imported before the rename keeps its context.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONTEXT_PATH = "src/contracts/design-context.json"
LEGACY_CONTEXT_PATH = "src/contracts/figma-context.json"

_PROVIDER_LABEL = {"figma": "Figma", "uxpilot": "UX Pilot", "screenshot": "reference screenshot"}


def write_design_context(
    output_dir: str | Path,
    *,
    provider: str,
    design_ref: str,
    tokens: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the context and return it.

    ``tokens`` is the ``design_tokens`` dict (colors/fonts/font_sizes/
    border_radii/spacings). ``figma_url`` is written for provider ``figma``
    because readers of the old file name look for it.
    """
    context: dict[str, Any] = {
        "provider": provider,
        "design_ref": design_ref,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "design_tokens": {
            "colors": list(tokens.get("colors") or []),
            "fonts": list(tokens.get("fonts") or []),
            "font_sizes": list(tokens.get("font_sizes") or []),
            "border_radii": list(tokens.get("border_radii") or []),
            "spacings": list(tokens.get("spacings") or []),
        },
    }
    if provider == "figma":
        context["figma_url"] = design_ref
    if extra:
        context.update(extra)

    path = Path(output_dir) / CONTEXT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2))
    logger.info(
        "[design_context] wrote %s (%s, %d colors, %d fonts)",
        path, provider, len(context["design_tokens"]["colors"]),
        len(context["design_tokens"]["fonts"]),
    )
    return context


def read_design_context(output_dir: str | Path) -> dict[str, Any] | None:
    """The persisted context, or None. Reads the current file name first and
    the Figma-era name second; a legacy file is reported as provider figma."""
    for rel in (CONTEXT_PATH, LEGACY_CONTEXT_PATH):
        path = Path(output_dir) / rel
        if not path.exists():
            continue
        try:
            ctx = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(ctx, dict):
            return None
        ctx.setdefault("provider", "figma")
        ctx.setdefault("design_ref", ctx.get("figma_url", ""))
        return ctx
    return None


def context_ref_changed(output_dir: str | Path, new_ref: str | None) -> bool:
    """True when a context exists and points at a different design."""
    if not new_ref:
        return False
    ctx = read_design_context(output_dir)
    if ctx is None:
        return False
    return (ctx.get("design_ref") or "") != new_ref


def get_design_context_for_prompt(output_dir: str | Path) -> str:
    """A prompt section naming the provider and the measured tokens, or ""
    when the project was not built from a design."""
    ctx = read_design_context(output_dir)
    if not ctx:
        return ""
    tokens = ctx.get("design_tokens") or {}
    colors = tokens.get("colors") or []
    fonts = tokens.get("fonts") or []
    font_sizes = tokens.get("font_sizes") or []
    border_radii = tokens.get("border_radii") or []
    spacings = tokens.get("spacings") or []
    provider = ctx.get("provider") or "figma"
    label = _PROVIDER_LABEL.get(provider, provider)

    sections = [
        "\n## Design Context",
        f"This project was generated from a {label} design. "
        "Use these design tokens for visual consistency:",
    ]
    if colors:
        sections.append(f"- Colors: {', '.join(colors[:20])}")
    if fonts:
        sections.append(f"- Fonts: {', '.join(fonts)}")
    if font_sizes:
        sections.append(f"- Font sizes: {', '.join(str(s) + 'px' for s in font_sizes)}")
    if border_radii:
        sections.append(f"- Border radii: {', '.join(str(r) + 'px' for r in border_radii)}")
    if spacings:
        sections.append(f"- Spacings: {', '.join(str(s) + 'px' for s in spacings)}")
    if provider == "figma":
        sections.append("- Reference design: reference.png (read if helpful)")
    sections.append("When making visual changes, prefer values from the original design system.")
    return "\n".join(sections)
