"""Tasks 8-11 (UAT): a request to look is answered, not planned; no framework
question; no 'change applied' sentence for a requirements reply; tiny apps get
a default look instead of a colour question."""
import json
import sys

from services.smith import clarify_brief as cb, gates, look_ask, plan as plan_mod


# --- 8 -------------------------------------------------------------------------------------------

def test_requests_to_look_are_recognised_and_changes_are_not():
    for m in ("Show me the screens", "open the preview", "Let me see it", "what does it look like?",
              "show me the app", "Can you show me the pages"):
        assert look_ask.is_look_request(m), m
    for m in ("show a delete button on each row", "show me a delete button on each row",
              "show the price column", "add a screen", "remove the preferred time field"):
        assert not look_ask.is_look_request(m), m


def test_a_look_is_answered_and_the_waiting_plan_is_untouched(tmp_path, monkeypatch):
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    plan_mod.remember(tmp_path, ["remove preferred time", "rebuild"], agreed=False)
    p = tmp_path / plan_mod.PENDING_PATH
    before = p.read_text()
    chosen = []
    for msg in ("Show me the screens", "open the preview", "let me see it"):
        got = handle_fn(project_id="p", output_dir=str(tmp_path), message=msg,
                        choose=lambda *a: chosen.append(a) or {"tool": "answer", "args": {"text": "x"}}, move=None)
        assert got.status == "resolved" and "screens" in got.said.lower()
    assert chosen == [] and p.read_text() == before                      # no model turn, plan unchanged


def test_a_real_change_still_reaches_the_loop(tmp_path, monkeypatch):
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    seen = []
    handle_fn(project_id="p", output_dir=str(tmp_path), message="show a delete button on each row",
              choose=lambda ask, page, obs, hist: (seen.append(ask), {"tool": "answer", "args": {"text": "ok"}})[1], move=None)
    assert seen and "delete button" in seen[0]


# --- 9 -------------------------------------------------------------------------------------------

def _provider(*qs):
    return lambda prompt: json.dumps({"questions": [{"question": q, "options": ["a", "b"]} for q in qs]})


def test_a_framework_question_is_never_asked():
    out = cb.clarify_brief("A medicine tracker for patients with reminders and a history of doses taken each day.",
                           provider=_provider("Which framework should MediTrack be built in?",
                                              "Who uses it, patients or carers?"))
    assert [q["question"] for q in out] == ["Who uses it, patients or carers?"]


def test_the_requirements_reply_says_how_it_is_built():
    doc = {"requirements": [{"id": "REQ-001", "description": "Track doses.", "status": "APPROVED"}]}
    said = gates.say_requirements(doc)
    assert "responsive web app that also installs on phones" in said and "framework" not in said.lower()


def test_an_explicit_native_demand_is_confirmed_once():
    brief = "Build me a native React Native app for tracking medicine."
    (q,) = cb.clarify_brief(brief, provider=_provider("never reached"))
    assert "web app" in q["question"] and q["options"][0] == cb.NATIVE_CONFIRM_YES
    assert cb.clarify_brief(brief + "\n" + cb.NATIVE_CONFIRM_YES, provider=_provider()) == []   # answered: not asked again


# --- 10 ------------------------------------------------------------------------------------------

def test_no_change_applied_sentence_before_there_is_an_app(tmp_path):
    from services.smith4 import verbs
    ctx = verbs.Ctx(output_dir=str(tmp_path), project_id="p", message="m", ask="m")
    ctx.applied = ["Recorded REQ-001"]
    said = verbs.rebuild(ctx, {}).said
    assert "nothing needs rebuilding" not in said and "already in the application" not in said
    assert "Publish carries them live" not in said


def test_a_real_applied_change_on_a_built_app_still_says_so(tmp_path):
    from services.smith4 import verbs
    (tmp_path / "app/src/schemas").mkdir(parents=True)
    (tmp_path / "app/package.json").write_text("{}")
    (tmp_path / "app/src/schemas/home.json").write_text("{}")
    ctx = verbs.Ctx(output_dir=str(tmp_path), project_id="p", message="m", ask="m")
    ctx.applied = ["Changed the form"]
    assert "nothing needs rebuilding" in verbs.rebuild(ctx, {}).said


# --- 11 ------------------------------------------------------------------------------------------

def test_a_tiny_app_gets_no_colour_question_a_larger_one_does():
    colour = "Which colour direction feels right for this app?"
    tiny = "A simple form where I enter a name and an email and it saves them."
    big = ("A clinic app with patient records, appointment booking, an admin dashboard for staff, "
           "reports on visits and payments, and reminders by email for every appointment.")
    assert cb.is_very_small(tiny) and not cb.is_very_small(big)
    assert cb.clarify_brief(tiny, provider=_provider(colour)) == []
    assert [q["question"] for q in cb.clarify_brief(big, provider=_provider(colour))] == [colour]


def test_a_colour_named_in_the_request_is_not_asked_and_the_prompt_says_so():
    seen = []
    cb.clarify_brief("A simple form app in forest green.", provider=lambda p: seen.append(p) or '{"questions": []}')
    assert "do NOT ask about colour" in seen[0] and "forest green" in seen[0]
