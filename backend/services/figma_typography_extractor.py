"""Extract typography tokens from Figma TEXT nodes.

Heading-named text votes for heading family/weight/letter-spacing.
Other TEXT nodes vote for body. Unique fontSize values populate scale.
"""
from __future__ import annotations
from collections import Counter
import re

HEADING_NAME_RE = re.compile(r"^(heading\s*\d|.+\s+title|.+\s+header)$", re.I)

# (px_threshold, tailwind_name, rem_value) — snap each Figma fontSize
# to the nearest entry by px distance.
_SIZE_LADDER = [
    (10, "xs",   "0.625rem"),
    (12, "xs",   "0.75rem"),
    (14, "sm",   "0.875rem"),
    (16, "base", "1rem"),
    (18, "lg",   "1.125rem"),
    (20, "xl",   "1.25rem"),
    (24, "2xl",  "1.5rem"),
    (30, "3xl",  "1.875rem"),
    (32, "4xl",  "2rem"),
    (36, "4xl",  "2.25rem"),
    (48, "5xl",  "3rem"),
    (60, "6xl",  "3.75rem"),
]

_DEFAULTS = {
    "font":          {"body": "Inter", "heading": "Inter"},
    "weight":        {"body": "400", "heading": "600"},
    "scale":         {},
    "lineHeight":    {"tight": "1.25", "normal": "1.5"},
    "letterSpacing": {"heading": "0", "body": "0"},
}


def _is_heading(name: str) -> bool:
    return bool(HEADING_NAME_RE.match((name or "").strip()))


def _nearest_size(px: float) -> tuple[str, str]:
    best = _SIZE_LADDER[0]
    best_diff = abs(_SIZE_LADDER[0][0] - px)
    for entry in _SIZE_LADDER:
        d = abs(entry[0] - px)
        if d < best_diff:
            best_diff = d
            best = entry
    return best[1], best[2]


def _fmt_number(x: float) -> str:
    s = f"{x:.2f}"
    s = s.rstrip("0").rstrip(".")
    return s or "0"


def _fmt_em(value_em: float) -> str:
    s = _fmt_number(value_em)
    # Cosmetic: -.016 looks cleaner than -0.016 (matches Tailwind config style).
    if s.startswith("-0."):
        s = "-." + s[3:]
    elif s.startswith("0."):
        s = "." + s[2:]
    return s + "em"


def extract_typography(walked_nodes: list[dict]) -> dict:
    fam_h: Counter = Counter()
    fam_b: Counter = Counter()
    wt_h: Counter = Counter()
    wt_b: Counter = Counter()
    sizes_px: set[float] = set()
    body_ratios: list[float] = []
    heading_letter_em: Counter = Counter()

    for entry in walked_nodes:
        node = entry["node"]
        if node.get("type") != "TEXT":
            continue
        style = node.get("style") or {}
        if not style:
            continue
        name = node.get("name") or ""
        is_h = _is_heading(name)

        fam = style.get("fontFamily")
        if fam:
            (fam_h if is_h else fam_b)[fam] += 1

        weight = style.get("fontWeight")
        if weight:
            (wt_h if is_h else wt_b)[str(weight)] += 1

        font_size = style.get("fontSize")
        if isinstance(font_size, (int, float)) and font_size > 0:
            sizes_px.add(float(font_size))

        line_h = style.get("lineHeightPx")
        if isinstance(font_size, (int, float)) and isinstance(line_h, (int, float)) and font_size > 0 and not is_h:
            body_ratios.append(line_h / font_size)

        letter = style.get("letterSpacing")
        if is_h and isinstance(letter, (int, float)) and isinstance(font_size, (int, float)) and font_size > 0:
            heading_letter_em[_fmt_em(letter / font_size)] += 1

    out: dict = {k: dict(v) for k, v in _DEFAULTS.items()}

    if fam_h:    out["font"]["heading"] = fam_h.most_common(1)[0][0]
    if fam_b:    out["font"]["body"]    = fam_b.most_common(1)[0][0]
    if fam_h and not fam_b: out["font"]["body"]    = out["font"]["heading"]
    if fam_b and not fam_h: out["font"]["heading"] = out["font"]["body"]

    if wt_h:    out["weight"]["heading"] = wt_h.most_common(1)[0][0]
    if wt_b:    out["weight"]["body"]    = wt_b.most_common(1)[0][0]
    if wt_h and not wt_b: out["weight"]["body"]    = out["weight"]["heading"]
    if wt_b and not wt_h: out["weight"]["heading"] = out["weight"]["body"]

    for px in sorted(sizes_px):
        name, rem = _nearest_size(px)
        out["scale"][name] = rem

    if body_ratios:
        avg = sum(body_ratios) / len(body_ratios)
        out["lineHeight"]["normal"] = _fmt_number(avg)

    if heading_letter_em:
        out["letterSpacing"]["heading"] = heading_letter_em.most_common(1)[0][0]

    return out
