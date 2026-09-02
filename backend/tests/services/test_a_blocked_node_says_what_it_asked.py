"""A run that stops to ask records what it asked.

`data_model` returned four proposals at confidence 0.20 and §17 held them —
"confidence 0.20 is below the clarification threshold of 0.40" — which is the
decision policy working exactly as written. Everything downstream was skipped,
the run ended in 156 seconds, and the only trace anywhere was the word
`data_model` in a `blocked` list.

`apply_agent_result` had already computed the reason and the agent's questions
were in `change_requests`; both were discarded at the point of recording. The
only way to learn why the run had stopped was to run the agent again and look.

A run that stops to ask and a run that stops dead must not look the same.
"""
from __future__ import annotations

import pathlib
import tempfile

from services.blueprint.orchestrator import RunReport, _asked
from services.blueprint.run_ledger import RunLedger, read


class _Blocked:
    reason = "confidence 0.20 is below the §17 clarification threshold of 0.40"
    change_requests = [
        {"question": "Is a Case one entity per guest complaint, or one per remedy line?"},
    ]


class _NoReason:
    reason = ""
    change_requests: list = []


def test_the_threshold_that_held_it_is_named():
    said = _asked(_Blocked())
    assert "0.20" in said and "0.40" in said


def test_the_agent_s_own_question_is_carried():
    """The reason says the confidence was low. The question says what would
    raise it, and that is the part someone can act on."""
    said = _asked(_Blocked())
    assert "one per remedy line" in said


def test_a_silent_decline_is_still_recorded_as_something():
    """An empty reason must not produce an empty string — that reads as "no
    reason was recorded" being indistinguishable from "nothing went wrong"."""
    assert _asked(_NoReason()) == "the agent declined without giving a reason"


def test_it_survives_the_process():
    """The ledger is the record that outlives the run. `blocked` held names
    only, so the one file written to answer "why did this stop" could not."""
    report = RunReport()
    report.blocked.append("data_model")
    report.blocked_because["data_model"] = _asked(_Blocked())

    out = pathlib.Path(tempfile.mkdtemp())
    RunLedger(out, "r1").finish(report)
    end = [e for e in read(out, "r1") if e.get("event") == "run:end"][0]

    assert "0.40" in end["blockedBecause"]["data_model"]
    assert "remedy line" in end["blockedBecause"]["data_model"]


def test_blocked_because_sits_beside_the_other_two():
    """`failed_because` and `skipped_because` already existed for exactly this
    reason. Blocking was the one outcome with no explanation attached."""
    report = RunReport()
    for attr in ("failed_because", "skipped_because", "blocked_because"):
        assert isinstance(getattr(report, attr), dict)


def test_both_paths_record_it():
    """A fan-out subject and a single-subject node block through different
    branches; the one that did not record would be the one that mattered."""
    import inspect

    from services.blueprint import orchestrator

    for fn in (orchestrator._apply_round, orchestrator._run_agent_subject):
        src = inspect.getsource(fn)
        assert "blocked_because[label] = _asked(application)" in src, fn.__name__
        assert '_note(ledger, "node_blocked"' in src, fn.__name__
