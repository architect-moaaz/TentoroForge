"""Two corpora of owner sentences, held to each other.

There are two, and there should be, because they answer two halves of one
question and neither answer can be derived from the other:

* `backend/tests/routing/corpus.jsonl` — STAGE ONE. Which verb should the
  MODEL pick for this sentence? `run_corpus.py` calls a model once per
  sentence to measure whether it does, which costs money and runs by hand.
* `backend/services/smith/phrasebook_corpus.yaml` — STAGE TWO. Given that
  verb, what does the CODE then do — act, ask something back, answer with a
  reason, or nothing at all? Deterministic, and it generates the phrasebook's
  section 08.

"get rid of the export link" is both `remove` and a question, at the same
time: the model is right to pick `remove`, and `remove` needs a screen the
sentence never names. One label cannot carry both facts, so merging the files
would lose one of them.

WHAT MUST STAY TRUE BETWEEN THEM. A sentence in both must be asking for the
same verb in both — that is the same fact written twice, and the only thing
here that can silently rot. And every sentence routing measures must be in the
phrasebook, so that the answer to "and then what happens?" exists for all of
them.

WHAT IS DELIBERATELY IN ONLY ONE. The lifecycle commands (`status`, `export`),
the consent gates ("build it", "not now") and the sentences that reach nothing
are in the phrasebook alone: the first two are answered by the router before
any understanding runs, and the last have no verb, so there is no right answer
for routing to measure. That asymmetry is asserted below rather than left to
be rediscovered.
"""

from __future__ import annotations

import re

import pytest

from services.smith import phrasebook
from services.smith.verbs import REQUIRED_BY_VERB
from tests.routing.run_corpus import rows


def _said(text: str) -> str:
    """A sentence reduced to its words, so the two files can be compared.

    Not `phrasebook._normalise`: this is only ever used to decide whether two
    files hold the SAME sentence, and it should not quietly treat two
    different sentences as one.
    """
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


@pytest.fixture(scope="module")
def routing() -> dict[str, dict]:
    return {_said(row["say"]): row for row in rows()}


@pytest.fixture(scope="module")
def book() -> dict[str, dict]:
    return {_said(entry["say"]): entry for entry in phrasebook.corpus()}


def test_a_sentence_in_both_asks_for_the_same_verb(routing, book):
    """The one fact written twice.

    Routing's `null` is not a disagreement: it says the sentence is too vague
    for the model to commit to any verb, and the phrasebook must then colour it
    `asks` — the same outcome, said at the other end of the pipeline.
    """
    wrong = []
    for said in sorted(set(routing) & set(book)):
        want = routing[said].get("verb")
        entry = book[said]
        got = (entry.get("reaches") or {}).get("verb")
        if want is None:
            colour = phrasebook.classify(entry).category
            if colour != phrasebook.ASKS:
                wrong.append(f"  “{entry['say']}”\n      routing says no verb "
                             f"should be picked; the phrasebook makes it {colour}")
            continue
        if want != got:
            wrong.append(f"  “{entry['say']}”\n      routing says `{want}`, "
                         f"the phrasebook says `{got}`")
    assert not wrong, (
        "the two corpora disagree about what these sentences are asking for:\n"
        + "\n".join(wrong)
        + "\n\nOne of them is wrong about the same sentence. Fix the label in "
          "whichever is wrong; do not change the sentence.")


def test_every_sentence_routing_measures_has_an_answer_here(routing, book):
    """Routing ⊆ phrasebook.

    Measuring which verb a sentence reaches is only half an answer while
    nothing says what the code then does with it.
    """
    missing = sorted(routing[s]["say"] for s in set(routing) - set(book))
    assert not missing, (
        "these sentences are measured by tests/routing/corpus.jsonl and this "
        "file cannot say what happens to them:\n  "
        + "\n  ".join(f"“{s}”" for s in missing)
        + "\n\nAdd each to phrasebook_corpus.yaml with the verb it asks for "
          "and the slots the sentence states, then rerun "
          "`python -m services.smith.phrasebook --rewrite-checked`.")


def test_every_verb_bearing_sentence_is_measured_by_routing(routing, book):
    """Phrasebook's verb-bearing sentences ⊆ routing.

    A sentence with a verb is a sentence a model has to route, and one nobody
    measures is one nobody knows reaches it.
    """
    missing = sorted(
        entry["say"] for said, entry in book.items()
        if (entry.get("reaches") or {}).get("verb") and said not in routing)
    assert not missing, (
        "these sentences declare a verb and no routing measurement covers "
        "them:\n  " + "\n  ".join(f"“{s}”" for s in missing)
        + "\n\nAdd a {\"say\": …, \"verb\": …} line to "
          "tests/routing/corpus.jsonl for each.")


def test_what_belongs_to_the_phrasebook_alone_stays_there(routing, book):
    """The asymmetry, asserted rather than assumed.

    A lifecycle command and a consent gate never reach `understand_ask` — the
    router answers them first — and a sentence that reaches nothing has no verb
    for routing to be right or wrong about. Put either in the routing corpus
    and it measures the model against an answer that does not exist.
    """
    for said, entry in book.items():
        reaches = entry.get("reaches") or {}
        if "verb" in reaches:
            continue
        kind = ("the `%s` command" % reaches["command"] if "command" in reaches
                else "the %s gate" % reaches["gate"] if "gate" in reaches
                else "a sentence that reaches nothing")
        assert said not in routing, (
            f"“{entry['say']}” is {kind} and is in the routing corpus, which "
            "measures which verb the model picks. There is no verb it should "
            "pick.")


def test_both_corpora_cover_every_verb(routing, book):
    """Neither file may quietly stop exercising a verb the other still does."""
    routed = {row.get("verb") for row in rows()}
    booked = {(e.get("reaches") or {}).get("verb") for e in phrasebook.corpus()}
    for name, covered in (("tests/routing/corpus.jsonl", routed),
                          ("phrasebook_corpus.yaml", booked)):
        missing = sorted(set(REQUIRED_BY_VERB) - covered)
        assert not missing, f"{name} has no sentence for {', '.join(missing)}"
