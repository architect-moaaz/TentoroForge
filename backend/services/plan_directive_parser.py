"""Parse structured directives from a freeform user prompt.

The planner writes solid plans from prose descriptions, but it treats every
part of the prompt as equally-weighted narrative. Callers who supply
STRUCTURED directives — "Preset = trust-navy", "Row-click navigates to
/x/[id]", "Gauge 0-150 target 110" — see those directives disappear into
the noise and the composer never honors them.

This module extracts those directives deterministically (regex + light
NLP) so downstream authors can consume them from `plan.hints`. Additive:
freeform prompts still work; structured ones just carry more signal.

What we parse today (Seams 1 & 3 of the KPI-dashboard slice):

  ▸ ``Preset = <name>``           → visual_lock preset picker hint
  ▸ ``Vocab: <name>``             → archetype vocabulary hint
  ▸ archetype keywords            → nearest archetype-vocabulary name
                                    (matches ``analytics dashboard`` →
                                    ``analytics-dashboard`` etc.)
  ▸ ``Row-click navigates to X``  → per-page row_click hint
  ▸ ``Filter bar with (a, b, c)`` → per-page filter dimensions
  ▸ ``Gauge <label> <min>-<max>
     target <t>``                 → Gauge widget hints
  ▸ ``as <chart-type> chart``     → chart_type per-chart hint

Every parser returns None / empty on no match — safe to compose.
"""
from __future__ import annotations

import re
from typing import Any

from services.archetype_keywords import prompt_phrase_table


# ── Preset ────────────────────────────────────────────────────────────
# Matches: "Preset = trust-navy", "preset: trust-navy", "Preset=trust-navy"
_PRESET_RE = re.compile(
    r"\bpreset\s*[:=]\s*([a-z0-9][a-z0-9_\-]*)",
    re.IGNORECASE,
)


def parse_visual_preset(prompt: str) -> str | None:
    """Return the preset slug the user asked for, or None.

    Accepts both underscore and hyphen slugs; normalizes to hyphenated
    (matches visual_lock_presets naming). Returns None when the prompt
    has no explicit preset directive — do NOT default a preset here;
    the brief author picks one when unspecified.
    """
    if not prompt or not isinstance(prompt, str):
        return None
    m = _PRESET_RE.search(prompt)
    if not m:
        return None
    return m.group(1).lower().replace("_", "-")


# ── Vocabulary / archetype ────────────────────────────────────────────
# Phrase → archetype-vocabulary id. The phrases live in
# services.archetype_keywords alongside the token set the plan-haystack
# matcher uses, so an archetype cannot be registered for one matcher and
# not the other — which is exactly how legislative-platform ended up
# recognised here and invisible to the candidate ranker.
#
# Keys are canonical registry ids (``*-platform``), not short slugs. The
# short-slug spelling used to reach the registry only via a suffix
# fallback in load_vocabulary; emitting the real id removes that bridge.
_ARCHETYPE_KEYWORDS: dict[str, tuple[str, ...]] = prompt_phrase_table()


# Explicit override: "Vocab: <name>" wins over keyword detection.
_VOCAB_RE = re.compile(
    r"\bvocab(?:ulary)?\s*[:=]\s*([a-z0-9][a-z0-9_\-]*)",
    re.IGNORECASE,
)


def detect_vocab_archetype(prompt: str) -> str | None:
    """Return the best-matching archetype-vocabulary slug, or None.

    Explicit ``Vocab: X`` always wins. Otherwise walks the keyword table
    and returns the first vocabulary whose phrase appears in the prompt
    (case-insensitive substring). Deterministic tie-break: table order.
    """
    if not prompt or not isinstance(prompt, str):
        return None
    m = _VOCAB_RE.search(prompt)
    if m:
        return m.group(1).lower().replace("_", "-")
    low = prompt.lower()
    for vocab, phrases in _ARCHETYPE_KEYWORDS.items():
        for phrase in phrases:
            if phrase in low:
                return vocab
    return None


# ── Row-click directives ──────────────────────────────────────────────
# Matches: "Row-click navigates to /subscriptions/[id]",
#          "clicking a row navigates to /x/[id]",
#          "click row → /x/[id]"
_ROW_CLICK_RE = re.compile(
    r"(?:row[- ]?click(?:ing)?|click(?:ing)?\s+(?:a\s+)?row)\s*"
    r"(?:navigates?\s+to|→|->)\s*"
    r"(/[a-z0-9\[\]/_\-]+)",
    re.IGNORECASE,
)


def parse_row_click_target(prompt: str) -> str | None:
    """Return the row-click target route (e.g. ``/subscriptions/[id]``) or None."""
    if not prompt or not isinstance(prompt, str):
        return None
    m = _ROW_CLICK_RE.search(prompt)
    return m.group(1) if m else None


# ── Filter bar dimensions ─────────────────────────────────────────────
# Matches "Filter bar with (Date range, Plan, Status)" or without parens.
_FILTER_BAR_RE = re.compile(
    r"filter\s+bar\s+with\s*[:\(]?\s*([^)\.]+)",
    re.IGNORECASE,
)


def parse_filter_dimensions(prompt: str) -> list[str]:
    """Return the filter dimension names the user asked for on the primary
    breakdown table. Empty list on no match. Dimensions are surface-level
    only — turning them into FilterBar chip options is the composer's job.
    """
    if not prompt or not isinstance(prompt, str):
        return []
    m = _FILTER_BAR_RE.search(prompt)
    if not m:
        return []
    body = m.group(1)
    # Split by comma or slash. Each dimension may have parenthetical detail
    # after the name; keep the leading noun only.
    parts = re.split(r"[,\n]+", body)
    out: list[str] = []
    for p in parts:
        name = re.split(r"[\(\-–—:]", p, maxsplit=1)[0].strip().rstrip(".").strip()
        if name and name.lower() not in ("with", "and"):
            out.append(name)
    return out[:8]  # sanity cap


