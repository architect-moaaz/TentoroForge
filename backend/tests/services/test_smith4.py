"""Smith v4 — the loop is the front door.

No `understand_ask`, no verb classifier, no `limits.cannot`. The first model
call is the same call as every other, and everything the old front door did
before the loop — answer, clarify, split a plan, refuse — is now something the
loop chooses, or a structural rule around it. The tests are named for the
behaviours; the fixtures are the loop tests' own.
"""
from __future__ import annotations

from services.smith import plan as plan_mod
from services.smith import tools
from services.smith.verbs import REQUIRED_BY_VERB
from services.smith4 import handle
from services.smith4.turn import LOOK_FIRST
from services.smith4.verbs import PERFORM
from tests.services._loop_fixtures import (_ClaimsWithoutWriting, _Chooser, _FindsNothing,
                                           _Writes, _rename, _repo)


def _turn(tmp_path, chooser, message="do it", *, move=None, history=None):
    return handle(project_id="p1", output_dir=str(tmp_path), message=message,
                  history=history, choose=chooser, move=move or _Writes(tmp_path))


# --------------------------------------------------------------------------- #
# There is no call before the loop
# --------------------------------------------------------------------------- #

def test_every_verb_is_performed_and_nothing_else_is():
    assert set(PERFORM) == set(REQUIRED_BY_VERB)


def test_the_front_door_has_no_classifier():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "services" / "smith4"
    for p in root.glob("*.py"):
        text = p.read_text("utf-8")
        assert "understand_ask(" not in text, p.name
        assert "limits.cannot" not in text and "cannot(" not in text, p.name


def test_the_first_step_is_the_models_choice(tmp_path):
    """No interpretation call decided a verb first; the chooser was asked
    with nothing above it and its choice was carried out."""
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"))

    result = _turn(tmp_path, chooser, "rename A", move=writes)

    assert chooser.seen[0] == []
    assert [c["target_file"] for c in writes.calls] == ["src/a.json"]
    assert result.status == "resolved" and "**A**" in result.said


# --------------------------------------------------------------------------- #
# The two failures the loop was written for, through the front door
# --------------------------------------------------------------------------- #

def test_a_move_that_found_nothing_is_read_by_the_step_after_it(tmp_path):
    from tests.services._loop_fixtures import _FindsNothing
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/page.json", "the dashboard"),
                       _rename("src/page.json", "Dashboard"))

    result = _turn(tmp_path, chooser, "yes please", move=_FindsNothing(writes))

    first = chooser.seen[1][0]
    assert first.status == "no_op" and "could not find" in first.said
    assert result.status == "resolved"


def test_three_asks_are_three_steps_of_one_turn(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"), _rename("src/b.json", "B"),
                       _rename("src/c.json", "C"))

    result = _turn(tmp_path, chooser, "a, b and c", move=writes)

    assert [c["target_file"] for c in writes.calls] == ["src/a.json", "src/b.json", "src/c.json"]
    assert result.status == "resolved"


# --------------------------------------------------------------------------- #
# What the old front door did is now the loop's choice
# --------------------------------------------------------------------------- #

def test_several_asks_become_a_plan_the_person_agrees_to_once(tmp_path):
    _repo(tmp_path)
    chooser = _Chooser({"tool": "propose_plan",
                        "args": {"steps": ["add a phone field", "show it on the form",
                                           "make it required"]}, "why": ""})

    result = _turn(tmp_path, chooser, "add a phone number, show it, make it required")

    assert result.status == "asked" and "Shall I work through them?" in result.said
    assert result.options == [plan_mod.ALL_LABEL, plan_mod.FIRST_LABEL, plan_mod.REWORD_LABEL]
    assert plan_mod.peek(str(tmp_path)) == ["add a phone field", "show it on the form",
                                            "make it required"]


def test_an_agreed_plan_step_is_a_turn_of_its_own(tmp_path):
    _repo(tmp_path)
    plan_mod.remember(str(tmp_path), ["rename A", "rename B"])
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"))

    result = _turn(tmp_path, chooser, plan_mod.ALL_LABEL, move=writes)

    assert [c["target_file"] for c in writes.calls] == ["src/a.json"]
    assert result.status == "resolved" and "rename B" in result.said   # the remaining note
    assert plan_mod.peek(str(tmp_path)) == ["rename B"]


