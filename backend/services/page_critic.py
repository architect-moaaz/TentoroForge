"""Page critic — Sprint 3 of the Forge Great Again plan.

After the Designer emits a page schema (Sprint 1's Design Context Pack
primed the turn; Sprint 2 marked the output as designer-authored), a
critic reviews the schema through a designer's eyes and returns a
structured verdict:

    {
      "score":  int,          # 1-10, 7+ = ships
      "passes": bool,
      "gaps":   [{"severity": "high"|"medium"|"low", "note": str}, …],
      "prose":  str,          # 1-3 sentences of overall reaction
    }

Two use cases:

1. **Observability** (Sprint 3 slice 1, shipping now) — every
   designer-authored page's critique is persisted to
   ``<output>/reports/page-critic/<slug>.json``. We learn where the
   Designer falls short WITHOUT changing generation. This is the
   read-only path — enabled by ``FORGE_PAGE_CRITIC=1``.

2. **REVISE loop** (opt-in, ``FORGE_PAGE_CRITIC_REVISE=1``) — when the
   critic returns any HIGH-severity gap, we re-invoke the Designer
   with the gaps prepended as a "REVISE:" block. One round only, to
   cap latency. Off by default so we can watch quality without doubling
   turn time.

Text-only in this slice. Sprint 8 adds vision (screenshot the rendered
page and score it) via the same interface — this module's ``critique``
function will accept an optional ``screenshot_bytes`` param when that
lands, no consumer changes needed.

Design philosophy: the critic is prompted as a design director doing an
art review, NOT a schema validator. The base ``schema_prompt`` and
downstream guards already handle technical correctness; the critic
looks at hierarchy, brand echo, semantic color, empty states, signature
moves, copy quality — the same dimensions the design mandate in the
Design Context Pack listed. Symmetry between the mandate (what the
Designer must do) and the critic (what we verify) is deliberate.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

_FLAG = "FORGE_PAGE_CRITIC"
_REVISE_FLAG = "FORGE_PAGE_CRITIC_REVISE"
_VISION_FLAG = "FORGE_PAGE_CRITIC_VISION"


# ── Public API ──────────────────────────────────────────────────────────

def page_critic_enabled() -> bool:
    """Read-only critique + persistence path. Default off; opt in with
    ``FORGE_PAGE_CRITIC=1``. Turning this on adds one LLM call per
    designer-authored page (Sonnet, <8k tokens); no schema rewrite."""
    return os.getenv(_FLAG, "0").strip() == "1"


def revise_loop_enabled() -> bool:
    """Add one Designer REVISE turn when the critic flags HIGH-severity
    gaps. Default off (doubles latency for gated pages). Opt in with
    ``FORGE_PAGE_CRITIC_REVISE=1`` once critique quality is proven."""
    return os.getenv(_REVISE_FLAG, "0").strip() == "1"


def vision_enabled() -> bool:
    """Sprint 8: use a vision-capable model + screenshot when critiquing.
    Default off — adds a Playwright screenshot round-trip + vision model
    call per page. Off means the text-only critic path runs (Sprint 3).
    Opt in with ``FORGE_PAGE_CRITIC_VISION=1``."""
    return os.getenv(_VISION_FLAG, "0").strip() == "1"


CritiqueFn = Callable[[str], Awaitable[str]]


async def critique_page_schema(
    *,
    schema: dict,
    page_purpose_prose: str,
    brief_prose: str = "",
    brief_primary_hex: str | None = None,
    brief_signature_moves: list[str] | None = None,
    screenshot_bytes: bytes | None = None,
    query_fn: Optional[CritiqueFn] = None,
) -> dict:
    """Ask the critic to review the schema. Returns a structured dict.

    Args:
        schema: The page schema (dict) the Designer emitted.
        page_purpose_prose: The synthesized page-purpose text from the
            Design Context Pack (or planner-authored ``page.purpose``
            once Sprint 4 promotes it). Frames what "good" means for
            this specific page.
        brief_prose: Optional design-brief prose (from
            ``brief_to_prompt``). When present the critic checks brand
            echo + signature-move usage against the brief's committed
            palette + moves.
        brief_primary_hex: Sprint 7 — the brief's primary color as
            ``#RRGGBB``. When present, the deterministic brand-echo
            detector runs alongside the LLM critic and appends a gap
            when the color echoes < N places (default 3).
        brief_signature_moves: Sprint 6 — the brief's committed signature
            move kinds. When non-empty, the deterministic signature-moves
            detector runs and appends a gap when < N committed moves
            appear on the page (default 2).
        screenshot_bytes: Sprint 8 — optional PNG bytes of the rendered
            page. When present + vision_enabled(), the critic sees the
            actual pixels alongside the schema.
        query_fn: Injection seam for tests. Signature ``(prompt) -> text``.
            When None uses the real Anthropic SDK boundary. Vision mode
            uses ``_default_vision_query`` unless a query_fn overrides.

    Returns:
        ``{"score": int, "passes": bool, "gaps": [...], "prose": str}``.
        Deterministic detector gaps (Sprint 6/7) are MERGED into the
        LLM's gaps list — so the caller sees one unified verdict.
        On any failure (LLM error, malformed JSON) returns a "no verdict"
        shape ``{"score": 0, "passes": True, "gaps": [], "prose": ...}``
        so the caller treats the schema as passing (better to ship a
        possibly-imperfect page than to block on critic infrastructure).
    """
    prompt = build_critic_prompt(
        schema=schema, page_purpose_prose=page_purpose_prose,
        brief_prose=brief_prose,
    )
    # ── LLM call ───────────────────────────────────────────────────────
    try:
        if query_fn is not None:
            text = await query_fn(prompt)
        elif screenshot_bytes is not None and vision_enabled():
            text = await _default_vision_query(prompt, screenshot_bytes)
        else:
            text = await _default_critic_query(prompt)
    except Exception:  # noqa: BLE001 — critic must never break the pipeline
        logger.exception("[page-critic] LLM call failed")
        return _no_verdict("critic unavailable (LLM error)")

    result = parse_critique(text)
    if result is None:
        result = _no_verdict("critic unavailable (unparseable response)")

    # ── Deterministic detectors (Sprint 6 + 7) ─────────────────────────
    # Run AFTER the LLM so their gaps append to whatever the model
    # produced. Detector failures are swallowed — they must never break
    # the critic, same fail-open contract as the LLM path.
    _merge_detector_gaps(
        result,
        schema=schema,
        primary_hex=brief_primary_hex,
        committed_moves=brief_signature_moves,
    )
    return result


def _merge_detector_gaps(
    critique: dict,
    *,
    schema: dict,
    primary_hex: str | None,
    committed_moves: list[str] | None,
) -> None:
    """Run the Sprint 6 + 7 deterministic detectors and append their
    findings as gaps on the critique dict (in place). Best-effort — any
    exception is logged and the critique is returned as-is.
    """
    try:
        from services.brand_echo_detector import (
            detect_brand_echo, as_critic_gap as brand_gap,
        )
        brand = detect_brand_echo(schema, primary_hex)
        g = brand_gap(brand)
        if g:
            critique.setdefault("gaps", []).append(g)
        critique.setdefault("_detectors", {})["brand_echo"] = brand
    except Exception:  # noqa: BLE001
        logger.exception("[page-critic] brand_echo detector failed")

    # Skip the signature-moves detector when the caller didn't pass any
    # brief context (committed_moves is None). Callers who want the
    # registered-defaults fallback can pass an empty list explicitly.
    if committed_moves is not None:
        try:
            from services.signature_moves_detector import (
                detect_signature_moves, as_critic_gap as sig_gap,
            )
            sig = detect_signature_moves(schema, committed_moves)
            g = sig_gap(sig)
            if g:
                critique.setdefault("gaps", []).append(g)
            critique.setdefault("_detectors", {})["signature_moves"] = sig
        except Exception:  # noqa: BLE001
            logger.exception("[page-critic] signature_moves detector failed")

    # Recompute passes when a HIGH-severity gap was appended — the
    # deterministic detectors override an LLM "passes: true" verdict
    # when they found a hard failure.
    if any(str(g.get("severity") or "").lower() == "high"
           for g in (critique.get("gaps") or []) if isinstance(g, dict)):
        critique["passes"] = False


def persist_critique(
    output_dir: str, slug: str, critique: dict,
) -> Optional[Path]:
    """Write the critique to ``<output>/reports/page-critic/<slug>.json``
    for observability. Never raises — best-effort. Returns the path
    written or None on failure."""
    try:
        reports = Path(output_dir) / "reports" / "page-critic"
        path = reports / f"{slug}.json"
        # Nested slugs (e.g. patients/[id]/timeline) → mkdir the FULL
        # parent, not just the reports root, or write_text raises ENOENT.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(critique, indent=2), encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        logger.exception(
            "[page-critic] could not persist critique for %s", slug,
        )
        return None


def build_critic_prompt(
    *,
    schema: dict,
    page_purpose_prose: str,
    brief_prose: str,
) -> str:
    """Assemble the critic's prompt. Split out so tests can inspect the
    exact shape and prompt-engineer iteratively without a live LLM."""
    schema_json = json.dumps(schema, indent=2)
    # Trim huge schemas — the critic doesn't need every last node to
    # spot design gaps. 20k chars ≈ ~5k tokens, comfortably under Sonnet's
    # per-call budget with the rest of the prompt.
    if len(schema_json) > 20_000:
        schema_json = schema_json[:20_000] + "\n... (schema truncated for brevity)"

    brief_block = ""
    if brief_prose and brief_prose.strip():
        brief_block = (
            "\n\nThis app's DESIGN BRIEF (what the design MUST honor):\n"
            f"{brief_prose.strip()}\n"
        )

    return f"""You are a design director doing an art review of a UI page authored
