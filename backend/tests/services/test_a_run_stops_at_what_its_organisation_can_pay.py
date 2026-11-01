"""A build or a turn carries what its organisation's balance and limits allow.

The gate before work was the only check: once a run started, retries, observer
rounds and repairs stacked with nothing to stop them, and a Smith turn could
make a hundred calls where the gate assumed $0.60 (audit, 2026-11-01).
"""
from __future__ import annotations

import time

import pytest

from services import build_usage, spending


class _Usage:
    model = "claude-opus-5-5"

    def __init__(self, out: int):
        self.out = out

    def as_ledger_dict(self):
        return {"input_tokens": 0, "output_tokens": self.out}


def test_the_ceiling_is_the_least_of_the_balance_and_what_every_limit_leaves():
    now = time.time()
    policy = {"credits": {"o1": [{"amount": 20, "at": now - 100}]},
              "limits": {"org:o1": {"day": 15}, "user:u@x": {"month": 50}}}
    rows = [{"org": "o1", "user": "u@x", "project": "p", "ts": now - 10, "est_cost_usd": 6.0}]
    assert spending.headroom(rows, org="o1", user="u@x", project="p", policy=policy, now=now) == pytest.approx(9.0)
    assert spending.headroom([], org="o2", policy={"credits": {}, "limits": {}}, now=now) is None


def test_a_run_past_its_ceiling_is_refused_its_next_call_and_says_why():
    with build_usage.run_budget(0.05) as budget:
        build_usage.check_budget()
        build_usage.spent(_Usage(out=10_000))  # well over five cents at any Opus price
        with pytest.raises(build_usage.RunBudgetSpent) as stopped:
            build_usage.check_budget()
    assert "all that the organisation's balance and spending limits allowed" in str(stopped.value)
    assert budget.spent_usd > 0.05
    build_usage.check_budget()  # outside the run, nothing is held


def test_no_ceiling_holds_nothing_and_a_run_inside_another_is_the_outer_runs_spend():
    with build_usage.run_budget(None) as none:
        assert none is None
        build_usage.spent(_Usage(out=10_000_000))
        build_usage.check_budget()
    with build_usage.run_budget(1.0) as outer:
        with build_usage.run_budget(100.0) as inner:
            assert inner is outer


def test_the_model_client_refuses_to_start_a_call_past_the_ceiling(monkeypatch):
    from services import llm_client

    with build_usage.run_budget(0.0):
        with pytest.raises(build_usage.RunBudgetSpent):
            llm_client._chat_model(None, model="claude-opus-5-5", max_tokens=10, temperature=None, timeout=None)


def test_a_dag_run_ends_on_its_ceiling_rather_than_retrying_it():
    from services.blueprint.orchestrator import _call

    def executor(_spec):
        raise build_usage.RunBudgetSpent("spent")

    with pytest.raises(build_usage.RunBudgetSpent):
        _call(executor, object())
    assert isinstance(_call(lambda _s: (_ for _ in ()).throw(ValueError("x")), object()), ValueError)


def test_a_smith_turn_ends_on_its_ceiling_in_the_organisations_terms():
    import inspect

    from services.smith import loop
    from services.smith4 import turn

    assert '"spent": True' in inspect.getsource(loop)
    assert 'chosen.get("spent")' in inspect.getsource(turn)


def test_every_start_carries_its_ceiling():
    import inspect

    from routers import blueprint_generate, drafts_room, output_projects

    src = inspect.getsource(blueprint_generate)
    assert "return await credits.headroom(db, **who)" in src
    assert src.count("_acting_as(work, user, project, ceiling)") == 2 and "_actor_of(user, project, ceiling)" in src
    assert "run_budget(actor.get(\"ceiling\"))" in src
    assert '"ceiling": ceiling' in inspect.getsource(drafts_room)
    assert "run_budget(ceiling)" in inspect.getsource(output_projects)
