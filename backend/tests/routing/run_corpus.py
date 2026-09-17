"""Measure where the classifier actually sends things.

Every fix to routing is a belief until this prints a number. The corpus is the
catalogue's own sentences, each already labelled with the verb it should reach
— including the sloppy phrasings, which are the ones that matter, because a
person who knows the right words was never the problem.

    python -m tests.routing.run_corpus                 # the whole corpus
    python -m tests.routing.run_corpus --verb add_field
    python -m tests.routing.run_corpus --limit 20 --json report.json

Measured on 2026-09-17, against the sample context below and the 138 sentences
the corpus held THEN: 5 reached a DIFFERENT verb (3.6%), 79 routed as
labelled, and 54 asked a question instead — which is not a failure, and for
most of those it is the right answer, since the sample application has no
dashboard to put a widget on. Track the first number.

The corpus has grown to 236 since and has not been re-measured, so that 3.6%
describes a smaller corpus than this one. Re-run before quoting it.

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


def _route(row: dict, context: str = SAMPLE_CONTEXT) -> dict:
    from services.smith.understand_ask import understand_ask

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
