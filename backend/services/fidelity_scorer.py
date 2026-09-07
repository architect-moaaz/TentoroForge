# backend/services/fidelity_scorer.py
"""Vision-grounded fidelity scoring against curated references."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache
import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

_REF_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "reference_images"
_INDEX_PATH = _REF_ROOT / "index.json"

_MODEL = os.getenv("FIDELITY_SCORER_MODEL", "claude-sonnet-4-6")
_MAX_TOKENS = 1024


@dataclass
class FidelityScore:
    score_0_to_10: float
    color_match_score: int
    layout_score: int
    density_score: int
    polish_score: int
    qualitative_notes: str
    # Routable defects, already filtered to the known taxonomy by
    # services.visual_findings.parse_findings. Empty when the model named
    # nothing actionable — which is the common case on a good page, and is
    # NOT the same as a low score.
    findings: list = field(default_factory=list)


@lru_cache(maxsize=1)
def _load_index() -> dict:
    if not _INDEX_PATH.exists():
        return {"domains": {}}
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


# Index keys that carry usable references. ``fitness`` is a key in the
# index but has an EMPTY page_types map, so resolving to it is
# indistinguishable from not resolving at all — it is excluded here so a
# fallback can never land somewhere that silently scores nothing.
_USABLE_DOMAINS = ("saas", "healthcare", "ecommerce", "recipe", "admin")

# Substring → index key, first match wins, so order encodes precedence.
# The planner emits industry labels ("E-Commerce & Retail", "CRM & Sales",
# "fintech"); the index keys on design families. This is the translation.
_DOMAIN_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ecommerce", "commerce", "retail", "shop", "store", "marketplace"), "ecommerce"),
    (("health", "clinic", "patient", "medical", "care", "pharma"), "healthcare"),
    (("recipe", "food", "restaurant", "kitchen", "menu", "hospitality",
      "cafe", "catering"), "recipe"),
    (("logistics", "supply", "warehouse", "inventory", "fleet", "field",
      "manufactur", "operations", "project", "hr", "people", "recruit",
      "fintech", "bank", "finance", "insur", "legal", "gov", "admin",
      "compliance", "asset", "maintenance"), "admin"),
    (("saas", "crm", "sales", "marketing", "analytics", "developer",
      "devtool", "platform", "productivity", "collaborat", "business",
      "general"), "saas"),
)


def normalize_domain(domain) -> str:
    """Map a planner domain label onto a usable reference-index key.

    ``reference_path_for`` is an exact dict lookup, and the planner never
    emits index keys — it emits industry prose. Without this every page
    logged "no reference for <domain>/<type>" and fidelity scoring was a
    no-op on every app ever generated.

    Always returns a key the index can actually serve; an unrecognised
    domain resolves to ``saas`` rather than to nothing, because a
    same-family comparison is informative and no comparison is not.
    """
    raw = str(domain or "").strip().lower()
    if raw in _USABLE_DOMAINS:
        return raw
    for needles, key in _DOMAIN_HINTS:
        if any(n in raw for n in needles):
            return key
    return "saas"


def reference_path_for(domain: str, page_type: str) -> Path | None:
    index = _load_index()
    domain_entry = index.get("domains", {}).get(domain)
    if not domain_entry:
        return None
    page_entry = domain_entry.get("page_types", {}).get(page_type)
    if not page_entry:
        return None
    p = _REF_ROOT / page_entry["file"]
    return p if p.exists() else None


_SCORING_PROMPT = """You are an expert UI designer scoring generated app screenshots against curated reference designs.

You will see two images:
1. REFERENCE: A polished, professionally designed app screenshot
2. GENERATED: A screenshot from our app generator

Score the GENERATED screenshot from 0-10 across these dimensions:
- color_match_score (0-10): How closely does the palette match the reference?
- layout_score (0-10): Hierarchy, spacing, alignment, density
- density_score (0-10): Information density vs. whitespace balance
- polish_score (0-10): Typography, shadows, rounded corners, micro-details

Then give an overall score_0_to_10 (can be decimal) and 1-2 sentences of qualitative_notes.

Then list any ACTIONABLE defects as `findings`. Use ONLY these types — each
one maps to a specific repair the pipeline can perform. If a problem does not
fit one of these, leave it out of findings and mention it in the notes instead:

- density_off       spacing/padding wrong for the content: cramped, or so airy
                    the page reads as empty
- bare_surface      a table, chart or list sits directly on the page background
                    with no card or panel containing it
- weak_hierarchy    nothing establishes what matters first; heading, primary
                    action and supporting content all read at the same weight
- flat_composition  every section is the same shape stacked vertically, with no
                    variation in rhythm or emphasis
- palette_mismatch  the colours are materially different from the reference
- type_scale_off    type sizes/weights don't form a usable scale

Only report a finding you can point at in the GENERATED image. An empty
findings array is a valid, common answer — do not invent problems to fill it.

Return ONLY a JSON object with exactly these keys:
{
  "score_0_to_10": <float>,
  "color_match_score": <int>,
  "layout_score": <int>,
  "density_score": <int>,
  "polish_score": <int>,
  "qualitative_notes": "<string>",
  "findings": [{"type": "<one of the types above>", "detail": "<what you see>"}]
}

Do not include any other text — only the JSON.
"""


def _call_vision_model(reference_image: bytes, generated_image: bytes) -> str:
    """Send both images to Claude vision, return raw response text.

    Separated for test mocking. Uses the anthropic SDK directly (sync client),
    mirroring the pattern in services/vision_evaluator/evaluator.py but with
    the synchronous Anthropic client since scoring is called from sync contexts.
    """
    from services.llm_client import Anthropic  # LangGraph migration (LG-1)

    client = Anthropic()
    message = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(reference_image).decode("ascii"),
                    },
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(generated_image).decode("ascii"),
                    },
                },
                {"type": "text", "text": _SCORING_PROMPT},
            ],
        }],
    )
    parts = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


def score_against_reference(
    generated_screenshot: Path,
    domain: str,
    page_type: str,
    route: str | None = None,
) -> FidelityScore | None:
    """Score a generated screenshot against the curated reference.

    Returns None if no reference exists for the (domain, page_type) pair,
    or if the vision model returns malformed JSON. Errors are logged but
    not raised — scoring is advisory, must never fail generation.
    """
    ref_path = reference_path_for(domain, page_type)
    if ref_path is None:
        logger.info(
            "fidelity: no reference for %s/%s, skipping score", domain, page_type
        )
        return None

    try:
        ref_bytes = ref_path.read_bytes()
        gen_bytes = generated_screenshot.read_bytes()
        raw = _call_vision_model(ref_bytes, gen_bytes)
        data = json.loads(raw.strip())
        from services.visual_findings import parse_findings
        return FidelityScore(
            score_0_to_10=float(data["score_0_to_10"]),
            color_match_score=int(data["color_match_score"]),
            layout_score=int(data["layout_score"]),
            density_score=int(data["density_score"]),
            polish_score=int(data["polish_score"]),
            qualitative_notes=str(data["qualitative_notes"]),
            # Unknown types are dropped here, at the boundary, so nothing
            # downstream has to defend against an invented category.
            # Findings are repaired per ROUTE, so stamp the real one. Falls
            # back to page_type only when a caller has no route to give.
            findings=parse_findings(data, route=route or page_type),
        )
    except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        logger.warning("fidelity: scoring failed for %s/%s: %s", domain, page_type, e)
        return None
