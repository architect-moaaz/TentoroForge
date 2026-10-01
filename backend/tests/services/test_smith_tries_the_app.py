"""Smith tries the app before deciding, and again before saying done.

F&B (UAT fxa532bj, 2026-10-01): a category that could not be added was
answered "Nothing needed doing" twice, after twelve steps of reading code that
read correctly; "can't add food" was answered "nothing has crashed"; a
sign-in that landed on the wrong screen got a rewritten `/login`. Each fault
was in what the app DID. These hold the three trials, the two rules that make
a turn use them, and the reply when a turn runs out of steps having changed
nothing.
"""
from __future__ import annotations

import json

import pytest

from services.smith import tools, trials
from services.smith4 import handle
from services.smith4.turn import NOTHING_TRIED, UNPROVEN
from tests.services._loop_fixtures import _Chooser, _repo, _Writes

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
    "workflows": [{"id": "FLOW-001", "name": "Create Category"},
                  {"id": "FLOW-002", "name": "Place Order"}],
    "pages": [],
}


def _turn(tmp_path, chooser, message="it does not work", **kw):
    return handle(project_id="p1", output_dir=str(tmp_path), message=message,
                  choose=chooser, move=_Writes(tmp_path), **kw)


def _try(workflow="FLOW-001"):
    return {"tool": "try_workflow", "args": {"workflow": workflow, "input": {"name": "Drinks"}}}


def _write(path="src/app/admin/categories/view.tsx"):
    return {"tool": "write_page_code", "args": {"route": "/admin/categories", "brief": "fix"}}


@pytest.fixture
def scripted(monkeypatch):
    """Trials and code writes, scripted: each trial answers the next canned
    observation; each write lands and touches a page file."""
    answers: list[str] = []
    calls: list[tuple[str, dict]] = []

    def fake_trial(name, args, *, bench, doc):
        calls.append((name, dict(args)))
        return answers.pop(0) if answers else "Create Category (FLOW-001) run as Admin (Admin): HTTP 201"

    def fake_write(name, args, *, output_dir, reasoning=None):
        calls.append((name, dict(args)))
        return {"applied": True, "said": "Rewrote **Categories**.",
                "touched": ["app/src/app/admin/categories/view.tsx"]}

    monkeypatch.setattr(trials, "run", fake_trial)
    monkeypatch.setattr("services.smith.writes.run", fake_write)
    return answers, calls


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #

def test_the_three_trials_are_tools_and_say_what_they_do():
    for name in ("try_workflow", "try_request", "open_page"):
        assert tools.is_tool(name) and tools.is_trial(name)
        assert not tools.is_read(name) and not tools.is_write(name)
    shown = tools.render()
    assert "Trying it (the running app, on a copy of its data" in shown
    assert "`try_workflow` (workflow: string, input: object, as: string)" in shown


def test_the_prompt_says_try_it_first_and_carries_no_dead_interface():
    from services.smith import loop
    prompt = loop._PROMPT
    assert "TRY IT FIRST" in prompt and "THEY SAID IT ALREADY" in prompt
    for gone in ("clarification_needed", "clarification_options", "explain_crash", '"verb": WHICH'):
        assert gone not in prompt, gone
    # each rule once: the block had been pasted three times over
    assert prompt.count("WHAT THE APPLICATION CANNOT DO IS SAID") == 1
    prompt.format(ask="a", history="", ctx="", observations="", catalogue="")


# --------------------------------------------------------------------------- #
# Done means tried
# --------------------------------------------------------------------------- #

def test_done_with_nothing_changed_and_nothing_tried_is_sent_to_try_once(tmp_path, scripted):
    _repo(tmp_path)
    chooser = _Chooser({"tool": "done", "args": {}}, {"tool": "done", "args": {}})
    result = _turn(tmp_path, chooser)
    assert chooser.seen[1][-1].said == NOTHING_TRIED
    assert result.status == "no_op"           # the second done stands


def test_a_failing_try_then_a_change_must_be_tried_again(tmp_path, scripted):
    answers, calls = scripted
    answers += ["Create Category (FLOW-001) run as Admin (Admin): HTTP 500\nanswer: "
                "{\"error\": \"A category with this name already exists\"}",
                "Create Category (FLOW-001) run as Admin (Admin): HTTP 201\nwritten:\ncategories: 1 row(s) now"]
    _repo(tmp_path)
    chooser = _Chooser(_try(), _write(), {"tool": "done", "args": {}}, _try(), {"tool": "done", "args": {}})
    result = _turn(tmp_path, chooser)
    nudge = chooser.seen[3][-1]
    assert nudge.tool == "done" and nudge.said.startswith(UNPROVEN) and "FLOW-001" in nudge.said
    assert [c[0] for c in calls] == ["try_workflow", "write_page_code", "try_workflow"]
    assert result.status == "resolved" and "Rewrote **Categories**." in result.said