by a junior designer. You have ONE screenshot's worth of attention — read
the schema and score it as a designed product, not a data dump.

The page's PURPOSE:
{page_purpose_prose.strip()}
{brief_block}
Score the page 1-10 across these dimensions (weight equally):

1. HERO — is there ONE thing that reads first? Does it earn the room?
2. READING ORDER — KPI row up top, primary content next, supporting
   rail on the side, richer lists at the bottom. Not inverted.
3. BRAND ECHO — the brief's primary color must appear in ≥3 semantic
   places (KPI icon tiles, chart accents, CTAs, active states, pills).
4. SEMANTIC COLOR — status uses green/amber/red meaningfully. Not
   everything grey.
5. COPY — authored eyebrows, sub-context, actionable CTAs. No raw
   column names ("Maintenance_request"), no naive plurals ("Propertys").
6. CARDS — cards-or-nothing consistency. Not some widgets in cards
   and others floating.
7. EMPTY STATES — every widget that could be empty has an authored
   empty state (icon/illustration + message + CTA). No dashed rectangles.
8. SIGNATURE MOVES — the brief's committed moves are applied ≥2
   places on this page. Or, if the brief lists none, the page has SOME
   visual signature moment (mono eyebrow, gradient chart, colored tile).

Then decide: "passes" = True when score >= 7 AND no HIGH-severity gap.

