"""A control may only run a workflow the application defines; the author must
be able to see which those are.

The page author was asked to write `{label, workflow}` and handed a brief with
no workflows in it. On a real run the /audit page targeted
`exportCaseActivity` — a name inferred from the page — and /audit/[id]
targeted `$item.value`, a template; the validator refused both, twice, and the
pages failed. The vocabulary was closed but invisible.

The brief now carries the live workflows by id, and the prompt says the id is
the only legal spelling. Nothing is repaired afterwards: an invented name is
still refused, because the author has now been told.
"""
from services.blueprint.page_planner import page_brief


DOC = {
    "pages": [{"id": "PAGE-009", "route": "/audit", "name": "Audit Log",
               "requirements": [], "users": [], "data": {}}],
    "workflows": [
        {"id": "FLOW-007", "name": "Case Assignment",
         "trigger": {"kind": "manual", "detail": "Manager picks an assignee."}},
        {"id": "FLOW-013", "name": "Overdue Case Sweep",
         "trigger": {"kind": "scheduled"}},
        {"id": "FLOW-099", "name": "Retired", "status": "DEPRECATED",
         "trigger": {"kind": "manual"}},
    ],
    "requirements": [], "roles": [], "widgets": [], "entities": [],
}


def test_the_brief_lists_every_live_workflow_by_id():
    ids = [w["id"] for w in page_brief(DOC, "PAGE-009")["workflows"]]
    assert ids == ["FLOW-007", "FLOW-013"]


def test_each_entry_says_what_the_workflow_is_for():
    """An id alone is a lottery ticket; the name and trigger are what let the
    author choose the right one."""
    first = page_brief(DOC, "PAGE-009")["workflows"][0]
    assert first == {"id": "FLOW-007", "name": "Case Assignment",
                     "trigger": "Manager picks an assignee."}


def test_a_scheduled_workflow_still_states_its_kind():
    sweep = page_brief(DOC, "PAGE-009")["workflows"][1]
    assert sweep["trigger"] == "scheduled"


def test_the_prompt_closes_the_vocabulary():
    """The instruction lives beside the brief, in the executor's user prompt."""
    import inspect
    from services.blueprint import executors
    src = inspect.getsource(executors)
    assert "names it by id from `workflows`" in src
    assert "there is no workflow this application runs that is not in" in src
