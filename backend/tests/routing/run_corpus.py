"""Measure where the classifier actually sends things.

Every fix to routing is a belief until this prints a number. The corpus is the
catalogue's own sentences, each already labelled with the verb it should reach
— including the sloppy phrasings, which are the ones that matter, because a
person who knows the right words was never the problem.

    python -m tests.routing.run_corpus                 # the whole corpus
    python -m tests.routing.run_corpus --verb add_field
    python -m tests.routing.run_corpus --limit 20 --json report.json

Measured on 2026-09-18 over the 262 sentences the corpus held that day: 4
reach a DIFFERENT verb (1.5%), 180 route as labelled (69%), and 78 ask a
question instead — which is not a failure, and for most of those it is the
right answer, since the sample application has no dashboard to put a widget
on. Track the first number.

  2026-09-17   5 / 138   3.6%
  2026-09-18   7 / 262   2.7%     the corpus nearly doubled in between
  2026-09-18   4 / 262   1.5%     after `context` (below) — three of the seven
                                  were being asked an unanswerable question

THE THIRD ROW IS PART MEASURED, PART CARRIED FORWARD. The 45 sentences on the
four verbs `context` touches were re-run; the rest keep their result from the
row above, because a row that names no state takes the identical path it
always did. Five sentences also moved between "as labelled" and "asked" in
that re-run, one of them on unchanged input — the model is not deterministic,
so treat a single point as ±1 rather than exact.

A row here is only ever true of the corpus as it stood; it grows most days.
Re-run before quoting one, and add a row rather than editing the last.

WHAT THE FOUR ARE. Two went to verbs that did not exist when their label was
written, and both reads are arguable rather than wrong:

    "/nurses just shows an error"                  compose_route -> explain_crash
    "our rota system needs to pull today's shifts automatically"
                                                   add_api -> connect_service

They are left labelled as they were. A label moved to match what the model did
is a measurement that has stopped measuring; if the intent really changed, the
label should change deliberately, and in BOTH corpora — see
`tests/services/test_corpora_agree.py`.

The other two are the model's own misreads, and unrelated to each other:
"on nurses, phone should be mobile" (rename_field -> change_field_type, where
the sentence is genuinely ambiguous in English) and "we say colleague, never
employee" (edit_product -> rename_entity, which is the very sentence
`limits.answer` offers as the nearest thing to a rename_entity).

THE FAMILY THAT USED TO BE HERE IS GONE. Three sentences — "show phone on the
nurse form", "I can't see the father's name on the registration page" and
"add a Ward with a name and a number of beds" — were counted as misroutes
because they were measured against an application that could not make them
right: the nurse had no phone and no father's name, and a Ward already
existed. The prompt was never the problem; the harness was asking a question
with no right answer. See `context` below.

Calls a model once per sentence, so it costs real money and is NOT part of the
test suite. `test_corpus.py` beside it checks the corpus itself — that every
label is a real verb and nothing is duplicated — which is free and does run.

THE OTHER HALF OF THE QUESTION lives in
`backend/services/smith/phrasebook_corpus.yaml`. This file asks which verb the
MODEL picks; that one asks what the CODE then does with it — acts, asks
something back, answers with a reason, or nothing at all. They are not the
same claim: "get rid of the export link" routes to `remove` and is still
answered with "which screen?", because `remove` needs one and the sentence
names none. Every sentence here is also there, and
`tests/services/test_corpora_agree.py` fails if a sentence in both is labelled
with two different verbs. Adding a sentence here means adding it there too;
the failure says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CORPUS = Path(__file__).with_name("corpus.jsonl")

# THE SAME ENVIRONMENT THE SERVER RUNS IN. Without this every call comes back
# "I could not reach my reasoning service", every sentence misroutes, and the
# number says the classifier is broken when the runner is.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:  # noqa: BLE001 — an env already set is fine
    pass


def rows(verb: str = "", limit: int = 0) -> list[dict]:
    out = [json.loads(line) for line in CORPUS.read_text("utf-8").splitlines() if line.strip()]
    if verb:
        out = [r for r in out if r.get("verb") == verb]
    return out[:limit] if limit else out


#: THE CONTEXT ROUTING DEPENDS ON. Measured against "(no application yet)",
#: "add phone" cannot be routed and Smith rightly asks which record — so the
#: number said the classifier was wrong when the question was unanswerable.
#: An application like the one the corpus talks about is the fair condition:
#: the same shape the panel passes, small enough to read.
SAMPLE_CONTEXT = """# App blueprint — project sample
## Domain: Nurse roster
- Primary actors: Admin, Ward Manager, Nurse
- Core verbs: Register Nurse, Edit Nurse Registration, Delete Nurse

## Requirements (3)
- REQ-001: Reception registers a nurse with their details.
- REQ-002: Any user can browse all submitted registrations.
- REQ-003: A registration can be edited after it is submitted.

## Entities
- Nurse (nurses): id, name, gender, specialities, location, experienceYears
- Ward (wards): id, name, capacity

