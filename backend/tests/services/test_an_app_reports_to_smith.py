"""forge-v3 (2026-10-01): no app had FORGE_URL or FORGE_PROJECT_ID, so the
error reporter was silent, Smith's inbox empty, and Smith told an F&B tester
"Nothing has been reported as crashing" about a form that never worked."""
from __future__ import annotations

import inspect

from services import app_reporting


def _app(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "package.json").write_text("{}")
    (root / ".env.local").write_text("DATABASE_URL=x\nFORGE_URL=\nFORGE_PROJECT_ID=\n")
    return root


def test_an_app_run_by_the_platform_reports_to_it(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_URL", raising=False)
    monkeypatch.delenv("FORGE_BACKEND_URL", raising=False)
    root = _app(tmp_path)
    assert app_reporting.wire(root, "4f016ff5-552e-47c2-b52f-0735d62e6a5b")
    env = (root / ".env.local").read_text()
    assert "FORGE_URL=http://127.0.0.1:6500\n" in env and "FORGE_PROJECT_ID=4f016ff5-552e-47c2-b52f-0735d62e6a5b\n" in env
    assert env.count("FORGE_URL=") == 1 and "DATABASE_URL=x" in env


def test_nothing_is_written_without_an_app_or_an_id(tmp_path):
    assert not app_reporting.wire(tmp_path / "nothing", "id")
    assert not app_reporting.wire(_app(tmp_path), None)


def test_a_published_app_reports_to_the_public_address(monkeypatch):
    monkeypatch.delenv(app_reporting.PUBLIC_ENV, raising=False)
    assert app_reporting.publish_env("p-1") == {}
    monkeypatch.setenv(app_reporting.PUBLIC_ENV, "https://forge-v3.tentoro.ai/")
    assert app_reporting.publish_env("p-1") == {"FORGE_URL": "https://forge-v3.tentoro.ai", "FORGE_PROJECT_ID": "p-1"}


def test_every_way_an_app_runs_is_wired():
    from routers import blueprint_generate, projects
    from services.deploy import vercel_provider
    assert "publish_env(snapshot.project_id)" in inspect.getsource(vercel_provider)
    assert "_wire_reporting(app_dir, project.id)" in inspect.getsource(projects.preview_start)
    assert '_wire_reporting(app_root, getattr(project, "id", None))' in inspect.getsource(blueprint_generate)
