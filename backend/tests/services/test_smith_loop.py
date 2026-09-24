"""The change turn as a loop — S1 of `2026-09-24-smith-as-a-loop`.

What is being asserted is narrow on purpose. The loop adds a SECOND LOOK and
nothing else: every step is a verb the dispatcher already had, carried out by
the code that carried out step one, proved by the same ground-truth checks.
So the tests are about who chooses the next step and what they are allowed to
choose — not about any verb's behaviour, which is unchanged.

The two failures it exists for have a test each and are named after them:
a move that reported it changed nothing (`docs/SMITH-VERBS.md`), and a message
that asked for three things.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from services.smith import tools
from services.smith.loop import MAX_STEPS, Observation, already_done, next_step
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP
from services.smith_blueprint import Blueprint
from services.smith_session import IterationMove, SmithSession, TurnResult


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _repo(tmp_path: Path) -> Path:
    subprocess.check_call(["git", "init", "-q", str(tmp_path)])
    subprocess.check_call(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"])
    subprocess.check_call(["git", "-C", str(tmp_path), "config", "user.name", "T"])
    (tmp_path / "seed.txt").write_text("seed")
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "."])
    subprocess.check_call(["git", "-C", str(tmp_path), "commit", "-qm", "seed"])
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()
    return tmp_path


def _understanding(**given: Any) -> dict:
    """What `understand_ask` returns, with only the keys a turn reads."""
    out = {"answer": "", "clarification_needed": "", "clarification_options": [],
           "asks": [], "verb": "rename", "route": "", "widgets": [],
           "target_file": "", "element_label": "", "new_value": "",
           "screen": given.get("target_file", ""),
           "entity": "", "change": "",
           "current_behavior": "was", "desired_behavior": "now", "field": {}}
    out.update(given)
    return out


class _Writes:
    """A move that really edits a file, so the ground-truth checks are real."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.calls: list[dict] = []

    def __call__(self, understanding: dict, output_dir: str):
        self.calls.append(dict(understanding))
        target = str(understanding.get("target_file") or "").strip()
        label = str(understanding.get("element_label") or "").strip()
        path = Path(output_dir) / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"label": "{label}"}}\n')
        return IterationMove(move_name=f"edit({target})", touched_paths=[target])


class _FindsNothing:
    """A move that reports it changed nothing — the `SMITH-VERBS.md` failure."""

    def __init__(self, then: Any):
        self.then = then
        self.calls = 0

    def __call__(self, understanding: dict, output_dir: str):
        self.calls += 1
        if self.calls == 1:
            return None
        return self.then(understanding, output_dir)


class _Chooser:
    """A scripted next-step seam; records what it was shown."""

    def __init__(self, *steps: dict):
        self.steps = list(steps)
        self.seen: list[list[Observation]] = []
        self.histories: list[list] = []

    def __call__(self, ask: str, ctx: str, observations: list,
                 history: list | None = None) -> dict:
        self.seen.append(list(observations))
        self.histories.append(list(history or []))
        if not self.steps:
            return {"tool": "done", "args": {}, "why": ""}
        return self.steps.pop(0)


def _session(tmp_path: Path, *, understanding: dict, move: Any,
             chooser: Any = None) -> SmithSession:
    return SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        guards_fn=lambda _out: [],
        understand_ask_fn=lambda *a, **k: understanding,
        iteration_move_fn=move,
        next_step_fn=chooser,
    )


def _rename(target: str, label: str) -> dict:
    return {"tool": "rename",
            "args": {"target_file": target, "element_label": label,
                     "new_value": label, "screen": target,
                     "current_behavior": "was", "desired_behavior": "now"},
            "why": f"rename {label}"}


# --------------------------------------------------------------------------- #
# The catalogue is the verb table
# --------------------------------------------------------------------------- #

def test_the_catalogue_is_the_verb_table_and_nothing_else():
    """No second list. A tool that is not a verb cannot be written."""
    named = [t["name"] for t in tools.catalogue()]
    assert named == list(REQUIRED_BY_VERB)
    assert all(t["description"] == VERB_HELP.get(t["name"], "") for t in tools.catalogue())


def test_every_required_field_has_a_declared_shape():
    """A verb requiring a field the catalogue cannot describe fails here
    rather than arriving at the model as an unexplained string."""
    assert tools.untyped() == frozenset()


