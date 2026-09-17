"""What Smith can do, in one place, because it is answered in three.

"What can you do?" was answered by the model paraphrasing the verb list in
`understand_ask`'s prompt, and the unknown-verb reply ran the same thirty
entries together in one semicolon-separated sentence. Both listed the CHANGES
and nothing else, so two real capabilities never appeared: `verify & fix`,
which is offered by name the moment a build finishes, and the lifecycle
commands — `status`, `preview`, `export`, and publishing, which is refused.
Someone asking what Smith can do was told about thirty things it does to an
application and none of the things it does WITH one.

GROUPED, AND THE GROUPING IS CHECKED. Thirty bullets is a wall; the groups
below are the ones the catalogue uses, which is how a person thinks about
them. Each names the verbs it covers, and a test asserts those cover
`REQUIRED_BY_VERB` exactly — so a verb added without a home fails rather than
going quietly unmentioned, which is the defect this module exists for.
"""

from __future__ import annotations

from services.smith.verbs import REQUIRED_BY_VERB

#: (heading, what it covers in plain words, the verbs it accounts for)
GROUPS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("The screens",
     "Build a screen that isn't there, lay one out again, add a section to "
     "one, change the words on something, take a control off, or remove a "
     "whole screen.",
     frozenset({"compose_route", "add_widgets", "rename", "remove",
                "remove_page"})),
    ("What it keeps",
     "Add a box to a kind of record, rename or remove one everywhere it is "
     "used, or add and retire a whole kind of record.",
     frozenset({"add_field", "rename_field", "remove_field",
                "add_entity", "remove_entity"})),
    ("What it does by itself",
     "Add, change or stop a process — an email after a registration, an "
     "archive instead of a delete, a reminder on a timer.",
     frozenset({"add_workflow", "edit_workflow", "remove_workflow"})),
    ("What it will not let people do",
     "Add, change or drop a rule that stops a record being saved.",
     frozenset({"add_rule", "edit_rule", "remove_rule"})),
    ("Who is allowed to do what",
     "Roles, permissions, and which screens each kind of person can open.",
     frozenset({"edit_access"})),
    ("The people who log in",
     "Give someone a login, take one away, or send someone a fresh link when "
     "they are locked out. Each person sets their own password — I never see "
     "one, and never tell you anyone else's.",
     frozenset({"add_login", "remove_login", "reset_login"})),
    ("How it looks",
     "The colours, type and density of the whole application, and the menu "
     "down the side.",
     frozenset({"restyle", "edit_navigation"})),
    ("What it is, and what it talks to",
     "Its name and purpose, requirements written down for later, API "
     "endpoints, and outside services — recorded with the names of their "
     "secrets, never connected for you.",
     frozenset({"edit_product", "add_requirement", "edit_requirement",
                "remove_requirement", "add_api", "remove_api",
                "add_integration", "remove_integration"})),
    ("Your own data",
     "Load the records you already have — attach a spreadsheet and say which "
     "records it holds. I say how many rows would land and which column "
     "becomes which field before anything is written, and a column your "
     "records have no field for is reported rather than guessed at. It goes "
     "out the same way: ask for a spreadsheet of any kind of record, or for a "
     "backup of everything, and you get the file.",
     frozenset({"import_data", "export_data"})),
    ("A design somebody gave you",
     "Build the screens from a Figma or UX Pilot file, or unhook it and "
     "compose them from the component library instead.",
     frozenset({"connect_figma", "connect_uxpilot", "disconnect_design"})),
    ("Asks I answer but cannot serve",
     "Renaming a whole kind of record, changing what kind of value a box "
     "holds, editing an endpoint in place, or moving things around on a "
     "screen. I say why, and offer the nearest thing that does work.",
     frozenset({"rename_entity", "change_field_type",
                "edit_api", "reorder"})),
    ("When it goes wrong in front of somebody",
     "Tell me it crashed or that it is slow, and I will tell you what the "
     "running application reported — what failed, where, how often, and what "
     "it said — and offer the repair where the failure names one.",
     frozenset({"explain_crash", "explain_slowness"})),
    ("Putting it back",
     "Undo the last change — the application returns to how it stood before "
     "it, and saying it again goes back another. Nothing is deleted: the undo "
     "is recorded too, so it can itself be undone.",
     frozenset({"revert"})),
    ("The whole application",
     "Regenerate it from its definition.",
     frozenset({"rebuild"})),
)

