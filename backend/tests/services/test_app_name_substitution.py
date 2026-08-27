from pathlib import Path
from services.runtime_injector import _substitute_app_name, _humanize_app_name


def test_humanize():
    assert _humanize_app_name("task_manager") == "Task Manager"
    assert _humanize_app_name("taskTracker") == "Task Tracker"
    assert _humanize_app_name(None) == "App"
    assert _humanize_app_name("") == "App"


def test_substitutes_placeholder_across_files(tmp_path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "layout.tsx").write_text('title: "__APP_NAME__"')
    (tmp_path / "src" / "app" / "(dashboard)").mkdir()
    (tmp_path / "src" / "app" / "(dashboard)" / "layout.tsx").write_text(">__APP_NAME__<")
    n = _substitute_app_name(tmp_path, "task_manager")
    assert n == 2
    for f in (tmp_path / "src").rglob("*.tsx"):
        assert "__APP_NAME__" not in f.read_text()
        assert "Task Manager" in f.read_text()
