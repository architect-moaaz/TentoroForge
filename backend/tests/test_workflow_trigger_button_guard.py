"""Tests for services.workflow_trigger_button_guard."""
import json
import os

from services.workflow_trigger_button_guard import neutralize_event_only_buttons


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def _workflow(id_, name, trigger_type):
    return {"id": id_, "name": name,
            "definition": {"trigger": {"type": trigger_type}, "steps": []}}


def _button(label, workflow):
    return {"id": "cta", "type": "Button",
            "props": {"label": label, "workflow": workflow}}


def _page(button):
    return {"root": {"type": "Stack", "children": [button]}}


def _setup(tmp_path):
    root = str(tmp_path)
    wf_dir = os.path.join(root, "workflows")
    os.makedirs(wf_dir, exist_ok=True)
    _write(os.path.join(wf_dir, "complianceCheck.json"),
           _workflow("compliancecheck", "ComplianceCheck", "db_change"))
    _write(os.path.join(wf_dir, "apiEvt.json"),
           _workflow("apievt", "ApiEvt", "api_event"))
    _write(os.path.join(wf_dir, "reminder.json"),
           _workflow("reminder", "Reminder", "schedule"))
    _write(os.path.join(wf_dir, "CreateThing.json"),
           _workflow("create-thing", "CreateThing", "manual"))
    return root


def test_event_button_on_list_page_removed(tmp_path):
    root = _setup(tmp_path)
    fp = os.path.join(root, "src", "schemas", "analytics.json")
    _write(fp, _page(_button("Run Full Compliance Check", "compliancecheck")))

    res = neutralize_event_only_buttons(root)

    assert len(res["removed"]) == 1
    page = json.loads(open(fp).read())
    # The dead button is gone.
    assert page["root"]["children"] == []


def test_api_event_and_schedule_buttons_removed(tmp_path):
    root = _setup(tmp_path)
    fp = os.path.join(root, "src", "schemas", "dash.json")
    _write(fp, {"root": {"type": "Stack", "children": [
        _button("Sync via API", "ApiEvt"),
        _button("Remind", "reminder"),
        _button("Create Thing", "CreateThing"),
    ]}})

    res = neutralize_event_only_buttons(root)

    assert len(res["removed"]) == 2  # api_event + schedule
    labels = [c["props"]["label"] for c in
              json.loads(open(fp).read())["root"]["children"]]
    assert labels == ["Create Thing"]  # only the manual button survives


def test_manual_workflow_button_untouched(tmp_path):
    root = _setup(tmp_path)
    fp = os.path.join(root, "src", "schemas", "things.json")
    _write(fp, _page(_button("Create Thing", "CreateThing")))

    res = neutralize_event_only_buttons(root)

    assert res["removed"] == []
    page = json.loads(open(fp).read())
    assert len(page["root"]["children"]) == 1


def test_event_button_on_detail_page_untouched(tmp_path):
    root = _setup(tmp_path)
    # A [id] detail route supplies the record context the workflow needs.
    fp = os.path.join(root, "src", "schemas", "candidates", "[id].json")
    _write(fp, _page(_button("Run Compliance Check", "compliancecheck")))

    res = neutralize_event_only_buttons(root)

    assert res["removed"] == []
    page = json.loads(open(fp).read())
    assert len(page["root"]["children"]) == 1


def test_event_button_in_row_actions_untouched(tmp_path):
    root = _setup(tmp_path)
    fp = os.path.join(root, "src", "schemas", "list.json")
    # A per-row action button carries its row's record context → leave it.
    _write(fp, {"root": {"type": "Table", "props": {"rowActions": [
        _button("Compliance Check", "compliancecheck"),
    ]}}})

    res = neutralize_event_only_buttons(root)

    assert res["removed"] == []


def test_idempotent(tmp_path):
    root = _setup(tmp_path)
    fp = os.path.join(root, "src", "schemas", "analytics.json")
    _write(fp, _page(_button("Run Full Compliance Check", "compliancecheck")))

    first = neutralize_event_only_buttons(root)
    assert len(first["removed"]) == 1
    second = neutralize_event_only_buttons(root)
    assert second["removed"] == []  # nothing left to remove
    assert second["files"] == 0


def test_no_workflows_dir_is_noop(tmp_path):
    root = str(tmp_path)
    fp = os.path.join(root, "src", "schemas", "p.json")
    _write(fp, _page(_button("X", "compliancecheck")))
    res = neutralize_event_only_buttons(root)
    assert res["removed"] == []
    assert res["disabled"] == []
