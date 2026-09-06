import json
from pathlib import Path


def test_the_shell_names_where_the_application_opens(tmp_path):
    """The scaffold's root page redirected to a hard-coded /home that no
    application has; the shell now carries the Blueprint's initial route, and
    falls back to the rail's first destination when the Blueprint says none."""
    from services.blueprint.projection import project_shell
    doc = {"application": {"name": "PLC"}, "pages": [{"id": "PAGE-001", "route": "/dashboard", "name": "Dashboard"}],
           "navigation": {"style": "sidebar", "initialRoute": {"default": "/dashboard"},
                          "tree": [{"label": "Overview", "children": [{"label": "Dashboard", "page": "PAGE-001", "href": "/dashboard"}]}]}}
    project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert shell["initialRoute"] == "/dashboard"
    doc["navigation"]["initialRoute"] = {"default": "/home"}
    project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert shell["initialRoute"] == "/dashboard"


def test_a_one_screen_application_still_gets_its_shell(tmp_path):
    from services.blueprint.projection import project_shell
    doc = {"application": {"name": "PLC"}, "pages": [{"id": "PAGE-002", "route": "/", "name": "لوحة التحكم"}],
           "navigation": {"style": "sidebar", "initialRoute": {"default": "/"},
                          "tree": [{"label": "لوحة التحكم", "page": "PAGE-002", "icon": "layout-dashboard"}]}}
    out = project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert out["files"] == ["src/schemas/shell.json"]
    assert shell["children"][0]["props"]["groups"][0]["label"] == "لوحة التحكم"
    assert shell["initialRoute"] == "/"
