"""Two checks that crashed or gave up on Personal Finance (u8w3uw4j,
2026-10-21), a one-role app: the way-in check crashed on a relative address,
and the who-sees-whose-data check found nobody to read as."""
from __future__ import annotations

from types import SimpleNamespace

from services.blueprint import access_check, sso_check


def test_being_sent_back_to_the_sign_in_page_is_no_session_not_a_crash(monkeypatch):
    calls: list[str] = []

    class _B:
        def json(self, method, url, **kw):
            calls.append(url)
            return 200, {"url": "/login?callbackUrl=http%3A%2F%2F127.0.0.1%3A42263%2Flogin"}

        def go(self, method, url, **kw):  # never reached
            raise AssertionError(f"followed {url}")

    monkeypatch.setattr(sso_check, "_Browser", _B)
    monkeypatch.setattr(sso_check, "_register", lambda *a: None)
    monkeypatch.setattr(sso_check, "_csrf", lambda b, base: "t")
    user, where = sso_check.sign_in_through(SimpleNamespace(base="http://127.0.0.1:42263"), {"id": "google"}, {})
    assert user is None
    assert where.startswith("http://127.0.0.1:42263/login?callbackUrl=")


def test_a_relative_issuer_and_callback_are_followed_on_the_apps_address(monkeypatch):
    went: list[str] = []

    class _B:
        def json(self, method, url, **kw):
            if url.endswith("/api/auth/session"):
                return 200, {"user": {"email": "a@x.com"}}
            return 200, {"url": "/dev/mock-idp/authorize?x=1"}

        def go(self, method, url, **kw):
            went.append(url)
            return 302, ("/api/auth/callback/google?code=c" if len(went) == 1 else "/"), ""

    monkeypatch.setattr(sso_check, "_Browser", _B)
    monkeypatch.setattr(sso_check, "_register", lambda *a: None)
    monkeypatch.setattr(sso_check, "_csrf", lambda b, base: "t")
    user, _ = sso_check.sign_in_through(SimpleNamespace(base="http://h:1"), {"id": "google"}, {})
    assert user == {"email": "a@x.com"}
    assert went == ["http://h:1/dev/mock-idp/authorize?x=1", "http://h:1/api/auth/callback/google?code=c"]


def test_a_one_role_apps_administrator_is_the_first_person_and_a_second_is_made(monkeypatch):
    from services.blueprint import page_review
    from services.seed_backstop import _ADMIN_UUID
    asked: list[str] = []

    def query(_app, sql):
        asked.append(sql)
        if "information_schema" in sql:
            return [["id"], ["email"], ["name"], ["role"], ["created_at"]]
        if f"id <> '{_ADMIN_UUID}'" in sql:
            return []
        if f"id = '{_ADMIN_UUID}'" in sql:
            return [[_ADMIN_UUID, "Admin"]]
        return []

    monkeypatch.setattr(page_review, "_query", query)
    monkeypatch.setattr(access_check, "second_person", lambda app, first: ("p2", f"{first[1]} (second)"))
    people = access_check.people_of_role(SimpleNamespace(), {}, "User")
    assert people == [(_ADMIN_UUID, "Admin"), ("p2", "Admin (second)")]
