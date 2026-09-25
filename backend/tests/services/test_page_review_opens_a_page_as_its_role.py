"""The page reviewer signs in as someone the page is for.

nlwtcyz5 (2026-09-25): /notifications is a Parent-only page. The reviewer
opened it as the seeded Admin, got the 403 page, scored THAT 2/10 ("the link
'Return to CKA' does nothing"), and rewrote the page twice for it. Three
rules follow: a page the administrator's role does not open is opened with a
session minted for its role — as a login of that role when the database has
one; the app is booted with the preview secret so that session is accepted;
and a page that still answers 403 is reported as an access defect, never
judged or rewritten, because the page was never seen.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import page_review as pr
from services.preview_session import PREVIEW_SECRET, derive_key

_ADMIN = "a0000000-0000-4000-8000-0000000000ad"

DOC = {
    "application": {"id": "cka"},
    "roles": [{"id": "ROLE-001", "name": "Parent"}, {"id": "ROLE-002", "name": "Doctor"},
              {"id": "ROLE-003", "name": "Admin"}],
    "data": {"entities": [{"id": "ENT-001", "name": "Parent", "table": "parents", "account": True}]},
    "pages": [
        {"id": "PAGE-003", "route": "/admin", "access": "role_restricted", "users": ["ROLE-003"]},
        {"id": "PAGE-015", "route": "/admin/patients", "access": "role_restricted", "users": ["ROLE-003"]},
        {"id": "PAGE-009", "route": "/notifications", "access": "role_restricted", "users": ["ROLE-001"]},
        {"id": "PAGE-026", "route": "/login", "access": "public", "pattern": "auth"},
    ],
}


def _app(rows=None):
    app = pr.RunningApp.__new__(pr.RunningApp)
    app.base = "http://127.0.0.1:5"
    app.clone = ("container", "copy", "postgres://x")
    return app


def _claims(cookie: dict | list) -> dict:
    from jose import jwe
    first = cookie[0] if isinstance(cookie, list) else cookie
    return json.loads(jwe.decrypt(first["value"], derive_key(PREVIEW_SECRET)))


def test_a_page_the_administrator_opens_is_opened_as_them(monkeypatch):
    monkeypatch.setattr(pr, "_query", lambda app, sql: pytest.fail("no lookup needed"))
    who = pr.who_opens(_app(), DOC, DOC["pages"][0])
    assert who == {"as": "Admin"}
    assert pr.who_opens(_app(), DOC, DOC["pages"][3]) == {"as": "Admin"}   # /login: no roles named


def test_a_page_for_another_role_is_opened_as_a_login_of_that_role(monkeypatch):
    asked: list[str] = []

    def query(app, sql):
        asked.append(sql)
        if "information_schema" in sql:
            return [["id"], ["email"], ["account_type"], ["name"], ["created_at"]]
        assert "account_type = 'Parent'" in sql and _ADMIN in sql
        return [["a45fb2de-1c30-41c1-9576-bf04b508a822", "Max"]]

    monkeypatch.setattr(pr, "_query", query)
    who = pr.who_opens(_app(), DOC, DOC["pages"][2])
    assert who["as"] == "Max (Parent)"
    claims = _claims(who["cookies"])
    assert claims["id"] == claims["sub"] == "a45fb2de-1c30-41c1-9576-bf04b508a822"
    assert claims["role"] == "Parent"                 # the NAME: what the app's guards compare
    # The app's own cookie name first (session-cookie.ts derives it from the
    # secret), next-auth's default for apps built before that.
    assert [c["name"] for c in who["cookies"]] == ["forge-dfdcd746.session-token", "next-auth.session-token"]


def test_with_no_login_of_the_role_any_account_row_stands_in(monkeypatch):
    def query(app, sql):
        if "information_schema" in sql:
            return [["id"], ["email"], ["created_at"]]          # no role column at all
        assert sql.startswith("select id from parents")
        return [["c06ab306-5c30-4dac-b5de-94c757300cfb"]]

    monkeypatch.setattr(pr, "_query", query)
    who = pr.who_opens(_app(), DOC, DOC["pages"][2])
    assert who["as"] == "Parent (preview) (Parent)"
    assert _claims(who["cookies"])["sub"] == "c06ab306-5c30-4dac-b5de-94c757300cfb"


def test_with_nothing_in_the_database_the_role_alone_is_minted(monkeypatch):
    monkeypatch.setattr(pr, "_query", lambda app, sql: [])
    who = pr.who_opens(_app(), DOC, DOC["pages"][2])
    assert _claims(who["cookies"])["sub"] == "preview-role-001"
    assert _claims(who["cookies"])["role"] == "Parent"


def test_the_shot_config_carries_who_opens_each_page(monkeypatch, tmp_path):
    monkeypatch.setattr(pr, "_query", lambda app, sql: [])
    monkeypatch.setattr(pr, "_playwright_modules", lambda: tmp_path)
    seen: dict = {}

    def run(cmd, **kw):
        seen["cfg"] = json.loads(Path(cmd[2]).read_text())
        return SimpleNamespace(stdout="[]\n", stderr="", returncode=0)

    monkeypatch.setattr(pr.subprocess, "run", run)
    pr.shoot(_app(), DOC, ["PAGE-003", "PAGE-009"], tmp_path / "round-1")
    pages = {p["id"]: p for p in seen["cfg"]["pages"]}
    assert seen["cfg"]["email"] == pr.ADMIN_EMAIL
    assert pages["PAGE-003"]["as"] == "Admin" and "cookies" not in pages["PAGE-003"]
    assert pages["PAGE-009"]["as"] == "Parent (preview) (Parent)" and len(pages["PAGE-009"]["cookies"]) == 2


def test_the_review_server_is_booted_with_the_preview_secret():
    src = inspect.getsource(pr.RunningApp.__enter__)
    assert "boot_env(self.base)" in src


def test_the_shot_script_opens_a_page_in_its_own_session():
    src = pr._SHOTS.read_text()
    assert "contextsFor(p)" in src and "own.addCookies(p.cookies)" in src
    assert "press(who.ctx, url, c)" in src and "firstId(who.ctx, p.entity)" in src
    assert "as: p.as" in src and "state: main.state" in src


def test_a_forbidden_page_is_an_access_defect_not_a_page_finding():
    shot = {"status": 200, "state": "403", "as": "Max (Parent)"}
    why = pr.forbidden(shot)
    assert "cannot be opened as Max (Parent)" in why and "403" in why
    assert pr.forbidden({"status": 403}) and not pr.forbidden({"status": 200, "state": None})


def test_a_forbidden_page_is_reported_and_never_rewritten(monkeypatch, tmp_path):
    import threading

    doc = json.loads(json.dumps(DOC))
    doc["pageCode"] = [{"page": "PAGE-009", "load": "x", "view": "y"}]
    svc = SimpleNamespace(doc=doc, lock=threading.RLock(), output_dir=str(tmp_path), save=lambda: None)

    class _App:
        def __init__(self, root): pass
        def __enter__(self): return self
        def __exit__(self, *a): return None

    monkeypatch.setattr(pr, "RunningApp", _App)
    monkeypatch.setattr(pr, "shoot", lambda app, doc, ids, out: [
        {"id": "PAGE-009", "route": "/notifications", "url": "/notifications", "status": 403,
         "state": "403", "as": "Max (Parent)", "file": str(tmp_path / "p.png"), "errors": [], "states": {}}])
    monkeypatch.setattr(pr, "critique", lambda *a, **k: pytest.fail("a page never seen was judged"))
    monkeypatch.setattr("services.blueprint.ui_engineer.compose_page",
                        lambda *a, **k: pytest.fail("a page never seen was rewritten"))
    monkeypatch.setattr("services.blueprint.app_sdk.project_code_pages", lambda *a, **k: None)

    out = pr.review_app(svc, tmp_path, client=None)
    page = out["pages"]["PAGE-009"]
    assert page["passed"] is False and page["rewritten"] is False
    assert page["review"]["forbidden"] and "cannot be opened as Max (Parent)" in page["review"]["broken"][0]
