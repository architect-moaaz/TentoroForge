"""Capability gate — decides whether the user's ask fits what Tentoro
Forge can structurally build (CRUD-over-database) BEFORE the planner
spends turns producing a coherent-but-wrong app.

Root cause of the "shell without content" class of bug (canonical
example: user asks for a calculator, pipeline ships an app with the
history table but no calculator): the DSL, generators, and validators
are all CRUD-shaped, but nothing at the entrance says "this ask is
not a shape we build." So calculator/timer/game/drawing prompts land,
Discovery extracts one HistoryEntry-like entity, the pipeline
faithfully produces a form-and-table around it, and the user sees a
brand-named empty log.

Public API:
  classify_capability(prompt) -> {"shape", "matched", "reason"}
      shape ∈ {"crud", "interactive", "unclear"}
  refusal_message(prompt, classification) -> str
      human-readable message the SSE stream can emit before halting.
  is_gate_enabled() -> bool
      env-flag gate so this ships in observe-mode first.

Fails open by design: on any error, returns shape="unclear" and the
caller proceeds as if it were CRUD. Never silently blocks.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Tokens that signal a COMPUTATIONAL tool the platform now DOES support
# via the `computational` archetype (interaction.computed reactive fields
# + `onClick:{kind:"compute"}` buttons). Matched prompts route to that
# archetype instead of being refused.
_COMPUTATIONAL_TOKENS: tuple[str, ...] = (
    "calculator", "calc",
    "converter", "unit converter", "currency converter",
    "counter", "tally",
    "quiz", "trivia", "flashcard", "flashcards",
    # Text-shape tools whose I/O boils down to formula-over-string
    "regex tester", "regex", "json formatter",
)

# Tokens that STILL exceed the DSL — pure client-side state machines,
# audio, canvas, animation, real-time games. These keep the refusal.
_INTERACTIVE_TOKENS: tuple[str, ...] = (
    # time-based (need setInterval/setTimeout + tick state — not yet supported)
    "stopwatch", "timer", "clock", "alarm", "pomodoro",
    # games / puzzles (need game-state model + move rules)
    "chess", "checkers", "sudoku", "wordle", "tic-tac-toe", "tictactoe",
    "puzzle", "game", "arcade", "solitaire",
    # audio/music (need WebAudio / MIDI wiring)
    "piano", "drum", "drums", "synth", "synthesizer",
    "sequencer", "metronome", "tuner",
    # drawing/canvas (need HTML canvas + input capture)
    "drawing", "paint", "sketch", "whiteboard",
    # rich text editors
    "text editor", "markdown editor", "notepad",
    # color picker library needed
    "colorpicker", "color picker",
)

# Side-effect / workflow-intent tokens — when these appear ALONGSIDE a
# computational keyword, the tool needs to hand its result off to a
# workflow (email/notify/save/book). The deterministic short-circuit
# can't author that workflow, so the classifier flips a `needs_workflow`
# hint and the router lets the ask flow through the LLM planner instead
# (guided by the HARD-STOP block in the planner prompt, which allows
# workflows on a computational archetype while keeping entities=[]).
_WORKFLOW_INTENT_TOKENS: tuple[str, ...] = (
    # notification / communication — includes plurals + 3rd-person forms
    "email", "emails", "emailed", "e-mail",
    "notify", "notifies", "notified", "notification", "notifications",
    "send", "sends", "sent",
    "alert", "alerts", "alerted",
    "text", "texts", "sms", "message", "messages",
    "call", "calls", "webhook", "webhooks", "ping", "post to",
    # persistence to external system (NOT the tool's own storage)
    "save to", "saves to", "log to", "logs to", "record to", "records to",
    "sync to", "syncs to", "sync with", "syncs with",
    "push to", "pushes to", "publish to", "publishes to",
    "upload to", "uploads to", "share to", "shares to",
    "share with", "shares with",
    # downstream actions
    "book", "books", "booking",
    "schedule appointment", "schedules appointment",
    "trigger", "triggers", "kick off", "kicks off",
    "start workflow", "starts workflow", "run workflow", "runs workflow",
)

# Regex compiled once. Sort long-first so multi-word matches win before
# their single-word substrings.
_COMPUTATIONAL_RE = re.compile(
    rf"\b(?:{'|'.join(sorted(map(re.escape, _COMPUTATIONAL_TOKENS), key=len, reverse=True))})s?\b",
    re.IGNORECASE,
)
_INTERACTIVE_RE = re.compile(
    rf"\b(?:{'|'.join(sorted(map(re.escape, _INTERACTIVE_TOKENS), key=len, reverse=True))})s?\b",
    re.IGNORECASE,
)
_WORKFLOW_INTENT_RE = re.compile(
    rf"\b(?:{'|'.join(sorted(map(re.escape, _WORKFLOW_INTENT_TOKENS), key=len, reverse=True))})\b",
    re.IGNORECASE,
)

# If ANY of these show up, the ask has real CRUD content alongside any
# interactive keyword — treat the whole thing as CRUD and let the
# pipeline build what it can. A "log calculator usage" is genuinely
# a CRUD app (logs of usage) that happens to mention calculator.
_CRUD_TOKENS: tuple[str, ...] = (
    "user", "users", "customer", "customers", "client", "clients",
    "order", "orders", "invoice", "invoices", "product", "products",
    "employee", "employees", "vendor", "vendors", "student", "students",
    "patient", "patients", "task", "tasks", "project", "projects",
    "role", "roles", "permission", "permissions", "team", "teams",
    "workflow", "approval", "approvals",
    "report", "reports", "audit", "audit log",
    # CRUD verbs
    "manage", "track", "assign", "approve", "review",
    "create record", "add record", "update record",
)
_CRUD_RE = re.compile(rf"\b(?:{'|'.join(map(re.escape, _CRUD_TOKENS))})\b", re.IGNORECASE)


def classify_capability(prompt: str) -> dict[str, Any]:
    """Classify a user prompt against the platform's structural shape.

    Returns {shape, matched, reason} where:
      shape="crud"          : proceed normally (no signals, or mixed
                              with CRUD content = build the CRUD)
      shape="computational" : proceed with `computational` archetype
                              (calculator, converter, quiz-scorer, …)
      shape="interactive"   : refuse / warn — pure client-side app
                              the DSL still can't express
      shape="unclear"       : empty/unparseable — treat as crud upstream
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return {"shape": "unclear", "matched": [], "reason": "empty prompt"}

    text = prompt.strip()
    comp_hits = _COMPUTATIONAL_RE.findall(text)
    interactive_hits = _INTERACTIVE_RE.findall(text)

    if not comp_hits and not interactive_hits:
        return {"shape": "crud", "matched": [], "reason": "no interactive-app signals"}

    # Mixed with CRUD content? Build CRUD; treat the interactive/computational
    # keyword as naming influence. A "calculator usage log" is CRUD.
    crud_hits = _CRUD_RE.findall(text)
    if crud_hits:
        return {
            "shape": "crud",
            "matched": sorted({m.lower() for m in comp_hits + interactive_hits}),
            "reason": (
                "interactive/computational keywords present but "
                f"CRUD content also present ({', '.join(sorted({c.lower() for c in crud_hits}))}) "
                "— building the CRUD side"
            ),
        }

    # Purely genuine-interactive (games, drawing, audio) — refuse.
    if interactive_hits and not comp_hits:
        matched_uniq = sorted({m.lower() for m in interactive_hits})
        return {
            "shape": "interactive",
            "matched": matched_uniq,
            "reason": f"detected interactive-app signals: {', '.join(matched_uniq)}",
        }

    # Computational-only (or comp + interactive — computational wins because
    # anything computational is representable, and the interactive token is
    # likely thematic packaging like "calculator game"). Route to the
    # computational archetype; planner sees a clean pass-through.
    matched_uniq = sorted({m.lower() for m in comp_hits})

    # Workflow-intent detection: when the ask includes "email/notify/send
    # /save-to/book/…" alongside the computational token, the tool needs a
    # side-effect the deterministic short-circuit can't author. Flip a hint
    # the router reads to decide whether to short-circuit or fall through
    # to the LLM planner (which the HARD-STOP block guides to emit a
    # computational archetype WITH workflows[] populated).
    workflow_hits = _WORKFLOW_INTENT_RE.findall(text)
    needs_workflow = bool(workflow_hits)
    result: dict[str, Any] = {
        "shape": "computational",
        "matched": matched_uniq,
        "archetype": "computational",
        "reason": f"detected computational-tool signals: {', '.join(matched_uniq)}",
    }
    if needs_workflow:
        wf_matched = sorted({w.lower() for w in workflow_hits})
        result["needs_workflow"] = True
        result["workflow_intent_matched"] = wf_matched
        result["reason"] += (
            f"; workflow intent also present ({', '.join(wf_matched)}) — "
            "letting LLM planner author workflows[]"
        )
    return result


