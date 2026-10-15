"""A `done` with nothing changed after a try is not "Nothing needed doing":
it says what was tried and what it showed, and where the person might be
looking. The tester on an earlier publish's address was told nothing
needed doing while the preview had the fix (pcn4owv7, 2026-10-15)."""
from __future__ import annotations

from services.smith4.outcome import Outcome
from services.smith4.turn import STILL_FAILS_FOR_YOU, _ended
from services.smith.loop import Observation


def test_a_done_after_a_try_reports_the_try():
    seen = [Observation(tool="try_request", args={"method": "POST", "path": "/api/auth/signup"}, status="read",
                        said="POST /api/auth/signup as signed out: HTTP 201 | answer: {\"id\": \"…\"}\nmore lines")]
    out = _ended("done", {}, [], [], None, seen)
    assert out.status == "no_op"
    assert out.said.startswith("I changed nothing this turn. What I tried, and what it showed:\n- POST /api/auth/signup as signed out: HTTP 201")
    assert out.said.endswith(STILL_FAILS_FOR_YOU)


def test_a_done_with_words_or_a_change_is_left_as_it_was():
    seen = [Observation(tool="try_request", args={}, status="read", said="HTTP 201")]
    assert _ended("done", {}, ["Rewrote /signup"], [], None, seen).said == "Rewrote /signup"
    assert _ended("done", {}, [], [], Outcome(status="no_op", said="All good."), seen).said == "All good."
    assert _ended("done", {}, [], [], None, []).said == "Nothing needed doing."
