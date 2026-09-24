"""An owner asks what their app has cost, and gets an honest answer.

The owner phrasebook's dead-end list ended with "how much has this cost me?"
against the note *no cost or usage visibility anywhere in the conversation* —
while every model call the pipeline has ever made sat in a ledger with its
project, its model, its tokens and a dollar figure on it. So what these hold
is not the measuring. It is the two ways the answer could be a lie:

* **By omission.** The observer recorded its spend with no project, which the
  ledger wrote as the literal string ``blueprint`` — so summing an
  application's rows left the watching out, 19-28% of three measured builds,
  and the omission looked like a cheaper app rather than a missing one.
* **By implication.** There is no billing anywhere in this platform. A dollar
  figure handed to an owner without the sentence saying whose cost it is would
  be an invoice nobody issued — and a made-up price for an unpriced model
  would be a second one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.executors import ModelReply, RunUsage, Usage
from services.blueprint.ids import page_key, role_key
from services.blueprint.observer import Observer
from services.blueprint.service import BlueprintService
from services.smith import spend
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP, missing_fields


@pytest.fixture()
def ledger(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))
    return path


@pytest.fixture()
def app(tmp_path) -> BlueprintService:
    svc = BlueprintService.create(output_dir=tmp_path / "out", app_id="acme01",
                                  name="Acme Roster", domain="health")
    svc.upsert("roles", {"name": "Admin"}, natural_key=role_key("Admin"))
    svc.upsert("pages", {"name": "Candidates", "route": "/candidates",
                         "purpose": "list candidates"},
               natural_key=page_key("/candidates"))
    svc.save()
    return svc


def _row(project: str, agent: str, *, phase: str = "", model: str = "claude-sonnet-5",
         inp: int = 1_000_000, out: int = 0, sdk: float = 0.0) -> dict:
    from services.build_usage import estimate_cost_usd
    usage = {"input_tokens": inp, "output_tokens": out}
    return {"ts": 1789000000.0, "project": project, "agent": agent, "kind": "blueprint",
            "phase": phase, "model": model, "input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "sdk_cost_usd": sdk,
            "est_cost_usd": estimate_cost_usd(model, usage),
            "duration_ms": 0, "num_turns": 0}


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", "utf-8")


# --- the omission -----------------------------------------------------------

class _Critic:
    """A critic that passes, and reports what the call consumed."""

    def __call__(self, *, system: str, user: str, schema: dict) -> ModelReply:
        return ModelReply(
            text=json.dumps({"verdict": "pass", "findings": []}),
            usage=Usage(model="claude-sonnet-5", input_tokens=1000, output_tokens=200))


def test_the_observers_spend_is_the_applications_spend(app, ledger):
    """It judges a document it was handed and holds no service, so it cannot
    name the application itself. The run it belongs to can, and does."""
    usage = RunUsage.for_app(app)
    assert usage.project == "acme01" and usage.phase == "build"

    Observer(critic=_Critic(), usage=usage).observe(
        "page_contracts", agent="page_design", subjects=["PAGE-001"], doc=app.doc)

    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert [r["project"] for r in rows] == ["acme01"]
    assert rows[0]["agent"].startswith("observer:")
    # The bucket that swallowed it is not written to at all any more.
    assert "blueprint" not in {r["project"] for r in rows}


def test_the_watching_is_counted_in_what_the_build_cost(app, ledger):
    """The whole point of fixing the tag: the observer's share reaches the
    total an owner is shown, instead of being someone else's line."""
    usage = RunUsage.for_app(app)
    usage.record(node="page_layouts", agent="page_design",
                 usage=Usage(model="claude-sonnet-5", input_tokens=1_000_000),
                 elapsed_s=1.0)
    Observer(critic=_Critic(), usage=usage).observe(
        "page_contracts", agent="page_design", subjects=["PAGE-001"], doc=app.doc)

    out = spend.report(app.output_dir)
    assert out["events"] == 2
    assert {s["stage"] for s in out["by_stage"]} == {"page_layouts", "observer"}
    assert out["total_usd"] == pytest.approx(2.0 + 0.004, rel=1e-6)


def test_a_change_run_is_recorded_as_a_change_not_a_build(app, ledger):
    """Which of the two a call is, is known where the run starts — so it is
    settled there rather than reconstructed from when the row was written."""
    build = RunUsage.for_app(app)
    change = RunUsage.for_app(app, phase="change")
    for run, model_in in ((build, 1_000_000), (change, 500_000)):
        run.record(node="page_layouts", agent="page_design",
                   usage=Usage(model="claude-sonnet-5", input_tokens=model_in),
                   elapsed_s=1.0)

    out = spend.report(app.output_dir)
    assert out["build"] == {"cost_usd": 2.0, "events": 1}
    assert out["change"] == {"cost_usd": 1.0, "events": 1}
    assert out["unsplit"] == {"cost_usd": 0.0, "events": 0}
    said = spend.summary_of(out)
    assert "Building it — **$2.00**" in said
    assert "Changes since — **$1.00**" in said


# --- the implication --------------------------------------------------------

def test_the_answer_never_reads_as_a_bill(app, ledger):
    _write(ledger, [_row("acme01", "page_layouts:page_design", phase="build")])
    said = spend.summary_of(spend.report(app.output_dir))
    assert spend.NOT_A_BILL in said
    assert "not what you owe" in said
    assert "does not charge you" in said
    # Never the vocabulary of an account. The figure is named as the
    # platform's cost of running the models, and nothing else.
    for word in ("invoice", "you owe $", "due", "amount payable", "your bill"):
        assert word not in said.lower().replace("**", "")