_REFUSAL_TEMPLATE = """**Heads up — this ask sits outside what we can build coherently.**

Tentoro Forge generates database-backed apps: forms, tables, dashboards, and workflows over Postgres. Your request looks centered on **{concept_phrase}**, which needs client-side state and pure logic that our schema DSL doesn't express.

If we proceed as-is, you'll get an app with the *shell* of what you asked for (branded page, empty history log) but no working {concept}. That's the wrong deliverable.

**A few ways forward:**

- **Reshape the ask into CRUD.** Example: instead of "a calculator", ask for "a calculation history dashboard — log entries with expression, result, timestamp, and user; filterable by date." We'll build that cleanly.
- **Wrap it in a data app.** Example: "a {concept} usage log with per-user stats and admin analytics." The {concept} itself won't be functional, but the surrounding app will be.
- **Use a different tool.** For pure client-side interactive apps (games, calculators, drawing tools), a general-purpose no-code platform (Bubble, Framer, Retool for interactive widgets) is a better fit.
- **Proceed anyway.** If you want to see what comes out and iterate manually afterwards, tell us "proceed anyway" and we'll build the CRUD side around the naming.

Detected signals: {matched}
"""


def refusal_message(prompt: str, classification: dict[str, Any]) -> str:
    """Human-readable refusal for interactive-app prompts. Suitable for
    an SSE `capability_refusal` event or a chat reply."""
    matched = classification.get("matched") or []
    concept = matched[0] if matched else "an interactive component"
    concept_phrase = (
        ", ".join(f'"{m}"' for m in matched[:3]) if matched else "client-side interactivity"
    )
    return _REFUSAL_TEMPLATE.format(
        concept=concept,
        concept_phrase=concept_phrase,
        matched=", ".join(matched) if matched else "(none)",
    )


