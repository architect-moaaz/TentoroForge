"""LLM-based Figma layer-name → component classifier (Spec D Wave 5 skeleton).

Purpose
-------
``services/figma_name_classifier.py`` maps Figma layer names to
component types via 100+ hardcoded rules ("card" → Card, "hero" → Hero,
"input" → Input, "btn/button/cta" → Button, etc.). Great for
convention-following files, useless for real Figma projects that name
frames "Onboarding step 2" or "Payment summary tile".

This module is the LLM-classifier replacement. It reads:

    * the Figma layer name
    * the Figma node type (FRAME, TEXT, RECTANGLE, INSTANCE, …)
    * the immediate neighbour layer names for context
    * the target app's *component registry* — the ONLY component
      identifiers it may return

and emits a :class:`FigmaNameClassification` whose ``component`` is
guaranteed to appear in ``component_registry`` (or ``"Box"`` as the
safe fallback). Registry-safety property matches
``intent_classifier``: the LLM suggests, the closed vocabulary wins.

This module is ADDITIVE. Nothing calls it yet — it's scaffolding so a
future commit can flip the boundary behind a flag once the fixture
corpus is in place.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


# The safe default when the LLM misbehaves. ``Box`` is the neutral
# layout container in the component library and always exists.
_FALLBACK_COMPONENT = "Box"


# --------------------------------------------------------------------------- #
# Result shape                                                                #
# --------------------------------------------------------------------------- #

class FigmaNameClassification(BaseModel):
    """LLM-derived component pick for one Figma layer.

    ``component`` is guaranteed (post-validation) to be either a member
    of the supplied ``component_registry`` or the safe fallback
    ``"Box"``.
    """

    component: str = _FALLBACK_COMPONENT
    confidence: float = 0.0

    @field_validator("component")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        return v or _FALLBACK_COMPONENT

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        if v is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


# LLM boundary — tests inject a stub; production wires a real Claude call.
QueryFn = Callable[[str, str], str]


_SYSTEM_PROMPT = """You pick the best-fitting component identifier for a \
Figma layer, given the target app's REGISTERED component set. Emit \
STRICT JSON only — no prose, no code fences.

You are given:
  * layer_name         : the Figma layer's authored name.
  * node_type          : the Figma node type (FRAME / TEXT / RECTANGLE / \
INSTANCE / GROUP / VECTOR / …).
  * neighbors          : sibling layer names, for context.
  * component_registry : the CLOSED list of component identifiers that \
exist in the target app. You may ONLY pick from this list. If nothing \
fits, return "Box".

Output JSON shape:
  {
    "component":  "<one identifier from component_registry, OR 'Box'>",
    "confidence": 0.0-1.0
  }

STRICT rules:
  * ``component`` MUST be verbatim from ``component_registry``. Never \
invent a component identifier. If the registry is empty or nothing is \
a plausible match, return "Box".
  * Prefer more specific components ("StatCard") over general ones \
("Card") when both fit and both are in the registry.
  * Use node_type as a strong hint: TEXT → text/heading/label, \
RECTANGLE → shape/divider, FRAME → container/section/card, INSTANCE → \
whatever the instance's name suggests.

Confidence rubric:
  * 0.9+   : layer_name and node_type both point at the pick
  * 0.7-0.9: strong match on one signal, weak on the other
  * 0.5-0.7: plausible but not certain
  * < 0.5  : return "Box" instead

Do not narrate. Emit ONE JSON object. No code fences."""


def _default_query_fn(system_prompt: str, user_prompt: str) -> str:
    """Real LLM call — kept minimal so tests can stub cleanly."""
    try:
        from services.llm_edit import _default_llm_query  # type: ignore
        return _default_llm_query(system_prompt, user_prompt)  # type: ignore[misc]
    except Exception:
        logger.exception("classify_figma_name_llm: default LLM query failed")
        return ""


def classify_figma_name_llm(
    layer_name: str,
    *,
    node_type: str = "",
    neighbors: Optional[list[str]] = None,
    component_registry: Optional[list[str]] = None,
    query_fn: Optional[QueryFn] = None,
) -> FigmaNameClassification:
    """Classify a Figma layer name into a registered component.

    Args:
        layer_name: The Figma layer's ``name``.
        node_type: The Figma node type (FRAME, TEXT, …). Empty string
            when unknown.
        neighbors: Sibling layer names (short list) for context.
        component_registry: The closed list of component identifiers
            that exist in the target app. ``None`` or ``[]`` → always
            returns the safe ``"Box"`` fallback.
        query_fn: LLM boundary — tests inject; ``None`` uses the real
            SDK call via :func:`_default_query_fn`.

    Returns:
        A :class:`FigmaNameClassification`. On any failure (malformed
        JSON, LLM raised, component not in registry) returns
        ``FigmaNameClassification(component="Box", confidence=0.0)`` —
        never raises.
    """
    q = query_fn or _default_query_fn
    registry = list(component_registry or [])
    neighbor_list = list(neighbors or [])

    # Fast path: empty registry means we can't pick anything real.
    if not registry:
        return FigmaNameClassification(component=_FALLBACK_COMPONENT, confidence=0.0)

    user_prompt = "\n\n".join([
        f"layer_name:\n{layer_name}",
        f"node_type:\n{node_type or 'UNKNOWN'}",
        "neighbors:\n" + json.dumps(neighbor_list, ensure_ascii=False),
        "component_registry:\n" + json.dumps(registry, ensure_ascii=False),
    ])

    try:
        raw = q(_SYSTEM_PROMPT, user_prompt) or ""
    except Exception:
        logger.exception("classify_figma_name_llm: LLM boundary raised")
        raw = ""

    parsed = _extract_json(raw)
    if parsed is None:
        return FigmaNameClassification(component=_FALLBACK_COMPONENT, confidence=0.0)

    try:
        pick = FigmaNameClassification(**parsed)
    except ValidationError:
        return FigmaNameClassification(component=_FALLBACK_COMPONENT, confidence=0.0)

    # Registry-safety: the pick MUST be in the closed vocabulary. "Box"
    # is always accepted as the acknowledged fallback even when the
    # registry doesn't include it — the caller's downstream code
    # handles the fallback marker.
    if pick.component == _FALLBACK_COMPONENT:
        return pick
    if pick.component in registry:
        return pick
    return FigmaNameClassification(component=_FALLBACK_COMPONENT, confidence=0.0)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _extract_json(text: str) -> Optional[dict]:
    """Extract the first ``{...}`` object from a string. Handles pure
    JSON, code-fence wrappers, and leading/trailing prose. Returns None
    on any failure."""
    if not text or not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        try:
            body = stripped.split("\n", 1)[1]
            body = body.rsplit("```", 1)[0]
            stripped = body.strip()
        except Exception:
            pass
    try:
        v = json.loads(stripped)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    start = stripped.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(stripped)):
        c = stripped[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    v = json.loads(stripped[start:i + 1])
                    return v if isinstance(v, dict) else None
                except Exception:
                    return None
    return None