Return ONLY a single valid JSON object, no prose outside:

{{
  "score": <1-10 int>,
  "passes": <bool>,
  "gaps": [
    {{"severity": "high"|"medium"|"low", "note": "<one sentence>"}}
  ],
  "prose": "<1-3 sentences of overall design director reaction>"
}}

Be honest. A widget-inventory dashboard with no hero, no brand color, and
empty dashed boxes scores 3-4 and does NOT pass. A composed dashboard
with a hero chart, KPI row, semantic-colored status pills, and authored
empty states scores 8-9 and passes.

--- PAGE SCHEMA ---
{schema_json}
"""


def parse_critique(text: str) -> Optional[dict]:
    """Extract the JSON object from the critic's reply. Returns None on
    unparseable input. Best-effort — tries the whole string first, then
    the first ``{...}`` block if the model wrapped its answer in prose."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return _validate_critique_shape(json.loads(text))
    except Exception:  # noqa: BLE001
        pass
    # Fall back to first braced block.
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return _validate_critique_shape(json.loads(m.group(0)))
    except Exception:  # noqa: BLE001
        return None


# ── Internals ───────────────────────────────────────────────────────────

def _validate_critique_shape(raw: Any) -> Optional[dict]:
    """Coerce and defensively-shape a critic reply. Returns None if the
    reply is unusable; otherwise a dict with the four required keys."""
    if not isinstance(raw, dict):
        return None
    score = raw.get("score")
    try:
        score_i = int(score)
    except (TypeError, ValueError):
        return None
    score_i = max(1, min(10, score_i))
    passes = bool(raw.get("passes", score_i >= 7))
    gaps_raw = raw.get("gaps") or []
    gaps: list[dict] = []
    if isinstance(gaps_raw, list):
        for g in gaps_raw:
            if not isinstance(g, dict):
                continue
            sev = str(g.get("severity") or "medium").lower().strip()
            if sev not in ("high", "medium", "low"):
                sev = "medium"
            note = str(g.get("note") or "").strip()
            if note:
                gaps.append({"severity": sev, "note": note})
    prose = str(raw.get("prose") or "").strip()
    return {
        "score":  score_i,
        "passes": passes,
        "gaps":   gaps,
        "prose":  prose,
    }


