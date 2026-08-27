"""Orchestrator Agent (#0) — intent classification and routing.

Classifies every user input into one of: PLAN, REFINE, EXPLAIN, SCAFFOLD,
AGENT, DISCOVER, NAVIGATE, UNDO, FIX, AMBIGUOUS. Uses Haiku for speed (1-2 turns).
"""

import json
import os
import re
from pathlib import Path

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import AssistantMessage, ResultMessage, TextBlock
from sse_helpers import billing_safe_query


ORCHESTRATOR_SYSTEM_PROMPT = r"""You are a routing agent for an application builder platform.
Your job is to classify the user's intent and route to the correct specialist agent.

You have access to the current project's AppModel index which tells you what exists.

## Classification Rules

Respond with EXACTLY ONE JSON object containing one of these categories:

APPROVE — User is approving, confirming, or signaling to proceed with an existing plan
  Examples: "Yes", "Go ahead", "Looks good", "Build it", "Proceed",
  "Use your best judgment", "Skip questions and just do it",
  "Make smart assumptions", "That works, generate it",
  "Just build it", "Approved", "Ship it"
  NOTE: This applies when a plan has been presented and the user is responding to it.
  Meta-instructions like "use your best judgment" or "skip questions" mean the user
  wants to proceed without further clarification.

PLAN — User wants to create a new app or add a major new module/feature
  Examples: "Build me a task app", "Add an inventory module",
  "I need user authentication", "Create a reporting dashboard"

REFINE — User wants to change something that already exists
  Examples: "Make the button red", "Add a search bar to the task list",
  "Change the card layout to a table", "Add validation to the email field"

FIX — User reports that an EXISTING feature is broken / not working, or pastes
  an error. The intent is to REPAIR declared behaviour, not to add anything new.
  Examples: "Creating an assessment crashes", "Scheduling fails to save",
  "The calendar is empty", "I can't upload a CV", "The form doesn't save",
  "error: candidate_id is a timestamp", "the dashboard shows nothing"
  (Distinguish from REFINE: FIX repairs something that should already work;
  REFINE adds or restyles. "Add a field" / "make it dark mode" are REFINE.)

EXPLAIN — User is asking a question, not requesting a change
  Examples: "How does the auth work?", "What tables exist?",
  "Why is the sidebar component structured this way?", "Show me the task flow"

SCAFFOLD — User wants to add a specific new feature to an existing module
  Examples: "Add a notifications system", "Add CSV export to the task list",
  "Add a dark mode toggle", "Add pagination to the API"
  (Distinguish from PLAN: scaffold is a focused feature, plan is a whole module)

AGENT — User wants to create, modify, or manage an AI agent within the app
  Examples: "Add a customer support chatbot", "Create an AI assistant that can query orders"

DISCOVER — User has a vague idea, problem, or reference but no clear requirements
  Examples: "I need something for my HR team", "We have a problem with tracking expenses",
  "Build something like Trello", "I'm not sure what I need but our onboarding is broken",
  "What apps would help my sales department?"

NAVIGATE — User wants to switch views or see something specific
  Examples: "Show me the data model", "Open the workflow editor",
  "Go to the preview", "Open the agent builder"

UNDO — User wants to revert a change
  Examples: "Undo that", "Revert the last change", "Go back to before"

AMBIGUOUS — You can't determine intent. Ask a clarifying question.

## Response Format

You MUST respond with ONLY this JSON (no markdown fences, no extra text):

{
  "intent": "APPROVE|PLAN|REFINE|EXPLAIN|SCAFFOLD|AGENT|DISCOVER|NAVIGATE|UNDO|FIX|AMBIGUOUS",
  "reasoning": "brief explanation of why you chose this intent",
  "clarification": "question to ask if AMBIGUOUS, null otherwise",
  "context_needed": ["list of AppModel sections the downstream agent will need"]
}

## Decision Heuristics

- If a plan is pending approval and the user's message signals agreement, acceptance,
  or a desire to proceed (even indirectly) → APPROVE
- If the project has NO generated files yet and the user describes what they want → PLAN
- If the project HAS files and the user reports a broken/not-working feature or
  pastes an error (symptom/complaint language) → FIX
- If the project HAS files and the user asks for a change → REFINE
- If the user asks a question (starts with "how", "what", "why", "can you explain") → EXPLAIN
- If the user mentions adding a specific feature to existing code → SCAFFOLD
- If the user is vague, uncertain, or describes a problem without a solution → DISCOVER
- If the user says "undo", "revert", "go back" → UNDO
- Default to REFINE if the project exists and the intent is unclear between REFINE and SCAFFOLD
"""