def test_a_try_that_passed_needs_no_second_try(tmp_path, scripted):
    _repo(tmp_path)
    chooser = _Chooser(_try(), {"tool": "done", "args": {}})
    result = _turn(tmp_path, chooser)
    assert len(chooser.seen) == 2 and result.status == "no_op"


def test_the_same_try_with_nothing_changed_between_is_refused(tmp_path, scripted):
    _answers, calls = scripted
    _repo(tmp_path)
    chooser = _Chooser(_try(), _try(), {"tool": "done", "args": {}})
    _turn(tmp_path, chooser)
    assert [c[0] for c in calls] == ["try_workflow"]
    assert "already been made and nothing has changed" in chooser.seen[2][-1].said


def test_a_turn_that_runs_out_of_steps_having_changed_nothing_says_so(tmp_path, monkeypatch, scripted):
    import services.smith.loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_STEPS", 2)
    _repo(tmp_path)
    chooser = _Chooser({"tool": "grep", "args": {"pattern": "a"}}, {"tool": "grep", "args": {"pattern": "b"}})
    result = _turn(tmp_path, chooser)
    assert "Nothing needed doing" not in result.said
    assert "have not changed anything yet" in result.said and "(2)" in result.said


# --------------------------------------------------------------------------- #
# The bench: one copy a turn, fresh after the data model changes
# --------------------------------------------------------------------------- #

class _FakeApp:
    started = 0
    stopped = 0

    def __init__(self, root, log=None):
        self.base = "http://127.0.0.1:1"

    def __enter__(self):
        _FakeApp.started += 1
        return self

    def __exit__(self, *exc):
        _FakeApp.stopped += 1


def test_the_bench_starts_once_and_stops_when_asked(tmp_path):
    _FakeApp.started = _FakeApp.stopped = 0
    bench = trials.Bench(str(tmp_path), factory=_FakeApp)
    assert not bench.running
    assert bench.app() is bench.app()
    assert _FakeApp.started == 1 and bench.running
    bench.reset()
    assert _FakeApp.stopped == 1 and not bench.running
    bench.app()
    bench.close()
    assert _FakeApp.started == 2 and _FakeApp.stopped == 2


def test_the_bench_reports_only_new_server_errors(tmp_path):
    bench = trials.Bench(str(tmp_path), factory=_FakeApp)
    bench.app()
    with open(bench.log, "a") as f:
        f.write("✓ Compiled /api/x in 2s\n⨯ Error: column \"fulfilled\" does not exist\n")
    assert bench.server_said() == ['⨯ Error: column "fulfilled" does not exist']
    assert bench.server_said() == []


# --------------------------------------------------------------------------- #
# What a trial shows
# --------------------------------------------------------------------------- #

def test_a_role_is_found_by_name_or_id_and_signed_out_is_nobody():
    assert trials._role(DOC, "") == ("Admin", True)
    assert trials._role(DOC, "customer") == ("Customer", False)
    assert trials._role(DOC, "ROLE-002") == ("Customer", False)
    assert trials._role(DOC, "signed out") == ("", False)
    with pytest.raises(ValueError, match="Admin, Customer"):
        trials._role(DOC, "Chef")


def test_an_unknown_process_is_named_with_what_there_is(tmp_path):
    bench = trials.Bench(str(tmp_path), factory=_FakeApp)
    said = trials.try_workflow(bench, DOC, "Delete Everything", {}, "")
    assert "No process called 'Delete Everything'" in said and "Place Order (FLOW-002)" in said
    assert not bench.running        # nothing was started to say so


def test_what_was_written_is_shown_without_secrets():
    row_before = json.dumps({"id": 1, "name": "Tea", "price": 2})
    row_after = json.dumps({"id": 1, "name": "Tea", "price": 3})
    user = json.dumps({"id": 9, "email": "a@b.c", "password_hash": "$2b$xyz", "api_key": "k"})
    lines = trials._diff({"items": {row_before}, "users": set(), "orders": 5000},
                         {"items": {row_after}, "users": {user}, "orders": 5001})
    text = "\n".join(lines)
    assert '+ {"id": 1, "name": "Tea", "price": 3}' in text and '- {"id": 1, "name": "Tea", "price": 2}' in text
    assert "a@b.c" in text and "$2b$xyz" not in text and "password_hash" not in text and "api_key" not in text
    assert "orders: 5000 -> 5001 rows" in text
    assert trials._diff({"a": set()}, {"a": set()}) == ["no rows were written"]


