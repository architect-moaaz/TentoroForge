"""PR #28 review, item 5 (2026-10-22). The live preview's address needs no sign-in (an iframe cannot send a token), so what it will do for an
anonymous caller has to be small:

* ONLY THE APP'S ONE ENTRY BUNDLE, with exactly the options the page names it by. A path ending in `.bundle`, with any options, made the dev
  server build a new bundle (several MB, seconds of CPU) for every combination. (Checked on the real picture of a built app: the page asks for
  this one bundle, and opening its other screens asks for no other.)
* ONLY THE MESSAGES A PAGE SENDS. A message naming an address the dev server does not know stopped the whole server once.
* NOTHING THE CALLER DOES KEEPS A SERVER ALIVE. Only the editor's signed-in calls mark it as used.
* A LIMIT, not an exemption, on how fast one caller may ask.
"""
import json

import pytest

from services import phone_live_proxy as proxy

ENTRY_WIN = ("/..%5Cpackages%5Cnode_modules%5Cexpo-router%5Centry.bundle?platform=web&dev=true&hot=false&lazy=true&transform.engine=hermes"
             "&transform.baseUrl=%2Fapi%2Fprojects%2Fabc%2Fphone%2Flive&transform.routerRoot=app")
ENTRY_LINUX = "/../../native/node_modules/expo-router/entry.bundle?platform=web&dev=true&hot=false&lazy=true&transform.routerRoot=app"
OWN_QUERY = ENTRY_WIN.partition("?")[2]


def _ask(entry, path):
    return proxy.bundle_allowed(path, entry.partition("?")[2], entry)


# ---- the bundle ------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("entry,path", [
    (ENTRY_WIN, "/..%5Cpackages%5Cnode_modules%5Cexpo-router%5Centry.bundle"),
    (ENTRY_LINUX, "/..%2F..%2Fnative/node_modules/expo-router/entry.bundle"),       # the Linux page request, written so a browser keeps it
    (ENTRY_LINUX, "/../../native/node_modules/expo-router/entry.bundle"),
])
def test_the_entry_bundle_with_its_own_options_is_passed_on_however_the_browser_wrote_the_path(entry, path):
    assert _ask(entry, path)


def test_its_source_map_is_passed_on_and_no_other_map():
    assert proxy.bundle_allowed("/..%5Cpackages%5Cnode_modules%5Cexpo-router%5Centry.map", OWN_QUERY, ENTRY_WIN)
    assert not proxy.bundle_allowed("/..%5Cpackages%5Cnode_modules%5Cother.map", OWN_QUERY, ENTRY_WIN)


@pytest.mark.parametrize("path", ["/other.bundle", "/index.bundle", "/..%5Cpackages%5Cnode_modules%5Cexpo-router%5Centry2.bundle",
                                  "/node_modules/react/index.bundle", "/..%5C..%5C..%5Cwindows%5Cwin.bundle", "/x/entry.bundle"])
def test_any_other_bundle_is_not(path):
    assert not proxy.bundle_allowed(path, OWN_QUERY, ENTRY_WIN)


@pytest.mark.parametrize("query", ["platform=web&dev=true", "", "platform=ios&dev=true&hot=false&lazy=true",
                                   OWN_QUERY + "&minify=true", OWN_QUERY + "&modulesOnly=true", OWN_QUERY.replace("dev=true", "dev=false")])
def test_the_entry_with_other_options_is_not(query):
    assert not proxy.bundle_allowed("/..%5Cpackages%5Cnode_modules%5Cexpo-router%5Centry.bundle", query, ENTRY_WIN)


def test_without_a_known_entry_no_bundle_is_passed_on():
    assert not proxy.bundle_allowed("/x.bundle", "platform=web", None) and not proxy.bundle_allowed("/x.bundle", "", "")


# ---- the sockets -----------------------------------------------------------------------------------------------------------------

def _register(*points):
    return json.dumps({"type": "register-entrypoints", "entryPoints": list(points)})


ENTRY_URL = "http://localhost:6501" + ENTRY_WIN


def test_the_page_may_register_its_own_entry_and_log():
    assert proxy.message_allowed(_register(ENTRY_URL), ENTRY_WIN, "/hot")
    assert proxy.message_allowed(json.dumps({"type": "log", "level": "warn", "data": ["x"]}), ENTRY_WIN, "/hot")
    assert proxy.message_allowed(json.dumps({"type": "log-opt-in"}), ENTRY_WIN, "/hot")


