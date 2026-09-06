"""LLM-based Figma action classifier (Spec D Wave 5 skeleton).

Purpose
-------
Today ``services/figma_action_classifier.py`` maps Figma layer labels to
actions via keyword rules ("submit"/"save" → workflow, "back"/"cancel" →
navigate, etc.). Fine for demo names, breaks on real Figma files where
buttons are labelled "Kick off the flow" or the domain word for
"invoice" in a language the keyword table doesn't know.

This module is the LLM-classifier replacement. It reads:

    * the button/CTA label as authored in Figma
    * the surrounding text (parent frame name, nearby labels)
    * the target app's *registry* of REAL routes + REAL workflow names

and emits a structured :class:`FigmaActionBinding` whose ``target`` is
guaranteed to appear in one of the two supplied lists (or is ``None``
for ``kind="none"`` / ``kind="external"`` with a URL). The LLM never
picks a target that isn't in the registry — same registry-safety
discipline as ``intent_classifier.classify_intent`` where tool names
are derived, not chosen.

This module is ADDITIVE. Nothing calls it yet — it's scaffolding so a
future commit can flip the boundary behind a flag once we have a
Figma-fixture corpus (3+ real Figma projects with varied naming) to
validate the LLM against the keyword baseline.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result shape                                                                #
# --------------------------------------------------------------------------- #

class FigmaActionBinding(BaseModel):
    """LLM-derived binding for a single Figma CTA/button.

    ``kind`` is one of:
      * ``navigate``  — route in the app (``target`` = a real route path
                        from the supplied ``available_routes``).
      * ``workflow``  — a workflow invocation (``target`` = a real name
                        from ``available_workflows``).
      * ``external``  — a full URL to something outside the app
                        (``target`` = the URL; not registry-checked).
      * ``none``      — the LLM couldn't confidently bind; caller
                        should skip / fall back to the keyword path.

    ``target`` is always ``None`` when ``kind="none"``.
    """

    kind: Literal["navigate", "workflow", "external", "none"]
    target: Optional[str] = None
    confidence: float = 0.0

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


_SYSTEM_PROMPT = """You bind a Figma layer label (usually a button or \
CTA) to ONE of four actions inside a target no-code app. Emit STRICT \
JSON only — no prose, no code fences.

You are given:
  * The Figma layer label as authored by the designer.
  * Optional surrounding text (parent frame name, sibling labels) for context.
  * available_routes:    the ONLY route paths the app has (e.g. "/candidates").
  * available_workflows: the ONLY workflow names the app has (e.g. "submit_application").

Output JSON shape:
  {
    "kind":       "navigate" | "workflow" | "external" | "none",
    "target":     "<route path OR workflow name OR full URL OR null>",
    "confidence": 0.0-1.0
  }

STRICT rules:
  * If kind == "navigate", target MUST be one of the strings in \
available_routes, verbatim. Never invent a route.
  * If kind == "workflow", target MUST be the id of one entry in \
