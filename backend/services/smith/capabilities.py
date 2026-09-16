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
     "one, change the words on something, or take a control off.",
     frozenset({"compose_route", "add_widgets", "rename", "remove"})),
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
    ("A design somebody gave you",
     "Build the screens from a Figma or UX Pilot file, or unhook it and "
     "compose them from the component library instead.",
     frozenset({"connect_figma", "connect_uxpilot", "disconnect_design"})),
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
