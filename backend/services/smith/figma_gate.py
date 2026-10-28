"""The Figma branch of "who designs the screens": ask for the design, read it, check it, go on.

`ui_designer` asks the question and records the answer. When the answer is Figma this module takes
over, in four steps that each arrive as an ordinary chat turn and are recognised by the turn before
them (as the designer question is), so these words inside a sentence decide nothing:

  1. PROMPT   Smith asks for the link to the design — and for the access token when none is saved.
              The token is typed in a field that stores it straight to the organisation's
              integrations; the link is not a secret and travels as the message.
  2. CONNECT  The link is read with `figma_connect` (the extraction the opening brief already uses).
  3. CHECK    `coverage.check` judges the design against the requirements.
  4. DECIDE   Sufficient: the build goes on. Not: Smith says what is missing and offers
              *update and check again* / *Forge designs the rest* / *only what I drew*. The last two
              set how the design is held (`treatAs`: evidence or specification) and go on.

WHERE THE STATE LIVES. The verdict and the report Smith showed are kept beside the extraction
(`.forge/figma/coverage.json`), not in the Blueprint: they are about a conversation, change on every
re-check, and must not be copied into every Blueprint version (§91) the way the design payload is not.
`stop()` is pure — it reads that file — so the build's own gate can ask it without a model call.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from services.figma import coverage as cov_mod

logger = logging.getLogger(__name__)

#: The sentence that identifies the request for the design in a transcript.
_PROMPT_MARK = "I need your Figma design"
#: What the panel sends once it has stored the token: these words, then the link.
FIGMA_SAVED = "Figma design saved"
TOKEN_KEY = "FIGMA_TOKEN"
#: A fixed line in the coverage report that offers the three ways forward.
_REPORT_MARK = "How would you like to go on?"
#: The build was asked to start with a design that was read but never checked. It is not let through:
#: the person is asked, and answers with one click.
_CHECK_MARK = "has not been checked against the requirements yet"
CHECK_NOW = "Check my design now"

UPDATE, FILL, ONLY = cov_mod.UPDATE_AND_RECHECK, cov_mod.FILL_WITH_FORGE, cov_mod.ONLY_WHAT_I_DREW
_CHOICES = {cov_mod.UPDATE_AND_RECHECK.lower(): "update", cov_mod.FILL_WITH_FORGE.lower(): "fill",
            cov_mod.ONLY_WHAT_I_DREW.lower(): "only"}


@dataclass
class Outcome:
    """What Smith says next, and whether the build may start now."""

    message: dict[str, Any]
    proceed: bool


def _norm(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _last_turn(history: Iterable[tuple[str, str]]) -> str:
    turns = [(str(r or "").lower(), str(t or "")) for r, t in history if str(t or "").strip()]
    return turns[-1][1] if turns and turns[-1][0] in ("smith", "assistant") else ""


# --------------------------------------------------------------------------- #
# Reading the conversation
# --------------------------------------------------------------------------- #

def is_prompt(text: str) -> bool:
    return _PROMPT_MARK in (text or "")


def is_report(text: str) -> bool:
    return _REPORT_MARK in (text or "")


def is_check_pending(text: str) -> bool:
    return _CHECK_MARK in (text or "")


def link_in(message: str, history: Iterable[tuple[str, str]]) -> str:
    """The Figma link ``message`` carries, when the turn before it was the request for one."""
    from services.smith.figma_connect import find_in

    if not is_prompt(_last_turn(history)):
        return ""
    found = find_in(message)
    return str(found["figma_url"]) if found else ""


def choice_in(message: str, history: Iterable[tuple[str, str]]) -> str:
    """``update`` / ``fill`` / ``only`` when ``message`` answers the coverage report just shown, or
    ``check`` when it answers the request to check a design that was read but never checked."""
    last = _last_turn(history)
    if is_check_pending(last):
        return "check" if _norm(message) == _norm(CHECK_NOW) else ""
    if not is_report(last):
        return ""
    return _CHOICES.get(_norm(message), "")


# --------------------------------------------------------------------------- #
# What is stored
# --------------------------------------------------------------------------- #

def _path(output_dir: Any) -> Path:
    from services.figma.store import store_dir

    return store_dir(output_dir) / "coverage.json"


def _read(output_dir: Any) -> dict[str, Any] | None:
    try:
        return json.loads(_path(output_dir).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _write(output_dir: Any, state: dict[str, Any]) -> None:
    path = _path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**state, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                               indent=2), "utf-8")


def source_of(doc: dict) -> dict | None:
    """The connected Figma design (a UX Pilot one is not this branch's)."""
    return next((s for s in doc.get("designSources") or []
                 if isinstance(s, dict) and str(s.get("id") or "").startswith("FIGMA")), None)


def unchecked(doc: dict, output_dir: Any) -> bool:
    """A Figma design is connected and nobody has checked it against the requirements yet."""
    return source_of(doc) is not None and _read(output_dir) is None


def token_configured(output_dir: Any) -> bool:
    from services.figma.integrations import config_for

    try:
        if (config_for(output_dir) or {}).get(TOKEN_KEY):
            return True
    except Exception:  # noqa: BLE001 — unknown is "ask for it"
        pass
    return bool(os.environ.get(TOKEN_KEY, "").strip())


def set_treat_as(output_dir: Any, treat_as: str) -> None:
    """How the connected design is held: ``evidence`` (the requirements decide the page set and Forge
    designs what the design lacks) or ``specification`` (the frames ARE the page set)."""
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.load(output_dir=str(output_dir))
    for source in svc.doc.get("designSources") or []:
        if isinstance(source, dict) and str(source.get("id") or "").startswith("FIGMA"):
            source["treatAs"] = treat_as
    svc.save()


# --------------------------------------------------------------------------- #
# The messages
# --------------------------------------------------------------------------- #

def prompt(output_dir: Any, *, problem: str = "") -> dict[str, Any]:
    """The request for the design: a link, and the token when none is saved yet."""
    from services.smith.ui_designer import USE_FORGE_INSTEAD

    lead = (f"{problem}\n\n" if problem else "Figma it is. ")
    link_help = ("This needs a design you have already made in Figma: I read it from its link, I do not create "
                 "one (no design yet? choose Forge or UX Pilot instead). Paste the link to the FILE, or to the "
                 "page that holds all your screens, with the share link from Figma without a node-id: a link to "
                 "a single frame reads only that one screen.")
    link_field = {"label": "Link to your Figma file or screens", "placeholder": "https://www.figma.com/design/..."}
    if token_configured(output_dir):
        # The token is saved: only the link is asked for, in the card's own field (a plain input with a
        # button), so it does not depend on the chat box. `skipSave` tells the panel there is nothing to store.
        text = (f"{lead}{_PROMPT_MARK}: paste the link to it in the box below. Your Figma access token is "
                f"already saved. {link_help}")
        return {"text": text, "options": [USE_FORGE_INSTEAD], "status": "asked", "secret": {
            "provider": "figma", "key": TOKEN_KEY, "label": "Figma access token", "saved": FIGMA_SAVED,
            "action": "Read design", "skipSave": True, "extra": link_field}}
    text = (f"{lead}{_PROMPT_MARK}: paste the link and your Figma access token in the box below. The token is "
            f"saved, encrypted, with your organisation's integrations and is never written into this "
            f"conversation. Create one in Figma under Settings → Security → Personal access tokens, with "
            f"read access to files. {link_help}")
    return {"text": text, "options": [USE_FORGE_INSTEAD], "status": "asked", "secret": {
        "provider": "figma", "key": TOKEN_KEY, "label": "Figma access token", "placeholder": "figd_...",
        "saved": FIGMA_SAVED, "action": "Save and read design", "extra": link_field}}


def _pending_message(state: dict[str, Any]) -> dict[str, Any]:
    return {"text": str(state.get("report") or ""), "options": list(cov_mod.OPTIONS), "status": "asked"}


def stop(doc: dict, output_dir: Any) -> dict[str, Any] | None:
    """The message to show INSTEAD of starting the build, or None. Pure: reads what was stored."""
    if source_of(doc) is None:
        return prompt(output_dir)
    state = _read(output_dir)
    if state is None:
        # READ BUT NEVER CHECKED (the check was interrupted, or the design came with the brief): the
        # build does not start on a design nobody has judged against the requirements.
        from services.smith.ui_designer import USE_FORGE_INSTEAD

        return {"text": f"Your Figma design is connected but {_CHECK_MARK}. Shall I check it now?",
                "options": [CHECK_NOW, USE_FORGE_INSTEAD], "status": "asked"}
    if state.get("decision") == "pending":
        return _pending_message(state)
    return None


# --------------------------------------------------------------------------- #
# The work
# --------------------------------------------------------------------------- #

def _client() -> Any:
    from services.blueprint.executors import tiered_router

    return tiered_router().for_task("figma_coverage", "figma_intelligence")


def _connect(output_dir: Any, url: str) -> None:
    from services.smith.figma_connect import connect

    connect(output_dir, figma_url=url, token_env=TOKEN_KEY, treat_as="evidence")


def _judge(output_dir: Any, client: Any, url: str) -> Outcome:
    """Check the connected design and decide whether the build may go on."""
    from services.blueprint.service import BlueprintService

    doc = BlueprintService.load(output_dir=str(output_dir)).doc
    try:
        cov = cov_mod.check(doc, output_dir, client if client is not None else _client())
    except cov_mod.CoverageUnavailable as exc:
        # The design is connected; only the check could not be made. Held as evidence, so Forge
        # designs whatever the design lacks, and the person is told the check did not happen.
        _write(output_dir, {"decision": "ok", "sufficient": None, "url": url, "report": ""})
        return Outcome({"text": f"{exc} Building with your design as the starting point; Forge will design "
                                f"anything it does not show.", "status": "reported"}, True)
    report = cov_mod.report(cov)
    if cov.sufficient:
        _write(output_dir, {"decision": "ok", "sufficient": True, "url": url, "report": report,
                            "coverage": cov.as_dict()})
        return Outcome({"text": report, "status": "reported"}, True)
    _write(output_dir, {"decision": "pending", "sufficient": False, "url": url, "report": report,
                        "coverage": cov.as_dict()})
    return Outcome(_pending_message({"report": report}), False)


def handle(svc: Any, output_dir: Any, *, link: str = "", choice: str = "",
           client: Any = None, connect: Callable[[Any, str], None] | None = None) -> Outcome:
    """One Figma step: a link was given, a way forward was chosen, or a connected design needs its check.

    ``connect`` and ``client`` are the two things that reach the network; they are parameters so the
    flow is tested without either.

    THE CHECK IS SPEND. It runs from the chat route, outside any Smith turn, so its model calls
    belonged to no usage scope and never reached the organisation's ledger (PR #34 review)."""
    from services.build_usage import usage_scope

    with usage_scope(agent="figma_coverage", output_dir=str(output_dir or ""), phase="define", kind="smith"):
        return _handle(svc, output_dir, link=link, choice=choice, client=client, connect=connect)


def _handle(svc: Any, output_dir: Any, *, link: str = "", choice: str = "",
            client: Any = None, connect: Callable[[Any, str], None] | None = None) -> Outcome:
    from services.smith.figma_connect import FigmaConnectError

    do_connect = connect or _connect
    state = _read(output_dir) or {}
    if choice in ("fill", "only"):
        set_treat_as(output_dir, "evidence" if choice == "fill" else "specification")
        _write(output_dir, {**state, "decision": "ok"})
        said = ("Your frames are built as drawn and Forge designs the screens they do not show, in the same style."
                if choice == "fill" else
                "The application is exactly the screens in your design: nothing is added around them.")
        return Outcome({"text": said + " Building now.", "status": "reported"}, True)

    url = link or str(state.get("url") or (source_of(svc.doc) or {}).get("url") or "")
    if (link or choice == "update") and not url:
        return Outcome(prompt(output_dir, problem="I do not have a link to read."), False)
    try:
        if link or choice == "update":
            do_connect(output_dir, url)
    except FigmaConnectError as exc:
        return Outcome(prompt(output_dir, problem=f"I could not read that design: {exc}"), False)
    except Exception as exc:  # noqa: BLE001 — said to the person; the definition stands
        logger.warning("[figma-gate] connect failed: %s: %s", type(exc).__name__, str(exc)[:200])
        return Outcome(prompt(output_dir, problem=f"I could not read that design ({type(exc).__name__})."), False)
    return _judge(output_dir, client, url)
