"""A page that already exists is changed with edits, not written again.

Live, 2026-09-28: "country, state and city should be related, for India and
Sri Lanka" rewrote /register whole three times — 16,438 characters a round,
60-80 seconds each: once for the change, once because the first line was
missing, once because the reviewer scored the page 7/10 on things that
predated the request. Now: when there is code, the writer returns edits that
quote what they replace; the one fixed first line is put there, not asked
for; and a changed page goes back to the writer only if the change broke it.
"""
import json

import pytest

from services.blueprint import page_look, ui_engineer
from services.blueprint.ui_engineer import (
    EditsDidNotApply, PAGE_CODE_SCHEMA, PAGE_EDIT_SCHEMA, apply_edits, compose_page,
)

LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'
VIEW = ('"use client";\nexport default function View() {\n  return (\n    <form className="p-6">\n'
        '      <input name="country" />\n      <input name="city" />\n    </form>\n  );\n}\n')


def _doc():
    return {"application": {"id": "t", "name": "Register", "description": "Workers."},
            "data": {"entities": [{"id": "ENTITY-001", "name": "Worker", "fields": [{"name": "country", "type": "string"}]}]},
            "pages": [{"id": "PAGE-001", "name": "Register", "route": "/register", "purpose": "Add a worker.",
                       "data": {"primaryEntity": "ENTITY-001"}}],
            "workflows": [], "composition": {"vision": "Calm.", "conventions": []}}


class _Writer:
    def __init__(self, replies):
        self.replies, self.calls, self.schemas = list(replies), [], []

    def __call__(self, *, system, user, schema, **_):
        self.calls.append(user)
        self.schemas.append(schema)
        return json.dumps(self.replies.pop(0))


class _Critic:
    accepts_images = True

    def __init__(self, verdicts):
        self.verdicts, self.seen = list(verdicts), 0

    def __call__(self, *, system, user, schema, images=()):
        self.seen += 1
        return json.dumps(self.verdicts.pop(0))


@pytest.fixture(autouse=True)
def _no_compiler(monkeypatch):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ui_engineer, "_page_plan", lambda *a, **k: None)
    monkeypatch.setattr(page_look, "render", lambda *a, **k: {"shots": {"desktop": "d.png"}, "errors": []})


def _edit(find, replace, file="view"):
    return {"file": file, "find": find, "replace": replace}


def _reply(*edits, load="", view=""):
    return {"rationale": "linked dropdowns", "edits": list(edits), "load": load, "view": view}


SELECT = '<select name="country"><option>India</option><option>Sri Lanka</option></select>'


def test_a_change_is_asked_for_as_edits_and_only_they_are_written(tmp_path):
    writer = _Writer([_reply(_edit('<input name="country" />', SELECT))])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer,
                           brief="country should be India or Sri Lanka",
                           current={"load": LOAD, "view": VIEW})
    assert writer.schemas == [PAGE_EDIT_SCHEMA]
    assert "CHANGE IT WITH EDITS" in writer.calls[0]
    assert SELECT in body["view"] and '<input name="city" />' in body["view"]
    assert body["view"].replace(SELECT, '<input name="country" />') == VIEW, "nothing else moved"
    assert body["load"] == LOAD


def test_a_first_write_is_still_the_whole_page(tmp_path):
    writer = _Writer([{"rationale": "", "load": LOAD, "view": VIEW}])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, writer)
    assert writer.schemas == [PAGE_CODE_SCHEMA]


def test_an_edit_that_does_not_match_changes_nothing_and_says_which(tmp_path):
    writer = _Writer([_reply(_edit('<input name="nation" />', SELECT)),
                      _reply(_edit('<input name="country" />', SELECT))])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, brief="India or Sri Lanka",
                           current={"load": LOAD, "view": VIEW})
    assert "edit 1 (view.tsx): `find` occurs 0 times" in writer.calls[1]
    assert "Its current code" in writer.calls[1] and '<input name="country" />' in writer.calls[1]
    assert SELECT in body["view"]


def test_edits_apply_all_or_nothing():
    with pytest.raises(EditsDidNotApply) as e:
        apply_edits({"load": LOAD, "view": VIEW},
                    [_edit('<input name="country" />', SELECT), _edit("name=", "id=")])
    assert "edit 2" in str(e.value) and "occurs" in str(e.value)


def test_a_whole_file_is_still_accepted_when_most_of_it_changes(tmp_path):
    new = '"use client";\nexport default function View() { return <main />; }\n'
    writer = _Writer([_reply(view=new)])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, brief="start the form over",
                           current={"load": LOAD, "view": VIEW})
    assert body["view"] == new and body["load"] == LOAD