def is_gate_enabled() -> bool:
    """Return True when the capability gate should HARD-BLOCK (halt +
    emit refusal) rather than run in observe-mode.

    Observe-mode (default): classifier still runs and can be logged /
    surfaced as a warning, but the pipeline proceeds. Flip the flag
    on once the classifier's false-positive rate is measured.
    """
    return os.getenv("FORGE_CAPABILITY_GATE", "").strip().lower() in {
        "1", "true", "yes", "on", "strict", "enforce",
    }


class InteractiveAppRefused(RuntimeError):
    """Raised when the gate is enabled AND the prompt classified as
    interactive. Carries the refusal message + classification so the
    router can turn it into an SSE event."""

    def __init__(self, message: str, classification: dict[str, Any]) -> None:
        super().__init__(message)
        self.classification = classification


def enforce_capability_gate(prompt: str) -> dict[str, Any]:
    """One-line integration for pipeline entry points. Always returns
    the classification. Raises InteractiveAppRefused only when the
    gate is enabled AND the prompt is interactive. Callers should
    always call this, log the classification, and let the exception
    bubble to the SSE stream when it fires."""
    classification = classify_capability(prompt)
    if classification["shape"] == "interactive" and is_gate_enabled():
        raise InteractiveAppRefused(
            refusal_message(prompt, classification),
            classification,
        )
    return classification