# --------------------------------------------------------------------------- #
# Deterministic FIX pre-classifier (keyword gate).
#
# classify_intent is LLM-based; this gate runs BEFORE the model so a clear
# broken-feature symptom or a pasted error deterministically routes to FIX on a
# has-code project. It is intentionally conservative: it must NOT hijack a
# feature-ADD / restyle request ("add a field", "make it dark mode"), which
# carry no failure language and stay REFINE.
# --------------------------------------------------------------------------- #

# Openers that mark an additive / restyle (REFINE) request. When a message
# starts with one of these and has no explicit failure token, we do NOT FIX it
# (guards e.g. "add error handling to the upload").
_ADD_OPENER_RE = re.compile(
    r"^\s*(please\s+)?(add|create|build|include|insert|put|append|give me|"
    r"i(?:'d| would)? (?:want|like|need)|could you (?:add|make|create)|can you (?:add|make|create)|"
    r"let'?s add|make it|change|rename|restyle|update the|set the|turn (?:it|the)|convert)\b",
    re.I,
)

# Unambiguous "this existing thing is broken" language.
_BROKEN_RE = re.compile(
    r"\b("
    r"broken|not working|doesn'?t work|does not work|isn'?t working|is not working|"
    r"won'?t work|stopped working|no longer works?|not functioning|"
    r"crash(?:es|ed|ing)?|nothing happens|doesn'?t do anything|"
    r"is broken|are broken"
    r")\b",
    re.I,
)

# A pasted error / stack trace.
_ERROR_PASTE_RE = re.compile(
    r"(\berror\b|\bexception\b|traceback|stack ?trace|\bnullpointer\b|"
    r"\bunhandled\b|violates .*constraint|not-null constraint|\bstacktrace\b)",
    re.I,
)


def looks_like_fix(user_message: str) -> bool:
    """Deterministic gate — True when the message reports a broken/not-working
    feature or pastes an error (a FIX symptom), and is NOT a plain feature-add.

    Reuses the fix-diagnoser's symptom taxonomy (save/create fails, empty data,
    can't upload, missing field) so author/classify/diagnose can't drift.
    """
    msg = (user_message or "").strip()
    if not msg:
        return False

    is_add_opener = bool(_ADD_OPENER_RE.match(msg))

    # Unambiguous broken-language always wins — even inside an add-shaped
    # sentence ("add a CV upload but it's not working").
    if _BROKEN_RE.search(msg):
        return True

    # The remaining signals (the diagnoser's symptom taxonomy + a bare pasted
    # error) are suppressed for a plain additive/restyle request so we never
    # hijack "add error handling to the upload" or "add a field".
    if is_add_opener:
        return False

    # 1. Symptom taxonomy (the same classifier the diagnoser locates against).
    try:
        from agents.fix_diagnoser import classify_symptom
        if classify_symptom(msg):
            return True
    except Exception:  # noqa: BLE001 — never let the gate crash classification
        pass

    # 2. A pasted error / stack trace.
    if _ERROR_PASTE_RE.search(msg):
        return True

    return False


