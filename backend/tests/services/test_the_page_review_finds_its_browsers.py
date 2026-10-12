"""The page review looks for Playwright's browsers where the machine keeps them.

It forced `~/Library/Caches/ms-playwright` (a Mac folder) into every run, so on Windows — where the browsers
are under %LOCALAPPDATA%\\ms-playwright — each page failed with Playwright's "install the browsers" banner and
the build's own app check reported every page as not working."""
from __future__ import annotations

import subprocess

import pytest

from services.blueprint import page_review


def _env_of_run(tmp_path, monkeypatch, *, home, preset=None):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    if preset:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", preset)
    monkeypatch.setattr(page_review.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(page_review.subprocess, "run", fake_run)
    monkeypatch.setattr(page_review, "_playwright_modules", lambda: tmp_path)
    monkeypatch.setattr(page_review, "link_dir", lambda link, target: link.mkdir())
    app = type("A", (), {"base": "http://127.0.0.1:1"})()
    page_review.run_shots(app, [], tmp_path / "out")
    return seen["env"]


def test_without_a_mac_cache_playwright_is_left_to_find_its_own(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    env = _env_of_run(tmp_path, monkeypatch, home=home)
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env


def test_a_mac_cache_that_exists_is_still_used(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Library/Caches/ms-playwright").mkdir(parents=True)
    env = _env_of_run(tmp_path, monkeypatch, home=home)
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(home / "Library/Caches/ms-playwright")


def test_an_explicit_setting_always_wins(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Library/Caches/ms-playwright").mkdir(parents=True)
    env = _env_of_run(tmp_path, monkeypatch, home=home, preset="/opt/browsers")
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/browsers"
