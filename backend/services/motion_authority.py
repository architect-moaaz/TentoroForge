"""Motion is a contract, not a suggestion.

Every generated app already ships ~13 ``cubic-bezier`` declarations, but
nothing owns them, so the values drift and one of them is plainly wrong:
``transition: all 150ms`` animates whatever happens to change — including
``padding``, ``height`` and ``width``, which force layout recalculation on
every frame.

This module is the single authority for motion. It owns the curve set, the
duration scale, and the invariants, and it can check emitted CSS against
them. Advice in a prompt does not survive the pipeline; a token set plus a
gate does.

Rules follow Emil Kowalski's design-engineering guidance (animations.dev),
adapted to this codebase's token shape:

  * Only ``transform`` and ``opacity`` animate — they are GPU-composited.
    Everything else triggers layout or paint.
  * ``ease-in`` is never used; it front-loads the slow part and reads as
    sluggish. Entering/exiting → ease-out. Moving on-screen → ease-in-out.
  * Duration scales with distance and surface size, and is capped: past
    ~300ms an interface stops feeling responsive.
  * Hover animation is gated behind a real pointer — on touch, ``:hover``
    sticks after tap and the animation fires at the wrong moment.
  * ``prefers-reduced-motion`` keeps opacity and color, drops transforms.
"""
from __future__ import annotations

import re

# ── the curve set ──────────────────────────────────────────────────────────
# ease-in is deliberately absent: there is no interaction in an app UI that
# is improved by starting slow and ending fast.
CURVES: dict[str, str] = {
    "--ease-out":    "cubic-bezier(0.23, 1, 0.32, 1)",
    "--ease-in-out": "cubic-bezier(0.77, 0, 0.175, 1)",
    "--ease-drawer": "cubic-bezier(0.32, 0.72, 0, 1)",
}

# ── the duration scale ─────────────────────────────────────────────────────
# Keyed by what is moving, not by a t-shirt size, so a caller picks by
# meaning ("this is a dropdown") rather than by guessing at "md".
DURATIONS_MS: dict[str, int] = {
    "press":    120,   # button feedback           100–160
    "tooltip":  160,   # tooltips, small popovers  125–200
    "dropdown": 200,   # dropdowns, selects        150–250
    "modal":    280,   # modals, drawers           200–500, capped below
}

# Past this an interface reads as laggy rather than smooth.
MAX_UI_DURATION_MS = 300

# Pressed state. Below ~0.95 the control looks like it broke.
ACTIVE_SCALE = 0.97
# Entry never starts from scale(0) — it reads as a pop, not an arrival.
MIN_ENTRY_SCALE = 0.95

# Properties that are cheap to animate. Anything else forces the browser to
# re-run layout (geometry) or repaint on every frame.
ANIMATABLE = frozenset({"transform", "opacity", "filter", "box-shadow", "color",
                        "background-color", "border-color", "outline-color"})
# The subset that is GPU-composited — the only two that stay smooth under load.
COMPOSITED = frozenset({"transform", "opacity"})
# Named explicitly so the gate's message can say WHY, not just "not allowed".
LAYOUT_PROPS = frozenset({"padding", "margin", "height", "width", "top", "left",
                          "right", "bottom", "position", "inset"})


def css_variables() -> dict[str, str]:
    """The `:root` custom properties an app needs for motion.

    Durations are emitted as CSS time values so a stylesheet can use them
    directly (``transition: transform var(--duration-press)``).
    """
    out = dict(CURVES)
    for name, ms in DURATIONS_MS.items():
        out[f"--duration-{name}"] = f"{min(ms, MAX_UI_DURATION_MS)}ms"
    return out


# ── the gate ───────────────────────────────────────────────────────────────

# `transition: <props> <time> ...` — capture the property list only.
_TRANSITION_RE = re.compile(r"transition\s*:\s*([^;{}]+)", re.I)
_EASE_IN_RE = re.compile(r"\bease-in\b(?!-out)", re.I)
_HOVER_RE = re.compile(r":hover\b")


def _properties_in(decl: str) -> list[str]:
    """Property names from one `transition` shorthand value."""
    props: list[str] = []
    for part in decl.split(","):
        tok = part.strip().split()
        if tok:
            props.append(tok[0].lower())
    return props


def check_css(css: str) -> list[dict]:
    """Motion violations in a stylesheet, most-actionable first.

    Returns ``[{rule, detail, snippet}]`` — empty when the sheet is clean.
    Reports rather than rewrites: a caller decides whether a violation
    fails a build or is repaired, and a silent rewrite of someone's
    stylesheet is worse than a named finding.
    """
    findings: list[dict] = []
    text = css or ""

    for m in _TRANSITION_RE.finditer(text):
        decl = m.group(1).strip()
        for prop in _properties_in(decl):
            if prop == "all":
                findings.append({
                    "rule": "transition_all",
                    "detail": "`transition: all` animates every property that "
                              "changes, including layout ones — each frame "
                              "forces a reflow. Name the properties instead.",
                    "snippet": f"transition: {decl[:60]}",
                })
            elif prop in LAYOUT_PROPS:
                findings.append({
                    "rule": "layout_property_animated",
                    "detail": f"`{prop}` is a layout property; animating it "
                              f"recalculates geometry every frame. Use "
                              f"transform instead.",
                    "snippet": f"transition: {decl[:60]}",
                })

    if _EASE_IN_RE.search(text):
        findings.append({
            "rule": "ease_in_used",
            "detail": "`ease-in` starts slow and ends fast — it reads as lag. "
                      "Use ease-out for enter/exit, ease-in-out for movement.",
            "snippet": "ease-in",
        })

    if "prefers-reduced-motion" not in text:
        findings.append({
            "rule": "no_reduced_motion",
            "detail": "No `prefers-reduced-motion` block — users who ask the "
                      "OS for less motion still get every transform.",
            "snippet": "",
        })

    if _HOVER_RE.search(text) and "hover: hover" not in text:
        findings.append({
            "rule": "ungated_hover",
            "detail": "`:hover` styles are not gated behind "
                      "`@media (hover: hover) and (pointer: fine)`; on touch "
                      "the state sticks after a tap.",
            "snippet": ":hover",
        })

    return findings


def duration_for(surface: str) -> int:
    """Milliseconds for a named surface, capped. Unknown → dropdown."""
    return min(DURATIONS_MS.get(surface, DURATIONS_MS["dropdown"]),
               MAX_UI_DURATION_MS)
