"""The brief before there is an application — everything the user has said.

Lifted from the Blueprint router so the loop and the router read the same
brief: the user's turns in order with Smith's questions dropped, the
documents they supplied labelled as such, whether a design travels with
it, and whether the organisation already has a design language to offer.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FUNCTIONLESS_SHAPE = (
    "just says", "just shows", "just displays", "only says", "only shows",
    "only displays", "simply says", "that says", "which says", "displaying the text",
    "shows the text", "says welcome", "says hello",
)

_ACTION_HINTS = (
    "create", "add", "manage", "track", "edit", "update", "delete", "remove",
    "approve", "schedule", "book", "assign", "submit", "review", "record",
    "store", "save", "search", "filter", "report", "upload", "download",
    "sign in", "log in", "login", "register", "post", "comment", "vote",
    "order", "pay", "invoice", "notify", "email", "list of", "dashboard",
    "workflow", "role", "user", "account", "database", "form", "calculate",
)

_DEFINE_STATE_CHAIN = ("DISCOVERY", "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW")


def brief_from(history: Any, message: str) -> str:
    """Everything the user has said, in order, as one brief.

    Smith's questions are dropped: a definition is written from what was
    asked for, and "which language should the interface be in?" is not part
    of the request. The answers are, and they read as qualifications of the
    sentences above them — which is how somebody would have written it had
    they thought of it first.
    """
    said: list[str] = []
    for turn in history or []:
        if isinstance(turn, (tuple, list)) and len(turn) == 2:      # the loop's (role, text)
            role, text = turn
        else:
            role = getattr(turn, "role", None) or (
                turn.get("role") if isinstance(turn, dict) else None)
            text = getattr(turn, "text", None) or (
                turn.get("text") if isinstance(turn, dict) else None)
        if str(role) == "user" and str(text or "").strip():
            said.append(str(text).strip())
    if str(message or "").strip():
        said.append(str(message).strip())
    # De-duplicated in order: a resent message must not appear twice.
    seen: set[str] = set()
    out = [t for t in said if not (t in seen or seen.add(t))]
    return "\n\n".join(out)


def with_documents(brief: str, evidence: Any) -> str:
    """The brief plus the supplied documents, labelled so the reader can tell
    what the person said from what a document said.

    For the turn's own reading — the clarifier, the design-link scan — not
    for the Blueprint: the documents are stored beside it by `_run_dag`
    (services.blueprint.documents) and the agents read them from there, so
    `application.description` stays the user's words.
    """
    from services.blueprint import documents as _documents
    block = _documents.labelled(evidence)
    return f"{brief}\n\n{block}" if block else brief


def is_functionless(brief: str) -> bool:
    """True for a brief that describes a page with no function — a static bit of
    text and nothing to do (DEFECT-C-06). Conservative: it must BOTH look like a
    static-text page AND name no capability, so a real app is never refused."""
    b = (brief or "").lower()
    if len(b) > 400:  # a substantial brief is not a one-line 'welcome' page
        return False
    looks_static = any(s in b for s in _FUNCTIONLESS_SHAPE)
    has_action = any(h in b for h in _ACTION_HINTS)
    return looks_static and not has_action


def has_design_references(project_id: str) -> bool:
    """Whether the user has designated an upload as design direction.

    The clarifier is told when a design travels with the brief so it does not
    ask which palette fits a design that has already chosen its own — and it
    only knew about a Figma or UX Pilot link in the prose. A screenshot
    attached and marked "read as design direction" is the same fact.
    """
    from services import chat_attachments, design_reference
    try:
        return bool(design_reference.read_design_references(
            chat_attachments.attachments_root(), str(project_id)))
    except Exception:  # noqa: BLE001 — no designation readable is no designation
        return False


def design_language_offer(output_dir: Path) -> tuple[str, str] | None:
    """`(company_name, summary)` when there is a language to offer, else None.

    Read off what was adopted rather than out of the database, so the gate
    asks about exactly the language the build would use — the two cannot
    disagree about which palette is on offer.
    """
    from services.blueprint import brand_language
    from services.smith import design_language

    if not brand_language.available(output_dir):
        return None
    tokens = brand_language.tokens(output_dir)
    if not tokens:
        return None
    name = str(tokens.get("_companyName") or "")
    return name, design_language.summary_of(
        {k: v for k, v in tokens.items() if not k.startswith("_")})


def advance_to_review(svc) -> None:
    """Walk the Blueprint state from wherever it is up to BLUEPRINT_REVIEW after
    a define, so GET /blueprint reports the review gate instead of DISCOVERY.
    Best-effort: a refused/illegal step just stops the walk."""
    from services.blueprint.orchestrator import transition, IllegalTransition
    cur = svc.doc.get("state", "DISCOVERY")
    if cur not in _DEFINE_STATE_CHAIN:
        return
    for nxt in _DEFINE_STATE_CHAIN[_DEFINE_STATE_CHAIN.index(cur) + 1:]:
        try:
            transition(svc, nxt)
        except IllegalTransition:
            break
