"""Smith intent classifier + scoped tool subsets (Phase 0).

Purpose
-------
Every Smith turn today loads the same 39-tool catalog and lets the LLM
pick. That's expensive (long prompt) and lossy (wrong-tool picks like
"deploy the app" fabrications, 12-option nav punts).

Phase 0 shrinks the tool surface Smith sees on high-confidence intents
by running ONE deterministic classifier LLM call at ingress. Output is
a structured ``Intent`` naming the intent class, the domain, an
extracted target, and the *derived* tool subset the ReAct loop should
be allowed to use.

Contract
--------
::

    intent = classify_intent(user_message, chat_history_summary=..., ...)
    # Intent(intent="add_page", domain="page", target="Pricing",
    #        tools=["add_page", "list_pages", "read_page", ...],
    #        confidence=0.92)

Then `run_smith_agent(..., scoped_tools=intent.tools)` filters the
tool catalog it exposes to the LLM. See `agents/smith_agent.py` for
the wiring.

When to skip scoping
--------------------
``tools is None`` means "no scoping — use the full catalog". This is
returned when:

* the LLM's confidence < 0.5 (ambiguous ask — need full surface to explore)
* the ``intent`` is ``"unclear"`` (garbage output / unknown label)
* the JSON failed to parse (defense in depth)

That way a mis-classification degrades to today's behavior instead of
locking Smith into the wrong tool subset — which would be strictly
worse than the monolith.

The tool subsets themselves are the "highly-repeatable-narrow"
specialist path: an ``add_field`` intent gets 5 tools, not 39. Tight
catalog + same ReAct loop = specialist behavior with no multi-agent
tax.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# The intent enum + tool subsets                                              #
# --------------------------------------------------------------------------- #
#
# Add a new intent here → add the same key to TOOL_SUBSETS below. The unit
# test contract (`test_every_intent_has_a_subset_or_explicit_none`) will fail
# loudly if you forget one.

INTENTS: tuple[str, ...] = (
    "chat",            # greeting / thanks / meta question, no artifact touch
    "query",           # app-map / status question ("what pages do I have?")
    "add_field",       # add a form field or schema column
    "add_page",        # new page
    "add_workflow",    # new workflow
    "add_entity",      # new data model
    "add_component",   # add a component to an existing page
    "add_token",       # add a design token (color / typography)
    "edit_page",       # tweak existing page content / props
    "edit_workflow",   # tweak an existing workflow
    "edit_token",      # tweak an existing design token
    "remove",          # destructive — remove a page / component / entity
    "fix",             # diagnose + repair ("the button doesn't work")
    "deploy",          # publish / build the app
    "feature",         # multi-step feature ask ("add candidate messaging")
    "undo",            # revert last change
    "unclear",         # low confidence or unknown — fall back to full catalog
)


# Every intent → the tool subset Smith is allowed to use when confidence
# is high enough. ``None`` means "no scoping — expose the full catalog".
#
# Every scoped subset MUST include ``answer`` + ``ask_user`` so Smith can
# always terminate the loop (either resolve or ask a clarifying question).
# ``understand_ask`` is included where a scope-check step is beneficial.
TOOL_SUBSETS: dict[str, Optional[list[str]]] = {
    # ---- Conversational / meta ------------------------------------------- #
    "chat": ["recall", "answer", "ask_user"],
    "query": [
        "recall", "list_pages", "list_entities", "list_workflows",
        "list_components", "read_page", "read_entity", "read_workflow",
        "grep_schemas", "find_resources", "find_component",
        "impact_analysis", "check_data_source", "read_column",
        "answer", "ask_user",
    ],

    # ---- Add family — tight specialists ---------------------------------- #
    "add_field": [
        "understand_ask", "read_page", "read_entity", "list_pages",
        "edit_page", "wire_form_to_workflow",
        "verify_promise", "answer", "ask_user",
    ],
    "add_page": [
        "understand_ask", "list_pages", "read_page", "list_entities",
        "add_page", "compose_route", "verify_promise", "answer", "ask_user",
    ],
    "add_workflow": [
        "understand_ask", "list_entities", "read_entity", "list_workflows",
        "add_workflow", "wire_form_to_workflow",
        "verify_promise", "answer", "ask_user",
    ],
    "add_entity": [
        "understand_ask", "list_entities", "read_entity",
        "add_entity", "add_role",  # role additions land here too
        "verify_promise", "answer", "ask_user",
    ],
    "add_component": [
        "understand_ask", "list_components", "list_pages", "read_page",
        "find_component", "edit_page", "add_widgets",
        "verify_promise", "answer", "ask_user",
    ],
    "add_token": [
        "understand_ask", "read_file", "edit_file",
        "verify_promise", "answer", "ask_user",
    ],

    # ---- Edit family ----------------------------------------------------- #
    "edit_page": [
        "understand_ask", "list_pages", "read_page", "list_components",
        "find_component", "edit_page", "restrict_page_to_role",
        # A screen that renders nothing is an edit ask in the user's words and
        # has no element to edit. Without these the intent scopes Smith to
        # tools that cannot answer it.
        "compose_route", "add_widgets",
        "verify_promise", "answer", "ask_user",
    ],
    "edit_workflow": [
        "understand_ask", "list_workflows", "read_workflow",
        "analyze_workflow_values", "edit_workflow",
        "verify_promise", "answer", "ask_user",
    ],
    "edit_token": [
        "understand_ask", "read_file", "edit_file", "grep_schemas",
        "verify_promise", "answer", "ask_user",
    ],

    # ---- Destructive ----------------------------------------------------- #
    "remove": [
        "understand_ask", "list_pages", "read_page", "impact_analysis",
        "remove_page", "remove_role", "edit_page", "edit_file",
        "verify_promise", "answer", "ask_user",
    ],

    # ---- Diagnostic ------------------------------------------------------ #
    "fix": [
        "understand_ask", "recall", "parse_error", "probe_logs",
        "probe_endpoint", "grep_schemas", "read_page", "read_workflow",
        "read_file", "check_data_source", "analyze_workflow_values",
        "impact_analysis",
        # Repair seams — cross-domain because a fix may touch any layer:
        "edit_page", "edit_workflow", "edit_file",
        "wire_form_to_workflow",
        "verify_promise", "answer", "ask_user",
    ],

    # ---- Terminal-shaped ------------------------------------------------- #
    "deploy": ["publish", "answer", "ask_user"],
    "feature": [
        "understand_ask", "recall", "list_pages", "list_entities",
        "list_workflows", "plan_and_apply", "compose_route", "add_widgets",
        "verify_promise", "answer", "ask_user",
    ],

    # ---- Undo (Phase 1b — revert_last_patch tool wired) ------------------ #
    "undo": ["recall", "revert_last_patch", "verify_promise", "answer", "ask_user"],

    # ---- Fallback: no scoping ------------------------------------------- #
    "unclear": None,
}

# Confidence below this floor means "scope the tools would be risky —
# keep the full catalog available so Smith can course-correct".
CONFIDENCE_SCOPING_FLOOR = 0.5


# --------------------------------------------------------------------------- #
# Spec D Wave 3 (D3-C) — tool-tag index (LLM-emitted `needed_tags` path)
# --------------------------------------------------------------------------- #
#
# Additive alternative to the 17-intent × closed-TOOL_SUBSETS lookup. The
# LLM emits `needed_tags: list[str]` from the open vocabulary below;
# `tools_for_tags()` computes the union of tools tagged with any wanted
# tag. Unknown tags are silently ignored, so a hallucinated tag can
# never leak an unregistered tool — the LLM still doesn't pick tool
# names directly (safety property preserved).
#
# When the LLM omits `needed_tags` (older prompts / low confidence),
# classify_intent falls back to the closed TOOL_SUBSETS[intent] lookup
# unchanged. Zero call-site changes for consumers.

KNOWN_TAGS: frozenset[str] = frozenset({
    # Verb tags — what kind of work
    "read", "add", "edit", "delete", "diagnose", "verify", "deploy",
    "undo", "feature", "chat",
    # Noun tags — what surface it touches
    "page", "entity", "workflow", "component", "token", "form",
    "shell", "auth", "meta",
})

# Every tool → its tag set. Multiple tags per tool: a tool that both
# reads AND edits a page carries both `read` and `edit` + `page`.
TOOL_TAGS: dict[str, set[str]] = {
    # Terminals (always included regardless of tags — see tools_for_tags)
    "answer":                    {"chat"},
    "ask_user":                  {"chat"},
    # Read
    "recall":                    {"read", "meta"},
    "list_pages":                {"read", "page"},
    "list_entities":             {"read", "entity"},
    "list_workflows":            {"read", "workflow"},
    "list_components":           {"read", "component"},
    "read_page":                 {"read", "page"},
    "read_entity":               {"read", "entity"},
    "read_workflow":             {"read", "workflow"},
    "read_column":               {"read", "entity"},
    "read_file":                 {"read"},
    "grep_schemas":              {"read"},
    "find_resources":            {"read"},
    "find_component":            {"read", "component"},
    "impact_analysis":           {"read", "verify"},
    "check_data_source":         {"read", "verify"},
    "analyze_workflow_values":   {"read", "workflow", "verify"},
    "understand_ask":            {"read", "meta"},
    # Add
    "add_page":                  {"add", "page"},
    # Whole-screen composition. Both verbs and `page`, because composing a
    # route creates a layout where there was none AND replaces one where
    # there was: tagging it `add` only would hide it from every edit ask.
    "compose_route":             {"add", "edit", "page"},
    "add_widgets":               {"add", "edit", "page", "component"},
    "add_workflow":              {"add", "workflow"},
    "add_entity":                {"add", "entity"},
    "add_role":                  {"add", "auth"},
    # Edit
    "edit_page":                 {"edit", "page"},
    "edit_workflow":             {"edit", "workflow"},
    "edit_file":                 {"edit"},
    "wire_form_to_workflow":     {"edit", "form", "workflow"},
    "restrict_page_to_role":    {"edit", "page", "auth"},
    # Delete
    "remove_page":               {"delete", "page"},
    "remove_role":               {"delete", "auth"},
    # Diagnose
    "parse_error":               {"diagnose"},
    "probe_logs":                {"diagnose"},
    "probe_endpoint":            {"diagnose"},
    # Meta terminals
    "verify_promise":            {"verify"},
    "plan_and_apply":            {"feature"},
    "publish":                   {"deploy"},
    "revert_last_patch":         {"undo"},
}


def tools_for_tags(tags: list[str]) -> Optional[list[str]]:
    """Return the union of tools whose TOOL_TAGS intersect any tag in
    ``tags``. Terminals (``answer``, ``ask_user``) are always included
    so Smith can terminate the loop. Unknown tags silently dropped.
    Returns None (no scoping) when the resulting subset would be
    empty or only the terminals — caller falls back to TOOL_SUBSETS.
    """
    if not tags or not isinstance(tags, list):
        return None
    wanted = {t.strip().lower() for t in tags if isinstance(t, str)}
    wanted = wanted & KNOWN_TAGS
    if not wanted:
        return None
    # Terminals always allowed so the loop can end.
    hits: set[str] = {"answer", "ask_user"}
    for name, tt in TOOL_TAGS.items():
        if tt & wanted:
            hits.add(name)
    # If only the terminals matched (no other tool has any of the
    # requested tags), return None so the caller falls back to the
    # closed subset — otherwise a bogus request scopes Smith to just
    # answer+ask_user and it can't do anything.
    if hits == {"answer", "ask_user"}:
        return None
    return sorted(hits)


# --------------------------------------------------------------------------- #
# Intent (result shape)                                                        #
# --------------------------------------------------------------------------- #

class Intent(BaseModel):
    """The output of ``classify_intent``.

    ``tools`` is DERIVED — the LLM never picks tool names directly.
    Two derivation paths:
      * Spec D W3 (D3-C) tag-based: LLM emits ``needed_tags`` from the
        open KNOWN_TAGS vocabulary; ``tools_for_tags()`` unions matching
        tools. Preferred when tags produce a non-terminal subset.
      * Legacy intent-based: closed TOOL_SUBSETS[intent] lookup. Fallback
        when needed_tags is empty/unusable.

    Either way a hallucinated LLM tag / tool name cannot leak into the
    ReAct loop — both paths look up in a registered index.
    """

    intent: str
    domain: str = "unknown"
    target: Optional[str] = None
    confidence: float = 0.0
    # None => no scoping (full catalog). A list => the allowed tool subset.
    tools: Optional[list[str]] = None
    # Spec D Wave 3 (D3-C) — LLM-emitted tag hints. Validated + unioned
    # in classify_intent; kept on the model so callers can log/observe
    # what the LLM asked for vs what it got.
    needed_tags: Optional[list[str]] = None

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        if v is None:
            return 0.0
        return max(0.0, min(1.0, float(v)))

    @field_validator("intent")
    @classmethod
    def _normalize_intent(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in INTENTS else "unclear"


# --------------------------------------------------------------------------- #
# The classifier LLM call                                                      #
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """You classify a user's chat message to Smith (an AI \
build-assistant for a no-code app platform) into ONE of the intents \
below. Emit STRICT JSON only — no prose, no code fences.

