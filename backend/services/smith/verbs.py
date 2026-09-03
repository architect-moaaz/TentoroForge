"""What a turn is asking for, and what each kind of asking needs.

`_UNDERSTAND_ASK_REQUIRED` demanded `screen`, `element_label`,
`current_behavior`, `desired_behavior` and `target_file` of every request. All
five describe a rename. So "build a dashboard at / with five widgets" could not
be EXPRESSED in the structure Smith answers in, let alone executed — the model
either failed validation or produced an `element_label` it had invented, and
the dispatcher then found nothing to rename and reported that the current state
already matched.

The fix is not to make the fields optional. That turns a mis-shaped contract
into no contract, and the relevance check that closes the "cheapest-edit-wins"
loophole — diff must touch `target_file` + `element_label` — depends on them
being present FOR A RENAME. Requirements are per verb, because a rename and a
composition genuinely need different facts.

WHY A CLOSED SET. An open `verb` string would let the model invent
`refactor_everything` and the dispatcher would fall through to the same silent
no-op this exists to remove. Unknown verbs are named as unknown and answered
honestly.
"""

from __future__ import annotations

#: verb -> the fields a turn must carry to be actionable.
#:
#: `rename` keeps exactly what it always required. The others ask for what
#: their own machinery needs and nothing more: a composition needs a route, not
#: a `current_behavior` for a page that does not exist yet.
REQUIRED_BY_VERB: dict[str, set[str]] = {
    "rename": {"screen", "element_label", "current_behavior",
               "desired_behavior", "target_file"},
    "compose_route": {"route"},
    "add_widgets": {"route", "widgets"},
    # `token_env` is the NAME of an environment variable, never the token.
    # §42 puts `chat history` first on the list of places the raw
    # credential must not come to rest, and Smith's conversation is
    # persisted — so the field Smith may ask for is the reference.
    "connect_figma": {"figma_url", "token_env"},
    "rebuild": set(),
}

#: What each verb is for, in the words a model should recognise. Shown in the
#: tool description so the choice is made from a list rather than guessed.
VERB_HELP: dict[str, str] = {
    "rename": (
        "Change the wording of something that already exists. Needs the exact "
        "current text and what it should say instead."
    ),
    "compose_route": (
        "Build or rebuild the screen at a route — when a route renders "
        "nothing, or the user wants it laid out again from scratch."
    ),
    "add_widgets": (
        "Add named sections or widgets to a screen that exists: "
        '"put upcoming sessions and quorum status on the dashboard".'
    ),
    "connect_figma": (
        "Attach a Figma design as evidence for the application: \"use this "
        "Figma design <url>\". Needs the design URL and the NAME of the "
        "environment variable holding the Figma token — never the token."
    ),
    "rebuild": (
        "Regenerate the application from its definition. The honest answer "
        "when a change is larger than a single screen."
    ),
}

DEFAULT_VERB = "rename"


def verb_of(understanding: dict) -> str:
    """The verb this understanding is asking for.

    Defaults to `rename` when unset, so an older caller — or a model that
    ignores the field — behaves exactly as before rather than falling into an
    unknown-verb branch it has never seen.
    """
    verb = str((understanding or {}).get("verb") or "").strip().lower()
    return verb or DEFAULT_VERB


def missing_fields(understanding: dict) -> list[str]:
    """Fields this verb needs and does not have.

    A list value counts as present when it is non-empty: `widgets` is the point
    of `add_widgets`, and an empty list is the request without its content.
    """
    verb = verb_of(understanding)
    required = REQUIRED_BY_VERB.get(verb)
    if required is None:
        return []                      # unknown verb: reported separately
    out = []
    for key in sorted(required):
        value = (understanding or {}).get(key)
        if isinstance(value, str):
            if not value.strip():
                out.append(key)
        elif isinstance(value, (list, tuple)):
            if not value:
                out.append(key)
        elif value is None:
            out.append(key)
    return out


def is_known(understanding: dict) -> bool:
    return verb_of(understanding) in REQUIRED_BY_VERB
