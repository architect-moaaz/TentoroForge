"""Med Tracker on forge-v3 (egqkhylj), 2026-09-29. The tester asked Smith to
remove a field; Smith showed what that takes and asked "Shall I go ahead?".
"Go ahead" is also a build consent, so the router answered it — "It is already
built from this definition, and nothing has changed since" — and the removal
never ran. "Build it again anyway", the rebuild question's own button, reached
Smith as a change and it asked about the removal again. Three rounds, then the
tester stopped.
"""
from __future__ import annotations

import ast
import inspect
import json

from routers import blueprint_generate as router
from services.smith import confirm, pending_ask, plan


def _pending(tmp_path, rel, body):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body))


def test_go_ahead_to_a_pending_confirmation_goes_to_smith(tmp_path):
    assert not router._smith_is_waiting(tmp_path, "Go ahead")  # nothing asked: a build consent as before
    _pending(tmp_path, confirm.PENDING_PATH, {"fingerprint": confirm.fingerprint("remove_field", "Medicine.preferredTime")})
    for said in ("Go ahead", "go ahead.", "Yes", "do it", "proceed"):
        assert router._smith_is_waiting(tmp_path, said), said


def test_a_pending_plan_or_question_is_answered_the_same_way(tmp_path):
    _pending(tmp_path, plan.PENDING_PATH, {"steps": ["remove the field"]})
    assert router._smith_is_waiting(tmp_path, "Go ahead")
    (tmp_path / plan.PENDING_PATH).unlink()
    _pending(tmp_path, pending_ask.PENDING_PATH, {"question": "which page?"})
    assert router._smith_is_waiting(tmp_path, "yes")


def test_an_explicit_build_is_still_a_build_while_smith_waits(tmp_path):
    _pending(tmp_path, confirm.PENDING_PATH, {"fingerprint": "remove_field:x"})
    for said in ("Build app", "build it", "Build it again anyway"):
        assert not router._smith_is_waiting(tmp_path, said), said


def test_smith_takes_the_yes_it_asked_for(tmp_path):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    assert confirm.granted(tmp_path, "Go ahead", "remove_field", "Medicine.preferredTime")


def test_the_rebuild_questions_buttons_each_do_what_they_say():
    assert router._is_forced_rebuild("Build it again anyway")
    assert not router._is_forced_rebuild("build it")  # a plain build is still asked about when nothing changed
    doc = {"pages": [{"id": "PAGE-004", "name": "Add/Edit Medicine", "route": "/medicines/[id]"},
                     {"id": "PAGE-009", "name": "Old", "route": "/old", "status": "DEPRECATED"}]}
    shown = router._rebuild_guard_answer("Show me the screens", doc)
    assert "**Add/Edit Medicine** — `/medicines/[id]`" in shown and "Old" not in shown
    assert "nothing rebuilt" in router._rebuild_guard_answer("Nothing, I'll change something first", doc)
    assert router._rebuild_guard_answer("remove Preferred time field", doc) is None


def test_the_handler_asks_smith_first():
    """Both build shortcuts in the chat handler stand aside for Smith's answer."""
    src = inspect.getsource(router)
    tree = ast.parse(src)
    guarded = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_src = ast.get_source_segment(src, node.test) or ""
            if "_is_build_consent(req.message)" in test_src:
                guarded.append("_answers_smith" in test_src)
    assert guarded and all(guarded), guarded
    body = inspect.getsource(router)
    assert body.index("_answers_smith = _smith_is_waiting(output_dir, req.message)") < body.index(
        "It is already built from this definition")