def test_a_question_with_nothing_read_is_sent_to_look_first_once(tmp_path):
    _repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "r.tsx").write_text("x\n")
    chooser = _Chooser({"tool": "ask_user", "args": {"question": "Badge or section?"}, "why": ""},
                       {"tool": "read_file", "args": {"path": "src/r.tsx"}, "why": ""},
                       {"tool": "ask_user", "args": {"question": "Badge or section?"}, "why": ""})

    result = _turn(tmp_path, chooser, "accepted should need attention")

    assert chooser.seen[1][-1].status == "error" and chooser.seen[1][-1].said == LOOK_FIRST
    assert chooser.seen[2][-1].status == "read"
    assert result.status == "asked" and result.said == "Badge or section?"


def test_an_answer_is_for_a_turn_that_changed_nothing(tmp_path):
    _repo(tmp_path)
    chooser = _Chooser({"tool": "answer", "args": {"text": "It stores them in a database."}, "why": ""})
    result = _turn(tmp_path, chooser, "does it store data?")
    assert result.status == "no_op" and result.said == "It stores them in a database."


def test_an_answer_never_adds_prose_to_a_change(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"),
                       {"tool": "answer", "args": {"text": "Also, identity documents…"}, "why": ""})
    result = _turn(tmp_path, chooser, "rename A", move=writes)
    assert "identity documents" not in result.said and result.status == "resolved"


def test_a_verb_missing_its_fields_is_told_which_after_the_message_is_tried(tmp_path):
    _repo(tmp_path)
    chooser = _Chooser({"tool": "add_field", "args": {"entity": "Nurse"}, "why": ""})
    _turn(tmp_path, chooser, "add something")
    refused = chooser.seen[1][-1]
    assert refused.status == "error" and "field" in refused.said


def test_a_tool_outside_the_catalogue_is_named_never_mapped(tmp_path):
    _repo(tmp_path)
    chooser = _Chooser({"tool": "refactor_everything", "args": {}, "why": ""})
    _turn(tmp_path, chooser, "do it all")
    assert "no tool called" in chooser.seen[1][-1].said


def test_a_read_is_observed_whole(tmp_path):
    _repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "t.tsx").write_text("<Button>Archive</Button>\n")
    chooser = _Chooser({"tool": "read_file", "args": {"path": "src/t.tsx"}, "why": ""})
    _turn(tmp_path, chooser, "look")
    looked = chooser.seen[1][-1]
    assert looked.status == "read" and "    1| <Button>Archive</Button>" in looked.said


# --------------------------------------------------------------------------- #
# Findings carry on; questions end; the reply is what landed
# --------------------------------------------------------------------------- #

def test_a_proof_the_edit_missed_is_handed_back(tmp_path):
    from tests.services._loop_fixtures import _ClaimsWithoutWriting
    _repo(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"), _rename("src/b.json", "B"))

    result = _turn(tmp_path, chooser, "rename A", move=_ClaimsWithoutWriting(tmp_path, claims=1))

    heard = chooser.seen[1][-1]
    assert heard.status == "finding" and "nothing was written" in heard.said
    assert result.status == "resolved"


def test_a_finding_the_loop_cannot_settle_is_still_shown(tmp_path):
    from tests.services._loop_fixtures import _ClaimsWithoutWriting
    _repo(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"))
    result = _turn(tmp_path, chooser, "rename A", move=_ClaimsWithoutWriting(tmp_path))
    assert result.status == "needs_user" and "nothing actually changed" in result.said


def test_the_cap_is_said(tmp_path, monkeypatch):
    import services.smith.loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_STEPS", 3)
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(*[_rename(f"src/{i}.json", f"L{i}") for i in range(6)])
    result = _turn(tmp_path, chooser, "many things", move=writes)
    assert len(writes.calls) == 3 and "3 steps" in result.said


def test_propose_plan_is_in_the_catalogue():
    assert "propose_plan" in tools.TERMINAL_NAMES and "propose_plan" in tools.render()


# --------------------------------------------------------------------------- #
# Carried over from the v2 loop's tests
# --------------------------------------------------------------------------- #

def test_already_done_is_identity_not_a_list_of_repeatable_verbs():
    from services.smith.loop import Observation, already_done
    seen = [Observation(tool="add_field", args={"entity": "Nurse", "field": {"name": "phone"}})]
    assert already_done("add_field", {"entity": "Nurse", "field": {"name": "phone"}}, seen)
    assert not already_done("add_field", {"entity": "Nurse", "field": {"name": "email"}}, seen)


def test_an_unreachable_chooser_ends_the_turn_on_what_landed():
    from services.smith.loop import next_step

    def boom(_prompt: str) -> str:
        raise RuntimeError("no network")

    assert next_step("x", "ctx", [], provider=boom)["tool"] == "done"
    assert next_step("x", "ctx", [], provider=lambda _p: "I think we should…")["tool"] == "done"


def test_a_refused_read_is_an_observation_the_loop_carries_on_from(tmp_path):
    _repo(tmp_path)
    (tmp_path / ".env").write_text("SECRET=x\n")
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "read_file", "args": {"path": ".env"}, "why": ""},
                       _rename("src/b.json", "B"))
    _turn(tmp_path, chooser, "do it", move=writes)
    refused = chooser.seen[1][-1]
    assert refused.status == "read" and "holds credentials" in refused.said
    assert len(writes.calls) == 1


