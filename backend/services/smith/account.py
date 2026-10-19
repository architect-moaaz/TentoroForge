"""The account a fix turn ends with: what was happening, what changed, what
proved it.

"Changed `globals.css`: make the background dark blue" is a receipt. The
account a good engineer gives has three parts — the mechanism in plain
words, the change, and the proof — and it is what the person reads to
decide whether to trust the fix (2026-10-17, against a Claude Code
transcript the owner held up as the standard). Deterministic where it can
be (the proof is the try that passed, in its own words); one small model
call for the mechanism, with a plain fallback when the call fails.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from services.smith import tools
from services.smith.loop import Observation

logger = logging.getLogger(__name__)

SYSTEM = (
    "You write the two-sentence account of a fault an engineer just fixed in a web application, for the "
    "person who owns it. Sentence one: what was happening, from the failing try — the screen or process "
    "by the name the person knows, what they saw. Sentence two: why — the mechanism, from the change that "
    "fixed it, in plain words (name a file only when it helps the person; never a step number, never a "
    "tool name). No preamble, no bullet points, no 'I'. Under 60 words."
)
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["account"],
          "properties": {"account": {"type": "string"}}}

_client: Callable[..., str] | None = None


def _head(text: str, n: int = 220) -> str:
    return " ".join((text or "").split("\n", 1)[0].split())[:n]


def _try_words(o: Observation) -> str:
    """A try, said the way a person would: 'opening /orders as a Manager'."""
    a = o.args or {}
    who = f" as {a['as']}" if a.get("as") else ""
    if o.tool == "open_page":
        return f"opening {a.get('route') or '/'}{who}"
    if o.tool == "try_workflow":
        return f"running {a.get('workflow') or 'the process'}{who}"
    if o.tool == "try_request":
        return f"asking the app {str(a.get('method') or 'GET').upper()} {a.get('path') or '/'}{who}"
    if o.tool == "run_checks":
        return f"running the application's {a.get('what') or 'own'} checks"
    if o.tool == "try_upload":
        return f"uploading a {a.get('kind') or 'file'}{who}"
    return o.tool


def fix_evidence(observations: list[Observation]) -> dict | None:
    """The failing try before a change and the same try passing after it —
    what makes a turn a fix. None when the turn has no such pair."""
    from services.smith import trials
    from services.smith4.turn import _is_change, _trial_key, inconclusive

    changes = [i for i, o in enumerate(observations) if _is_change(o)]
    if not changes:
        return None
    last_change = changes[-1]
    after = [(i, o) for i, o in enumerate(observations) if i > last_change and tools.is_trial(o.tool)
             and o.status == "read" and o.said and not inconclusive(o.said) and not trials.failed(o.said)]
    if not after:
        return None
    for i_pass, passed in reversed(after):
        key = _trial_key(passed)
        before = [o for j, o in enumerate(observations) if j < last_change
                  and tools.is_trial(o.tool) and o.status == "read" and _trial_key(o) == key
                  and trials.failed(o.said or "")]
        if before:
            changed = [o for i, o in enumerate(observations) if _is_change(o)]
            return {"failed": before[0], "passed": passed, "changes": changed}
    return None


def proof_line(evidence: dict) -> str:
    passed, failed = evidence["passed"], evidence["failed"]
    return (f"What proved it: {_try_words(passed)} showed “{_head(failed.said, 140)}” before the change; "
            f"after it, the same try came back “{_head(passed.said, 140)}”.")


def _fallback(evidence: dict) -> str:
    failed = evidence["failed"]
    why = ""
    for o in evidence["changes"]:
        a = o.args or {}
        why = str(a.get("because") or a.get("why") or "").strip()
        if why:
            break
    return (f"What was happening: {_try_words(failed)} showed “{_head(failed.said, 160)}”."
            + (f" The cause: {why[:200]}." if why else ""))


def happening(ask: str, evidence: dict, client: Callable[..., str] | None = None) -> str:
    """Sentence one and two, from the model; the deterministic line when the
    call fails or says nothing."""
    client = client or _client or _default_client()
    if client is None:
        return _fallback(evidence)
    failed, passed = evidence["failed"], evidence["passed"]
    changes = "\n".join(f"- {o.tool} {json.dumps({k: v for k, v in (o.args or {}).items() if k != 'content'}, default=str)[:300]}: "
                        f"{_head(o.said, 200)}" for o in evidence["changes"][-4:])
    user = (f"The person asked: {ask[:400]}\n\nThe try that failed ({_try_words(failed)}):\n{failed.said[:1800]}\n\n"
            f"The change(s):\n{changes}\n\nThe same try afterwards ({_try_words(passed)}):\n{passed.said[:600]}")
    try:
        raw = client(system=SYSTEM, user=user, schema=SCHEMA)
        text = str((json.loads(raw) if isinstance(raw, str) else raw).get("account") or "").strip()
    except Exception:  # noqa: BLE001 — the account is a courtesy; the fallback is still true
        logger.debug("[account] the model's account could not be had", exc_info=True)
        text = ""
    if not text:
        return _fallback(evidence)
    return "What was happening: " + text


def _default_client() -> Callable[..., str] | None:
    try:
        from services.blueprint.executors import AGENT_MODEL, AnthropicModel
        return AnthropicModel(model=AGENT_MODEL, effort="low")
    except Exception:  # noqa: BLE001
        return None


def compose(ask: str, observations: list[Observation], said: str, *, client: Callable[..., str] | None = None) -> str:
    """The three-part ending for a fix turn; `said` unchanged when the turn
    was not one."""
    evidence = fix_evidence(observations)
    if evidence is None:
        return said
    parts = [happening(ask, evidence, client), said.strip(), proof_line(evidence)]
    return "\n\n".join(p for p in parts if p)


__all__ = ["compose", "fix_evidence", "happening", "proof_line"]