def test_the_one_fixed_first_line_is_put_there_not_asked_for(tmp_path):
    writer = _Writer([{"rationale": "", "load": LOAD, "view": VIEW.replace('"use client";\n', "")}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer)
    assert len(writer.calls) == 1
    assert body["view"].startswith('"use client";')


TASTE = {"score": 7, "verdict": "revise", "strengths": ["clear"],
         "issues": [{"severity": "medium", "where": "header", "problem": "tight spacing", "fix": "more air"}]}
BROKE = {"score": 4, "verdict": "revise", "strengths": [],
         "issues": [{"severity": "high", "where": "form", "problem": "submit is off-screen", "fix": "move it",
                     "fromChange": True}]}
#: What Test2's Master Data was sent back for (2026-09-28): high-severity,
#: and on the page before the skill filter was ever asked for.
OLD = {"score": 4, "verdict": "revise", "strengths": [],
       "issues": [{"severity": "high", "where": "table, Country column", "problem": "shows numbers",
                   "fix": "show names", "fromChange": False},
                  {"severity": "high", "where": "phone", "problem": "drops five columns", "fix": "stack them",
                   "fromChange": False}]}


def test_a_changed_page_is_not_sent_back_for_taste(tmp_path):
    critic = _Critic([TASTE])
    writer = _Writer([_reply(_edit('<input name="country" />', SELECT))])
    body, spent = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic,
                               brief="India or Sri Lanka", current={"load": LOAD, "view": VIEW})
    assert critic.seen == 1 and len(writer.calls) == 1, "one write, one look"
    assert SELECT in body["view"]


def test_a_changed_page_the_change_broke_goes_back_as_edits(tmp_path):
    critic = _Critic([BROKE, {"score": 8, "verdict": "pass", "strengths": [], "issues": []}])
    writer = _Writer([_reply(_edit('<input name="country" />', SELECT)),
                      _reply(_edit('<form className="p-6">', '<form className="p-6 pb-24">'))])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic,
                           brief="India or Sri Lanka", current={"load": LOAD, "view": VIEW})
    assert critic.seen == 2 and writer.schemas == [PAGE_EDIT_SCHEMA, PAGE_EDIT_SCHEMA]
    assert "pb-24" in body["view"] and SELECT in body["view"]


def test_a_first_write_is_still_held_to_the_reviewers_taste(tmp_path):
    critic = _Critic([TASTE, {"score": 9, "verdict": "pass", "strengths": [], "issues": []}])
    writer = _Writer([{"rationale": "", "load": LOAD, "view": VIEW},
                      _reply(_edit('<form className="p-6">', '<form className="p-8">'))])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic)
    assert critic.seen == 2 and "p-8" in body["view"]
    # The send-back of a first write is itself an edit of what was written.
    assert writer.schemas == [PAGE_CODE_SCHEMA, PAGE_EDIT_SCHEMA]


def test_the_edit_schema_carries_no_keyword_the_api_refuses():
    text = json.dumps(PAGE_EDIT_SCHEMA)
    for k in ("maxItems", "minItems", "maxLength", "minLength", "pattern", "uniqueItems"):
        assert f'"{k}"' not in text


def test_a_change_is_not_sent_back_for_what_the_page_already_had(tmp_path):
    critic = _Critic([OLD])
    writer = _Writer([_reply(_edit('<input name="country" />', SELECT))])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=critic,
                 brief="add a filter on skill", current={"load": LOAD, "view": VIEW})
    assert critic.seen == 1 and len(writer.calls) == 1


def test_the_reviewer_is_told_the_change_and_asked_what_it_caused(tmp_path, monkeypatch):
    seen = {}

    class _Looking(_Critic):
        def __call__(self, *, system, user, schema, images=()):
            seen.update(user=user, schema=schema)
            return super().__call__(system=system, user=user, schema=schema, images=images)
    writer = _Writer([_reply(_edit('<input name="country" />', SELECT))])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=_Looking([TASTE]),
                 brief="add a filter on skill", current={"load": LOAD, "view": VIEW})
    assert "JUST CHANGED" in seen["user"] and "add a filter on skill" in seen["user"]
    assert "fromChange" in seen["schema"]["properties"]["issues"]["items"]["required"]


def test_a_first_write_is_judged_whole_with_the_shared_schema(tmp_path):
    from services.blueprint.page_review import REVIEW_SCHEMA
    seen = {}

    class _Looking(_Critic):
        def __call__(self, *, system, user, schema, images=()):
            seen.update(user=user, schema=schema)
            return super().__call__(system=system, user=user, schema=schema, images=images)
    writer = _Writer([{"rationale": "", "load": LOAD, "view": VIEW}])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, writer,
                 critic=_Looking([{"score": 9, "verdict": "pass", "strengths": [], "issues": []}]))
    assert seen["schema"] is REVIEW_SCHEMA and "JUST CHANGED" not in seen["user"]


def test_the_send_back_of_a_change_lists_only_what_it_caused():
    verdict = {"score": 4, "issues": [OLD["issues"][0], BROKE["issues"][0]]}
    brief = page_look.look_brief(verdict, change_only=True)
    assert "submit is off-screen" in brief and "shows numbers" not in brief


def test_the_reviewer_of_a_change_is_told_the_ask_outranks_the_apps_conventions(tmp_path):
    """Test2, 2026-09-28: asked to add an Area to the location fields, the
    reviewer sent the form back — "high", caused by the change — because the
    build's conventions said the location panel holds exactly three fields."""
    seen = {}

    class _Looking(_Critic):
        def __call__(self, *, system, user, schema, images=()):
            seen["user"] = user
            return super().__call__(system=system, user=user, schema=schema, images=images)
    writer = _Writer([_reply(_edit('<input name="country" />', SELECT))])
    compose_page(_doc(), _doc()["pages"][0], tmp_path, writer, critic=_Looking([TASTE]),
                 brief="add an Area field", current={"load": LOAD, "view": VIEW})
    assert "OUTRANKS THE APP'S CONVENTIONS" in seen["user"]