# ── Gauges ────────────────────────────────────────────────────────────
# Matches: "Net Revenue Retention Gauge, 0-150, target 110"
#          "NRR Gauge 0..150 target 110"
#          "Quarterly Target SplitArc — target $500K, actual bound to X"
_GAUGE_RE = re.compile(
    r"(?P<label>[A-Z][A-Za-z0-9 ]{2,60}?)\s+"
    r"(?P<kind>Gauge|SplitArc)"
    r"(?:[,\s]+(?P<min>[$\d][\d.,]*[KMB]?)\s*(?:-|to|\.\.)\s*(?P<max>[$\d][\d.,]*[KMB]?))?"
    r"(?:[,\s]+target\s+(?P<target>[$\d][\d.,]*[KMB]?))?",
    re.IGNORECASE,
)


def _parse_number(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip().lstrip("$").replace(",", "")
    mult = 1.0
    if s.endswith("K"): mult, s = 1_000, s[:-1]
    elif s.endswith("M"): mult, s = 1_000_000, s[:-1]
    elif s.endswith("B"): mult, s = 1_000_000_000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_gauges(prompt: str) -> list[dict[str, Any]]:
    """Return a list of Gauge/SplitArc widget hints. Each entry has:
    ``{label, kind, min?, max?, target?}`` — the composer wires the value
    binding from the plan's dataSources. Empty list on no match.
    """
    if not prompt or not isinstance(prompt, str):
        return []
    out: list[dict[str, Any]] = []
    for m in _GAUGE_RE.finditer(prompt):
        entry: dict[str, Any] = {
            "label": m.group("label").strip(),
            "kind": m.group("kind").lower(),
        }
        mn = _parse_number(m.group("min"))
        mx = _parse_number(m.group("max"))
        tg = _parse_number(m.group("target"))
        if mn is not None: entry["min"] = mn
        if mx is not None: entry["max"] = mx
        if tg is not None: entry["target"] = tg
        out.append(entry)
    return out


# ── Chart type per line ───────────────────────────────────────────────
# Matches inline chart-type hints: "MRR trend as line chart",
# "Revenue by Plan as bar chart", "Segmentation as donut chart".
_CHART_TYPE_RE = re.compile(
    r"([A-Z][A-Za-z0-9 ]{2,60}?)\s+as\s+(line|bar|area|pie|donut|funnel|radar)\s+chart",
    re.IGNORECASE,
)


def parse_chart_types(prompt: str) -> list[dict[str, str]]:
    """Return ``[{title, chartType}]`` for every "X as <kind> chart" line."""
    if not prompt or not isinstance(prompt, str):
        return []
    return [
        {"title": m.group(1).strip(), "chartType": m.group(2).lower()}
        for m in _CHART_TYPE_RE.finditer(prompt)
    ]


# ── One-shot ──────────────────────────────────────────────────────────

def parse_all_directives(prompt: str) -> dict[str, Any]:
    """Convenience: run every parser and return a ``plan.hints`` payload.

    Fields are omitted when the parser found nothing — the resulting dict
    can be merged into ``plan.hints`` with a simple ``.update()`` without
    clobbering unrelated hints.
    """
    if not prompt or not isinstance(prompt, str):
        return {}
    hints: dict[str, Any] = {}
    preset = parse_visual_preset(prompt)
    if preset:
        hints["visual_preset"] = preset
    vocab = detect_vocab_archetype(prompt)
    if vocab:
        hints["archetype_vocabulary"] = vocab
    row_click = parse_row_click_target(prompt)
    if row_click:
        hints["row_click_target"] = row_click
    filters = parse_filter_dimensions(prompt)
    if filters:
        hints["filter_dimensions"] = filters
    gauges = parse_gauges(prompt)
    if gauges:
        hints["gauges"] = gauges
    charts = parse_chart_types(prompt)
    if charts:
        hints["chart_types"] = charts
    return hints


def enrich_plan_with_directives(plan: dict) -> list[str]:
    """Mutate ``plan`` in place with parsed directives. Returns the list
    of hint keys added.

    Reads ``plan.description | plan.brief | plan.prompt`` as the prompt
    source. Merges parsed hints into ``plan.hints`` (preserving existing
    keys). Backfills ``plan.archetype`` from the vocab detector when the
    primary classifier didn't already stamp one. Lifts a detected preset
    into ``plan.brief_hints.visual_preset`` for the brief author to read.

    Never raises — safe to call unconditionally in the pipeline.
    """
    if not isinstance(plan, dict):
        return []
    prompt = (
        plan.get("description") or plan.get("brief") or plan.get("prompt") or ""
    )
    if not isinstance(prompt, str) or not prompt.strip():
        return []
    hints = parse_all_directives(prompt)
    if not hints:
        return []
    existing = plan.get("hints") if isinstance(plan.get("hints"), dict) else {}
    plan["hints"] = {**existing, **hints}
    if not (plan.get("archetype") or plan.get("app_archetype")):
        v = hints.get("archetype_vocabulary")
        if v:
            plan["archetype"] = v
    preset = hints.get("visual_preset")
    if preset:
        brief_hints = plan.setdefault("brief_hints", {})
        brief_hints.setdefault("visual_preset", preset)
    return list(hints.keys())


__all__ = [
    "parse_visual_preset",
    "detect_vocab_archetype",
    "parse_row_click_target",
    "parse_filter_dimensions",
    "parse_gauges",
    "parse_chart_types",
    "parse_all_directives",
    "enrich_plan_with_directives",
]
