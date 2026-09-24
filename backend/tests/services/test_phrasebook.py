"""The phrasebook's claims, checked against the code that answers them.

The document these sentences come from closes with a list of the ones that
"reach nothing today". That list was wrong on the day it was read: it named
"Put it back how it was — no undo and no restore point" while
`services/smith/revert.py` was shipped and `VERB_HELP` quoted the words "put
it back" as the way to ask for it. A hand-kept list of what a product cannot do
is false the day after the code moves, and the document is only worth anything
while it is true.

So the list is generated, and these tests are what make the generation
trustworthy. They fail in BOTH directions:

* a sentence NEWLY ANSWERED — something that reached nothing now reaches a
  verb, a command or a consent gate, so the closing list is lying by keeping
  it;
* a verb that QUIETLY STOPPED ANSWERING ONE — a slot added to a verb turns
  every sentence that does not state it from "Smith acts" into "Smith asks",
  and the document goes on promising the change happens.

Nothing here is exempted. Where the verb set does not line up with itself, the
corpus writes the defect down under `open_findings` and this asserts that list
exactly — so fixing one is noticed as loudly as introducing one.
"""

from __future__ import annotations

import pytest

from services.smith import capabilities, phrasebook
from services.smith.verbs import REQUIRED_BY_VERB

REGENERATE = "python -m services.smith.phrasebook --rewrite-checked"


@pytest.fixture(scope="module")
def rows() -> list[phrasebook.Classified]:
    return phrasebook.classified()


def test_the_corpus_loads_and_every_sentence_is_named(rows):
    assert rows, "the corpus is empty: there is nothing to keep true"
    ids = [row.id for row in rows]
    assert len(set(ids)) == len(ids), "two sentences share an id"
    for row in rows:
        assert row.say.strip(), f"{row.id} has no sentence"
        assert row.entry.get("source") in ("code", "phrasebook", "routing"), \
            f"{row.id} does not say where its sentence came from"


def test_every_sentence_still_gets_the_colour_it_was_given(rows):
    """The drift test, in both directions.

    `checked` is what the code answered when the corpus was last written; the
    left side of each comparison is what it answers now.
    """
    drifted = []
    for row in rows:
        was = row.entry.get("checked") or {}
        now = {"colour": row.category, "via": row.via}
        if row.missing:
            now["missing"] = list(row.missing)
        if now != {k: v for k, v in was.items()}:
            drifted.append(f"  “{row.say}”\n"
                           f"      was {was}\n"
                           f"      now {now}  ({row.because or 'no reason given'})")
    assert not drifted, (
        "The code no longer does what the phrasebook says it does:\n\n"
        + "\n".join(drifted)
        + "\n\nThis is not a test to silence. Read each line: a sentence that "
          "moved OFF `nothing` means the closing section of the document is "
          "claiming the product cannot do something it does, and a sentence "
          "that moved ONTO `asks` means a verb stopped answering it. When the "
          f"change is intended, rerun `{REGENERATE}` and re-read section 08.")


def test_a_sentence_the_code_quotes_cannot_be_called_dead(rows):
    """The exact shape of the staleness this exists for.

    `verbs.VERB_HELP` and the understanding prompt quote sentences as examples
    of asking for a verb — they are what the chips offer and what the model
    reads. A sentence the document files under "reaches nothing" that the code
    quotes is a sentence the code claims to serve.
    """
    for row in rows:
        if "reaches" in row.entry:
            continue
        quoted = phrasebook.quoted_under(row.say)
        assert not quoted, (
            f"“{row.say}” is listed as reaching nothing, and the code quotes "
            f"it as an example of {', '.join(quoted)}. This is how the list "
            "came to name “Put it back how it was” after undo shipped.")


def test_put_it_back_is_answered_by_the_revert_verb(rows):
    """The regression itself, named, so it cannot come back quietly."""
    found = [row for row in rows if row.say == "Put it back how it was"]
    assert found, "the sentence the closing list got wrong is not in the corpus"
    assert found[0].category == phrasebook.ACTS
    assert (found[0].entry.get("reaches") or {}).get("verb") == "revert"


def test_code_sourced_sentences_are_still_quoted_by_the_code(rows):
    """Verbatim, or they are not evidence.

    Every sentence marked `source: code` was copied out of `VERB_HELP` or the
    understanding prompt. Reworded here — or reworded there — it stops being
    the thing that was checked.
    """
    for row in rows:
        if row.entry.get("source") != "code":
            continue
        assert phrasebook.quoted_verbatim(row.say), (
            f"“{row.say}” is recorded as quoted in the code and no longer is. "
            "Either the example changed wording, in which case copy the new "
            "words, or it is gone, in which case the sentence reaches "
            "something else now.")


def test_every_verb_is_exercised_by_a_sentence():
    """A verb with no sentence is a verb the document cannot describe."""
    covered = {str((entry.get("reaches") or {}).get("verb"))
               for entry in phrasebook.corpus()}
    missing = sorted(set(REQUIRED_BY_VERB) - covered)
    assert not missing, (
        f"{', '.join(missing)} — a verb was added and no owner sentence asks "
        "for it, so the phrasebook cannot say what happens when someone does. "
        "Add the sentence a person would actually type.")


def test_refusals_are_scored_as_neither_success_nor_gap(rows):
    """The deliberate recognise-and-refuse verbs get their own colour.

    `smith4.verbs.honest_refusal` names them; each says why in a clause and offers the
    nearest thing that works. Counting one as a success overstates the
    product, and counting it as a silent gap understates it — and the closing
    section is built on that distinction.
    """
    refusals = sorted(v for v in REQUIRED_BY_VERB if phrasebook._refused(v))
    assert refusals, "the refusal table is empty; the distinction has gone"
    for verb in refusals:
        said = [row for row in rows
                if (row.entry.get("reaches") or {}).get("verb") == verb
                and not row.missing]
        assert said, f"no sentence asks for {verb} with everything it needs"
        for row in said:
            assert row.category == phrasebook.ANSWERS, (
                f"“{row.say}” is a refusal and is scored {row.category}")
            assert row.via == phrasebook.VIA_LIMIT