Intents (pick the SINGLE best fit):
  * chat        — greeting, thanks, meta question ("what can you do?")
  * query       — asking about the app ("what pages do I have?", "is X bound?")
  * add_field   — add a form field / schema column
  * add_page    — add a new whole page
  * add_workflow — add a new workflow
  * add_entity  — add a new data model / table
  * add_component — add a component to an existing page (button, section, spinner…)
  * add_token   — add a design token (color / typography / spacing)
  * edit_page   — change props/text/layout on an existing page
  * edit_workflow — change nodes/config on an existing workflow
  * edit_token  — change a design token value
  * remove      — destructive — remove a page / component / entity / field / role
  * fix         — diagnose + repair ("X isn't working", "fix the Y")
  * deploy      — publish / build / ship the app
  * feature     — cross-domain add — needs multiple seams (add entity + page + \
workflow + wiring)
  * undo        — revert the last change
  * unclear     — you can't confidently pick from the above

Output JSON shape:
  {
    "intent":     "<one of the intents above>",
    "domain":     "page" | "entity" | "workflow" | "auth" | "token" | "nav" | \
"meta" | "unknown",
    "target":     "<short slug/name if extractable, else null>",
    "confidence": 0.0-1.0,   // your self-assessed likelihood
    "needed_tags": ["<tag>", ...]  // optional; see below
  }

