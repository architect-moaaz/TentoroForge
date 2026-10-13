"""The execute route keeps the engine's own keys to itself, and a task is
completed by who it is assigned to.

Three holes, all reached from outside the browser:

* `__step_<node>_completed` in a request's `input` marked a node already run,
  so a caller who wrote it on a fresh run skipped that node, an approval too.
  `__guest`, `__user` and `__origin` are the route's to set; a client's are
  dropped.
* a task's id was enough to complete it: the resume asked for the launch role
  and nothing about the task. The inbox lists a task for its assignee, a
  person holding its role, or anyone when it names neither; the resume now
  asks the same three questions.
* `/api/form-rules` believed a `user` written into the body, so a rule that
  reads `user.role` could be asked for as any role. It reads the session.

These prove the generated routes say so; the answer on a running app is read
by the contract tests against a seeded copy."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INJECTOR = (ROOT / "services" / "runtime_injector.py").read_text(encoding="utf-8")
FORM_RULES = (ROOT / "templates" / "app-foundation" / "src" / "app" / "api" / "form-rules" / "route.ts").read_text(encoding="utf-8")


def _execute_route() -> str:
    start = INJECTOR.index("def _generate_workflow_api_route")
    return INJECTOR[start:INJECTOR.index("def _generate_workflow_event_route", start)
                    if "def _generate_workflow_event_route" in INJECTOR[start:] else start + 20000]


def test_a_client_cannot_write_the_engines_keys():
    route = _execute_route()
    strip = route.index("THE ENGINE'S OWN KEYS ARE NOT THE CALLER'S TO WRITE")
    assert "/^__(step_|user$|guest$|origin$)/.test(k)" in route[strip:strip + 900]
    # The strip comes before the route sets those keys itself.
    assert strip < route.index("input.__origin =") and strip < route.index("(input as any).__guest = _guest")
    assert strip < route.index("[`__step_${resumeTaskRow.node_id}_completed`]: true")


def test_the_callers_decision_and_form_survive_the_strip():
    route = _execute_route()
    pattern = re.search(r"test\(k\)\) delete", route)
    assert pattern
    assert "step_|user$|guest$|origin$" in route and "decision" not in route[route.index("step_|user$"):route.index("step_|user$") + 60]


def test_a_task_is_completed_by_who_it_is_assigned_to():
    route = _execute_route()
    assert route.count("assignee_id, assignee_role") == 2, "both ways of finding the task read its assignee"
    check = route.index("A TASK IS COMPLETED BY WHO IT IS ASSIGNED TO")
    body = route[check:check + 1200]
    assert "!a.assignee_id && !a.assignee_role" in body, "a task naming nobody is anyone's"
    assert "a.assignee_id === String(user?.id)" in body
    assert 'split(",")' in body and "includes(String(user?.role))" in body
    assert "status: user?.id ? 403 : 401" in body
    # And it is decided before the task's markers are written.
    assert check < route.index("const pv =")


def test_form_rules_read_the_session_not_the_body():
    assert 'import { auth } from "@/auth";' in FORM_RULES
    assert "evaluateFormRules(model, values, user)" in FORM_RULES
    assert "body?.user" not in FORM_RULES