def test_each_step_is_proved_against_its_own_baseline(tmp_path):
    """A second step measured from the first step's baseline would claim the
    first step's files, so a step that wrote nothing would look like it had."""
    from tests.services._front_door import IterationMove
    _repo(tmp_path)

    class _SecondClaims(_Writes):
        def __call__(self, understanding, output_dir):
            if not self.calls:
                return super().__call__(understanding, output_dir)
            self.calls.append(dict(understanding))
            return IterationMove(move_name="claims a change", touched_paths=["src/b.json"])

    move = _SecondClaims(tmp_path)
    chooser = _Chooser(_rename("src/a.json", "A"), _rename("src/b.json", "B"))
    result = _turn(tmp_path, chooser, "two things", move=move)
    assert len(move.calls) == 2
    assert result.status == "needs_user" and "nothing actually changed" in result.said
    assert "src/a.json" in result.touched


def test_the_composer_not_drawing_what_it_was_told_is_a_finding(tmp_path, monkeypatch):
    """"I changed /admin/dashboard, but the new screen does not show what you
    asked for" — a proof, so the step after it gets to act."""
    import services.smith.compose as compose_mod
    _repo(tmp_path)
    monkeypatch.setattr(compose_mod, "run", lambda *a, **k: {
        "applied": True, "edited_paths": ["src/pages/dashboard.tsx"],
        "missing": ["Rentals", "Overdue Returns"], "diff_summary": "composed"})
    chooser = _Chooser({"tool": "compose_route", "args": {"route": "/admin/dashboard"}, "why": ""},
                       {"tool": "add_field", "args": {"entity": "Rental", "field": {"name": "overdue"}},
                        "why": ""})
    _turn(tmp_path, chooser, "build the dashboard")
    proof = chooser.seen[1][-1]
    assert proof.status == "finding" and "does not draw" in proof.said and "Rentals" in proof.said


def test_the_prompt_renders_and_reaches_the_provider():
    """A live turn ended with zero model calls: a stray `{lat, lng}` in the
    prompt made `str.format` raise, and `next_step` swallowed it as "provider
    unreachable" and ended the turn. Every test injects a chooser, so nothing
    rendered the template. This does."""
    from services.smith.loop import next_step
    seen: dict = {}

    def capture(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"tool": "done", "args": {}, "why": ""}'

    out = next_step("rename the button", "the slice", [], [("user", "hi")], provider=capture)
    assert out["tool"] == "done" and out["why"] == ""
    assert "rename the button" in seen["prompt"] and "the slice" in seen["prompt"]
    assert "`read_page_code`" in seen["prompt"] and "`propose_plan`" in seen["prompt"]


def test_a_question_with_no_words_is_an_error_not_a_silent_end(tmp_path):
    """Live: `ask_user {}` ended a define turn with "Nothing needed doing"."""
    _repo(tmp_path)
    (tmp_path / "src").mkdir(); (tmp_path / "src" / "r.tsx").write_text("x\n")
    chooser = _Chooser({"tool": "read_file", "args": {"path": "src/r.tsx"}, "why": ""},
                       {"tool": "ask_user", "args": {}, "why": ""},
                       {"tool": "ask_user", "args": {"question": "Which shift?"}, "why": ""})
    result = _turn(tmp_path, chooser, "swap it")
    assert chooser.seen[2][-1].status == "error" and "needs `question`" in chooser.seen[2][-1].said
    assert result.status == "asked" and result.said == "Which shift?"


def test_an_answer_with_no_words_is_an_error_too(tmp_path):
    _repo(tmp_path)
    chooser = _Chooser({"tool": "answer", "args": {}, "why": ""},
                       {"tool": "answer", "args": {"text": "It does."}, "why": ""})
    result = _turn(tmp_path, chooser, "does it?")
    assert chooser.seen[1][-1].status == "error" and result.said == "It does."
