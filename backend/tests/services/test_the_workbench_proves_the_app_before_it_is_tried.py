"""The Workbench proves five things before anything runs the app.

TStyle (forge-v3, 2026-10-09): a cut-off install left a lockfile npm could
not read; the database got its tables while the app was not installed and
never its rows; the handover named a login that did not exist; 18 statements
were refused at the sign-in form and reported as the app's failures. Each
door to the running app had checked a different thing or nothing. Now there
is one door (`services.workbench`), and a precondition the platform cannot
establish is the platform's fault — named, reported, never a result for the
app.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services import workbench


def _app(tmp_path, *, installed: bool = False) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    (root / "package.json").write_text("{}")
    if installed:
        from services.blueprint.assembly import INSTALLED_MARK
        (root / "node_modules").mkdir()
        (root / "node_modules" / INSTALLED_MARK).write_text("npm install finished\n")
    return root


def _database_ready(monkeypatch) -> None:
    monkeypatch.setattr(workbench, "_database",
                        lambda root: {"schema": {"ok": True, "did": ""}, "seeded": {"ok": True, "did": ""}})


def test_a_cut_off_install_is_thrown_away_and_installed_again(monkeypatch, tmp_path):
    from services.blueprint import assembly
    root = _app(tmp_path)
    (root / "node_modules" / "next").mkdir(parents=True)          # no marker: cut off mid-write
    installed = []

    def install(r, **kw):
        installed.append(Path(r))
        (Path(r) / "node_modules").mkdir(exist_ok=True)
        (Path(r) / "node_modules" / assembly.INSTALLED_MARK).write_text("npm install finished\n")
        return 0
    monkeypatch.setattr(assembly, "install_dependencies", install)
    _database_ready(monkeypatch)
    out = workbench.prepare(root)
    assert installed == [root]
    assert out["installed"]["did"].startswith("installed after a cut-off install")
    assert not (root / "node_modules" / "next").exists(), "the half-written tree is gone"
    assert workbench.prepare(root)["installed"]["did"] == "", "a finished install is left alone"


def test_an_install_that_fails_is_the_platforms_fault(monkeypatch, tmp_path):
    from services.blueprint import assembly
    root = _app(tmp_path)

    def refuse(r, **kw):
        raise assembly.BuildFailed("npm install failed (1): EACCES: permission denied")
    monkeypatch.setattr(assembly, "install_dependencies", refuse)
    with pytest.raises(workbench.PlatformFault) as e:
        workbench.prepare(root)
    assert e.value.precondition == "installed" and "EACCES" in str(e.value)


def test_on_the_apps_server_tables_and_a_login_are_proven(monkeypatch, tmp_path):
    from services import app_databases
    root = _app(tmp_path, installed=True)
    monkeypatch.setenv(app_databases.SERVER_ENV, "postgresql://u:p@apps-db:5432")
    state = {"tables": False, "login": False}

    def ensure(r):
        state.update(tables=True, login=True)
        return {"pushed": True, "reason": ""}
    monkeypatch.setattr(app_databases, "ensure", ensure)
    monkeypatch.setattr(app_databases, "_has_tables", lambda name: state["tables"])
    monkeypatch.setattr(app_databases, "_has_a_login", lambda name: state["login"])
    out = workbench.prepare(root)
    assert out["schema"]["did"] == "pushed and seeded" and out["seeded"]["ok"]

    # A database the platform could not seed is its fault, in the seed's words.
    monkeypatch.setattr(app_databases, "ensure", lambda r: {"pushed": False, "reason": "drizzle-kit refused: column x"})
    state.update(tables=True, login=False)
    with pytest.raises(workbench.PlatformFault) as e:
        workbench.prepare(root)
    assert e.value.precondition == "seeded" and "drizzle-kit refused" in str(e.value)
    state.update(tables=False)
    with pytest.raises(workbench.PlatformFault) as e:
        workbench.prepare(root)
    assert e.value.precondition == "schema"


def test_with_docker_the_apps_own_start_script_is_the_door(monkeypatch, tmp_path):
    from services import app_databases
    from services.blueprint import page_review
    root = _app(tmp_path, installed=True)
    monkeypatch.delenv(app_databases.SERVER_ENV, raising=False)
    monkeypatch.setattr(page_review, "ensure_docker_database", lambda r: True)
    assert workbench.prepare(root)["seeded"]["started"] is True

    def no_docker(r):
        raise page_review.ReviewUnavailable("Docker is not available for the app's database")
    monkeypatch.setattr(page_review, "ensure_docker_database", no_docker)
    with pytest.raises(workbench.PlatformFault) as e:
        workbench.prepare(root)
    assert e.value.precondition == "schema" and "Docker" in str(e.value)


class _Reply:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, n: int = -1) -> bytes:
        return self.body


class _Opener:
    """The app's auth routes, answering as next-auth does."""

    def __init__(self, session: bytes):
        self.session = session
        self.calls: list[tuple[str, bytes | None]] = []

    def open(self, url: str, data: bytes | None = None, timeout: float = 0) -> _Reply:
        self.calls.append((url.split("/api/", 1)[-1], data))
        if url.endswith("/csrf"):
            return _Reply(b'{"csrfToken":"t0k"}')
        if url.endswith("/callback/credentials"):
            return _Reply(b"")
        return _Reply(self.session)


