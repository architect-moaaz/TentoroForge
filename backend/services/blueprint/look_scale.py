"""Depth, type scale and motion — the design's, not one fixed library default.

On the web every generated app shared the SAME shadows, the SAME rhythm of type
sizes and the SAME (minimal) motion, because those lived as constants in the
library's `default-tokens.ts` and the token contract had no home for them. Two
apps differed in hue and typeface but read at the same depth and rhythm — the
templated tell. The native side already drove these from the Blueprint
(`native_tokens.py`); this gives the web the same.

Each function turns a `designSystem` choice — a NAMED scheme the design system
agent can state in one word, or explicit values when it wants them — into the
CSS custom properties the kit and Tailwind read (`--shadow-*`, `--text-*`,
`--tracking-*`, `--motion-*`). The named schemes are the common, good-looking
cases; explicit values always win, so nothing here caps what a design can ask
for. Values are plain CSS, emitted inside `html:root { … }` beside the colours.

The projector (`projection.project_design_tokens`) calls these; the defaults
also live in the scaffold's `theme.css`/Tailwind config so a var resolves even
before a design fills it.
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Elevation — how the surfaces lift off the page.
# --------------------------------------------------------------------------- #

#: Four shadow ramps, flat → dramatic. Each is (sm, md, lg, xl). A design states
#: one word (`elevation: { scheme: "soft" }`, or just `elevation: "soft"` as a
#: bare string the projector passes through) and the surfaces lift as a set.
#: `flat` leans on borders, not shadow (the crisp, utilitarian register); `soft`
#: is the gentle default; `layered` is the richer product look; `dramatic` is
#: deep, for a dark/luxe register. Tuned to read on both grounds.
_ELEVATION_SCHEMES: dict[str, tuple[str, str, str, str]] = {
    "flat": (
        "0 1px 2px 0 rgb(0 0 0 / 0.04)",
        "0 1px 3px 0 rgb(0 0 0 / 0.06)",
        "0 2px 6px -2px rgb(0 0 0 / 0.08)",
        "0 4px 10px -4px rgb(0 0 0 / 0.10)",
    ),
    "soft": (
        "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "0 4px 6px -1px rgb(0 0 0 / 0.08), 0 2px 4px -2px rgb(0 0 0 / 0.06)",
        "0 10px 15px -3px rgb(0 0 0 / 0.10), 0 4px 6px -4px rgb(0 0 0 / 0.08)",
        "0 20px 25px -5px rgb(0 0 0 / 0.12), 0 8px 10px -6px rgb(0 0 0 / 0.10)",
    ),
    "layered": (
        "0 1px 2px 0 rgb(0 0 0 / 0.06), 0 1px 1px -0.5px rgb(0 0 0 / 0.04)",
        "0 2px 4px -1px rgb(0 0 0 / 0.08), 0 4px 10px -2px rgb(0 0 0 / 0.10)",
        "0 8px 16px -4px rgb(0 0 0 / 0.12), 0 12px 28px -6px rgb(0 0 0 / 0.14)",
        "0 16px 32px -8px rgb(0 0 0 / 0.16), 0 28px 56px -12px rgb(0 0 0 / 0.18)",
    ),
    "dramatic": (
        "0 2px 4px 0 rgb(0 0 0 / 0.10)",
        "0 6px 12px -2px rgb(0 0 0 / 0.16), 0 3px 6px -3px rgb(0 0 0 / 0.12)",
        "0 16px 32px -6px rgb(0 0 0 / 0.22), 0 8px 16px -8px rgb(0 0 0 / 0.18)",
        "0 28px 56px -12px rgb(0 0 0 / 0.30), 0 16px 32px -16px rgb(0 0 0 / 0.24)",
    ),
}
DEFAULT_ELEVATION = "soft"
_SHADOW_KEYS = ("sm", "md", "lg", "xl")

#: The schemes whose shadow takes the brand's hue unless the design says
#: otherwise. A shadow is light the surface blocked, so on a warm clay product it
#: is warm and on a deep violet one it is violet — neutral black under every app
#: is the same depth tell the ramps above were written to break. Held to the rich
#: registers: a `flat` utility console casts almost nothing, and tinting a hairline
#: only muddies it.
_TINTED_SCHEMES = frozenset({"layered", "dramatic"})

#: How much a tinted shadow is deepened to hold its weight. A coloured shadow of
#: the same opacity reads lighter than a black one, because the hue carries part
#: of the contrast the darkness used to.
_TINT_GAIN = 1.25

_BLACK = "rgb(0 0 0 / "


def _rgb(hex_colour: Any) -> tuple[int, int, int] | None:
    """`#rrggbb` (or `#rgb`) as a channel triple; None for anything else."""
    text = str(hex_colour or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def _tinted(shadow: str, rgb: tuple[int, int, int]) -> str:
    """One ramp step restated in the brand's hue.

    The ramps are written as `rgb(0 0 0 / α)`; this swaps the channels and lifts
    α by `_TINT_GAIN`, leaving every offset and blur alone so the scheme still
    reads as the scheme.
    """
    out, rest = [], shadow
    while (at := rest.find(_BLACK)) != -1:
        close = rest.find(")", at)
        if close == -1:
            break
        try:
            alpha = float(rest[at + len(_BLACK):close])
        except ValueError:
            out.append(rest[:close + 1])
            rest = rest[close + 1:]
            continue
        out.append(rest[:at])
        out.append("rgb(%d %d %d / %.3f)" % (*rgb, min(alpha * _TINT_GAIN, 1.0)))
        rest = rest[close + 1:]
    return "".join(out) + rest


def _scheme_name(value: Any, default: str, known: dict) -> str:
    """The scheme a design asked for: a bare string, or a record's `scheme`/
    `level`/`name`. Falls back to `default` when it names none we know."""
    name = value if isinstance(value, str) else (
        (value.get("scheme") or value.get("level") or value.get("name"))
        if isinstance(value, dict) else None)
    name = str(name or "").strip().lower()
    return name if name in known else default


def elevation_vars(elevation: Any, tint: Any = None) -> list[str]:
    """`--shadow-sm/md/lg/xl` for the chosen elevation scheme. Explicit values in
    the record (``{sm, md, lg, xl}``) win over the scheme they sit beside.

    ``tint`` is the brand colour the shadow takes on the rich schemes; the design
    overrules with ``elevation.tint`` of ``"brand"`` or ``"neutral"``.
    """
    scheme = _scheme_name(elevation, DEFAULT_ELEVATION, _ELEVATION_SCHEMES)
    ramp = dict(zip(_SHADOW_KEYS, _ELEVATION_SCHEMES[scheme]))

    asked = str((elevation or {}).get("tint") or "").strip().lower() \
        if isinstance(elevation, dict) else ""
    wants_tint = asked == "brand" or (asked != "neutral" and scheme in _TINTED_SCHEMES)
    if wants_tint and (rgb := _rgb(tint)):
        ramp = {k: _tinted(v, rgb) for k, v in ramp.items()}

    if isinstance(elevation, dict):
        for k in _SHADOW_KEYS:
            v = elevation.get(k) or elevation.get(f"shadow-{k}")
            if isinstance(v, str) and v.strip():
                ramp[k] = v.strip()
    return [f"  --shadow-{k}: {ramp[k]};" for k in _SHADOW_KEYS]


# --------------------------------------------------------------------------- #
# Type scale — a real h1→caption ramp, not five fixed sizes for every app.
# --------------------------------------------------------------------------- #

#: A modular scale: each step is the one below × ratio. Named ratios keyed by how
#: much hierarchy the register wants — `tight` for dense tools, `comfortable` for
#: most apps, `expressive`/`editorial` for content and marketing where the
#: display type is meant to carry the page.
_SCALE_RATIOS: dict[str, float] = {
    "tight": 1.18,
    "balanced": 1.25,
    "comfortable": 1.25,
    "expressive": 1.333,
    "editorial": 1.414,
}
DEFAULT_SCALE = "comfortable"
#: step name → how many ratio steps above the body size. Body is the anchor (0).
_TYPE_STEPS = (("caption", -1), ("body", 0), ("h3", 2), ("h2", 3), ("h1", 4))

#: TWO STEPS BELOW CAPTION, WHERE A DENSE PRODUCT ACTUALLY SPENDS ITS TYPE.
#: The ramp had one word below body and five above. Criterion CARES — the one
#: application a person designed by hand — ran the other way: 297 of its 715
#: typographic decisions sit between 9px and 13px, on five sizes, and its five
#: busiest are ALL at or under 13px (2026-11-04). That band is the table header,
#: the eyebrow, the chip, the timestamp, the unit, the helper line — and Forge
#: offered `caption` for all of them, so every page drew them identically.
#:
#: The descent is NOT the heading ratio. A modular ratio compounds, so an
#: `editorial` register (1.414) would put the smallest step at 5.7px; and a
#: table header is 11px whatever the brand's display face does. The ratio sets
#: the hierarchy ABOVE body; below it, legibility does. So: a damped ratio,
#: floored where type stops being readable, and always a visible step down.
_DESCENT_DAMPING = 0.45     # how much of the register's ratio survives downward
_LABEL_FLOOR_REM = 0.6875   # 11px
_MICRO_FLOOR_REM = 0.5625   # 9px
_MIN_STEP_DOWN = 0.94       # a step you cannot see is not a step


def _below(top: float, ratio: float, floor: float) -> float:
    """One damped step under `top`, never under `floor`, always a visible step."""
    damped = 1 + (ratio - 1) * _DESCENT_DAMPING
    return min(top * _MIN_STEP_DOWN, max(floor, top / damped))

#: A DISPLAY STEP ABOVE h1, because the ramp stopped where the page titles are.
#: `h1` is base x ratio^4 — 31px on a `tight` register — so a product whose type
#: is meant to carry the page had no size to carry it with; the writer reached
#: for Tailwind's own `text-4xl` instead and every app's titles came out the same.
#: One ratio step above h1, clamped: a further step at `editorial` is 90px, which
#: is a poster, and it must never sit so close to h1 that it is not a step.
_DISPLAY_MAX_REM = 4.5      # 72px — the biggest a page title goes
_DISPLAY_MIN_OVER_H1 = 1.12


def _base_rem(typography: dict | None) -> float:
    """The body size in rem. `baseSize` may be `16px`, `1rem`, or a number."""
    raw = str((typography or {}).get("baseSize") or "").strip().lower()
    try:
        if raw.endswith("px"):
            return round(float(raw[:-2]) / 16, 4)
        if raw.endswith("rem"):
            return float(raw[:-3])
        if raw:
            return round(float(raw) / 16, 4) if float(raw) > 4 else float(raw)
    except ValueError:
        pass
    return 1.0


def _rem(value: Any) -> float | None:
    """A stated size in rem. `40px`, `2.5rem` or a bare number of px."""
    raw = str(value or "").strip().lower()
    try:
        if raw.endswith("px"):
            return round(float(raw[:-2]) / 16, 4)
        if raw.endswith("rem"):
            return float(raw[:-3])
        if raw:
            n = float(raw)
            return round(n / 16, 4) if n > 4 else n
    except ValueError:
        pass
    return None


def type_scale_vars(typography: dict | None) -> list[str]:
    """`--text-caption/body/h3/h2/h1/display` sized by a modular scale, plus
    `--tracking-tight` and `--tracking-display` for headings. The ratio comes
    from `typography.scaleMode` (or `scaleRatio` as an explicit number).

    A stated `typography.titleSize` wins for `--text-h1`: the design agent is
    asked for it in px and the ramp used to ignore it, so an application could
    ask for a 40px title and be given 31px.
    """
    typ = typography or {}
    ratio_raw = typ.get("scaleRatio")
    try:
        ratio = float(ratio_raw) if ratio_raw not in (None, "") else None
    except (TypeError, ValueError):
        ratio = None
    if ratio is None:
        mode = str(typ.get("scaleMode") or "").strip().lower()
        ratio = _SCALE_RATIOS.get(mode, _SCALE_RATIOS[DEFAULT_SCALE])
    base = _base_rem(typ)
    h1 = _rem(typ.get("titleSize")) or base * (ratio ** 4)
    out: list[str] = []
    for name, steps in _TYPE_STEPS:
        size = h1 if name == "h1" else base * (ratio ** steps)
        out.append(f"  --text-{name}: {round(size, 4)}rem;")
    display = max(min(h1 * ratio, _DISPLAY_MAX_REM), h1 * _DISPLAY_MIN_OVER_H1)
    out.append(f"  --text-display: {round(display, 4)}rem;")
    label = _below(base / ratio, ratio, _LABEL_FLOOR_REM)
    micro = _below(label, ratio, _MICRO_FLOOR_REM)
    out.append(f"  --text-label: {round(label, 4)}rem;")
    out.append(f"  --text-micro: {round(micro, 4)}rem;")
    # A tighter track on display sizes reads as designed, not default; the
    # bigger the ratio (the more editorial), the tighter the heading track.
    # THE RANGE USED TO BE TOO NARROW TO SEE: -0.0089em at `tight` to -0.0159em
    # at `editorial`, when Tailwind's own `tracking-tight` is -0.025em and a
    # designed display head is around -0.045em. Anchored at the tight end now,
    # so the editorial end reaches where a display face actually sits.
    tracking = -0.012 - (ratio - _SCALE_RATIOS["tight"]) * 0.09
    out.append(f"  --tracking-tight: {round(tracking, 4)}em;")
    out.append(f"  --tracking-display: {round(tracking * 1.4, 4)}em;")
    # AND A POSITIVE TRACK, which the ramp had none of. Every heading track was
    # negative, so a small-caps label — the one thing in a dense UI that must be
    # let out, not pulled in — had no token and came out at Tailwind's 0. CARES
    # sets +0.16em on nineteen of them. The wider the heading track is pulled
    # in, the further a label at a tenth of the size is let out.
    out.append(f"  --tracking-label: {round(0.06 - tracking * 1.6, 4)}em;")
    return out


# --------------------------------------------------------------------------- #
# Motion — how much the UI moves, from none to expressive.
# --------------------------------------------------------------------------- #

#: level → (fast, normal, easing). `none` collapses durations to 0 so a
#: reduced/utilitarian app simply does not animate; `expressive` is longer with
#: an eased-out curve for a consumer/playful register.
_MOTION_LEVELS: dict[str, tuple[str, str, str]] = {
    "none":       ("0ms", "0ms", "linear"),
    "subtle":     ("120ms", "200ms", "cubic-bezier(0.4, 0, 0.2, 1)"),
    "expressive": ("180ms", "320ms", "cubic-bezier(0.22, 1, 0.36, 1)"),
}
DEFAULT_MOTION = "subtle"


def motion_vars(motion: Any) -> list[str]:
    """`--motion-duration-fast/normal`, `--motion-easing`, and `--motion-level`
    (a word the kit's `useMotion` reads to turn whole animations off). Explicit
    `durationFast`/`durationNormal`/`easing` in the record win."""
    level = _scheme_name(motion, DEFAULT_MOTION, _MOTION_LEVELS)
    fast, normal, easing = _MOTION_LEVELS[level]
    if isinstance(motion, dict):
        fast = str(motion.get("durationFast") or fast).strip()
        normal = str(motion.get("durationNormal") or normal).strip()
        easing = str(motion.get("easing") or easing).strip()
    return [
        f"  --motion-level: {level};",
        f"  --motion-duration-fast: {fast};",
        f"  --motion-duration-normal: {normal};",
        f"  --motion-easing: {easing};",
    ]


def look_vars(design: dict) -> list[str]:
    """Every depth/type/motion var for one design, in one call."""
    colors = design.get("colors") or {}
    return (
        elevation_vars(design.get("elevation"), colors.get("primary"))
        + type_scale_vars(design.get("typography") or {})
        + motion_vars(design.get("motion"))
    )


__all__ = [
    "DEFAULT_ELEVATION", "DEFAULT_MOTION", "DEFAULT_SCALE",
    "elevation_vars", "type_scale_vars", "motion_vars", "look_vars",
]
