"""Smith could not open a page on Windows: making the screenshot tool's `node_modules` was a symlink, and a Windows user
without the privilege got `WinError 1314`. The link is now made the way the Expo build makes its own (a junction on Windows)."""
from __future__ import annotations

from pathlib import Path

import pytest

from services import native_build
from services.blueprint import page_review as pr


class _Stop(Exception):
    pass


@pytest.fixture
def shots(tmp_path, monkeypatch):
    modules = tmp_path / "playwright-modules"
    modules.mkdir()
    monkeypatch.setattr(pr, "_playwright_modules", lambda: modules)

    def no_symlink(self, target, target_is_directory=False):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(Path, "symlink_to", no_symlink)
    monkeypatch.setattr(pr, "_IS_WINDOWS", True)

    def stop(*a, **k):
        raise _Stop()          # the link is made before node is run: stop there

    monkeypatch.setattr(pr.subprocess, "run", stop)
    app = type("App", (), {"base": "http://localhost:1"})()
    return tmp_path / "out", modules, app


def test_the_link_is_made_without_a_symlink(shots, monkeypatch):
    out, modules, app = shots
    made = []
    monkeypatch.setattr(native_build, "_link_packages", lambda target, link: made.append((target, link)) or True)
    with pytest.raises(_Stop):
        pr.run_shots(app, [], out)
    assert made == [(modules, out / "run" / "node_modules")]


def test_a_link_that_cannot_be_made_is_a_reason(shots, monkeypatch):
    out, modules, app = shots
    monkeypatch.setattr(native_build, "_link_packages", lambda target, link: False)
    with pytest.raises(pr.ReviewUnavailable):
        pr.run_shots(app, [], out)


def test_everywhere_else_it_is_still_a_symlink(shots, monkeypatch):
    out, modules, app = shots
    made = []
    monkeypatch.setattr(pr, "_IS_WINDOWS", False)
    monkeypatch.setattr(Path, "symlink_to", lambda self, target, target_is_directory=False: made.append((self, target)))
    monkeypatch.setattr(native_build, "_link_packages", lambda target, link: pytest.fail("a junction is Windows only"))
    with pytest.raises(_Stop):
        pr.run_shots(app, [], out)
    assert made == [(out / "run" / "node_modules", modules)]