def test_the_dispatcher_accounts_for_every_verb():
    """The table (`smith4.verbs.PERFORM`) is the only thing that knows whether
    a verb changes the application. A verb dropped from it must be seen here
    rather than quietly colouring everything `acts`."""
    facts = phrasebook.dispatch_facts()
    assert set(facts) == set(REQUIRED_BY_VERB)
    handled = {v for v, f in facts.items() if f.via == phrasebook.VIA_HANDLER}
    assert len(handled) > 20, "almost nothing reaches a handler: the table is no longer being read"
    assert facts["revert"].handler == "revert"
    assert facts["rename"].via == phrasebook.VIA_MOVE
    assert facts["rename_entity"].via == phrasebook.VIA_LIMIT


def test_the_slot_gate_exemption_is_read_from_the_code():
    """No verb is excused from `missing_fields` any more — the old dispatcher
    excused `rename` because the classifier enforced its fields; there is no
    classifier. What the tree edit still asks for before it runs is read off
    it, not assumed."""
    assert phrasebook.slot_gate_skips() == frozenset()
    assert phrasebook.move_requires() == frozenset({"target_file"})


def test_the_commands_and_gates_are_the_routers_own():
    """Not verbs, and missing from every list built out of the verb table."""
    answered = phrasebook.commands()
    assert answered["status"] == phrasebook.ANSWERS
    assert answered["deploy"] == phrasebook.ANSWERS, \
        "publishing is refused in words; a refusal is an answer, not a gap"
    assert set(phrasebook.gates()) == {"build_consent", "verify_consent", "declined"}
    assert phrasebook.gates()["build_consent"]("build it") == phrasebook.ACTS


def test_the_quote_rule_is_capabilities_own():
    """One definition of "a quoted example", not two that drift apart."""
    assert phrasebook._QUOTE.pattern == capabilities._EXAMPLE.pattern


def test_the_verb_sets_open_defects_are_exactly_the_ones_written_down():
    """Where an exception would have gone.

    A sentence that cannot be coloured without excusing a verb is a defect in
    the verb set, and it is written into the corpus under its own name rather
    than hidden in the classifier. This fails when a new one appears AND when
    a recorded one is fixed — the second so that a fix is struck from the list
    instead of being absorbed into it.
    """
    now = {(f.about, f.verbs)
           for f in phrasebook.findings() + phrasebook.contract_gaps()}
    recorded = phrasebook.recorded_findings()
    appeared = sorted(f"{about}: {', '.join(verbs)}" for about, verbs in now - recorded)
    fixed = sorted(f"{about}: {', '.join(verbs)}" for about, verbs in recorded - now)
    assert not appeared, (
        "the verb set has a new defect no sentence can be blamed for:\n  "
        + "\n  ".join(appeared)
        + "\n\nWrite it into `open_findings` in the corpus, or fix it.")
    assert not fixed, (
        "the corpus still records defects that are fixed:\n  "
        + "\n  ".join(fixed) + "\n\nStrike them from `open_findings`.")


def test_section_08_names_only_sentences_that_reach_nothing(rows):
    """The deliverable: the closing section, emitted from the corpus."""
    import re

    text = phrasebook.section_08()
    assert phrasebook.SECTION_08_TITLE in text
    # The bulleted sentences above the refusals, which is the list itself.
    listed = set(re.findall(r"^- \u201c(.+?)\u201d",
                            text.split("**Recognised, and refused")[0], re.M))
    dead = {row.say for row in rows if row.category == phrasebook.NOTHING}
    assert listed == dead, (
        "section 08 and the sentences that reach nothing are different sets: "
        f"listed only {sorted(listed - dead)}, missing {sorted(dead - listed)}")
    for row in rows:
        if row.category != phrasebook.NOTHING:
            continue
        assert row.entry.get("gap"), f"{row.id} reaches nothing and says nothing about what kind"
        assert row.entry.get("because"), f"{row.id} reaches nothing and does not say why"


def test_the_known_dead_ends_are_still_dead(rows):
    """The ones the document names, each expected red until it closes.

    They are asserted by the kind of thing they are rather than one by one, so
    a sentence added to a gap is covered the moment it is written down.

    FOUR OF THEM CLOSED ON 2026-09-18 and are struck from this list rather
    than left in it failing: getting data in (`import_data`), people and
    passwords (`add_login`, `remove_login`, `reset_login`), getting data out
    (`export_data`) and when something is wrong (`explain_crash`,
    `explain_slowness`). Their sentences moved up into the body of the corpus
    with a verb each, which is what striking one means.

    A FIFTH, "What it costs", closed the same day with `spend`. It was the
    last entry on section 08 — "How much has this cost me so far?", against
    the note that a build's spend is recorded against the run and never
    surfaced in the conversation that spent it — and the ledger it wanted was
    already on disk. Struck here, and the sentence is in the body now.
    """
    dead_by_gap: dict[str, list[str]] = {}
    for row in rows:
        if row.category == phrasebook.NOTHING:
            dead_by_gap.setdefault(str(row.entry.get("gap")), []).append(row.say)
    for gap in ("Keeping it safe", "Pictures and branding",
                "Paper out the other end"):
        assert dead_by_gap.get(gap), (
            f"nothing under “{gap}” reaches nothing any more. If that is "
            "because the product closed it, say so: strike the sentences and "
            f"give them a verb. Rerun `{REGENERATE}` afterwards.")
