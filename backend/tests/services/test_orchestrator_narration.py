"""A run's ledger is watchable while it happens.

``RunLedger`` records what a run planned, did and stopped on, for a post-mortem
that used to be archaeology. The virtual office is a *second reader* of that
same account: `run(..., observer=...)` hands every line to the observer as it
is written, so a node outcome the run records cannot be missing from the
picture because somebody forgot to emit it twice.

These tests pin the lines an observer receives — in particular the ones that
describe *outcomes*, since a run that only reported "started" and "finished"
would look identical whether it authored eighteen pages or refused all
eighteen.
"""
from __future__ import annotations

import json

import pytest

from services.blueprint.agent_contract import AgentResult
from services.blueprint.orchestrator import run
from services.blueprint.service import BlueprintService
from services.office_events import OfficeNarrator


@pytest.fixture()
def svc(ats, tmp_path) -> BlueprintService:
    """The standing ATS fixture, adopted into a scratch directory.

    Adopted rather than loaded so the id allocator is bootstrapped from the
    document — a run against an un-bootstrapped Blueprint renumbers everything
    it touches.
    """
    from services.smith.smith import bootstrap

    service = BlueprintService(output_dir=str(tmp_path))
    service.doc = ats
    service.root.mkdir(parents=True, exist_ok=True)
    service.save()
    bootstrap(service)
    return service


def ok(spec):
    return AgentResult(task_id=spec.task_id, agent=spec.agent)


def kinds(lines: list[dict]) -> list[str]:
    return [line["event"] for line in lines]


def watch(svc, executor, **kw) -> list[dict]:
    """Run, and return everything the observer saw."""
    seen: list[dict] = []
    run(svc, executor, observer=seen.append, **kw)
    return seen


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------

def test_a_run_announces_its_plan_before_it_starts(svc):
    """Written first so a run that dies in its opening seconds still says what
    it MEANT to do."""
    seen = watch(svc, ok, plan=["business_rules"])

    assert seen[0]["event"] == "run:start"
    assert seen[1]["event"] == "plan"
    assert seen[1]["nodes"] == ["business_rules"]
    assert seen[-1]["event"] == "run:end"


def test_each_node_is_bracketed_by_start_and_done(svc):
    seen = watch(svc, ok, plan=["business_rules", "workflows"])

    assert kinds(seen) == [
        "run:start", "plan",
        "node:start", "node:start",   # one wave: the two are independent
        "node:subject", "node:subject",
        "node:done", "node:done",
        "run:end",
    ]


def test_the_observer_and_the_file_agree(svc):
    """Two readers of one account, not two accounts."""
    seen = watch(svc, ok, plan=["business_rules"])
    run_id = seen[0]["runId"]
    path = svc.root.parent.parent / ".forge" / "runs" / f"{run_id}.jsonl"
    on_disk = [json.loads(line) for line in path.read_text().splitlines()]
    assert kinds(seen) == kinds(on_disk)


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------

def test_a_node_that_authors_nothing_is_reported_failed(svc):
    """Not silently missing. A hole in the app the picture cannot show is the
    whole failure mode §28 exists to prevent."""
    def refuse(spec):
        raise RuntimeError("no")

    seen = watch(svc, refuse, plan=["business_rules"], max_attempts=1)
    failed = [line for line in seen if line["event"] == "node:failed"]
    assert failed and failed[0]["node"] == "business_rules"


def test_a_retry_is_recorded_with_what_was_wrong(svc):
    """A retry nobody can see looks like an agent that stalled. It also makes
    the cost of the retry loop unreadable from a finished run."""
    calls = {"n": 0}

    def flaky(spec):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("envelope was malformed")
        return ok(spec)

    seen = watch(svc, flaky, plan=["business_rules"], max_attempts=2)
    retry = next(line for line in seen if line["event"] == "node:retry")
    assert retry["attempt"] == 2 and retry["of"] == 2
    assert "malformed" in retry["reason"]
    assert "node:done" in kinds(seen)


def test_a_fanning_out_node_records_each_subject(svc):
    """"Which of the eighteen stopped it" is unanswerable from one aggregate
    line, and eighteen model calls with no lines between them is a silence the
    office cannot draw progress through."""
    seen = watch(svc, ok, plan=["page_layouts"])

    start = next(line for line in seen if line["event"] == "node:start")
    subjects = [line for line in seen if line["event"] == "node:subject"]

    assert start["subjects"] > 1
    assert len(subjects) == start["subjects"]
    assert [line["index"] for line in subjects] == list(range(1, len(subjects) + 1))
    assert all(line["total"] == len(subjects) for line in subjects)
    assert all(line["ok"] for line in subjects)


def test_a_projection_with_nowhere_to_project_is_blocked_not_failed(svc):
    seen = watch(svc, ok, plan=["frontend"])
    blocked = next(line for line in seen if line["event"] == "node:blocked")
    assert blocked["node"] == "frontend"
    assert blocked["reason"]


# ---------------------------------------------------------------------------
# The office reads it
# ---------------------------------------------------------------------------

def test_the_office_narrator_survives_a_whole_run(svc):
    """End to end: ledger lines in, office events out, nothing unhandled."""
    from services.office_events import ROOM_OF

    office: list[dict] = []
    run(svc, ok, plan=["business_rules", "workflows", "frontend"],
        observer=OfficeNarrator(office.append))

    assert office[0]["type"] == "run_plan"
    assert {"agent_start", "agent_complete"} <= set(e["type"] for e in office)
    # Every office event names an agent the office can actually move.
    for evt in office:
        for key in ("agent", "from", "to"):
            if key in evt:
                assert evt[key] in ROOM_OF, evt


def test_a_run_with_no_observer_behaves_exactly_as_before(svc):
    """Watching is optional; nothing about the run depends on anyone doing it."""
    report = run(svc, ok, plan=["business_rules"])
    assert report.completed == ["business_rules"]