def test_a_tool_outside_the_catalogue_is_named_not_mapped():
    assert not tools.is_tool("refactor_everything")
    assert "refactor_everything" in tools.unknown("refactor_everything")
    assert all(tools.is_tool(v) for v in REQUIRED_BY_VERB)
    assert all(tools.is_tool(t) for t in tools.TERMINAL_NAMES)


# --------------------------------------------------------------------------- #
# The two failures it exists for
# --------------------------------------------------------------------------- #

def test_a_move_that_found_nothing_is_read_by_the_step_after_it(tmp_path):
    """`docs/SMITH-VERBS.md`: "yes please" to Smith's own offer came back as
    "I don't see anything to change". The report is now an observation."""
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/page.json", "Dashboard"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/page.json",
                                     element_label="the dashboard",
                                     new_value="Dashboard"),
        move=_FindsNothing(writes), chooser=chooser)

    result = session.run_iteration("yes please")

    # The first step reported nothing; the second was chosen from that report.
    assert chooser.seen, "the chooser was never asked for a second step"
    first = chooser.seen[0][0]
    assert first.status == "no_op"
    assert "could not find" in first.said
    assert result.status == "resolved"
    assert "src/page.json" in result.touched_paths


def test_three_asks_in_one_message_are_three_steps_of_one_turn(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/b.json", "Phone"),
                       _rename("src/c.json", "Required"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json",
                                     element_label="Phone number",
                                     new_value="Phone number"),
        move=writes, chooser=chooser)

    result = session.run_iteration("add a phone number, show it, make it required")

    assert [c["target_file"] for c in writes.calls] == \
        ["src/a.json", "src/b.json", "src/c.json"]
    assert result.status == "resolved"
    assert {"src/a.json", "src/b.json", "src/c.json"} <= set(result.touched_paths)


# --------------------------------------------------------------------------- #
# What the loop may choose
# --------------------------------------------------------------------------- #

def test_an_unknown_tool_costs_a_step_and_never_reaches_a_seam(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "refactor_everything", "args": {}, "why": "all of it"},
                       _rename("src/b.json", "Phone"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration("do something")

    assert [c["target_file"] for c in writes.calls] == ["src/a.json", "src/b.json"]
    refused = chooser.seen[-1][-2]
    assert refused.status == "error"
    assert "no tool called" in refused.said


def test_the_same_call_twice_is_refused_by_identity(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    repeat = _rename("src/a.json", "A")
    chooser = _Chooser(repeat, _rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration("do it")

    # The repeat never reached the seam; a different call did.
    assert [c["target_file"] for c in writes.calls] == ["src/a.json", "src/b.json"]
    assert "already been taken" in chooser.seen[-1][-2].said


def test_a_step_missing_a_required_field_is_told_which(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "add_field", "args": {"entity": "Nurse"}, "why": ""},
                       {"tool": "done", "args": {}, "why": ""})
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration("add something")

    refused = chooser.seen[-1][-1]
    assert refused.status == "error" and "field" in refused.said


def test_already_done_is_identity_not_a_list_of_repeatable_verbs():
    seen = [Observation(tool="add_field", args={"entity": "Nurse", "field": {"name": "phone"}})]
    assert already_done("add_field", {"entity": "Nurse", "field": {"name": "phone"}}, seen)
    assert not already_done("add_field", {"entity": "Nurse", "field": {"name": "email"}}, seen)


# --------------------------------------------------------------------------- #
# Where the loop stops
# --------------------------------------------------------------------------- #

def test_a_turn_with_no_chooser_takes_the_one_step_it_always_did(tmp_path):
    """Every caller predating the loop, and `MAX_STEPS = 1`, get this."""
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=None)

    result = session.run_iteration("rename A")

    assert len(writes.calls) == 1
    assert result.status == "resolved"


def test_a_step_that_cannot_run_is_recovered_from_not_fatal(tmp_path):
    """Want of a fact costs a step and is said; it does not end the turn.
    The turn ends on a step that RAN and failed its proof — see the baseline
    test at the bottom."""
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "compose_route", "args": {"route": ""}, "why": ""},
                       _rename("src/c.json", "C"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    result = session.run_iteration("do two things")

    assert [c["target_file"] for c in writes.calls] == ["src/a.json", "src/c.json"]
    assert result.status == "resolved"


def test_the_cap_is_reported_rather_than_dropped(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(*[_rename(f"src/{i}.json", f"L{i}") for i in range(MAX_STEPS + 3)])
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    result = session.run_iteration("do a great many things")

    assert len(writes.calls) == MAX_STEPS
    assert f"{MAX_STEPS} steps" in result.answer


def test_the_step_after_the_first_is_shown_the_exchange(tmp_path):
    """"yes please" means nothing without the question above it. Step one gets
    the history; the steps after it were reaching the chooser with the word
    alone, which answered a question nobody had asked."""
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "done", "args": {}, "why": ""})
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration("yes please", history=[
        ("user", "add a dashboard?"), ("smith", "Shall I build it at /admin?")])

    assert chooser.histories[0] == [("user", "add a dashboard?"),
                                    ("smith", "Shall I build it at /admin?")]


