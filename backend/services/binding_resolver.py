"""Answer the entity questions the deterministic binder could not.

Why this module exists
----------------------
`_resolve_entity` matches entity aliases as SUBSTRINGS of a path or a label.
That is right most of the time and free, and it is why this module only ever
sees the residue. But it cannot resolve a label that contains no entity name:

    quorumGauge, label 'نسبة النصاب القانوني'  → fell back to Bill
    KeyValueList on /sessions/[id]              → fell back to Attendance
    assignedAssessorId                          → no table is called Assessor

Every one of those is a judgement a reader makes instantly from the route, the
label and the list of entities that exist. None of them is a string operation.
So the binder stops pretending: it emits a question, and this answers it.

The contract that keeps it safe
-------------------------------
* **Closed set.** An answer is honoured only if it names one of the candidates
  the question carried. An invented entity would become a dataSource nothing
  serves — the exact failure the closed set exists to prevent.
* **Residue only.** No questions means no call. Bindings that resolved
  deterministically are never re-litigated, so this costs nothing on the pages
  that were already right.
* **Never fatal.** A provider that errors, times out or returns junk yields no
  answers and the binder keeps its own fallback. A resolver outage degrades
  composition quality; it must not fail a build.
* **Silence is an answer.** A question the model declines to answer stays
  unanswered rather than being forced — "I don't know which entity this is"
  is more useful than a confident wrong pick, which is what we already have.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# prompt -> raw model text. Injected in tests; the default calls the LLM.
Provider = Callable[[str], str]

MAX_QUESTIONS = int(os.environ.get("FORGE_BINDING_RESOLVER_MAX", "12"))


def _entity_lines(registry: dict, candidates: list[str]) -> list[str]:
    """Each candidate with a few of its columns — enough to tell Session from
    Attendance without pasting the whole schema into the prompt."""
    ents = (registry or {}).get("entities") or {}
    out: list[str] = []
    for name in candidates:
        cols = [c.get("name") for c in (ents.get(name) or {}).get("columns") or []]
        cols = [c for c in cols if c][:8]
        out.append(f"  - {name}: {', '.join(cols) if cols else '(no columns)'}")
    return out


def build_prompt(questions: list[dict], *, registry: dict, route: str,
                 kind: str = "") -> str:
    """The whole prompt. Separate from the call so a test can read it."""
    candidates: list[str] = []
    for q in questions:
        for c in q.get("candidates") or []:
            if c not in candidates:
                candidates.append(c)

    lines = [
        "A UI composer proposed components for one page of a generated app.",
        "For each component below, the binder could not tell which entity it "
        "reads from, and fell back to a guess.",
        "",
        f"ROUTE: {route}",
    ]
    if kind:
        lines.append(f"PAGE KIND: {kind}")
    lines += [
        "",
        "ENTITIES THAT EXIST (you may answer ONLY with a name from this list):",
        *_entity_lines(registry, candidates),
        "",
        "COMPONENTS NEEDING AN ENTITY:",
    ]
    for q in questions:
        lines.append(
            f"  - id={q.get('component')!r} label={q.get('label')!r} "
            f"path={q.get('path')!r} (binder guessed {q.get('assumed')!r})")
    lines += [
        "",
        "Use the route and the label to decide what each component is ABOUT.",
        "Labels may be in any language. A label naming a concept that belongs "
        "to one entity (a quorum belongs to a session, an assessor is a user "
        "in a role) should resolve to that entity even when the words do not "
        "match the entity name.",
        "",
        "If you cannot tell, OMIT that component. An omission keeps the "
        "binder's own fallback; a wrong answer ships a page that looks correct "
        "and reports the wrong number, which is far more expensive.",
        "",
        'Reply with JSON only: {"<component id>": "<EntityName>", ...}',
    ]
    return "\n".join(lines)


def _parse(text: str) -> dict:
    """Model text → dict. Tolerates prose or a fenced block around the JSON."""
    if not isinstance(text, str) or not text.strip():
        return {}
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def _default_provider(prompt: str) -> str:
    # `complete` is keyword-only — passing the prompt positionally raises
    # "takes 0 positional arguments", which the caller swallows as a resolver
    # outage and silently keeps every guess. Cost a live run its answers once.
    from services.llm_client import complete
    return complete(content=prompt, max_tokens=1024)


def resolve_entities(questions: list[dict], *, registry: dict, route: str,
                     kind: str = "",
                     provider: Optional[Provider] = None) -> dict[str, str]:
    """questions → {component id: entity}. Only answers inside the closed set.

    Never raises: an unavailable resolver returns no answers and the binder
    keeps the fallback it already had.
    """
    qs = [q for q in (questions or []) if isinstance(q, dict) and q.get("component")]
    if not qs:
        return {}  # nothing guessed — don't pay for a call that has no question
    if len(qs) > MAX_QUESTIONS:
        logger.info("[binding-resolver] %d questions, asking the first %d",
                    len(qs), MAX_QUESTIONS)
        qs = qs[:MAX_QUESTIONS]

    call = provider or _default_provider
    try:
        raw = call(build_prompt(qs, registry=registry, route=route, kind=kind))
    except Exception as exc:  # noqa: BLE001 — quality degrades, build does not
        logger.warning("[binding-resolver] provider failed: %s", exc)
        return {}

    proposed = _parse(raw)
    if not isinstance(proposed, dict):
        return {}

    allowed = {q["component"]: set(q.get("candidates") or []) for q in qs}
    answers: dict[str, str] = {}
    for cid, ent in proposed.items():
        cid, ent = str(cid), str(ent)
        if cid not in allowed:
            continue  # answered something nobody asked about
        if ent not in allowed[cid]:
            logger.info("[binding-resolver] %s: %r is not a registered entity "
                        "— ignored", cid, ent)
            continue
        answers[cid] = ent
    return answers
