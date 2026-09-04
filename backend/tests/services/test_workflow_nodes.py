from services.workflow_nodes import workflow_node


def test_node_shape_matches_what_the_editor_reads():
    n = workflow_node("s1", "user_task", 2, {"table": "tickets"}, "Review")
    assert n["type"] == "user_task"
    assert n["data"]["nodeType"] == "user_task"
    assert n["data"]["config"] == {"table": "tickets", "nodeType": "user_task"}
    assert n["data"]["label"] == "Review"
    assert n["data"]["status"] == "idle"
    assert n["position"] == {"x": 250, "y": 240}


def test_builder_does_not_mutate_the_caller_config():
    cfg = {"type": "manual"}
    workflow_node("trigger", "trigger", 0, cfg, "Start")
    assert cfg == {"type": "manual"}