def test_an_answer_never_adds_prose_to_a_turn_that_changed_something(tmp_path):
    """The turn's reply is what the seams reported. Prose written at the end is
    prose about work nobody checked."""
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "answer",
                        "args": {"text": "Also, here is how identity documents work."},
                        "why": ""})
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    result = session.run_iteration("rename A")

    assert "identity documents" not in result.answer
    assert result.status == "resolved"


def test_a_cap_of_one_is_the_turn_as_it_shipped(tmp_path, monkeypatch):
    """Nobody is asked for a second step, so nothing is cut off — and the turn
    must not say it stopped early when it did everything there was."""
    import services.smith.loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_STEPS", 1)
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(_rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    result = session.run_iteration("rename A")

    assert len(writes.calls) == 1
    assert chooser.seen == []
    assert "steps in one turn" not in result.answer


def test_an_unreachable_chooser_ends_the_turn_on_what_landed():
    def boom(_prompt: str) -> str:
        raise RuntimeError("no network")

    assert next_step("x", "ctx", [], provider=boom)["tool"] == "done"


def test_an_unparseable_choice_ends_the_turn_rather_than_guessing():
    assert next_step("x", "ctx", [], provider=lambda _p: "I think we should…")["tool"] == "done"


# --------------------------------------------------------------------------- #
# A finding is evidence; a question is not
# --------------------------------------------------------------------------- #

class _ClaimsWithoutWriting(_Writes):
    """Reports a change it did not make — git catches it. `then` many times,
    after which it writes for real, so a test can watch a recovery."""

    def __init__(self, tmp_path, *, claims: int = 99):
        super().__init__(tmp_path)
        self.claims = claims

    def __call__(self, understanding, output_dir):
        if len(self.calls) < self.claims:
            self.calls.append(dict(understanding))
            return IterationMove(move_name="claims a change",
                                 touched_paths=["src/ghost.json"])
        return super().__call__(understanding, output_dir)


def test_a_proof_that_the_edit_missed_is_handed_back_not_to_the_person(tmp_path):
    """git said the tree did not change. That is evidence, and the step after
    it acts on it — where before it was four minutes of work ending in chips."""
    _repo(tmp_path)
    chooser = _Chooser(_rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=_ClaimsWithoutWriting(tmp_path, claims=1), chooser=chooser)

    result = session.run_iteration("rename A")

    # The turn did not end on the finding; the chooser was shown it.
    assert chooser.seen, "the finding ended the turn instead of being read"
    first = chooser.seen[0][0]
    assert first.status == "finding"
    assert "nothing was written" in first.said
    assert result.status == "resolved"


def test_a_question_is_not_a_finding_and_still_ends_the_turn(tmp_path):
    """"I do not recognise that", "are you sure" — no amount of thinking makes
    them answerable. Only a proof is worth a second step."""
    _repo(tmp_path)
    asked = TurnResult(status="needs_user", answer="Which screen did you mean?")
    chooser = _Chooser(_rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=_Writes(tmp_path), chooser=chooser)
    session._perform = lambda *a, **k: asked                     # noqa: SLF001

    result = session.run_iteration("rename A")

    assert chooser.seen == []
    assert result is asked


def test_a_finding_the_loop_cannot_settle_is_still_shown(tmp_path):
    """Kept out of what landed, so it has to be put back at the end — or the
    turn says "Done" and reports `needs_user` in the same breath."""
    _repo(tmp_path)
    chooser = _Chooser()                       # says `done` at once
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=_ClaimsWithoutWriting(tmp_path), chooser=chooser)

    result = session.run_iteration("rename A")

    assert result.status == "needs_user"
    assert "nothing actually changed" in result.answer


