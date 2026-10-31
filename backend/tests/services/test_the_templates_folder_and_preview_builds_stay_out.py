"""Two notes from the template review (PR #20): the saved templates' own
folder is not listed as a project, and a generated app's git ignores the
preview, review and verify builds (`.next-*`), not only `.next/`."""
from __future__ import annotations

import pytest

from services import git_service, project_paths


def test_the_templates_folder_is_no_project(tmp_path, monkeypatch):
    for name in ("abc123", "_templates", ".hidden"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(project_paths, "OUTPUT_ROOT", tmp_path)
    assert [p["id"] for p in project_paths.list_projects()] == ["abc123"]


@pytest.mark.asyncio
async def test_a_new_app_ignores_every_next_build(tmp_path):
    await git_service.git_init(str(tmp_path))
    assert ".next-*/" in (tmp_path / ".gitignore").read_text().splitlines()


@pytest.mark.asyncio
async def test_an_apps_own_gitignore_is_kept_and_the_builds_added_once(tmp_path):
    (tmp_path / ".gitignore").write_text("dist/")
    await git_service.git_init(str(tmp_path))
    await git_service.git_init(str(tmp_path))
    assert (tmp_path / ".gitignore").read_text() == "dist/\n.next-*/\n"
