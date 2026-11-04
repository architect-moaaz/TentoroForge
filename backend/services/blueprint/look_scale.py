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


def _scheme_name(value: Any, default: str, known: dict) -> str:
    """The scheme a design asked for: a bare string, or a record's `scheme`/
    `level`/`name`. Falls back to `default` when it names none we know."""
    name = value if isinstance(value, str) else (
        (value.get("scheme") or value.get("level") or value.get("name"))
        if isinstance(value, dict) else None)
    name = str(name or "").strip().lower()
    return name if name in known else default


def elevation_vars(elevation: Any) -> list[str]:
    """`--shadow-sm/md/lg/xl` for the chosen elevation scheme. Explicit values in
    the record (``{sm, md, lg, xl}``) win over the scheme they sit beside."""
    scheme = _scheme_name(elevation, DEFAULT_ELEVATION, _ELEVATION_SCHEMES)
    ramp = dict(zip(_SHADOW_KEYS, _ELEVATION_SCHEMES[scheme]))
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


def type_scale_vars(typography: dict | None) -> list[str]:
    """`--text-caption/body/h3/h2/h1` sized by a modular scale, plus
    `--tracking-tight` for headings. The ratio comes from
    `typography.scaleMode` (or `scaleRatio` as an explicit number)."""
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
    out: list[str] = []
    for name, steps in _TYPE_STEPS:
        out.append(f"  --text-{name}: {round(base * (ratio ** steps), 4)}rem;")
    # A tighter track on display sizes reads as designed, not default; the
    # bigger the ratio (the more editorial), the tighter the heading track.
    tracking = -0.011 - (ratio - 1.25) * 0.03
    out.append(f"  --tracking-tight: {round(tracking, 4)}em;")
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
    return (
        elevation_vars(design.get("elevation"))
        + type_scale_vars(design.get("typography") or {})
        + motion_vars(design.get("motion"))
    )


__all__ = [
    "DEFAULT_ELEVATION", "DEFAULT_MOTION", "DEFAULT_SCALE",
    "elevation_vars", "type_scale_vars", "motion_vars", "look_vars",
]