def test_an_estimate_is_called_an_estimate_and_a_measurement_is_not(app, ledger):
    _write(ledger, [_row("acme01", "a:b", phase="build")])
    assert "still an estimate" in spend.summary_of(spend.report(app.output_dir))

    _write(ledger, [_row("acme01", "a:b", phase="build", sdk=1.25)])
    out = spend.report(app.output_dir)
    assert out["measured_usd"] == 1.25 and out["estimated_usd"] == 0.0
    said = spend.summary_of(out)
    assert "what the model provider reported" in said and "estimate" not in said


def test_a_model_we_hold_no_price_for_contributes_tokens_and_no_dollars(app, ledger):
    """`estimate_cost_usd` prices an unknown model as sonnet-class rather than
    refusing, so the row on disk HAS a dollar figure. It is a placeholder, and
    putting it in a total presented as spend would be inventing money."""
    _write(ledger, [_row("acme01", "a:b", phase="build", model="gpt-4o", inp=2_000_000),
                    _row("acme01", "c:d", phase="build", inp=1_000_000)])
    out = spend.report(app.output_dir)

    assert out["total_usd"] == 2.0                      # the sonnet row alone
    assert out["unpriced"] == {"models": ["gpt-4o"], "tokens": 2_000_000, "events": 1}
    assert out["input_tokens"] == 3_000_000             # the tokens are real
    said = spend.summary_of(out)
    assert "`gpt-4o`" in said and "would have to make them up" in said
    assert "2,000,000 tokens" in said
    # The headline counts the calls the figure is MADE OF — not the one that
    # contributed nothing to it.
    assert "across 1 model call(s)" in said


def test_when_no_call_can_be_priced_the_work_is_reported_and_no_money_is(app, ledger):
    _write(ledger, [_row("acme01", "a:b", phase="build", model="gpt-4o",
                         inp=2_000_000, out=100_000)])
    out = spend.report(app.output_dir)
    assert out["total_usd"] == 0.0 and out["unpriced"]["events"] == 1

    said = spend.summary_of(out)
    assert "`gpt-4o`" in said and "2,000,000 tokens read" in said
    assert "would mean inventing a price" in said
    # Not a dollar figure anywhere — not even a zero, which would read as free.
    assert "$" not in said


def test_nothing_recorded_is_said_plainly_rather_than_shown_as_zero(app, ledger):
    out = spend.report(app.output_dir)
    assert out["events"] == 0 and out["total_usd"] == 0.0
    said = spend.summary_of(out)
    assert "cannot see what it cost" in said
    assert "$0" not in said


def test_rows_from_before_the_split_are_named_as_unsplit(app, ledger):
    """The ledger predates the phase, and the honest handling of a row that
    cannot say which side it is on is to say so — not to file it under
    whichever side makes the report look tidier."""
    _write(ledger, [_row("acme01", "a:b"), _row("acme01", "c:d", phase="change",
                                                inp=500_000)])
    out = spend.report(app.output_dir)
    assert out["unsplit"] == {"cost_usd": 2.0, "events": 1}
    assert out["total_usd"] == 3.0
    said = spend.summary_of(out)
    assert "A further $2.00 was recorded before a call said which" in said

    _write(ledger, [_row("acme01", "a:b")])
    assert "I cannot split that" in spend.summary_of(spend.report(app.output_dir))


def test_another_applications_spend_is_not_this_ones(app, ledger):
    _write(ledger, [_row("acme01", "a:b", phase="build"),
                    _row("someone-else", "a:b", phase="build", inp=9_000_000),
                    _row("blueprint", "observer:x", phase="build", inp=9_000_000)])
    out = spend.report(app.output_dir)
    assert out["events"] == 1 and out["total_usd"] == 2.0


def test_a_fraction_of_a_cent_is_not_shown_as_free():
    assert spend._money(0.0004) == "$0.0004"
    assert spend._money(1.5) == "$1.50"
    assert spend._money(1234.5) == "$1,234.50"


# --- the wiring -------------------------------------------------------------

def test_the_verb_needs_nothing_and_is_offered_by_name():
    assert REQUIRED_BY_VERB["spend"] == set()
    assert missing_fields({"verb": "spend"}) == []
    assert "how much has this cost me?" in VERB_HELP["spend"]

    from services.smith import tools
    catalogue = " ".join(tools.render().split())
    assert "`spend`" in catalogue and "how much has this cost me?" in catalogue

    from services.smith import capabilities as cap
    assert cap.unaccounted() == frozenset()
    assert "spend" in cap.verbs_covered()


def test_the_turn_answers_and_changes_nothing(app, ledger):
    from tests.services._front_door import SmithSession

    _write(ledger, [_row("acme01", "page_layouts:page_design", phase="build")])
    session = SmithSession(
        project_id="p1", output_dir=str(app.output_dir), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": "spend"},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="how much has this cost me?")

    assert result.status == "resolved"
    assert result.touched_paths == []
    assert "**Acme Roster** has cost $2.00" in result.answer
    assert "not what you owe" in result.answer


def test_the_tool_entry_answers_without_a_blueprint(tmp_path, ledger):
    from services.smith_tools import _smith_spend

    out = _smith_spend(str(tmp_path))
    assert out["applied"] is True and out["edited_paths"] == []
    assert "cannot see what it cost" in out["diff_summary"]