@pytest.mark.parametrize("said, bad", [
    ("Place Order (FLOW-002) run as Admin (Admin): HTTP 500\nanswer: {}", True),
    ("GET /api/notifications as Admin (Admin): HTTP 200\nanswer: []", False),
    ("x: HTTP 201\nsteps:\n  0. Save [db_insert] failed — null value in column", True),
    ("/admin as Admin (Admin): HTTP 200\nbrowser error: pageerror: x is undefined", True),
    ('/admin as Admin (Admin): HTTP 200\ncontrols, each pressed from a fresh load:\n'
     '  button "Save": does nothing when pressed', True),
    ("x: HTTP 201\nwritten:\nno rows were written\nthe server printed:\n  ⨯ Error: boom", True),
])
def test_a_try_that_shows_something_broken_counts_as_failed(said, bad):
    assert trials.failed(said) is bad


def test_a_trial_that_cannot_start_is_an_observation_not_a_crash(tmp_path):
    from services.blueprint.page_review import ReviewUnavailable

    class _NoDocker(_FakeApp):
        def __enter__(self):
            raise ReviewUnavailable("Docker is not available for the app's database")

    bench = trials.Bench(str(tmp_path), factory=_NoDocker)
    said = trials.run("try_workflow", {"workflow": "FLOW-001"}, bench=bench, doc=DOC)
    assert said.startswith("The app could not be started to try this: Docker is not available")


# --------------------------------------------------------------------------- #
# A refusal goes to the loop before it goes to the person
# --------------------------------------------------------------------------- #

def test_a_seam_that_did_nothing_is_a_finding_unless_it_offers_choices():
    from services.smith4.outcome import from_seam
    refused = from_seam({"applied": False, "reason": "refused 2 times and nothing has been changed. "
                                                     "The last reason was: the agent returned nothing usable"},
                        fail="x")
    assert refused.finding and not refused.done       # the loop reads it and carries on
    choice = from_seam({"applied": False, "reason": "Which screen?", "options": ["Menu", "Orders"]}, fail="x")
    assert choice.finding == "" and choice.options == ["Menu", "Orders"]   # the person's to answer


def test_a_try_that_still_fails_after_the_change_is_said_and_never_hidden(tmp_path, scripted):
    """The live F&B replay: the workflow was changed, tried again, failed the
    same way — and the reply said only that it had been changed."""
    from services.smith4.turn import STILL_FAILING
    answers, _calls = scripted
    fail = "Create Category (FLOW-001) run as Admin (Admin): HTTP 422\nanswer: {\"error\": \"already exists\"}"
    answers += [fail, fail]
    _repo(tmp_path)
    chooser = _Chooser(_try(), _write(), _try(), {"tool": "done", "args": {}}, {"tool": "done", "args": {}})
    result = _turn(tmp_path, chooser)
    assert chooser.seen[4][-1].said.startswith(STILL_FAILING)
    assert "Rewrote **Categories**." in result.said and "It still does not work" in result.said


def test_a_step_shows_what_it_handed_on_without_secrets():
    shown = trials._shown(json.dumps({"rows": [{"id": 1, "password_hash": "x"}], "count": 1}))
    assert shown == '{"rows": [{"id": 1}], "count": 1}'


# --------------------------------------------------------------------------- #
# An app runs on the platform's current engine
# --------------------------------------------------------------------------- #

def test_a_stale_engine_is_brought_up_to_the_platforms_and_nothing_else_moves(tmp_path):
    """F&B kept the engine it was built with: the lookup fix shipped and its
    duplicate check went on refusing every new category."""
    from services.runtime_injector import _TEMPLATE_DIR
    from services.smith.sync_app import refresh_engine

    app = tmp_path / "app"
    stale = app / "src/lib/workflows/query-result.ts"
    stale.parent.mkdir(parents=True)
    stale.write_text("return { ...(first ?? {}), rows: list, count: list.length };")
    projected = app / "src/lib/workflows/definitions/flow-001.json"
    projected.parent.mkdir(parents=True)
    projected.write_text('{"id": "FLOW-001"}')
    roles = app / "src/lib/workflows/launch-roles.ts"
    roles.write_text("export const LAUNCH_ROLES = {};")

    changed = refresh_engine(app)

    assert "src/lib/workflows/query-result.ts" in changed
    assert stale.read_bytes() == (_TEMPLATE_DIR / "workflows/query-result.ts").read_bytes()
    assert (app / "src/lib/feel-lite/evaluator.ts").is_file()
    assert projected.read_text() == '{"id": "FLOW-001"}' and roles.read_text() == "export const LAUNCH_ROLES = {};"
    assert not any(c.startswith("src/lib/workflows/definitions") for c in changed)
    assert refresh_engine(app) == []          # current: nothing written, nothing recompiles


def test_every_turn_on_a_built_app_starts_on_the_current_engine(tmp_path, scripted):
    _repo(tmp_path)
    app = tmp_path / "app"
    (app / "src/lib/workflows").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    (app / "src/lib/workflows/query-result.ts").write_text("old")
    _turn(tmp_path, _Chooser({"tool": "answer", "args": {"text": "ok"}}), "what is this?")
    assert (app / "src/lib/workflows/query-result.ts").read_text() != "old"