## Workflows
- Register Nurse (manual)
- Edit Nurse Registration (manual)
- Delete Nurse (manual)

## Pages
- /nurse-registration (Nurse Registration)
- /master-data (Master Data)
- /nurse-registration/[id] (Edit Nurse)

## Design decisions
- DEC-001: primary colour blue
"""


#: ONE SENTENCE CAN NEED A DIFFERENT APPLICATION FROM ANOTHER. Half the corpus
#: asks for a phone number to be ADDED to a nurse and half asks why the phone
#: number is not SHOWN, and the right verb is a different one in each case —
#: `add_field` when the column is not there, `add_widgets` when it is. No
#: single application satisfies both, so measuring them all against the one
#: above asked six sentences a question with no right answer and then counted
#: the answer as a misroute. The same for "add a Ward…", which is `add_entity`
#: only in an application that has no Ward yet.
#:
#: So a row says which state it assumes, in `context`, and gets it. This is the
#: same discipline as the note above about "(no application yet)": the number
#: is about the classifier only when the question is answerable.
def _with_fields(base: str) -> str:
    """The same application AFTER phone, father's name and ward were added."""
    line = "- Nurse (nurses): id, name, gender, specialities, location, experienceYears"
    assert line in base, "the Nurse entity line moved; this variant is now a lie"
    return base.replace(line, line + ", phone, fathersName, ward")


def _without_ward(base: str) -> str:
    """The same application BEFORE anyone added a Ward."""
    line = "- Ward (wards): id, name, capacity\n"
    assert line in base, "the Ward entity line moved; this variant is now a lie"
    return base.replace(line, "")


#: The states a row may ask for. "" is the application as it stands above.
CONTEXTS: dict[str, str] = {
    "": SAMPLE_CONTEXT,
    "fields-already-there": _with_fields(SAMPLE_CONTEXT),
    "no-ward-yet": _without_ward(SAMPLE_CONTEXT),
}


def _route(row: dict, context: str = SAMPLE_CONTEXT) -> dict:
    from services.smith.understand_ask import understand_ask

    # A row that names a state gets it; `--no-context` still overrides every
    # row, because that run is deliberately asking the harder question.
    if context is SAMPLE_CONTEXT and row.get("context"):
        context = CONTEXTS[row["context"]]
    got = understand_ask(row["say"], context)
    verb = str(got.get("verb") or "").strip() or None
    if got.get("clarification_needed") and not verb:
        verb = None
    return {**row, "got": verb, "asked": bool(got.get("clarification_needed")),
            "hit": verb == row.get("verb")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verb", default="", help="only sentences labelled with this verb")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--json", default="", help="write the full result here")
    ap.add_argument("--no-context", action="store_true",
                    help="route against an empty application (a harder, less "
                         "representative condition)")
    args = ap.parse_args(argv)

    cases = rows(args.verb, args.limit)
    if not cases:
        print("nothing to run")
        return 1
    import os

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")):
        print("no model credentials in the environment — every sentence would "
              "misroute and the number would be about the runner, not the "
              "classifier. Set them, or run from the backend directory where "
              "the .env is.")
        return 1
    context = "(no application yet)" if args.no_context else SAMPLE_CONTEXT
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda row: _route(row, context), cases))

    hits = sum(1 for r in results if r["hit"])
    asked = sum(1 for r in results if not r["hit"] and r["got"] is None)
    wrong = sum(1 for r in results if not r["hit"] and r["got"])
    # THE MISROUTE RATE IS THE NUMBER THAT MATTERS. A question is not a
    # misroute — Smith is built to ask, and "add phone" on an application with
    # two records SHOULD ask which one. Leading with "routed as labelled"
    # buries the thing that actually hurts, which is an ask that quietly
    # reached the wrong verb and changed the wrong part of the application.
    print(f"MISROUTED: {wrong}/{len(results)} "
          f"({100.0 * wrong / len(results):.1f}%) reached a different verb")
    print(f"  routed as labelled: {hits} ({100.0 * hits / len(results):.0f}%)")
    print(f"  asked a question instead: {asked}\n")

    for r in results:
        if not r["hit"] and r["got"]:
            print(f"  ! {r['say']}\n      wanted {r['verb']}, went to {r['got']}")
    if wrong:
        print()
    missed = [r for r in results if not r["hit"]]
    by_verb: Counter = Counter(r.get("verb") or "(none)" for r in missed)
    if by_verb:
        print("misroutes by intended verb:")
        for verb, n in by_verb.most_common():
            total = sum(1 for r in results if (r.get("verb") or "(none)") == verb)
            print(f"  {verb:<20} {n}/{total}")
        print()
        for r in missed:
            print(f"  {r['say']}\n      wanted {r.get('verb')}, got {r['got']}")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), "utf-8")
        print(f"\nwritten to {args.json}")
    return 0 if not missed else 2


if __name__ == "__main__":
    sys.exit(main())