def test_the_composer_not_drawing_what_it_was_told_is_a_finding(tmp_path, monkeypatch):
    """The case the spec singled out: "I changed /admin/dashboard, but the new
    screen does not show what you asked for". Four minutes of work ending in
    three chips. It is a proof — the composer was told what to draw and the
    code does not draw it — so the step after it gets to act."""
    import services.smith.compose as compose_mod

    _repo(tmp_path)
    monkeypatch.setattr(compose_mod, "run", lambda *a, **k: {
        "applied": True, "edited_paths": ["src/pages/dashboard.tsx"],
        "missing": ["Rentals", "Overdue Returns"], "diff_summary": "composed",
    })
    chooser = _Chooser({"tool": "add_field",
                        "args": {"entity": "Rental", "field": {"name": "overdue"}},
                        "why": "the widget needs a field that is not there"})
    session = _session(
        tmp_path,
        understanding=_understanding(verb="compose_route", route="/admin/dashboard",
                                     target_file="/admin/dashboard",
                                     widgets=["Rentals", "Overdue Returns"]),
        move=_Writes(tmp_path), chooser=chooser)
    session.run_iteration("build the dashboard")

    assert chooser.seen, "the composer's proof ended the turn instead of being read"
    proof = chooser.seen[0][0]
    assert proof.status == "finding"
    assert "does not draw" in proof.said and "Rentals" in proof.said


# --------------------------------------------------------------------------- #
# The loop can look before it acts
# --------------------------------------------------------------------------- #

def test_a_read_is_observed_whole_and_the_next_step_acts_on_it(tmp_path):
    """§0: "knows the whole code in and out". A read writes nothing, needs no
    baseline and no proof, and what it saw is shown to the step after it as it
    was — not collapsed to a line."""
    _repo(tmp_path)
    (tmp_path / "src" / "pages").mkdir(parents=True)
    (tmp_path / "src" / "pages" / "tools.tsx").write_text("<Button>Archive</Button>\n")
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "read_file", "args": {"path": "src/pages/tools.tsx"}, "why": "look first"},
                       _rename("src/b.json", "Archive"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration("rename it to match the page")

    looked = chooser.seen[-1][-2]
    assert looked.status == "read"
    assert "    1| <Button>Archive</Button>" in looked.said
    assert "<Button>Archive</Button>" in looked.line()      # shown as read, not collapsed
    assert [c["target_file"] for c in writes.calls] == ["src/a.json", "src/b.json"]


def test_a_refused_read_is_an_observation_the_loop_carries_on_from(tmp_path):
    _repo(tmp_path)
    (tmp_path / ".env").write_text("SECRET=x\n")
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "read_file", "args": {"path": ".env"}, "why": ""},
                       _rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration("do it")

    refused = chooser.seen[-1][-2]
    assert refused.status == "read" and "holds credentials" in refused.said
    assert len(writes.calls) == 2