available_workflows — the part before " — " — or the entry verbatim. The \
name and trigger after it say what the workflow does; match the label to \
them. Never invent a workflow.
  * If kind == "external", target MUST be a full URL (http:// or https://).
  * If nothing in the registry is a plausible match, or the label is \
ambiguous, return {"kind":"none","target":null,"confidence":0.0}.
  * When available_routes or available_workflows is empty, you may still \
return "none" or "external"; you MUST NOT invent a target for the empty side.

Confidence rubric:
  * 0.9+   : exact/near-exact label→registry match ("Save" ↔ "save_application")
  * 0.7-0.9: strong semantic match, minor rewording
  * 0.5-0.7: plausible but not certain — caller may want to double-check
  * < 0.5  : return "none" instead

Do not narrate. Emit ONE JSON object. No code fences."""


#: The shape `classify_figma_action_llm` parses back. Declared so the reply is
#: machine-checked rather than hoped for — the parser's fallback for anything
#: it cannot read is `kind="none"`, which is indistinguishable from a genuine
#: "no action" and is exactly how the broken import stayed invisible.
_REPLY_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string",
                 "enum": ["navigate", "workflow", "external", "none"]},
        "target": {"type": "string"},
        "confidence": {"type": "number"},
    },
}


def _default_query_fn(system_prompt: str, user_prompt: str) -> str:
    """Real LLM call — kept minimal so tests can stub cleanly.

    Uses the same shared boundary as intent_classifier / smart_edit_page
    so we don't fork provider handling. Falls back to an empty string on
    any error; the caller treats that as "garbage → none".
    """
    # THIS IMPORTED A FUNCTION THAT NO LONGER EXISTS.
    #
    # It was `from services.llm_edit import _default_llm_query`, removed when
    # that module made every caller pass its own boundary. The ImportError
    # landed in the `except` below and was logged, and the CALLER swallows a
    # failure as "garbage → none" — so the registry-safe classifier had been
    # silently dead, and every Figma button fell through to keyword matching.
    #
    # The cost was invisible until a design with real buttons arrived: keyword
    # matching either invented a workflow the app does not define, or declared
    # none, and the Blueprint validator refuses BOTH. A 15-screen design lost
    # every page to a dangling import.
    #
    # Bound to the same client the rest of the pipeline uses, so timeouts,
    # retries and the model choice are not forked here.
    try:
        from services.blueprint.executors import AnthropicModel

        reply = AnthropicModel(max_tokens=1024)(
            system=system_prompt, user=user_prompt, schema=_REPLY_SCHEMA)
        return str(getattr(reply, "text", reply) or "")
    except Exception:
        logger.exception("classify_figma_action_llm: default LLM query failed")
        return ""


def classify_figma_action_llm(
    label: str,
    *,
    surrounding_text: str = "",
    available_routes: Optional[list[str]] = None,
    available_workflows: Optional[list[str]] = None,
    query_fn: Optional[QueryFn] = None,
) -> FigmaActionBinding:
    """Classify a Figma CTA label into a structured action binding.

    Args:
        label: The Figma layer's ``name`` (e.g. "Kick off the flow").
        surrounding_text: Optional parent frame name + sibling labels
            joined by newlines, to help disambiguate follow-ups.
        available_routes: The closed list of real route paths in the
            target app. ``None`` or ``[]`` → no route bindings possible.
        available_workflows: The closed list of real workflow names.
            ``None`` or ``[]`` → no workflow bindings possible.
        query_fn: LLM boundary — tests inject; ``None`` uses the real
            SDK call via :func:`_default_query_fn`.

    Returns:
        A :class:`FigmaActionBinding`. On any failure (malformed JSON,
        LLM raised, target not in registry, unknown kind) returns
        ``FigmaActionBinding(kind="none", target=None, confidence=0.0)``
        — never raises.
    """
    q = query_fn or _default_query_fn
    routes = list(available_routes or [])
    workflows = list(available_workflows or [])

    user_prompt_bits = [f"Label:\n{label}"]
    if surrounding_text:
        user_prompt_bits.append(f"Surrounding text:\n{surrounding_text}")
    user_prompt_bits.append(
        "available_routes:\n" + json.dumps(routes, ensure_ascii=False)
    )
    user_prompt_bits.append(
        "available_workflows:\n" + json.dumps(workflows, ensure_ascii=False)
    )
    user_prompt = "\n\n".join(user_prompt_bits)

    try:
        raw = q(_SYSTEM_PROMPT, user_prompt) or ""
    except Exception:
        logger.exception("classify_figma_action_llm: LLM boundary raised")
        raw = ""

    parsed = _extract_json(raw)
    if parsed is None:
        return FigmaActionBinding(kind="none", target=None, confidence=0.0)

    try:
        binding = FigmaActionBinding(**parsed)
    except ValidationError:
        return FigmaActionBinding(kind="none", target=None, confidence=0.0)

    # Registry-safety: enforce that the LLM's chosen target actually
    # exists in the closed vocabulary supplied by the caller.
    return _enforce_registry_safety(binding, routes, workflows)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _enforce_registry_safety(
    binding: FigmaActionBinding,
    routes: list[str],
    workflows: list[str],
) -> FigmaActionBinding:
    """Downgrade to ``kind="none"`` when the LLM's target isn't in the
    supplied registry. Same discipline as intent_classifier's tool
    subset lookup: the LLM can suggest, but the closed vocabulary wins.
    """
    if binding.kind == "none":
        return FigmaActionBinding(kind="none", target=None, confidence=0.0)

    if binding.kind == "navigate":
        if not binding.target or binding.target not in routes:
            return FigmaActionBinding(kind="none", target=None, confidence=0.0)
        return binding

    if binding.kind == "workflow":
        # An entry may read "FLOW-009 — Refund Approval Decision: …"; the
        # model may answer with the entry or with the id. Either way the
        # binding's target is the id — the only spelling a page may carry.
        ids = {w.split(" — ")[0].strip(): w for w in workflows}
        target = (binding.target or "").strip()
        if target in workflows:
            target = target.split(" — ")[0].strip()
        if not target or target not in ids:
            return FigmaActionBinding(kind="none", target=None, confidence=0.0)
        return FigmaActionBinding(kind="workflow", target=target, confidence=binding.confidence)

    if binding.kind == "external":
        t = (binding.target or "").strip()
        if not (t.startswith("http://") or t.startswith("https://")):
            return FigmaActionBinding(kind="none", target=None, confidence=0.0)
        return binding

    # Unknown kind — pydantic Literal should have caught it, but defense in depth.
    return FigmaActionBinding(kind="none", target=None, confidence=0.0)


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
