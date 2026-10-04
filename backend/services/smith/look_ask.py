"""A request to LOOK is a question, not a change.

"Show me the screens" while a plan was waiting was read as one more thing to
do: Smith added "Show the screens so you can see the result" as the plan's
third step instead of showing them (UAT Med Tracker). Looking changes nothing,
so it is answered at once and never joins, creates or alters a waiting plan or
a held question.

Deliberately narrow: the whole message must be a request to see the app, its
screens or the preview. "Show a delete button on each row" is a change and
falls through to the normal path.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_THING = r"(?:the |my |our )?(?:app|application|screens?|pages?|preview|result|results|it|everything|what (?:you|i|we)(?:'ve| have)? (?:built|made|done))"
_LOOK = re.compile(
    r"^(?:(?:please|ok|okay|can you|could you|can i|let me|i want to|i'd like to|i would like to)\s+)*"
    r"(?:"
    r"show(?: me)?|display|open|launch|preview|view|see|look at|let me see|let me look at|take a look at|have a look at|"
    r"go to|bring up"
    r")\s+" + _THING + r"(?:\s+(?:again|now|first|so i can (?:see|check) (?:it|them)))?$"
    r"|^what does (?:it|the app|the application) look like$"
    r"|^let me see(?: it)?$|^show me$|^preview$|^open (?:the )?preview$",
    re.I,
)


def is_look_request(message: str) -> bool:
    m = " ".join((message or "").strip().lower().rstrip(".!?").split())
    return bool(m) and bool(_LOOK.match(m))


def answer(output_dir: str | Path) -> str:
    """The screens, as the Blueprint has them, and how to open them."""
    pages: list[dict] = []
    try:
        from services.blueprint.service import BlueprintService
        doc = BlueprintService.load(output_dir=str(output_dir)).doc
        pages = [p for p in doc.get("pages") or [] if isinstance(p, dict)
                 and str(p.get("status") or "").upper() not in ("DEPRECATED", "SUPERSEDED")]
    except Exception:  # noqa: BLE001 — nothing to list is still an answer
        pages = []
    built = (Path(output_dir) / "app" / "package.json").is_file()
    if not pages:
        return "There are no screens yet. Tell me what the app should show."
    lines = [f"- **{p.get('name') or p.get('id')}** — `{p.get('route') or ''}`" for p in pages]
    how = ("Open the Preview to click through them" if built else
           "They are not built yet — approve the definition and build, then open the Preview to click through them")
    return "These are the screens:\n" + "\n".join(lines) + f"\n\n{how}. Anything waiting is still waiting."


__all__ = ["is_look_request", "answer"]
