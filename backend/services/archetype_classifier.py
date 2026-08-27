"""LLM archetype classifier + refiner.

Sits on top of the deterministic keyword detector (services.archetype_detector):

  detect_archetype()          — keyword-scored classifier. Cheap, offline, no LLM.
  classify_app_archetype()    — this file. Uses an LLM to (a) confirm or override
                                the keyword pick and (b) TAILOR the archetype's
                                default entities/features to the specific
                                description. A "digital art print scanner and
                                marketplace price checker" still matches
                                visual-product-search, but the LLM renames
                                Scan→ArtworkScan, Retailer→Marketplace, etc.
                                so the generated app matches the user's domain
                                vocabulary instead of a generic template.

The LLM call is best-effort. When ANTHROPIC_API_KEY is missing or the SDK
raises, the classifier falls back to the deterministic detector's pick with
no rename — same shape as before, just less domain-tailored. Callers get
back an ArchetypeMatch either way; they don't need to know which path ran.

Contract (JSON the LLM must emit; stricter parse than free-form):

    {
      "archetype":         "<one of the registered NAMEs or null>",
      "confidence":        <float 0..1>,
      "renames":           { "<default_name>": "<domain_name>", ... },
      "extra_entities":    [ { "name": ..., "kind": "event"|"entity"|... } ],
      "reason":            "<one short sentence>"
    }

Renames apply to entities, features (by verb), and workflows. Extra entities
are unioned into the spec after the archetype defaults are applied.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

from services.archetype_detector import detect_archetype
from services.archetypes import all_archetypes, get_archetype

logger = logging.getLogger(__name__)


@dataclass
class ArchetypeMatch:
    archetype: str | None
    confidence: float = 0.0
    renames: dict[str, str] = field(default_factory=dict)
    extra_entities: list[dict] = field(default_factory=list)
    reason: str = ""
    source: str = "deterministic"  # "deterministic" | "llm" | "llm-fallback"

    def to_dict(self) -> dict:
        return asdict(self)


def _list_archetypes_for_prompt() -> list[dict]:
    """Compact metadata about every registered archetype — used as context
    the LLM ranks against. Cheap and stable per session."""
    out = []
    for mod in all_archetypes():
        out.append({
            "name": getattr(mod, "NAME", ""),
            "summary": getattr(mod, "SUMMARY", ""),
            "keywords": list(getattr(mod, "KEYWORDS", []) or [])[:12],
            "default_entities": [
                e.get("name") for e in (getattr(mod, "DEFAULT_ENTITIES", []) or [])
            ],
        })
    return out


def _build_llm_prompt(description: str) -> str:
    """Prompt is intentionally boring + strict — we want reliable JSON, not
    creativity. Names below match the ArchetypeMatch fields exactly."""
    catalog = json.dumps(_list_archetypes_for_prompt(), indent=2)
    return (
        "You are classifying an app description against a closed catalog of "
        "archetypes and tailoring the archetype's defaults to the description's "
        "domain vocabulary.\n\n"
        "CATALOG:\n"
        f"{catalog}\n\n"
        "DESCRIPTION:\n"
        f"{description.strip()}\n\n"
        "TASK:\n"
        "1. Pick the single best-fit archetype NAME from the catalog, or null "
        "   if none fits.\n"
        "2. Confidence: 0.0 (no fit) to 1.0 (perfect fit).\n"
        "3. Renames: for each archetype default entity/workflow whose name "
        "   sounds generic in this specific domain, map it to a domain-fitting "
        "   name (e.g. Scan→ArtworkScan for an art scanner, Retailer→Marketplace "
        "   for a marketplace app). Keys are the archetype defaults; values are "
        "   the domain-specific names. Empty object if no renames needed.\n"
        "4. Extra entities: any additional entity the description implies "
        "   that isn't in the archetype's DEFAULT_ENTITIES. Each entry must be "
        '   an object {"name": "<PascalCase>", "kind": "event"|"entity"|'
        '"role"|"external"|"derived"}.\n'
        "5. Reason: one short sentence explaining your archetype pick.\n\n"
        "OUTPUT: pure JSON matching this schema, no prose, no code fences:\n"
        "{"
        '"archetype": string|null, '
        '"confidence": number, '
        '"renames": object, '
        '"extra_entities": array, '
        '"reason": string'
        "}"
    )


async def _call_llm(description: str) -> dict | None:
    """Return parsed JSON dict from the LLM, or None on any failure.

    Uses the anthropic SDK directly (small, targeted, no dependency on
    the platform's Smith orchestrator). Returns None when the SDK isn't
    installed OR the key isn't set OR the response isn't valid JSON;
    callers fall back to the deterministic detector.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        # Lazy import so tests that don't exercise this path don't need the
        # SDK installed. anthropic is already a dep on the backend but let's
        # be defensive.
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    except Exception:
        return None
    try:
        client = llm_client.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=os.getenv("FORGE_ARCHETYPE_MODEL", "claude-opus-4-5-20250929"),
            max_tokens=1024,
            temperature=0.0,
            messages=[{"role": "user", "content": _build_llm_prompt(description)}],
        )
        # Response content is a list of blocks; concatenate text blocks.
        text = "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", "") == "text"
        ).strip()
        if not text:
            return None
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[archetype-classifier] LLM call failed: %s", exc)
        return None


