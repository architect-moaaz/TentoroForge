"""The answer to "what can you do?" names everything, not only the verbs.

It was built from the verb table alone — by the model paraphrasing the verb
list in its prompt, and by the unknown-verb reply running the same thirty
entries together — so two real capabilities never appeared: `verify & fix`,
offered by name the moment a build finishes, and the lifecycle commands
`status`, `preview` and `export`, plus publishing, which is refused.
"""

from __future__ import annotations

from services.smith import capabilities as cap
from services.smith.verbs import REQUIRED_BY_VERB


def test_every_verb_has_a_home_in_the_list():
    """A verb added without a group would go quietly unmentioned — which is
    the defect this module exists for, one level up."""
    assert cap.unaccounted() == frozenset(), sorted(cap.unaccounted())
    assert cap.verbs_covered() == frozenset(REQUIRED_BY_VERB)
    # No group claims a verb that does not exist.
    assert cap.verbs_covered() <= frozenset(REQUIRED_BY_VERB)
    # And no verb is claimed twice, or a reader is told the same thing under
    # two headings.
    seen: set[str] = set()
    for _heading, _said, verbs in cap.GROUPS:
        assert not (seen & verbs), sorted(seen & verbs)
        seen |= verbs


def test_the_answer_names_the_things_that_are_not_verbs():
    said = cap.summary()
    for command in ("`status`", "`preview`", "`export`", "`verify & fix`"):
        assert command in said, command
    # What verify & fix actually does, so the name is not a bare label.
    assert "every page as it renders" in said
    # The two things a person asks for here and does not get.
    assert "Approve and build" in said
    assert "Publishing is never done from this box" in said


def test_the_answer_covers_each_group_in_plain_words():
    said = cap.summary()
    for heading, sentence, _verbs in cap.GROUPS:
        assert f"**{heading}**" in said and sentence in said
    # Markdown for the bubble, and no verb identifiers leaking into prose.
    assert said.startswith("I can change any part of this application")
    for ident in ("add_field", "compose_route", "edit_access", "rename_field"):
        assert ident not in said, ident


def test_help_is_a_command_the_chat_answers_itself():
    from routers.blueprint_generate import _lifecycle_verb

    assert _lifecycle_verb("help") == "help"
    assert _lifecycle_verb("Help.") == "help"
    # A sentence that merely contains the word is not the command.
    assert _lifecycle_verb("help me add a phone number") is None
