# backend/tests/services/test_crud_actions.py
from services.crud_actions import derive_crud_actions

_WF = {"CreateTask", "UpdateTask", "DeleteTask"}
_PAGES = [
    {"route": "/tasks", "type": "list", "entity": "Task"},
    {"route": "/tasks/new", "type": "form", "entity": "Task"},
    {"route": "/tasks/:id", "type": "detail", "entity": "Task"},
]


def test_list_page_gets_new_nav_and_row_delete():
    acts = derive_crud_actions(_PAGES[0], "Task", _WF, _PAGES)
    kinds = {(a["label"], a["kind"], a.get("workflow"), a.get("to")) for a in acts}
    assert ("New", "navigate", None, "/tasks/new") in kinds
    assert ("Delete", "row_action", "DeleteTask", None) in kinds


def test_detail_page_gets_edit_nav_and_delete():
    acts = derive_crud_actions(_PAGES[2], "Task", _WF, _PAGES)
    labels = {(a["label"], a["kind"]) for a in acts}
    assert ("Edit", "navigate") in labels
    assert ("Delete", "page_action") in labels


def test_only_targets_existing_workflows():
    acts = derive_crud_actions(_PAGES[0], "Task", set(), _PAGES)  # no workflows
    # Delete dropped (no DeleteTask); New nav still present (nav needs no workflow)
    assert all(a["kind"] == "navigate" for a in acts)


def test_form_and_entityless_pages_get_nothing():
    assert derive_crud_actions(_PAGES[1], "Task", _WF, _PAGES) == []
    assert derive_crud_actions({"route": "/x", "type": "dashboard", "entity": None}, None, _WF, _PAGES) == []