def _validate_llm_result(data: dict) -> ArchetypeMatch | None:
    """Enforce the schema. Reject archetypes not in the catalog so an LLM
    hallucination can't inject a bogus archetype name downstream."""
    if not isinstance(data, dict):
        return None
    name = data.get("archetype")
    if name is not None and get_archetype(str(name)) is None:
        # Archetype the LLM invented — reject to freeform.
        name = None
    confidence = float(data.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    renames = data.get("renames") or {}
    if not isinstance(renames, dict):
        renames = {}
    # Filter renames: keys + values must be strings.
    renames = {
        str(k): str(v) for k, v in renames.items()
        if isinstance(k, str) and isinstance(v, str) and v.strip()
    }
    extras = data.get("extra_entities") or []
    clean_extras: list[dict] = []
    if isinstance(extras, list):
        for e in extras:
            if not isinstance(e, dict):
                continue
            n = e.get("name")
            k = e.get("kind")
            if isinstance(n, str) and isinstance(k, str) and k in {
                "event", "entity", "role", "external", "derived"
            }:
                clean_extras.append({"name": n, "kind": k})
    reason = str(data.get("reason") or "")[:280]
    return ArchetypeMatch(
        archetype=name,
        confidence=confidence,
        renames=renames,
        extra_entities=clean_extras,
        reason=reason,
        source="llm",
    )


async def classify_app_archetype(description: str) -> ArchetypeMatch:
    """LLM-refined archetype classification.

    Flow:
      1. Deterministic detector picks a base archetype (fast, offline).
      2. If ANTHROPIC_API_KEY is set, ask the LLM to (a) confirm/override
         the pick and (b) rename defaults to the domain. Cross-check the
         LLM's archetype against the catalog — invented names → None.
      3. If the LLM path fails or is disabled, return the deterministic
         pick with no renames.

    Return value is safe to persist to contracts/archetype.json. Callers
    can pass `.archetype` + `.renames` into apply_archetype_to_spec.
    """
    if not isinstance(description, str) or not description.strip():
        return ArchetypeMatch(archetype=None, confidence=0.0, reason="empty description")

    # Deterministic pick — always the baseline. This is what nothing-goes-wrong
    # looks like: LLM off or fails, we still get a coherent archetype.
    det_name = detect_archetype(description)
    baseline = ArchetypeMatch(
        archetype=det_name,
        confidence=0.7 if det_name else 0.0,
        renames={},
        extra_entities=[],
        reason=f"keyword classifier: {det_name or 'no match'}",
        source="deterministic",
    )

    llm_data = await _call_llm(description)
    if llm_data is None:
        return baseline
    refined = _validate_llm_result(llm_data)
    if refined is None:
        return baseline

    # LLM archetype = None but keyword classifier had a hit ⇒ trust the
    # keyword classifier. Prevents an LLM refusal from silently disabling
    # the archetype path.
    if refined.archetype is None and baseline.archetype is not None:
        refined.archetype = baseline.archetype
        refined.confidence = max(refined.confidence, baseline.confidence * 0.8)
        refined.reason = f"llm ambivalent; kept deterministic pick: {baseline.archetype}"
        refined.source = "llm-fallback"

    return refined