def test_sign_in_is_proven_through_the_form(monkeypatch):
    op = _Opener(b'{"user":{"email":"admin@example.com","name":"Admin"}}')
    monkeypatch.setattr(workbench.urllib.request, "build_opener", lambda *a: op)
    assert workbench.signs_in("http://127.0.0.1:1", "admin@example.com", "admin1234")
    assert [c[0] for c in op.calls] == ["auth/csrf", "auth/callback/credentials", "auth/session"]
    assert b"csrfToken=t0k" in op.calls[1][1] and b"password=admin1234" in op.calls[1][1]

    nobody = _Opener(b"{}")
    monkeypatch.setattr(workbench.urllib.request, "build_opener", lambda *a: nobody)
    with pytest.raises(workbench.PlatformFault) as e:
        workbench.served("http://127.0.0.1:1", "admin@example.com", "admin1234")
    assert e.value.precondition == "login" and "could not sign in through the form" in str(e.value)


def test_the_fault_is_found_behind_whatever_wrapped_it():
    fault = workbench.PlatformFault("seeded", "the seed wrote no login")
    try:
        try:
            raise fault
        except workbench.PlatformFault as f:
            raise RuntimeError("the app's database could not be prepared") from f
    except RuntimeError as outer:
        assert workbench.fault_of(outer) is fault
    assert workbench.fault_of(RuntimeError("something else")) is None
    assert "seeded rows and logins" in str(fault)


def test_the_review_server_meets_the_app_at_the_workbench(monkeypatch, tmp_path):
    from services import app_databases
    from services.blueprint import page_review
    monkeypatch.setenv(app_databases.SERVER_ENV, "postgresql://u:p@apps-db:5432")

    def not_seeded(root):
        raise workbench.PlatformFault("seeded", "the seed wrote no login")
    monkeypatch.setattr(workbench, "prepare", not_seeded)
    served = []
    monkeypatch.setattr(page_review.RunningApp, "_serve", lambda self: served.append(1))
    with pytest.raises(page_review.ReviewUnavailable) as e:
        page_review.RunningApp(tmp_path).__enter__()
    assert workbench.fault_of(e.value).precondition == "seeded" and not served


def test_a_workbench_server_never_speaks_as_the_app():
    import inspect
    from services.blueprint import page_review
    src = inspect.getsource(page_review.RunningApp._serve)
    assert '"FORGE_PROJECT_ID": ""' in src, "a trial server's crashes are not the app's incidents"
    assert "workbench.served(self.base, ADMIN_EMAIL, ADMIN_PASSWORD)" in src


def test_statements_kept_from_running_by_the_platform_are_recorded_as_its_fault(tmp_path):
    from services.blueprint.page_review import ReviewUnavailable
    from services.expects import build

    doc = {"expectations": [{"id": "EXP-001", "says": "a", "kind": "rule", "steps": []},
                            {"id": "EXP-002", "says": "b", "kind": "rule", "steps": []},
                            {"id": "EXP-003", "says": "c", "kind": "rule", "steps": []}], "runtime": {}}

    class Svc:
        def __init__(self):
            self.doc = doc

        def save(self):
            pass

    class App:
        def __init__(self, root):
            pass

        def __enter__(self):
            try:
                raise workbench.PlatformFault("login", "admin@example.com could not sign in through the form at http://x/login")
            except workbench.PlatformFault as f:
                raise ReviewUnavailable(str(f)) from f

        def __exit__(self, *a):
            pass

    tried = []
    out = build._prove(Svc(), str(tmp_path), app_factory=App,
                       trial=lambda *a, **k: tried.append(1) or {}, author=lambda *a, **k: [], record=True)
    assert not tried and out["passed"] == 0
    assert out["untried"] == ["EXP-001", "EXP-002", "EXP-003"]
    assert out["platform"][0]["precondition"] == "login"
    assert out["platform"][0]["statements"] == ["EXP-001", "EXP-002", "EXP-003"]
    issues = doc["runtime"]["issues"]
    fault = [i for i in issues if i["kind"] == "platform"][0]
    assert fault["precondition"] == "login" and "could not sign in" in fault["detail"]
    assert not [i for i in issues if i["kind"] == "expectation"], "the app is not blamed"


def test_the_handover_names_the_platforms_fault_not_the_checks_luck():
    from routers.blueprint_generate import _check_score
    doc = {"runtime": {
        "expectations": {"statements": 3, "passed": 0, "failing": [], "untried": ["EXP-001", "EXP-002", "EXP-003"]},
        "issues": [{"kind": "platform", "precondition": "login", "statements": ["EXP-001", "EXP-002", "EXP-003"],
                    "detail": "the platform could not get the app signed in to: admin@example.com could not "
                              "sign in through the form at http://x/login"}]}}
    said = _check_score(doc)
    assert "the platform's to fix, not your app" in said and "could not sign in" in said
    assert "my check failing" not in said
    assert "The same fault showed up across the app" not in said, "said once, not twice"


def test_the_data_gate_runs_on_the_apps_server_when_there_is_one(monkeypatch):
    from services import app_databases
    from services.blueprint import data_gate
    monkeypatch.setenv(app_databases.SERVER_ENV, "postgresql://u:p@apps-db:5432")
    ran: list[str] = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def execute(self, sql):
            ran.append(sql)

    class Con:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    monkeypatch.setattr(app_databases, "_connect", lambda *a: Con())
    monkeypatch.setattr(app_databases, "drop", lambda name: ran.append("DROP " + name))
    with data_gate.throwaway_database() as (url, why):
        assert url.startswith("postgresql://u:p@apps-db:5432/gate_") and why == ""
    assert ran[0].startswith('CREATE DATABASE "gate_')
    assert any("CREATE EXTENSION" in r for r in ran)
    assert ran[-1].startswith("DROP gate_")


def test_the_preview_meets_the_app_at_the_workbench(monkeypatch, tmp_path):
    import asyncio

    import preview
    seen = []
    monkeypatch.setattr(workbench, "prepare", lambda r: seen.append(str(r)))
    asyncio.run(preview._ensure_database(str(tmp_path)))
    assert seen == [str(tmp_path)]
