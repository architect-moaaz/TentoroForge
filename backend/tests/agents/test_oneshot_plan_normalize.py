from agents.planner import _normalize_oneshot_plan


def test_entities_dict_becomes_data_models_list():
    plan = {
        "domain": "Tasks",
        "entities": {
            "Task": {"table": "tasks",
                     "fields": [{"name": "id", "type": "uuid"}, {"name": "title", "type": "varchar"}],
                     "depends_on": ["Project"]},
            "Project": {"table": "projects", "fields": [{"name": "id", "type": "uuid"}]},
        },
        "pages": [],
    }
    out = _normalize_oneshot_plan(plan)
    dm = {m["name"]: m for m in out["data_models"]}
    assert set(dm) == {"Task", "Project"}
    assert dm["Task"]["table"] == "tasks"
    assert dm["Task"]["fields"][0]["primaryKey"] is True  # id marked PK
    # relation derived from depends_on
    assert any(r["from"] == "Task" and r["to"] == "Project" for r in out["relations"])
    assert out["module_name"]  # filled


def test_idempotent_when_data_models_already_present():
    plan = {"data_models": [{"name": "X", "fields": []}],
            "entities": {"Y": {"fields": []}}}
    out = _normalize_oneshot_plan(plan)
    assert [m["name"] for m in out["data_models"]] == ["X"]  # not clobbered


def test_noop_without_entities():
    plan = {"pages": [], "module_name": "m"}
    assert _normalize_oneshot_plan(plan) == {"pages": [], "module_name": "m"}
