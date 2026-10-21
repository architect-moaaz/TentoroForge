"""A calculator with seven rules and no process read "Ran the processes and
tried the rules: 0 of 7 hold, 7 I couldn't try" and, at the end, "7 I could
not try — my own check failed, not the app" (Mark 8, 2026-10-16). Nothing
had failed: no process carries those rules, so no trial can judge them. They
are skipped with the reason, outside the total, and said apart."""
from __future__ import annotations

from types import SimpleNamespace

from services.blueprint import scorecard as sc
from services.blueprint.fix_to_green import _logic_line, _write_logic


def _svc():
    doc = {"version": 3, "pages": [], "workflows": [],
           "businessRules": [{"id": f"RULE-00{i}", "name": f"Rule {i}"} for i in range(1, 8)]}
    return SimpleNamespace(doc=doc, save=lambda: None)


def test_seven_rules_no_process_carries_are_said_apart_and_count_nowhere():
    svc = _svc()
    rules = {"total": 0, "green": [], "red": [], "untried": [],
             "skipped": [sc.item(f"RULE-00{i}", f"Rule {i}", "gates no process a trial can run", f"RULE-00{i}") for i in range(1, 8)]}
    _write_logic(svc, {"passed": [], "fixed": [], "left": [], "untried": []}, rules)
    v = sc.read(svc.doc)["criteria"]["logic"]
    assert v["total"] == 0 and v["untried"] == [] and len(v["skipped"]) == 7
    assert _logic_line(svc) == "No process or rule a trial could run here; 7 rules gate no process, so there is nothing to try them in."
    # The closing never counts them among what the check could not try.
    assert "could not try" not in sc.closing(svc.doc)


def test_a_rule_a_trial_could_reach_is_still_counted_and_a_down_bench_is_still_untried():
    svc = _svc()
    rules = {"total": 2, "green": [sc.item("RULE-001", "Rule 1", "refuses it", "RULE-001")], "red": [],
             "untried": [sc.item("RULE-002", "Rule 2", "the app could not be started to try it: boom", "RULE-002")],
             "skipped": [sc.item("RULE-003", "Rule 3", "gates no process a trial can run", "RULE-003")]}
    _write_logic(svc, {"passed": [], "fixed": [], "left": [], "untried": []}, rules)
    v = sc.read(svc.doc)["criteria"]["logic"]
    assert v["total"] == 2 and len(v["untried"]) == 1 and len(v["skipped"]) == 1
    # The first untried reason is the headline, not just the count (7df66754).
    assert _logic_line(svc) == ("Ran the processes and tried the rules: 1 of 2 hold, 1 I couldn't try "
                                "(the app could not be started to try it: boom); "
                                "1 rule gates no process, so there is nothing to try it in.")
    assert "1 I could not try" in sc.closing(svc.doc)
