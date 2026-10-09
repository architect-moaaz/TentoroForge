"""The statements run on the app's production build, served, not on a cold
dev server.

ToroCommerce's 46 statements on forge-v3 (2026-10-09): a `next dev` capped at
2.5 GB restarted itself twenty times in 35 minutes — each restart refusing
connections, then recompiling every page at 20–30 s — and 17 statements
failed on "connection refused". Measured on the same app: `next build`
compiles in 17 s; `next start` is ready in 0.3 s, serves a page in 8–110 ms,
and holds 264 MB. The assemble step already makes that build; the statements
serve it as it is, and build it again only when a source changed since.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import assembly, page_review


def _app(tmp_path) -> Path:
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "page.tsx").write_text("export default () => null;")
    (root / "package.json").write_text("{}")
    return root


def _built(root: Path) -> Path:
    dist = root / assembly.VERIFY_DIST_DIR
    dist.mkdir()
    (dist / "BUILD_ID").write_text("abc")
    assembly.stamp_build(root, assembly.VERIFY_DIST_DIR)
    return dist


def _server(monkeypatch, root: Path, *, build_rc: int = 0):
    """A RunningApp in production mode with the processes and the network stubbed."""
    from services import app_databases, workbench
    started: list[tuple[list[str], dict]] = []
    ran: list[list[str]] = []

    class P:
        pid = 1

        def __init__(self, cmd, **kw):
            started.append((cmd, kw.get("env") or {}))

        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(page_review.subprocess, "Popen", P)
    monkeypatch.setattr(page_review.subprocess, "run",
                        lambda cmd, **kw: ran.append(list(cmd)) or SimpleNamespace(returncode=build_rc, stdout="built", stderr=""))
    monkeypatch.setattr(page_review.urllib.request, "urlopen", lambda *a, **k: None)
    monkeypatch.setattr(workbench, "served", lambda *a, **k: {})
    monkeypatch.setattr(page_review.os, "killpg", lambda *a: None)
    monkeypatch.setattr(page_review.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(app_databases, "drop", lambda name: None)
    app = page_review.RunningApp(root, mode="production", dist_dir=assembly.VERIFY_DIST_DIR)
    app.clone = ("", "app_copy", "postgresql://h/app_copy")
    return app, started, ran


def test_a_fresh_build_is_served_as_it_is(monkeypatch, tmp_path):
    root = _app(tmp_path)
    dist = _built(root)
    app, started, ran = _server(monkeypatch, root)
    app._serve()
    cmd, env = started[0]
    assert cmd[:3] == ["npx", "next", "start"]
    assert env["NEXT_DIST_DIR"] == assembly.VERIFY_DIST_DIR and env["DATABASE_URL"] == "postgresql://h/app_copy"
    assert env["FORGE_PROJECT_ID"] == "", "a Workbench server never speaks as the app"
    assert not any("build" in c for c in ran), "built once by the assemble step; served, not built again"
    app._stop()
    assert (dist / "BUILD_ID").exists(), "the production build is kept for the next run"


def test_a_changed_source_is_built_before_it_is_served(monkeypatch, tmp_path):
    root = _app(tmp_path)
    _built(root)
    later = os.stat(root / "src" / "page.tsx").st_mtime + 60
    os.utime(root / "src" / "page.tsx", (later, later))
    assert not assembly.build_is_fresh(root, assembly.VERIFY_DIST_DIR)
    app, started, ran = _server(monkeypatch, root)
    app._serve()
    assert ran[0][:3] == ["npx", "next", "build"] and started[0][0][:3] == ["npx", "next", "start"]
    assert assembly.build_is_fresh(root, assembly.VERIFY_DIST_DIR), "the new build is stamped with what it was made from"


def test_a_build_that_fails_is_said_not_served(monkeypatch, tmp_path):
    root = _app(tmp_path)
    app, started, ran = _server(monkeypatch, root, build_rc=1)
    with pytest.raises(page_review.ReviewUnavailable, match="production build failed"):
        app._serve()
    assert not started


def test_a_dev_server_still_takes_its_own_dist_away(monkeypatch, tmp_path):
    root = _app(tmp_path)
    (root / ".next-review").mkdir()
    app, started, ran = _server(monkeypatch, root)
    app.mode, app.dist_dir = "development", ".next-review"
    app._serve()
    assert started[0][0][:3] == ["npx", "next", "dev"]
    app._stop()
    assert not (root / ".next-review").exists()


def test_the_verify_build_stamps_what_it_built_from(monkeypatch, tmp_path):
    import subprocess
    root = _app(tmp_path)
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    assembly.verify_build(root, install=False, build=True, dispatches=False)
    assert (root / assembly.VERIFY_DIST_DIR / assembly.BUILT_FROM).is_file()


def test_the_statements_and_their_runner_use_the_production_build():
    import inspect

    from services.expects import build, runner
    assert 'mode="production"' in inspect.getsource(build._prove)
    assert 'mode="production"' in inspect.getsource(runner.main)