#: The things Smith does WITH an application rather than TO it. Not verbs:
#: they are commands and one of them is a refusal, which is why they were
#: missing from a list built out of the verb table.
COMMANDS: tuple[tuple[str, str], ...] = (
    ("`status`", "where this application is up to, and what is still open."),
    ("`preview`", "where to look at it, once it is built."),
    ("`verify & fix`",
     "after a build, I read every page as it renders — is it laid out well, "
     "does it match what you asked for, do the buttons and links work — and "
     "re-compose anything that is off."),
    ("`export`", "take the source away as a zip, or push it to a repository."),
)

#: Said last, because both are things a person asks for and does not get here.
LIMITS = (
    "Building runs from the **Approve and build** card above, not from a "
    "typed sentence — that card is what approves the definition it builds.",
    "Publishing is never done from this box: it puts the application on the "
    "internet under your account and needs credentials and a deliberate "
    "go-ahead.",
)


def summary() -> str:
    """Everything Smith can do, as markdown for the chat bubble."""
    lines = ["I can change any part of this application, and run it through "
             "its lifecycle."]
    for heading, said, _verbs in GROUPS:
        lines += ["", f"**{heading}**", said]
    lines += ["", "**Getting it built, looked at and out**"]
    lines += [f"- {name} — {said}" for name, said in COMMANDS]
    lines += [""] + [f"- {limit}" for limit in LIMITS]
    return "\n".join(lines)


#: An example is only useful as a chip if clicking it SAYS something Smith can
#: route — so the chip labels are the quoted examples inside `VERB_HELP`,
#: which are written in a user's words and classify back to their own verb.
_EXAMPLE = __import__("re").compile(r"[\"“]([^\"“”]{8,70})[\"”]")

#: Shorter than this and a word says nothing about which verb is meant. One
#: rule, no list of words to maintain (see `compose._distinctive`).
MIN_WORD = 4


#: Endings trimmed so an inflection is the same word. Three rules rather than
#: a stemmer or a list of pairs — and they are applied to BOTH sides, which is
#: what matters: matching "change" to "changes" by prefix while counting them
#: as different words made "changes" look like a word unique to one verb, and
#: ranked `revert` above `edit_access` for "change who can delete a nurse".
#: "s" before "es": a word ending in "e" keeps it ("changes" -> "change", not
#: "chang"), which is what makes it the same word as the one in the help text.
_ENDINGS = ("ing", "ed", "s", "es")


def _stem(word: str) -> str:
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= MIN_WORD:
            return word[:-len(ending)]
    return word


def _words(text: str) -> set[str]:
    import re
    return {_stem(w.lower()) for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", text or "")
            if len(w) >= MIN_WORD}


def nearest(message: str, limit: int = 3) -> list[tuple[str, str]]:
    """The verbs closest to `message`, as (verb, an example of asking for it).

    An unrecognised ask was answered with all thirty capabilities, which is a
    wall to read and nothing to click. Ranked by the words the ask and the
    verb's own help have in common — a guess about which is MEANT would be
    wrong to act on, but offering three to choose between is a question, and
    a question is always safe.
    """
    from services.smith.verbs import VERB_HELP

    asked = _words(message)
    if not asked:
        return []
    # A WORD IN EVERY ENTRY DISTINGUISHES NOTHING. "make" and "nurse" are in
    # half the help texts; "colour" is in one. Weighting by how few entries a
    # word appears in is what puts `restyle` above `edit_access` for "make the
    # colours nicer" — and it is computed from the table, not from a list of
    # words someone has to keep.
    per_verb = {v: _words(h) for v, h in VERB_HELP.items()}
    spread: dict[str, int] = {}
    for words in per_verb.values():
        for word in words:
            spread[word] = spread.get(word, 0) + 1
    scored: list[tuple[float, str, str]] = []
    for verb, help_text in VERB_HELP.items():
        overlap = sum(1.0 / spread[w] for w in (asked & per_verb[verb]))
        if not overlap:
            continue
        example = _EXAMPLE.search(help_text)
        if not example:
            continue                       # nothing a click could say
        scored.append((overlap, verb, example.group(1)))
    scored.sort(key=lambda row: (-round(row[0], 6), row[1]))
    return [(verb, example) for _score, verb, example in scored[:limit]]


def verbs_covered() -> frozenset[str]:
    """Every verb the groups account for — compared against the verb table."""
    out: set[str] = set()
    for _heading, _said, verbs in GROUPS:
        out |= verbs
    return frozenset(out)


def unaccounted() -> frozenset[str]:
    """Verbs no group mentions. Empty, or the list is lying by omission."""
    return frozenset(REQUIRED_BY_VERB) - verbs_covered()


__all__ = ["GROUPS", "COMMANDS", "LIMITS", "summary", "verbs_covered", "unaccounted"]