@pytest.mark.parametrize("said", [
    _register("http://evil.example/anything.bundle?platform=web"),
    _register("http://localhost:6501/..%5Cother.bundle?platform=web&dev=true"),
    _register(ENTRY_URL + "&minify=true"),
    _register(ENTRY_URL, "http://x/other.bundle"),
    json.dumps({"type": "register-entrypoints"}), json.dumps({"type": "register-entrypoints", "entryPoints": []}),
    json.dumps({"type": "register-entrypoints", "entryPoints": [1]}),
    json.dumps({"type": "register-entrypoints", "entryPoints": [ENTRY_URL] * 5}),
    json.dumps({"type": "something-else"}), json.dumps(["log"]), "log", "not json", "",
])
def test_nothing_else_is_passed_to_the_dev_server(said):
    assert not proxy.message_allowed(said, ENTRY_WIN, "/hot")


def test_a_message_over_the_size_limit_is_not_passed_on():
    assert not proxy.message_allowed(json.dumps({"type": "log", "x": "y" * 70000}), ENTRY_WIN, "/hot")


def test_with_no_known_entry_a_registration_is_not_passed_on():
    assert not proxy.message_allowed(_register(ENTRY_URL), None, "/hot")


def test_the_tools_socket_takes_a_small_json_object_and_nothing_else():
    assert proxy.message_allowed('{"method": "ping"}', None, "/message")
    assert not proxy.message_allowed("reload", None, "/message") and not proxy.message_allowed("[1]", None, "/message")
    assert not proxy.message_allowed(json.dumps({"x": "y" * 70000}), None, "/message")


# ---- through the route ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    """The route, with a record for a running server whose entry is known and a stand-in for the dev server behind it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import phone_live as router_module
    from services import phone_live as pl

    calls: list[str] = []
    monkeypatch.setattr(pl, "port_of", lambda short_id: 1234)
    monkeypatch.setattr(pl, "entry_of", lambda short_id: ENTRY_WIN)

    class _Up:
        status_code = 200
        headers = {"content-type": "application/javascript"}

        async def aread(self):
            return b"//bundle"

        async def aclose(self):
            pass

    class _Client:
        async def aclose(self):
            pass

    async def fake_fetch(port, path, query, method, accept):
        calls.append(path + ("?" + query if query else ""))
        return _Up(), _Client()

    monkeypatch.setattr(router_module.proxy, "fetch", fake_fetch)
    app = FastAPI()
    app.include_router(router_module.router)
    client = TestClient(app)
    client.calls = calls
    return client


def test_the_route_passes_on_the_entry_bundle_and_refuses_every_other_without_asking_the_dev_server(served):
    base = "/api/projects/abc/phone/live/"
    ok = served.get(base + ENTRY_WIN.lstrip("/"))
    assert ok.status_code == 200 and len(served.calls) == 1
    for url in (base + "other.bundle?platform=web", base + ENTRY_WIN.lstrip("/") + "&minify=true",
                base + "index.bundle?platform=web&dev=true", base + "e.map?platform=web"):
        assert served.get(url).status_code == 404, url
    assert len(served.calls) == 1, "the dev server was asked once, for the entry"


# ---- who marks a server as used ----------------------------------------------------------------------------------------------------

def test_the_editors_status_call_marks_the_server_as_used_and_the_picture_does_not():
    import inspect

    from routers import phone_preview as router_module
    from services import phone_live as pl

    assert "phone_live.touch(project.short_id)" in inspect.getsource(router_module), "the signed-in status call marks it in use"
    assert "touch(" not in inspect.getsource(pl.port_of)


# ---- the rate limit -----------------------------------------------------------------------------------------------------------------

def _limited():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from middleware import rate_limit

    app = FastAPI()
    app.add_middleware(rate_limit.RateLimitMiddleware)

    @app.get("/{path:path}")
    def _all(path: str):
        return {"ok": True}

    return TestClient(app)


def test_the_picture_has_a_limit_per_caller_and_project_that_a_page_load_does_not_reach(monkeypatch):
    from middleware import rate_limit

    monkeypatch.setattr(rate_limit, "PICTURE_PER_MINUTE", 60)
    monkeypatch.setattr(rate_limit, "PICTURE_BURST", 30)
    client = _limited()
    codes = [client.get("/api/projects/abc/phone/live/x").status_code for _ in range(40)]
    assert codes[:30] == [200] * 30, "a page load (a dozen files) passes"
    assert 429 in codes[30:], "but it is a limit"
    assert client.get("/api/projects/other/phone/live/x").status_code == 200, "another project has its own"


def test_the_real_limit_is_generous_enough_for_a_page_load():
    from middleware import rate_limit

    assert rate_limit.PICTURE_BURST >= 100 and rate_limit.PICTURE_PER_MINUTE >= 600
