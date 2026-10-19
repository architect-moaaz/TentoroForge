"""From the forge-v3 transcripts (2026-10-03..17): 31 processes retried with
the same words a round later; two screens' syntax error posted and repaired
twice; 106 screens each saying "could not sign in"; "Done. v3 added 2."
naming nothing."""
from __future__ import annotations

from services.blueprint import process_trials, route_check
from services.smith import gates


def _f(i, said):
    return ({"id": f"w{i}", "name": f"Flow {i}"}, {"input": {}, "as": "Admin"}, said)


def test_a_failure_unchanged_after_a_repair_that_changed_nothing_is_left():
    failing = [_f(1, '{"error": "relation people does not exist"}'), _f(2, '{"error": "x is undefined"}')]
    still, groups, singles = process_trials.sort_failures(
        failing, repeated={"w1": "relation people does not exist"}, changed=set())
    assert [f["id"] for f, _r, _s in still] == ["w1"]
    assert [f["id"] for f, _r, _s in singles] == ["w2"] and groups == []
    # a repair that did change something earns another try
    still, _g, singles = process_trials.sort_failures(
        failing, repeated={"w1": "relation people does not exist"}, changed={"w1"})
    assert still == [] and len(singles) == 2


def test_many_failing_with_the_same_words_are_one_group():
    failing = [_f(i, '{"error": "could not sign in"}') for i in range(4)] + [_f(9, "step 2 failed: boom")]
    still, groups, singles = process_trials.sort_failures(failing, repeated={}, changed=set())
    assert still == [] and len(groups) == 1 and len(groups[0]) == 4
    assert [f["id"] for f, _r, _s in singles] == ["w9"]


def test_a_role_that_cannot_sign_in_is_one_cause_not_a_fault_per_screen(monkeypatch):
    doc = {"pages": [], "data": {"entities": []}, "roles": []}
    todo = [{"page": f"p{i}", "name": f"Page {i}", "route": f"/p{i}", "as": "Doctor", "expect": "200", "entity": ""}
            for i in range(3)]
    monkeypatch.setattr(route_check, "expected_outcomes", lambda d: todo)
    monkeypatch.setattr("services.smith.trials._session", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no login")))
    out = route_check.check_routes(object(), doc)
    assert out["total"] == 3 and len(out["untried"]) == 3
    assert all("one cause for every screen of that role" in u["why"] for u in out["untried"])
    assert out["causes"] == ["could not sign in as Doctor: 3 screens not tried"]


def test_the_requirements_reply_names_what_it_changed():
    change = {"added": ["r3", "r4"], "removed": [{"id": "r1", "description": "Old thing"}],
              "changed": [{"id": "r2", "was": "before"}]}
    names = {"r2": "Scan a product's barcode with the camera", "r3": "Upload a picture from the gallery",
             "r4": "A home screen that lists the company's products first"}
    text = gates.say_requirements_change(change, 3, names=names)
    assert text.startswith("Done. v3 added 2 (Upload a picture from the gallery; A home screen")
    assert "removed 1 (Old thing)" in text and "changed 1 (Scan a product's barcode" in text
    assert gates.say_requirements_change(change, 3).startswith("Done. v3 added 2, removed 1 (Old thing), changed 1.")