def test_an_answer_from_the_slice_alone_can_be_replaced_after_looking(tmp_path):
    """Measured 2026-09-25: asked what code decides which rentals need
    attention, Smith answered from the slice — five statuses where the code
    names three — and said it could not see the code. Now it can look."""
    _repo(tmp_path)
    (tmp_path / "src" / "pages").mkdir(parents=True)
    (tmp_path / "src" / "pages" / "rentals.tsx").write_text(
        'const ATTENTION = ["requested", "overdue", "disputed"];\n')
    chooser = _Chooser({"tool": "grep", "args": {"pattern": "ATTENTION"}, "why": "look"},
                       {"tool": "answer",
                        "args": {"text": "Three statuses: requested, overdue, disputed."},
                        "why": ""})
    session = _session(
        tmp_path,
        understanding=_understanding(answer="The Blueprint does not expose the filter; "
                                            "probably all five statuses."),
        move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("what decides which rentals need attention?")

    assert chooser.seen[0][0].tool == "answer"                  # the first answer, as a step
    assert chooser.seen[1][-1].status == "read"                 # then it looked
    assert result.answer == "Three statuses: requested, overdue, disputed."
    assert result.status == "no_op"


def test_a_clarification_the_code_can_answer_becomes_a_read_then_an_act(tmp_path):
    """Measured 2026-09-25: asked to make accepted rentals need attention,
    Smith asked whether the section existed. The code said it did."""
    _repo(tmp_path)
    (tmp_path / "src" / "pages").mkdir(parents=True)
    (tmp_path / "src" / "pages" / "rentals.tsx").write_text("const attention = [];\n")
    writes = _Writes(tmp_path)
    chooser = _Chooser({"tool": "grep", "args": {"pattern": "attention"}, "why": "look"},
                       _rename("src/pages/rentals.tsx", "attention"))
    session = _session(
        tmp_path,
        understanding=_understanding(clarification_needed="Does a needs-attention section already exist?",
                                     clarification_options=["Yes", "No"]),
        move=writes, chooser=chooser)

    result = session.run_iteration("accepted rentals should need attention too")

    assert chooser.seen[0][0].tool == "ask_user"                # the question, as a step
    assert chooser.seen[1][-1].status == "read"                 # then it looked
    assert result.status == "resolved"
    assert "Does a needs-attention" not in result.answer


def test_a_second_question_without_looking_is_sent_to_look_first(tmp_path):
    """Live: "does the section exist?" became "badge or section?" with the
    code unread. One refusal; after a look, a question that stands is asked."""
    _repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "r.tsx").write_text("x\n")
    chooser = _Chooser({"tool": "ask_user", "args": {"question": "Badge or section?"}, "why": ""},
                       {"tool": "read_file", "args": {"path": "src/r.tsx"}, "why": ""},
                       {"tool": "ask_user", "args": {"question": "Badge or section?"}, "why": ""})
    session = _session(
        tmp_path,
        understanding=_understanding(clarification_needed="Does the section exist?"),
        move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("accepted should need attention")

    refused = chooser.seen[1][-1]
    assert refused.status == "error" and "nothing has been read" in refused.said
    assert chooser.seen[2][-1].status == "read"
    assert result.status == "asked" and result.answer == "Badge or section?"


def test_a_clarification_left_standing_is_still_asked(tmp_path):
    _repo(tmp_path)
    chooser = _Chooser()                                        # done at once
    session = _session(
        tmp_path,
        understanding=_understanding(clarification_needed="Which colour?",
                                     clarification_options=["Red", "Blue"]),
        move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("change the colour")

    assert result.status == "asked" and result.answer == "Which colour?"
    assert result.options == ["Red", "Blue"]


def test_the_plans_consent_question_never_enters_the_loop(tmp_path):
    """Consent is the person's to give. The loop must not answer it for them."""
    _repo(tmp_path)
    chooser = _Chooser(_rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(asks=["add a field", "show it", "make it required"]),
        move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("add a field, show it, make it required")

    assert result.status == "asked" and "Shall I work through them?" in result.answer
    assert chooser.seen == []


def test_a_question_answered_and_left_alone_keeps_its_answer(tmp_path):
    """`done` after an answer from the slice: the answer stands."""
    _repo(tmp_path)
    chooser = _Chooser()                                        # done at once
    session = _session(
        tmp_path,
        understanding=_understanding(answer="It stores them in a database."),
        move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("does it store data?")

    assert result.answer == "It stores them in a database."
    assert result.status == "no_op"


# --------------------------------------------------------------------------- #
# A plan step is a turn
# --------------------------------------------------------------------------- #

def test_a_step_of_an_agreed_plan_loops_like_any_other_turn(tmp_path):
    """Measured 2026-09-24: an agreed plan took 0 loop steps, because
    `_run_step` went in one level below the loop."""
    from services.smith import plan as plan_mod

    _repo(tmp_path)
    writes = _Writes(tmp_path)
    plan_mod.remember(str(tmp_path), ["rename A", "rename B"])
    chooser = _Chooser(_rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=writes, chooser=chooser)

    session.run_iteration(plan_mod.ALL_LABEL)

    assert chooser.seen, "a plan step did not reach the loop"
    assert [c["target_file"] for c in writes.calls] == ["src/a.json", "src/b.json"]


# --------------------------------------------------------------------------- #
# Ground truth stays per step
# --------------------------------------------------------------------------- #

def test_each_step_is_proved_against_its_own_baseline(tmp_path):
    """A second step measured from the first step's baseline would claim the
    first step's files, so a step that wrote nothing would look like it had."""
    _repo(tmp_path)

    class _SecondClaimsWithoutWriting(_Writes):
        def __call__(self, understanding, output_dir):
            if not self.calls:
                return super().__call__(understanding, output_dir)
            self.calls.append(dict(understanding))
            return IterationMove(move_name="claims a change",
                                 touched_paths=["src/b.json"])

    move = _SecondClaimsWithoutWriting(tmp_path)
    chooser = _Chooser(_rename("src/b.json", "B"))
    session = _session(
        tmp_path,
        understanding=_understanding(target_file="src/a.json", element_label="A",
                                     new_value="A"),
        move=move, chooser=chooser)

    result = session.run_iteration("two things")

    assert len(move.calls) == 2
    assert result.status == "needs_user"
    assert "nothing actually changed" in result.answer
    # And what step one really did is still reported rather than thrown away.
    assert "src/a.json" in result.touched_paths
