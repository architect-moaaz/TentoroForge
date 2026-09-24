"""The verbs, as the tool catalogue of a loop (S1, `2026-09-24-smith-as-a-loop`).

There is no second list in this file. A tool IS a verb: its name is the verb's
name, its description is the verb's own help text (``VERB_HELP`` — the same
sentences ``capabilities.nearest`` offers as chips), and its required arguments
are the fields the verb already declares (``REQUIRED_BY_VERB``). A verb added
to :mod:`services.smith.verbs` is a tool in the same commit, and a tool that is
not a verb cannot be written here at all.

WHY THE NAME IS STILL CLOSED. `verbs.py` argues it for the dispatcher and it is
just as true for a loop: an open tool name lets the model invent
``refactor_everything``, and the dispatcher falls through to the silent no-op
the closed set exists to remove. A name outside this catalogue is a tool
ERROR — handed back as the loop's next observation, so the model picks again
and nothing has been written. The loop changes who chooses the next step. It
does not widen what may be chosen.

SINCE 2026-09-25 THE CATALOGUE IS NOT ONLY VERBS. `reads.READS` — `read_file`,
`grep`, `read_page_code` and the rest — are the loop's eyes (spec §0: "knows
the whole code in and out"). They write nothing, so none of the machinery a
verb needs applies to them: no baseline, no proof, no capability. They are
listed apart in the rendered catalogue because a model choosing between
looking and acting should see which is which.

Three moves are not verbs. ``done``, ``answer`` and ``ask_user`` end the loop
rather than change anything. They are the terminal set the legacy Smith already
had (``agents/smith_agent.py``), and they are the one part of that palette worth
carrying forward unchanged.

THE TYPES ARE HERE BECAUSE THEY ARE NOWHERE ELSE. `REQUIRED_BY_VERB` names
fields and says nothing about their shape; `understand_ask` builds the shape in
a return statement a prompt cannot read. :data:`FIELD_TYPES` is that shape
written down once, and `test_every_required_field_has_a_type` fails the moment
a verb requires a field this table has never heard of — so a new field is
declared rather than silently arriving as a string.
"""
from __future__ import annotations

from services.smith.reads import READ_NAMES, READS
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP
from services.smith.writes import WRITE_NAMES, WRITES

#: The shape of every field a verb can require. Strings unless said otherwise;
#: the two exceptions are the two the understanding itself special-cases.
FIELD_TYPES: dict[str, str] = {
    "api": "string",
    "change": "string",
    "current_behavior": "string",
    "desired_behavior": "string",
    "element_label": "string",
    "email": "string",
    "entity": "string",
    "field": "object",          # {name, type} for add_field; {name} otherwise
    "figma_url": "string",
    "integration": "string",
    "key_env": "string",
    "new_value": "string",
    "person": "string",
    "requirement": "string",
    "route": "string",
    "rule": "string",
    "screen": "string",
    "target_file": "string",
    "token_env": "string",
    "uxpilot_ref": "string",
    "widgets": "array",         # of strings
    "workflow": "string",
}

#: What ends the loop. `(name, description, arguments)`.
#:
#: `done` carries no argument on purpose: what was done is in the observations,
#: and a summary the model writes at the end is a chance for it to describe a
#: change that did not happen. The turn's answer is assembled from what the
#: seams reported, never from this.
TERMINAL: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("done",
     "Everything they asked for has been done. Ends the turn; the reply is "
     "written from what the steps actually reported, not from you.",
     ()),
    ("answer",
     "They asked something rather than asked for something, or there is "
     "nothing left to change and it needs saying. Ends the turn with `text`.",
     ("text",)),
    ("ask_user",
     "You cannot pick the next step without a fact only they have. Ends the "
     "turn with `question`. Asking is not a failure — acting on the wrong "
     "reading is.",
     ("question",)),
)

TERMINAL_NAMES: frozenset[str] = frozenset(name for name, _d, _a in TERMINAL)


def catalogue() -> list[dict]:
    """Every verb as a tool, in the order `REQUIRED_BY_VERB` declares them."""
    out: list[dict] = []
    for verb, required in REQUIRED_BY_VERB.items():
        out.append({
            "name": verb,
            "description": VERB_HELP.get(verb, ""),
            "required": sorted(required),
            "properties": {f: FIELD_TYPES[f] for f in sorted(required)},
        })
    return out


def is_tool(name: str) -> bool:
    """Whether `name` is something the loop may call at all."""
    name = (name or "").strip()
    return (name in REQUIRED_BY_VERB or name in READ_NAMES or name in WRITE_NAMES
            or name in TERMINAL_NAMES)


def is_read(name: str) -> bool:
    """A read looks and writes nothing: no baseline, no proof, no boundary."""
    return (name or "").strip() in READ_NAMES


def is_write(name: str) -> bool:
    """A write primitive: code, through the build's own seam, not a verb."""
    return (name or "").strip() in WRITE_NAMES


def unknown(name: str) -> str:
    """What a tool error says. Named, never mapped onto the nearest verb.

    `turn.py`'s rule holds here: a plan naming something that does not exist is
    re-asked with the failure named, not patched into the closest thing that
    does. The difference a loop makes is that the model now gets to act on the
    failure instead of the turn ending on it.
    """
    return (f"There is no tool called `{(name or '').strip() or '(nothing)'}`. "
            "Pick one from the list, or end with done / answer / ask_user.")


def render() -> str:
    """The catalogue as the text a prompt carries."""
    lines: list[str] = []
    for tool in catalogue():
        args = ", ".join(f"{f}: {tool['properties'][f]}" for f in tool["required"])
        head = f"- `{tool['name']}`" + (f" ({args})" if args else " (no arguments)")
        lines.append(head)
        if tool["description"]:
            lines.append(f"    {' '.join(tool['description'].split())}")
    lines.append("")
    lines.append("Looking (these change nothing, and cost a step like anything else):")
    for name, said, args in READS:
        shown = ", ".join(f"{a}: {t}" for a, t in args.items())
        lines.append(f"- `{name}` ({shown})")
        lines.append(f"    {' '.join(said.split())}")
    lines.append("")
    lines.append("Changing code (after reading it; the compiler's verdict comes back):")
    for name, said, args in WRITES:
        shown = ", ".join(f"{a}: {t}" for a, t in args.items())
        lines.append(f"- `{name}` ({shown})")
        lines.append(f"    {' '.join(said.split())}")
    lines.append("")
    lines.append("Ending the turn:")
    for name, said, args in TERMINAL:
        shown = ", ".join(f"{a}: string" for a in args) or "no arguments"
        lines.append(f"- `{name}` ({shown})")
        lines.append(f"    {' '.join(said.split())}")
    return "\n".join(lines)


def untyped() -> frozenset[str]:
    """Required fields :data:`FIELD_TYPES` has never heard of. Empty, or the
    catalogue is describing an argument it cannot say the shape of."""
    required = {f for fields in REQUIRED_BY_VERB.values() for f in fields}
    return frozenset(required - set(FIELD_TYPES))


__all__ = ["FIELD_TYPES", "TERMINAL", "TERMINAL_NAMES", "catalogue", "is_read",
           "is_tool", "is_write", "render", "unknown", "untyped"]
