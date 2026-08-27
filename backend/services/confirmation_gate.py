"""Destructive-action confirmation gate (Phase 1a).

Purpose
-------
Today a user saying "remove the Pricing page" causes Smith to execute
``remove_page`` immediately. The UAT test spec (rows 26–33) requires a
"confirm first, list what breaks, proceed only on yes" pattern.

Design
------
Instead of persisting `pending_confirmation` state across turns
server-side, we lean on the existing chat-history threading:

  1. Destructive tools (``remove_page``, later ``remove_component``,
     ``remove_workflow``, ``add_entity`` with delete-and-recreate) grow
     a `_confirmed: bool` arg.
  2. When the LLM calls them WITHOUT `_confirmed=True`, the tool refuses
     to run and returns a structured "needs confirmation" reply
     containing a plain-language impact summary.
  3. Smith relays that as an ``answer`` waiting for yes/no.
  4. On the next user turn, ``parse_confirmation_reply`` classifies the
     message as "yes"/"no"/"unclear".
  5. If "yes", the LLM (which sees the previous "needs confirmation"
     tool result in the chat trace) re-issues the same call with
     ``_confirmed=True``. If "no", the LLM answers "OK, not removing".

This is stateless on the server: the state lives in the message
history, which Smith already threads. No new DB table.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

# Words that clearly mean "go ahead". Kept narrow so a rambling "yes but
# only if…" doesn't trip us — that becomes "unclear" and Smith asks again.
_YES_PATTERNS = (
    r"\byes\b",
    r"\byep\b",
    r"\byeah\b",
    r"\bconfirm(ed)?\b",
    r"\bgo\s+ahead\b",
    r"\bproceed\b",
    r"\bdo\s+it\b",
    r"\bremove\s+it\b",
    r"\bdelete\s+it\b",
    r"\bok(ay)?\b",
    r"\bsure\b",
    r"\bplease\s+do\b",
)

_NO_PATTERNS = (
    r"\bno\b",
    r"\bnope\b",
    r"\bnah\b",
    r"\bcancel\b",
    r"\babort\b",
    r"\bstop\b",
    r"\bactually\s+no\b",
    r"\bdon['']?t\s+(remove|delete|do)\b",
    r"\bnever\s+mind\b",
    r"\bforget\s+it\b",
    r"\bkeep\s+it\b",
)


#: The exact sentence every confirmation prompt ends with. Emitted by
#: :func:`build_impact_summary`, so it is OUR string, not model prose —
#: which makes it a reliable server-side record that a prompt was actually
#: shown to the user. :func:`confirmation_was_requested` matches on it.
CONFIRMATION_PROMPT_MARKER = "Reply **yes** to proceed, or **no** to cancel."


def confirmation_was_requested(prior_messages: Optional[list[dict]]) -> bool:
    """Did the LAST assistant turn actually ask the user to confirm?

    ``_confirmed`` is an ordinary tool argument the model supplies, and
    nothing recorded server-side that a prompt had ever been shown — so a
    single turn could emit a destructive call already marked confirmed
    (register S24-3). Pairing this with :func:`parse_confirmation_reply`
    on the current user turn makes confirmation something the SERVER
    derives from the conversation rather than something the model asserts.
    """
    if not prior_messages:
        return False
    for msg in reversed(prior_messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            # Some providers deliver content as a list of blocks.
            try:
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            except TypeError:
                content = ""
        return CONFIRMATION_PROMPT_MARKER in (content or "")
    return False


def parse_confirmation_reply(
    message: str,
) -> Literal["yes", "no", "unclear"]:
    """Classify a fresh user turn as yes/no/unclear w.r.t. a pending confirmation.

    The caller is responsible for knowing there IS a pending confirmation
    (typically by inspecting the previous assistant message). This helper
    only looks at the current turn's text.
    """
    if not isinstance(message, str):
        return "unclear"
    s = message.strip().lower()
    if not s:
        return "unclear"
    # NO wins if both match — a "no thanks" shouldn't be misread as "OK".
    for pat in _NO_PATTERNS:
        if re.search(pat, s):
            return "no"
    for pat in _YES_PATTERNS:
        if re.search(pat, s):
            return "yes"
    return "unclear"


# --------------------------------------------------------------------------- #
# Impact summarization                                                        #
# --------------------------------------------------------------------------- #

def build_impact_summary(
    kind: str,
    target: str,
    *,
    dependents: Optional[list[str]] = None,
    cascade: bool = False,
    removes: Optional[list[str]] = None,
) -> str:
    """Build a plain-language impact summary the LLM can relay to the user.

    ``kind``: "page" | "component" | "entity" | "workflow" | "field" | "role"
    ``target``: the human name / route / slug the user recognises.
    ``dependents``: things that would break if the target were removed
        (nav edges pointing to the page, forms bound to the entity, etc).
        The caller runs the impact analysis; this helper just formats.
    ``cascade``: whether the operation also removes everything nested under
        the target. There was NO parameter to receive this (register SX-1),
        so the user read "About to remove page: /x" whether one page or the
        whole feature slice was going — and ``cascade`` is LLM-supplied, so
        they could not tell which they were agreeing to.
    ``removes``: the exact artefacts that will be deleted, from the seam
        that will do the deleting. Names what goes, rather than inferring
        it from nav edges that only point AT the named route.
    """
    scope = " and everything nested under it" if cascade else ""
    lines = [f"About to remove **{kind}: {target}**{scope}."]
    if cascade:
        lines.append("")
        lines.append(
            "⚠️ This is a **cascade** removal — it deletes the whole slice, "
            "not just the one page."
        )
    if removes:
        n = len(removes)
        lines.append("")
        lines.append(f"It will delete {n} file{'s' if n != 1 else ''}:")
        for rem in removes[:15]:
            lines.append(f"  • {rem}")
        if n > 15:
            lines.append(f"  • …and {n - 15} more")
    if dependents:
        n = len(dependents)
        head = f"This will affect {n} thing{'s' if n != 1 else ''}:"
        lines.append("")
        lines.append(head)
        for d in dependents[:10]:
            lines.append(f"  • {d}")
        if n > 10:
            lines.append(f"  • …and {n - 10} more")
    lines.append("")
    lines.append(CONFIRMATION_PROMPT_MARKER)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Tool-result shape                                                           #
# --------------------------------------------------------------------------- #

def needs_confirmation_result(
    kind: str, target: str, dependents: Optional[list[str]] = None,
    *, cascade: bool = False, removes: Optional[list[str]] = None,
) -> dict:
    """Standard shape returned by a destructive tool when `_confirmed` is
    absent. Smith's system prompt tells the LLM to relay ``.summary`` to
    the user and wait for a yes/no on the next turn.

    ``cascade`` / ``removes`` carry the true blast radius through to the
    summary — see :func:`build_impact_summary` (register SX-1)."""
    return {
        "status":       "needs_confirmation",
        "kind":         kind,
        "target":       target,
        "cascade":      bool(cascade),
        "removes":      list(removes or []),
        "dependents":   list(dependents or []),
        "summary":      build_impact_summary(
            kind, target, dependents=dependents,
            cascade=cascade, removes=removes,
        ),
    }
