"""Spec C4 wiring — motion CSS tokens.

Reads ``spec.motion`` and ``spec.responsive`` from the app's
``src/contracts/design-spec.json`` and appends the corresponding CSS
custom properties + a small ``@media (prefers-reduced-motion)``
override to ``src/app/globals.css``. Also emits a small helper class
so any component can write ``transition: all var(--motion-fast-ms)ms
var(--ease-out);`` and inherit the brief's timing.

Additive + idempotent: uses a delimiter comment block; re-runs
replace the block in place.

Flag-gated (``FORGE_POLISH_MOTION``). No-op when the design-spec has
no ``motion`` key (older generations).
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_BLOCK_START = "/* Spec C4/C8 — motion + responsive tokens (auto-generated) */"
_BLOCK_END = "/* /Spec C4/C8 */"
_BLOCK_RE = re.compile(
    re.escape(_BLOCK_START) + r".*?" + re.escape(_BLOCK_END),
    re.DOTALL,
)


def is_enabled() -> bool:
    return os.getenv("FORGE_POLISH_MOTION", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _load_spec(root: Path) -> dict | None:
    p = root / "src" / "contracts" / "design-spec.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _build_block(motion: dict, responsive: dict | None) -> str:
    """Render the motion + responsive CSS block. All values guarded."""
    fast = int(motion.get("durationFastMs", 120) or 120)
    med = int(motion.get("durationMediumMs", 240) or 240)
    slow = int(motion.get("durationSlowMs", 480) or 480)
    ease_out = str(motion.get("easeOut") or "cubic-bezier(0.2, 0.0, 0.0, 1.0)")
    ease_in_out = str(motion.get("easeInOut") or "cubic-bezier(0.4, 0.0, 0.2, 1.0)")
    reduce_respect = bool(motion.get("reduceMotionRespect", True))

    lines: list[str] = []
    lines.append(_BLOCK_START)
    lines.append(":root {")
    lines.append(f"  --motion-fast-ms: {fast}ms;")
    lines.append(f"  --motion-medium-ms: {med}ms;")
    lines.append(f"  --motion-slow-ms: {slow}ms;")
    lines.append(f"  --ease-out: {ease_out};")
    lines.append(f"  --ease-in-out: {ease_in_out};")
    if isinstance(responsive, dict):
        pff = str(responsive.get("primaryFormFactor") or "desktop")
        lines.append(f"  --primary-form-factor: \"{pff}\";")
    lines.append("}")
    if reduce_respect:
        lines.append("@media (prefers-reduced-motion: reduce) {")
        lines.append("  :root {")
        lines.append("    --motion-fast-ms: 0ms;")
        lines.append("    --motion-medium-ms: 0ms;")
        lines.append("    --motion-slow-ms: 0ms;")
        lines.append("  }")
        lines.append("  *, *::before, *::after {")
        lines.append("    animation-duration: 0.01ms !important;")
        lines.append("    animation-iteration-count: 1 !important;")
        lines.append("    transition-duration: 0.01ms !important;")
        lines.append("    scroll-behavior: auto !important;")
        lines.append("  }")
        lines.append("}")
    # Small utilities for opting into brief-driven timing without repeating
    # vars. Spec E Wave 2 accessibility spine: gate the actual transition
    # declarations behind `prefers-reduced-motion: no-preference` so the
    # user preference wins even when the platform-level reduce block
    # above (which zeros the durations) is absent or overridden by a
    # user stylesheet. Belt-and-braces WCAG 2.3.3.
    lines.append("@media (prefers-reduced-motion: no-preference) {")
    lines.append("  .motion-tint { transition: background-color var(--motion-fast-ms) var(--ease-out), "
                 "color var(--motion-fast-ms) var(--ease-out), "
                 "border-color var(--motion-fast-ms) var(--ease-out); }")
    lines.append("  .motion-lift { transition: transform var(--motion-medium-ms) var(--ease-out), "
                 "box-shadow var(--motion-medium-ms) var(--ease-out); }")
    lines.append("}")
    # Reduced-motion fallback: only emitted when the brief opts in to
    # respecting the user preference (matching the earlier
    # `reduceMotionRespect` gate above). Preserve final-state visual
    # (no jump) by killing the transitions on the utility classes.
    if reduce_respect:
        lines.append("@media (prefers-reduced-motion: reduce) {")
        lines.append("  .motion-tint, .motion-lift { transition: none !important; }")
        lines.append("}")
    lines.append(_BLOCK_END)
    return "\n".join(lines)


def write_motion_tokens(output_dir: str) -> dict:
    """Append or replace the motion/responsive token block in globals.css.

    Returns ``{written, spec_had_motion}``. Absent design-spec or absent
    ``motion`` block → no-op.
    """
    root = Path(output_dir)
    css_path = root / "src" / "app" / "globals.css"
    if not css_path.is_file():
        return {"written": False, "spec_had_motion": False}
    spec = _load_spec(root)
    if not isinstance(spec, dict):
        return {"written": False, "spec_had_motion": False}
    motion = spec.get("motion")
    if not isinstance(motion, dict):
        return {"written": False, "spec_had_motion": False}
    responsive = spec.get("responsive") if isinstance(spec.get("responsive"), dict) else None

    block = _build_block(motion, responsive)
    try:
        text = css_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[motion-tokens] read failed for %s: %s", css_path, exc)
        return {"written": False, "spec_had_motion": True}

    if _BLOCK_RE.search(text):
        new_text = _BLOCK_RE.sub(block, text)
    else:
        # Append with a leading newline for readability.
        new_text = text.rstrip() + "\n\n" + block + "\n"

    if new_text == text:
        return {"written": False, "spec_had_motion": True}

    try:
        css_path.write_text(new_text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[motion-tokens] write failed for %s: %s", css_path, exc)
        return {"written": False, "spec_had_motion": True}
    return {"written": True, "spec_had_motion": True}


__all__ = ["is_enabled", "write_motion_tokens"]
