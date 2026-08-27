

def test_workflow_artifact_routes_never_reach_menu():
    """/scanproductworkflow-scansession is a machine-name mash, not a user
    destination; a plain /workflows admin section stays legitimate."""
    from services.shell_menu_sync import derive_shell_groups
    nav = {"pages": [
        {"route": "/", "title": "Home", "shell": True},
        {"route": "/scanproductworkflow-scansession",
         "title": "Scanproductworkflow Scansession", "shell": True},
        {"route": "/workflows", "title": "Workflows", "shell": True},
    ]}
    groups = derive_shell_groups(nav)
    routes = [g["route"] for g in groups]
    assert "/scanproductworkflow-scansession" not in routes
    assert "/workflows" in routes


def test_glued_machine_title_falls_back_to_route_label():
    from services.shell_menu_sync import derive_shell_groups
    nav = {"pages": [
        {"route": "/scan-sessions", "title": "Scanproductworkflowsessions",
         "shell": True},
    ]}
    groups = derive_shell_groups(nav)
    assert groups and groups[0]["label"] == "Scan Sessions"
