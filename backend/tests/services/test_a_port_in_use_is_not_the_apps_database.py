"""wz7a99ir (local, 2026-10-04): a new app still named the default port
5432, a Postgres installed on the machine answered there, and the review
took it for the app's database — it started nothing, found no container to
copy, and the build's checks ran no page and no workflow ("could not make a
copy of the app's database to click through"). Up means the app's own
container serves the port; anything else is started."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import page_review


@pytest.fixture()
def app(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://postgres:pw@localhost:5432/app_x\n")
    ran: list[list[str]] = []
    monkeypatch.setattr(page_review.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(page_review, "_listening", lambda port: True)

    def run(cmd, **kw):
        ran.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(page_review.subprocess, "run", run)
    monkeypatch.setattr(page_review, "_clone_database", lambda root: ("c1", "app_x_review_1", "postgresql://x"))
    monkeypatch.setattr(page_review.RunningApp, "_serve", lambda self: self)
    return tmp_path, ran


def test_a_port_another_postgres_answers_on_starts_the_apps_own(app, monkeypatch):
    root, ran = app
    monkeypatch.setattr(page_review, "_database_container", lambda port: "")
    running = page_review.RunningApp(root).__enter__()
    assert ["bash", "start.sh", "--seed-only"] in ran and running.started_db


def test_the_apps_own_running_container_is_used_as_it_is(app, monkeypatch):
    root, ran = app
    monkeypatch.setattr(page_review, "_database_container", lambda port: "c1")
    running = page_review.RunningApp(root).__enter__()
    assert ["bash", "start.sh", "--seed-only"] not in ran and not running.started_db


def test_the_container_is_found_by_the_port_it_publishes(monkeypatch):
    monkeypatch.setattr(page_review.shutil, "which", lambda name: "/usr/bin/docker")
    asked = []
    monkeypatch.setattr(page_review.subprocess, "run", lambda cmd, **kw: asked.append(cmd) or
                        SimpleNamespace(returncode=0, stdout="abc123\n", stderr=""))
    assert page_review._database_container(5439) == "abc123"
    assert asked == [["docker", "ps", "-q", "--filter", "publish=5439"]]
    assert page_review._database_container(None) == ""
