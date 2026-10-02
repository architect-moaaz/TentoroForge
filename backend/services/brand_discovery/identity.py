"""Who you are, what you do, how you do it — read off the company's own site.

THE THREE QUESTIONS ARE THE INTERVIEW, and the site has usually answered all
three already. A homepage says who the company is in its hero, what it does in
its feature sections, and how it does it in the words it chooses to do that
in. Asking a person to retype that during onboarding is asking them to
transcribe their own marketing site, which is why the discovery starts by
reading rather than by asking — and why every answer it produces is editable
afterwards. The read is a first draft, not a verdict.

A MODEL HERE, UNLIKE `design.py`. The colour of a button is a fact and reading
it with a model would only add error. "What does this company do" is not a
fact on the page, it is the summary of a page, and summarising is the thing a
model is actually for. The division is the same one the Blueprint draws
between a service node and an agent node.

WHAT IT MAY NOT DO. It may not invent. A site that never says what industry it
is in gets `industry: ""` and the person fills it in; a model that guesses
"SaaS" because the page has a pricing table has put a word into a company's
mouth and then every app built afterwards inherits it. The prompt says so and
the parse drops anything that is not a string.

NO KEY, NO FAILURE. Without `ANTHROPIC_API_KEY` this returns what the page
stated outright — its title and its meta description — under `what_you_do`,
and says in `source` that nobody read it. Onboarding still completes, the
design language is still extracted, and Settings still offers to finish the
identity later.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re

from services.brand_discovery.site import Reading

logger = logging.getLogger(__name__)

#: The keys the rest of the system reads off `identity`. Stated here because
#: the model's JSON is untrusted: anything outside this set is dropped rather
#: than stored, so a hallucinated field cannot reach a prompt later.
FIELDS: tuple[str, ...] = (
    "who_you_are", "what_you_do", "how_you_do_it",
    "industry", "audience", "tone", "voice", "values",
)

#: Free-text fields are capped so one strange page cannot push a wall of text
#: into every agent prompt for the life of the organisation.
_MAX_CHARS = 600

_SYSTEM = """You are reading a company's own website to fill in a short profile \
of that company. The profile is shown back to the person who works there, who \
will correct it — so a careful, plain reading is worth far more than an \
impressive one.

Answer ONLY from what the page says. If the page does not say something, give \
an empty string for it. Do not infer an industry from a pricing table, do not \
name an audience the page never addresses, and never write marketing copy of \
your own — you are summarising theirs.

Return ONLY a JSON object, no prose around it, with exactly these keys:

  who_you_are     One or two sentences: what this organisation IS. The kind of
                  company, what it exists to do, who runs it if the page says.
  what_you_do     One or two sentences: the product or service, in the page's
                  own vocabulary. Use their words for their own things.
  how_you_do_it   One or two sentences: how they say they work — their method,
                  their model, what they claim makes their way different.
  industry        Two or three words, lowercase, or "".
  audience        Who the page is addressed to, in a short phrase, or "".
  tone            Three or four adjectives for how the writing sounds,
                  comma-separated. Read the copy, not the pictures.
  voice           One short sentence a writer could follow to sound like them.
  values          Up to four short phrases the page states as what they stand
                  for, comma-separated, or "".

The vocabulary matters more than the polish. An application built for this \
company should call things what this company calls them."""


def _fallback(reading: Reading) -> dict:
    """What the page stated outright, with nothing read into it."""
    return {
        "who_you_are": "",
        "what_you_do": (reading.description or reading.title or "").strip()[:_MAX_CHARS],
        "how_you_do_it": "",
        "industry": "",
        "audience": "",
        "tone": "",
        "voice": "",
        "values": "",
        "source": "the page's own description — nobody has read the site yet",
    }


def _clean(raw: dict) -> dict:
    """Only the declared keys, only strings, trimmed."""
    out: dict = {}
    for key in FIELDS:
        value = raw.get(key)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        out[key] = str(value or "").strip()[:_MAX_CHARS]
    return out


_JSON = re.compile(r"\{.*\}", re.S)


def _parse(text: str) -> dict | None:
    """The JSON object in a reply, or None.

    Tolerant of a model that wraps its answer in a fence or a sentence,
    because a reply that is 99% right should not cost the person their
    onboarding.
    """
    m = _JSON.search(text or "")
    if not m:
        return None
    try:
        loaded = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


async def read_identity(reading: Reading) -> dict:
    """The three answers plus their surroundings. Never raises.

    The screenshot goes with the words when there is one: how a company
    presents itself is half of how it sounds, and the tone read from prose
    alone misses a site that is playful in everything except its sentences.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not (reading.text or reading.description or reading.title):
        return _fallback(reading)

    page = "\n".join(filter(None, [
        f"URL: {reading.url}",
        f"Title: {reading.title}" if reading.title else "",
        f"Meta description: {reading.description}" if reading.description else "",
        f"Site name: {reading.site_name}" if reading.site_name else "",
        "",
        "--- the page's visible text ---",
        (reading.text or "")[:9000],
    ]))

    content: list[dict] = [{"type": "text", "text": page}]
    if reading.screenshot:
        content.insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": base64.b64encode(reading.screenshot).decode()},
        })

    try:
        from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)

        client = AsyncAnthropic(api_key=key)
        msg = await client.messages.create(
            model=os.environ.get("FORGE_BRAND_MODEL",
                                 os.environ.get("FORGE_TRANSFORMER_MODEL",
                                                "claude-sonnet-4-6")),
            max_tokens=1500,
            system=_SYSTEM,
            messages=[{"role": "user", "content": content}],
            temperature=0.0,
        )
        text = "".join(block.text for block in msg.content
                       if getattr(block, "type", "") == "text")
    except Exception as exc:  # noqa: BLE001 — onboarding survives a bad call
        logger.warning("[brand] identity read failed for %s: %s", reading.url, exc)
        return _fallback(reading)

    parsed = _parse(text)
    if parsed is None:
        logger.warning("[brand] identity reply was not JSON for %s", reading.url)
        return _fallback(reading)

    out = _clean(parsed)
    out["source"] = (f"read from {reading.url}"
                     + ("" if reading.rendered else " (page source only)"))
    return out


def company_name(reading: Reading, identity: dict) -> str:
    """The best available name for the company, or "".

    `og:site_name` is the one place a site states its own name as a name;
    everything else is a title with a tagline welded to it, so the separators
    a title uses are cut off rather than carried into an organisation's name.
    """
    if reading.site_name.strip():
        return reading.site_name.strip()[:120]
    title = (reading.title or "").strip()
    if title:
        return re.split(r"\s+[|–—\-·:]\s+", title)[0].strip()[:120]
    host = re.sub(r"^www\.", "", (reading.url.split("//")[-1].split("/")[0]))
    return host.split(".")[0].title() if host else ""