async def classify_intent(
    user_message: str,
    output_dir: str,
    conversation_history: list[dict] | None = None,
    has_pending_plan: bool = False,
) -> dict:
    """Classify user intent using the orchestrator agent.

    Returns dict with: intent, reasoning, clarification, context_needed.
    """
    os.environ.pop("CLAUDECODE", None)

    # Check if project has generated code files (not just empty dirs or config)
    has_files = False
    has_app_model = False
    app_model_path = Path(output_dir) / "app-model.json"
    _ignore = {".git", ".gitignore", "node_modules", "workflows", "agent-definitions"}

    if Path(output_dir).exists():
        has_files = any(
            f for f in Path(output_dir).iterdir()
            if f.name not in _ignore and (f.is_file() or any(f.iterdir()) if f.is_dir() else True)
        )
        has_app_model = app_model_path.exists()

    # Deterministic FIX pre-classifier gate — a clear broken-feature symptom or
    # a pasted error on a HAS-CODE project routes to FIX without the LLM (and
    # without a pending plan, which the user is more likely approving/refining).
    if has_files and not has_pending_plan and looks_like_fix(user_message):
        return {
            "intent": "FIX",
            "reasoning": "Symptom/error language on a has-code project (deterministic FIX gate).",
            "clarification": None,
            "context_needed": [],
        }

    context = f"Project has generated files: {has_files}"
    if has_app_model:
        context += "\nAn app-model.json exists — read it to understand the current app structure."
    if has_pending_plan:
        context += "\nA plan has been generated and is PENDING APPROVAL. The user may be responding to it."

    # Include recent conversation history for context
    history_text = ""
    if conversation_history:
        recent = conversation_history[-6:]  # last 3 exchanges
        history_lines = []
        for msg in recent:
            role = msg["role"].upper()
            content = msg["content"][:300]  # truncate long messages
            history_lines.append(f"  {role}: {content}")
        history_text = "\n## Recent Conversation\n" + "\n".join(history_lines)

    user_prompt = f"""## Project Context
{context}
{history_text}

## User Message
{user_message}

Classify this user's intent. Respond with ONLY the JSON object."""

    options = ClaudeAgentOptions(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        allowed_tools=["Read"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=2,
        model="claude-haiku-4-5-20251001",
    )

    result_text = ""
    async for message in billing_safe_query(query(prompt=user_prompt, options=options)):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    result_text += block.text

    # Parse the JSON response
    try:
        # Try to extract JSON from the response
        text = result_text.strip()
        # Handle markdown code fences
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        # Fallback: try to determine intent from keywords
        return {
            "intent": _fallback_classify(user_message, has_files, has_pending_plan),
            "reasoning": "Fallback classification (JSON parse failed)",
            "clarification": None,
            "context_needed": [],
        }


def _fallback_classify(message: str, has_files: bool, has_pending_plan: bool = False) -> str:
    """Simple keyword-based fallback classification."""
    msg = message.lower().strip()

    if any(w in msg for w in ["undo", "revert", "go back", "roll back"]):
        return "UNDO"

    if any(msg.startswith(w) for w in ["how ", "what ", "why ", "can you explain", "tell me about", "describe "]):
        return "EXPLAIN"

    if any(w in msg for w in ["show me", "open ", "go to ", "navigate to", "switch to"]):
        return "NAVIGATE"

    if any(w in msg for w in ["i need something", "we have a problem", "not sure what",
                               "something for my", "like trello", "like salesforce",
                               "help my", "what apps"]):
        return "DISCOVER"

    # Check for approval patterns when a plan is pending
    if has_pending_plan:
        _approve_exact = {"yes", "yes please", "approve", "do it", "build it",
                          "create it", "make it", "generate it", "start building"}
        if msg in _approve_exact:
            return "APPROVE"
        _approve_substr = ["go ahead", "looks good", "let's go", "proceed", "ship it",
                           "approved", "best judgment", "best judgement", "skip questions",
                           "smart assumptions", "just do it", "just build"]
        if any(p in msg for p in _approve_substr):
            return "APPROVE"

    if not has_files:
        return "PLAN"

    # Broken-feature symptom / pasted error on a has-code project → FIX.
    if not has_pending_plan and looks_like_fix(message):
        return "FIX"

    if any(w in msg for w in ["add a new", "create a new module", "build a new",
                               "i need a new", "add an entire"]):
        return "SCAFFOLD"

    return "REFINE"
