"""The shape of an understanding — what a tool call becomes before a seam reads it.

Until Smith v4 this module was the front door: one prompt, one model call,
one verb. That call is gone (`services.smith4.turn` chooses from step one)
and what remains is the SHAPE the seams read and the small normalisers the
loop applies to a tool call before handing it on: `_blank` gives every key,
`_is_route` reconciles the two names for a screen, `_env_name_only` and
`_design_scope` keep a credential and a scope word honest, `_parse` and
`_default_provider` are the model seam the chooser shares.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

def _design_scope(raw: object) -> str:
    """`evidence`, `specification`, or "" when they have not said.

    THE WORD SMITH ASKS FOR MUST BE A WORD SMITH ACCEPTS. The question offers
    "specification or reference", and `reference` is what a person then says —
    while the Blueprint's own vocabulary for it is `evidence` (§48). Mapping
    here rather than changing the contract: `evidence` is the accurate name for
    what the frames are to the rest of the pipeline, and `reference` is the
    accurate word for what the user is telling you.
    """
    text = str(raw or "").strip().lower()
    if text in ("specification", "spec", "the specification"):
        return "specification"
    if text in ("evidence", "reference", "a reference", "the reference"):
        return "evidence"
    return ""


def _env_name_only(raw: object) -> str:
    """An environment variable NAME, or "" — never a credential.

    §42's first forbidden resting place for a raw token is chat history, and
    this return value is written to the conversation log. A Figma personal
    access token is `figd_...`; anything carrying that, or too long or too
    punctuated to be a variable name, is a secret the model was told not to
    return. Dropping it is the point: Smith then asks for the NAME, and the
    token never reaches disk.
    """
    text = str(raw or "").strip()
    if not text or "figd_" in text or len(text) > 64:
        return ""
    return text if all(c.isalnum() or c == "_" for c in text) else ""


def _default_provider(prompt: str, reasoning: Callable[[str], None] | None = None) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=1200,
                    reasoning_callback=reasoning)


def _render_history(history: list | None) -> str:
    """The exchange as plain lines, oldest first.

    Bounded to the last few turns: a clarifying question and its answer are
    adjacent, so the window only has to be long enough to hold the pair, and a
    whole transcript would crowd out the Blueprint slice beside it.
    """
    turns = [t for t in (history or []) if t]
    if not turns:
        return "(nothing yet — this is the first turn)"
    lines = []
    for t in turns[-6:]:
        role, text = (t if isinstance(t, (tuple, list)) and len(t) == 2
                      else ("user", t))
        who = "Smith" if str(role).lower() in ("smith", "assistant") else "They"
        lines.append(f"{who}: {str(text).strip()}")
    return "\n".join(lines)


#: Every key an understanding carries, so a caller's `.get()` never meets a
#: partial dict on exactly the paths that already went wrong.
SHAPE: frozenset[str] = frozenset({
    "answer", "clarification_needed", "clarification_options", "verb", "route",
    "widgets", "figma_url", "token_env", "uxpilot_ref", "key_env", "treat_as",
    "target_file", "element_label", "change", "workflow", "rule", "requirement",
    "api", "integration", "new_value", "entity", "field", "asks",
    "email", "person", "person_name", "role",
})


def _blank(**given: Any) -> dict[str, Any]:
    """An understanding with nothing in it but `given` — the full shape."""
    out: dict[str, Any] = {k: "" for k in SHAPE}
    out.update({"widgets": [], "field": {}, "clarification_options": [],
                "asks": []})
    out.update(given)
    return out


def _is_route(text: str) -> bool:
    """Whether a `target_file` is a ROUTE rather than a path to a file.

    Understanding returns either, depending on what the Blueprint slice showed
    it; only the route half is the same fact as `route`.
    """
    text = (text or "").strip()
    return bool(text) and text.startswith("/") and not text.endswith(".json") \
        and "src/" not in text


def _labels(raw: Any) -> list[str]:
    """Chip labels: strings, trimmed, non-empty, deduplicated, at most five."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip() if not isinstance(item, dict) else str(item.get("label") or "").strip()
        if text and text not in out:
            out.append(text)
    return out[:5]


def _parse(raw: str) -> dict | None:
    """The JSON object in `raw`, however it was wrapped.

    Models fence JSON in ```json blocks and prepend a sentence often enough
    that a bare `json.loads` fails on output that is otherwise perfectly good.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    try:
        parsed = json.loads(_escape_inner_quotes(match.group(0)))
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _escape_inner_quotes(text: str) -> str:
    """`text` with the double quotes INSIDE its string values escaped.

    Asked which requirements came from the uploaded document, the model
    answered well — and wrote the document's title in quotes inside the
    JSON string, so the object would not load and the turn fell through to
    "I did not follow that": a change-request deflection to a question it
    had just answered. A quote inside a string that is not followed (after
    whitespace) by `,` `}` `]` or `:` cannot be closing the string, so it is
    content. Only reached when a plain load has already failed.
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                out.append(text[i:i + 2])
                i += 2
                continue
            if ch == '"':
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j >= n or text[j] in ",}]:":
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
        i += 1
    return "".join(out)
