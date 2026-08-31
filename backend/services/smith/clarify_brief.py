"""§16 — ask before defining, when the brief leaves something material unsaid.

Smith asks well once an application exists: `understand_ask` weighs a change
against the Blueprint and returns a question rather than a guess. Before the
first definition it asked nothing at all. A brief went straight to the DAG
under "Let me define that first", and whatever it had not said was settled by
twenty agents inventing an answer each.

That is the expensive place to guess. A definition run costs a couple of
minutes and every later node builds on it, so a question worth thirty seconds
here saves a rebuild.

ONE ROUND, AND ONLY AT THE START. Asked only when the conversation has no
history — the first thing anybody says. Once they have answered, or said
anything at all, the next message defines. A clarifier that can fire twice is
a clarifier that can fire forever, and §16 wants Smith to ask rather than to
interrogate.

SILENCE IS THE DEFAULT. A brief that names what the application is for and
what people do in it needs no question, and asking anyway is worse than not
asking: it reads as not having listened. Every failure — no provider, bad
JSON, an empty answer — resolves to no question and the definition proceeds.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_PROMPT = """Someone has described an application they want built. It will now
be defined in detail by a team of agents, and anything the description leaves
unsaid will be decided for them.

Ask ONE question, only if the answer would change what gets built. Worth
asking: who uses this and whether they are different kinds of people; whether
records are shared or private; what happens to something after the last step
they mention. Not worth asking: anything you can reasonably decide (visual
style, field ordering, wording), anything they have already said, or a
question so broad it just asks them to write the brief again.

Most good descriptions need no question. Returning none is the common case and
the right one.

Return ONLY a JSON object:

  "question": the one question, in plain language, or "" to ask nothing.
  "options": 2-4 short concrete answers they could pick, or [] if the question
      is genuinely open. Offering answers is how a question stops being
      homework.

Do not explain. Do not wrap the JSON in prose or code fences.

WHAT THEY WROTE:
{brief}"""


def _default_provider(prompt: str) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=400)


def clarify_brief(
    brief: str,
    *,
    provider: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """`{question, options}` — or empty when the brief stands on its own."""
    text = (brief or "").strip()
    empty: dict[str, Any] = {"question": "", "options": []}
    if not text:
        return empty

    call = provider or _default_provider
    try:
        raw = call(_PROMPT.format(brief=text))
    except Exception:  # noqa: BLE001 — a question is a courtesy, never a gate
        return empty

    data = _parse(raw)
    if not isinstance(data, dict):
        return empty

    question = str(data.get("question") or "").strip()
    if not question:
        return empty
    options = [str(o).strip() for o in (data.get("options") or [])
               if str(o).strip()]
    return {"question": question, "options": options[:4]}


def _parse(raw: str) -> dict | None:
    """The JSON object in `raw`, however it was wrapped."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:  # noqa: BLE001
        return None
