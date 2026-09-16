"""The corpus itself is checked for free; running it against a model is not.

`run_corpus.py` calls a model once per sentence, so it costs money and cannot
live in the suite. What CAN live here is the thing that rots: a label that is
no longer a verb, a sentence counted twice, a verb with no example at all.
"""

from __future__ import annotations

from collections import Counter

from services.smith.verbs import REQUIRED_BY_VERB
from tests.routing.run_corpus import rows

CORPUS = rows()


def test_every_label_is_a_verb_the_dispatcher_runs():
    for row in CORPUS:
        assert "say" in row and row["say"].strip(), row
        if row.get("verb") is not None:
            assert row["verb"] in REQUIRED_BY_VERB, row["verb"]


def test_no_sentence_is_counted_twice():
    said = Counter(r["say"].strip().lower() for r in CORPUS)
    assert [s for s, n in said.items() if n > 1] == []


def test_the_sloppy_phrasings_are_in_it():
    """A person who knows the right words was never the problem."""
    said = {r["say"] for r in CORPUS}
    for sloppy in ("add phone", "make it nicer", "can u add phone",
                   "too bright", "undo that", "where's the phone number gone?"):
        assert sloppy in said, sloppy


def test_every_verb_that_can_be_asked_for_has_at_least_one_sentence():
    """A verb with no example is a verb nobody has checked can be reached."""
    labelled = {r.get("verb") for r in CORPUS}
    missing = set(REQUIRED_BY_VERB) - labelled
    assert missing == set(), sorted(missing)