`needed_tags` (Spec D W3): a list describing what CATEGORY of work
this touches. Pick from this open vocabulary (unknown tags dropped):
  verbs:  read, add, edit, delete, diagnose, verify, deploy, undo,
          feature, chat
  nouns:  page, entity, workflow, component, token, form, shell, auth,
          meta

Emit tags whenever you can be confident about the shape of work.
Example: "add a Status column to the Candidate table" → ["add",
"entity"]. "the Save button doesn't work" → ["diagnose", "page",
"workflow"]. When you're unsure, omit the field entirely — the
classifier falls back to the legacy per-intent tool subset unchanged.

Confidence rubric:
  * 0.9+  : unambiguous ("add a page called Pricing")
  * 0.7-0.9: clear intent, target extractable but not verified
  * 0.5-0.7: intent likely but target vague ("update the button")
  * < 0.5 : ambiguous — return the best guess and low confidence so Smith \
falls back to a full toolset

Do not narrate. Emit ONE JSON object. No code fences."""


# LLM boundary — tests inject a stub; production wires a real Claude call.
QueryFn = Callable[[str, str], str]


def _default_query_fn(system_prompt: str, user_prompt: str) -> str:
    """Real LLM call — kept minimal so tests can stub cleanly.

    Uses the same shared boundary as smart_edit_page so we don't fork
    provider handling. Falls back to an empty string on any error;
    ``classify_intent`` treats that as "garbage → unclear".
    """
    try:
        from services.llm_edit import _default_llm_query  # type: ignore
        return _default_llm_query(system_prompt, user_prompt)  # type: ignore[misc]
    except Exception:
        logger.exception("classify_intent: default LLM query failed")
        return ""


def classify_intent(
    user_message: str,
    *,
    chat_history_summary: str = "",
    app_map_summary: str = "",
    query_fn: Optional[QueryFn] = None,
) -> Intent:
    """Classify one user turn into an ``Intent``.

    Args:
        user_message: The literal user turn text.
        chat_history_summary: Optional short summary of prior turns to
            help disambiguate follow-ups ("did you fix it?").
        app_map_summary: Optional very short app-map hint (page slugs,
            entity names) to help target extraction.
        query_fn: LLM boundary — tests inject; ``None`` uses the real
            SDK call via :func:`_default_query_fn`.

    Returns:
        An :class:`Intent`. On any failure (malformed JSON, unknown
        intent label, LLM raised) the intent falls back to ``unclear``
        with ``confidence=0`` and ``tools=None`` (no scoping — full
        catalog fallback). So callers can always treat the result as
        "hint, not mandate".
    """
    q = query_fn or _default_query_fn

    user_prompt_bits = [f"User message:\n{user_message}"]
    if chat_history_summary:
        user_prompt_bits.append(f"Chat history summary:\n{chat_history_summary}")
    if app_map_summary:
        user_prompt_bits.append(f"App map hint:\n{app_map_summary}")
    user_prompt = "\n\n".join(user_prompt_bits)

    try:
        raw = q(_SYSTEM_PROMPT, user_prompt) or ""
    except Exception:
        logger.exception("classify_intent: LLM boundary raised")
        raw = ""

    # Best-effort JSON extraction. Handle the common "prose then JSON"
    # tail we see when a model doesn't fully follow the "no prose" rule.
    parsed = _extract_json(raw)
    if parsed is None:
        return Intent(intent="unclear", confidence=0.0, tools=None)

    try:
        intent = Intent(**parsed)
    except ValidationError:
        return Intent(intent="unclear", confidence=0.0, tools=None)

    # DERIVE tools deterministically. The LLM never chooses tool names
    # directly — both paths look up in a registered index.
    if (
        intent.intent == "unclear"
        or intent.confidence < CONFIDENCE_SCOPING_FLOOR
    ):
        intent.tools = None
    else:
        # Spec D W3 (D3-C) — prefer tag-derived subset when the LLM
        # gave usable tags. Falls back to the closed intent lookup
        # when tags are empty, all-unknown, or resolve to terminals
        # only (see tools_for_tags contract).
        tag_subset = tools_for_tags(intent.needed_tags or [])
        intent.tools = tag_subset if tag_subset is not None else TOOL_SUBSETS.get(intent.intent)

    return intent


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _extract_json(text: str) -> Optional[dict]:
    """Extract the first ``{...}`` object from a string. Handles the
    common cases: pure JSON, JSON wrapped in code fences, JSON with
    leading/trailing prose. Returns None on any failure."""
    if not text or not isinstance(text, str):
        return None
    stripped = text.strip()
    # Strip code fences like ```json ... ```
    if stripped.startswith("```"):
        # find the first newline after the fence, and the last fence.
        try:
            body = stripped.split("\n", 1)[1]
            body = body.rsplit("```", 1)[0]
            stripped = body.strip()
        except Exception:
            pass
    # Fast path.
    try:
        v = json.loads(stripped)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    # Slow path — find the first {...} block.
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