def _no_verdict(reason: str) -> dict:
    """A "critic unavailable" verdict. score=0, passes=True (fail-open —
    don't block generation on critic infrastructure), gaps=[] and prose
    carries the reason for the observability log."""
    return {"score": 0, "passes": True, "gaps": [], "prose": reason}


async def _default_critic_query(prompt: str) -> str:
    """Real LLM boundary — Anthropic SDK. Kept minimal so tests can
    swap it via the ``query_fn`` injection param."""
    from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system="You are a design director. Output ONLY a single JSON object.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


async def _default_vision_query(prompt: str, screenshot_bytes: bytes) -> str:
    """Sprint 8: multimodal boundary — text prompt + PNG screenshot.

    Sends an image block first so the model literally SEES the page as
    the user would. Falls back gracefully in text-only mode when the
    screenshot bytes are empty or the vision-capable model rejects the
    request (caller handles the exception via fail-open path)."""
    if not screenshot_bytes:
        # Missing bytes → don't send an empty image block; fall back to
        # text-only.
        return await _default_critic_query(prompt)
    import base64
    from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)
    b64 = base64.b64encode(screenshot_bytes).decode("ascii")
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=(
            "You are a design director looking at a screenshot of a UI page "
            "AND its authoring schema. Score the design as a user would see "
            "it. Output ONLY a single JSON object."
        ),
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            }},
            {"type": "text", "text": prompt},
        ]}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def has_high_severity_gap(critique: dict) -> bool:
    """True when the critic flagged at least one HIGH-severity issue —
    triggers the REVISE round when enabled."""
    if not isinstance(critique, dict):
        return False
    for g in critique.get("gaps") or []:
        if isinstance(g, dict) and str(g.get("severity") or "").lower() == "high":
            return True
    return False


def format_gaps_for_revise(critique: dict) -> str:
    """Render the critic's gaps as a designer-facing "REVISE:" block that
    the Designer's next turn prepends. High-severity gaps land first."""
    gaps = critique.get("gaps") if isinstance(critique, dict) else []
    if not gaps:
        return ""
    order = {"high": 0, "medium": 1, "low": 2}
    sorted_gaps = sorted(gaps, key=lambda g: order.get(g.get("severity", "medium"), 1))
    lines = ["<revise-notes>",
             "The design director reviewed your first pass and flagged these",
             "issues. Rewrite the page schema to fix them all. Keep the same",
             "page purpose; fix the design.",
             ""]
    for g in sorted_gaps:
        sev = str(g.get("severity") or "medium").upper()
        note = str(g.get("note") or "").strip()
        lines.append(f"  [{sev}] {note}")
    lines.append("</revise-notes>")
    return "\n".join(lines)


__all__ = [
    "page_critic_enabled",
    "revise_loop_enabled",
    "vision_enabled",
    "critique_page_schema",
    "persist_critique",
    "build_critic_prompt",
    "parse_critique",
    "has_high_severity_gap",
    "format_gaps_for_revise",
]
