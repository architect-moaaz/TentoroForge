"""The live phone preview: a dev server kept running for a project, reached by the browser only through the backend.

A change shows in under a second because the bundler keeps running and swaps the changed piece into the open page. The browser never
talks to it: the backend passes on a short list of requests under `/api/projects/{short_id}/phone/live/`, and the two live-update sockets,
which Expo's page opens at the top of the host and which the live copy patches to carry that path. These tests cover the path rules, the
rewritten page, the patched runtime, keeping the copy current, and the proxy itself against a small fake dev server (pages, a bundle and a
real WebSocket) so no phone toolchain is needed."""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from services import phone_live as pl, phone_live_proxy as proxy

# ---- which paths a browser may ask the dev server for ---------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/", "/index.bundle", "/..%5C..%5C..%5Cnative%5Cnode_modules%5Cexpo-router%5Centry.bundle", "/entry.bundle.map",
    "/assets/fonts/Ionicons.ttf", "/_expo/static/js/web/entry.js", "/favicon.ico", "/manifest.json",
])
def test_what_a_page_needs_is_passed_on(path):
    assert proxy.allowed(path)


@pytest.mark.parametrize("path", [
    "/open-stack-frame", "/open-url", "/launch-js-devtools", "/debugger-ui/", "/inspector/debug", "/symbolicate", "/logs", "/json/list",
    "/status", "/src/screens/PAGE-001.tsx", "/../../etc/passwd", "/node_modules/react/index.js", "/hot", "/message",
])
def test_the_dev_servers_own_tools_and_the_projects_files_are_not(path):
    assert not proxy.allowed(path)


def test_the_two_scripts_the_editor_adds_are_the_platforms_own():
    assert proxy.own_file("/__bridge.js")[0].endswith("bridge.js")
    assert proxy.own_file("/__fit.js")[0].endswith("fit.js")
    assert proxy.own_file("/index.bundle") is None


# ---- the page, under the path it is served from -----------------------------------------------------------------------------

PAGE = ('<!DOCTYPE html><html><head><meta charset="utf-8" /><title>x</title></head><body><div id="root"></div>'
        '<script src="/..%5Cnative%5Cexpo-router%5Centry.bundle?platform=web&dev=true" defer></script></body></html>')


def test_the_pages_links_move_under_the_prefix_and_it_learns_the_prefix_first():
    out = proxy.rewrite_html(PAGE, "/api/projects/abc/phone/live")
    assert 'src="/api/projects/abc/phone/live/..%5Cnative%5Cexpo-router%5Centry.bundle?platform=web&dev=true"' in out
    assert out.index("window.__FORGE_LIVE__") < out.index("entry.bundle"), "before anything else runs"
    assert 'window.__FORGE_LIVE__="/api/projects/abc/phone/live"' in out
    assert '<script src="/api/projects/abc/phone/live/__bridge.js"></script>' in out and out.index("__bridge.js") > out.index("entry.bundle")


def test_the_page_keeps_its_real_address_so_a_reload_lands_on_the_same_screen():
    """It used to move its address to the top of the host; a full reload (any change that cannot be hot-swapped) then loaded the
    platform's own home page inside the phone frame (reported 2026-10-22)."""
    out = proxy.rewrite_html(PAGE, "/api/projects/abc/phone/live")
    assert "replaceState" not in out and "history." not in out
    assert 'window.__FORGE_LIVE__="/api/projects/abc/phone/live";</script>' in out, "it still learns the prefix, for its sockets"


def test_a_link_to_another_site_is_left_alone():
    out = proxy.rewrite_html('<head></head><body><a href="//cdn.example.com/x">x</a><img src="https://a.test/b.png"></body>', "/p")
    assert 'href="//cdn.example.com/x"' in out and 'src="https://a.test/b.png"' in out


def test_the_path_the_dev_server_is_asked_for_is_the_raw_one_without_the_prefix():
    raw = b"/api/projects/abc/phone/live/..%5C..%5Cnative%5Centry.bundle"
    assert proxy.upstream_path(raw, "/api/projects/abc/phone/live") == "/..%5C..%5Cnative%5Centry.bundle", "encoded characters are kept as sent"
    assert proxy.upstream_path(b"/api/projects/abc/phone/live", "/api/projects/abc/phone/live") == "/"


# ---- Expo's two sockets, made to carry the prefix ----------------------------------------------------------------------

GUARD = "if (process.env.NODE_ENV !== 'development') {"
GET_STATE = ('const a = require("./findFocusedRoute");\nconst b = __importDefault(require("./validatePathConfig"));\nconst c = require("../matchers");\n'
             f'function stripBaseUrl(path, baseUrl = process.env.EXPO_BASE_URL) {{\n    {GUARD}\n        if (baseUrl) return path.replace(baseUrl, "");\n    }}\n    return path;\n}}\n')
GET_PATH = ('const core = require("@react-navigation/core");\nconst c = require("../matchers");\n'
            f'function appendBaseUrl(path, baseUrl = process.env.EXPO_BASE_URL) {{\n    {GUARD}\n        if (baseUrl) return baseUrl + path;\n    }}\n    return path;\n}}\n')


def _runtime(tmp_path: Path, hmr: str, message: str, state: str = GET_STATE, path: str = GET_PATH) -> Path:
    base = tmp_path / "node_modules" / "@expo" / "metro-runtime" / "build"
    base.mkdir(parents=True)
    (base / "HMRClient.js").write_text(hmr, encoding="utf-8")
    (base / "messageSocket.js").write_text(message, encoding="utf-8")
    router = tmp_path / "node_modules" / "expo-router" / "build" / "fork"
    router.mkdir(parents=True)
    (router / "getStateFromPath.js").write_text(state, encoding="utf-8")
    (router / "getPathFromState.js").write_text(path, encoding="utf-8")
    return tmp_path / "node_modules"


HMR = ('const A = require("./LoadingView");\nconst B = require("./error-overlay/LogBox");\nconst C = require(\'./getDevServer\');\n'
       'const client = new MetroHMRClient(`${serverScheme}://${window.location.host}/hot`);\nconsole.log(`URL: ${window.location.host}`);\n')
MESSAGE = 'const messageSocket = new WebSocket(`${protocol}://${window.location.host}/message`);\n'


def test_the_sockets_read_a_prefix_from_the_page_and_the_copy_names_its_neighbours_in_full(tmp_path):
    out = pl.patched_runtime(_runtime(tmp_path, HMR, MESSAGE))
    assert "${window.location.host}${window.__FORGE_LIVE__ || ''}/hot" in out["HMRClient.js"]
    assert "${window.location.host}${window.__FORGE_LIVE__ || ''}/message" in out["messageSocket.js"]
    assert "URL: ${window.location.host}`" in out["HMRClient.js"], "only the socket address changes"
    for name in ("LoadingView", "error-overlay/LogBox", "getDevServer"):
        assert f'require("@expo/metro-runtime/build/{name}")' in out["HMRClient.js"]


def test_the_refreshing_bar_is_silenced_in_the_live_copy_only(tmp_path):
    """Expo's "Refreshing... Using Fast Refresh" bar would cover the phone's tab bar on every change."""
    out = pl.patched_runtime(_runtime(tmp_path, HMR, MESSAGE))
    assert "showMessage() {}" in out["LoadingView.js"] and "hide() {}" in out["LoadingView.js"]
    assert out["LoadingView.js"].count("\n") == 2, "a real two-line module, not one line with a stray escape"
    pl.write_live_files(_runtime(tmp_path / "again", HMR, MESSAGE).parent)
    assert "LoadingView" in (tmp_path / "again" / "metro.config.js").read_text(encoding="utf-8")


def test_an_expo_that_is_not_the_one_it_knows_is_said_and_the_build_is_used(tmp_path):
    with pytest.raises(pl.LiveUnavailable) as e:
        pl.patched_runtime(_runtime(tmp_path, "nothing recognisable", MESSAGE))
    assert "not the version" in str(e.value)
    with pytest.raises(pl.LiveUnavailable):
        pl.patched_runtime(tmp_path / "missing")


def test_the_routers_base_path_works_in_development_too_so_the_page_keeps_its_address(tmp_path):
    """Expo Router strips and adds its base path only outside development. Under the live path that left no screen."""
    out = pl.patched_runtime(_runtime(tmp_path, HMR, MESSAGE))
    for name, function in (("getStateFromPath.js", "stripBaseUrl"), ("getPathFromState.js", "appendBaseUrl")):
        assert GUARD not in out[name] and "if (true) {" in out[name] and function in out[name]
    assert out["getStateFromPath.js"].count("if (true) {") == 1, "only that guard"


def test_the_routers_neighbours_are_named_in_full_whether_they_sit_beside_it_or_above_it(tmp_path):
    out = pl.patched_runtime(_runtime(tmp_path, HMR, MESSAGE))
    state = out["getStateFromPath.js"]
    assert 'require("expo-router/build/fork/findFocusedRoute")' in state
    assert 'require("expo-router/build/fork/validatePathConfig")' in state
    assert 'require("expo-router/build/matchers")' in state, "`../matchers` climbs out of fork/"
    assert 'require("@react-navigation/core")' in out["getPathFromState.js"], "a package is left as it was"


def test_a_router_that_is_not_the_one_it_knows_is_said_and_the_build_is_used(tmp_path):
    with pytest.raises(pl.LiveUnavailable) as e:
        pl.patched_runtime(_runtime(tmp_path, HMR, MESSAGE, state="function stripBaseUrl(path) { return path; }"))
    assert "stripBaseUrl" in str(e.value) and "not the version" in str(e.value)
    with pytest.raises(pl.LiveUnavailable):
        pl.patched_runtime(_runtime(tmp_path / "two", HMR, MESSAGE, path=GET_PATH + GET_PATH))      # the guard twice: not what it knows


def test_the_metro_config_swaps_exactly_the_files_it_was_written_for(tmp_path):
    modules = _runtime(tmp_path, HMR, MESSAGE)
    stage = modules.parent
    pl.write_live_files(stage)
    config = (stage / "metro.config.js").read_text(encoding="utf-8")
    assert "HMRClient|messageSocket" in config and "getStateFromPath|getPathFromState" in config and "forge-live" in config
    assert all((stage / "forge-live" / f).is_file() for f in ("HMRClient.js", "messageSocket.js", "LoadingView.js", "getStateFromPath.js", "getPathFromState.js"))
    assert (stage / "forge-live" / "HMRClient.js").is_file() and (stage / "forge-live" / "messageSocket.js").is_file()


# ---- keeping the copy current ---------------------------------------------------------------------------------------------

def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")


def test_a_changed_screen_is_copied_and_a_removed_one_is_removed(tmp_path):
    real, stage = tmp_path / "real", tmp_path / "stage"
    _tree(real, {"src/screens/PAGE-001.tsx": "one", "src/theme.generated.ts": "green", "app/index.tsx": "x"})
    _tree(stage, {"src/screens/PAGE-001.tsx": "one", "src/theme.generated.ts": "green", "app/index.tsx": "x", "src/screens/PAGE-009.tsx": "old"})
    assert pl.sync_files(real, stage) == 1 and not (stage / "src/screens/PAGE-009.tsx").exists(), "what is gone is gone"
    (real / "src/screens/PAGE-001.tsx").write_text("two", encoding="utf-8")
    (real / "src/theme.generated.ts").write_text("red", encoding="utf-8")
    assert pl.sync_files(real, stage) == 2
    assert (stage / "src/screens/PAGE-001.tsx").read_text(encoding="utf-8") == "two"
    assert (stage / "src/theme.generated.ts").read_text(encoding="utf-8") == "red"
    assert pl.sync_files(real, stage) == 0, "nothing changed, so nothing is written (and the bundler is not disturbed)"


def test_a_new_file_is_copied_in(tmp_path):
    real, stage = tmp_path / "real", tmp_path / "stage"
    _tree(real, {"src/screens/PAGE-002.tsx": "new"})
    (stage / "src").mkdir(parents=True)
    assert pl.sync_files(real, stage) == 1 and (stage / "src/screens/PAGE-002.tsx").read_text(encoding="utf-8") == "new"


def test_the_previews_own_files_are_never_overwritten_or_removed(tmp_path):
    real, stage = tmp_path / "real", tmp_path / "stage"
    _tree(real, {"src/sdk/api.ts": "the project's own", "src/sdk/preview.ts": "not the preview's"})
    _tree(stage, {"src/sdk/api.ts": "patched for the preview", "src/sdk/preview.ts": "the sample backend", "src/sdk/preview-data.json": "{}"})
    pl.sync_files(real, stage)
    assert (stage / "src/sdk/api.ts").read_text(encoding="utf-8") == "patched for the preview"
    assert (stage / "src/sdk/preview.ts").read_text(encoding="utf-8") == "the sample backend"
    assert (stage / "src/sdk/preview-data.json").exists()


# ---- starting, using, and stopping -----------------------------------------------------------------------------------------

class _Process:
    def __init__(self, code=None):
        self.returncode = code
        self.pid = 0


@pytest.fixture(autouse=True)
def _clean():
    pl._servers.clear()
    yield
    pl._servers.clear()


def _server(short_id: str, state="ready", port=1234, used=0.0, code=None) -> "pl.Server":
    s = pl.Server(short_id=short_id, output_dir="x", state=state, port=port, process=_Process(code))
    s.last_used = used
    pl._servers[short_id] = s
    return s


def test_nothing_runs_until_it_is_asked_for():
    assert pl.status("abc") == {"state": "off", "path": "/api/projects/abc/phone/live", "error": ""}
    assert pl.port_of("abc") is None


def test_a_server_that_is_up_has_a_port_and_a_server_that_is_starting_does_not():
    _server("up")
    _server("coming", state="starting", port=0)
    assert pl.port_of("up") == 1234 and pl.port_of("coming") is None
    assert pl.status("coming")["state"] == "starting"


def test_a_server_whose_process_died_says_so():
    _server("dead", code=1)
    assert pl.status("dead") == {"state": "failed", "path": "/api/projects/dead/phone/live", "error": "The live preview stopped."}


def test_using_a_server_counts_as_use(monkeypatch):
    s = _server("up", used=0.0)
    pl.port_of("up")
    assert s.last_used > 0.0


def test_stopping_forgets_it_and_cancels_what_it_was_doing(monkeypatch):
    killed = []
    monkeypatch.setattr(pl, "_kill", lambda process: killed.append(process))
    s = _server("up")

    class T:
        cancelled = False

        def cancel(self):
            self.cancelled = True
    t = T()
    s.tasks.append(t)
    pl.stop("up")
    assert "up" not in pl._servers and t.cancelled and len(killed) == 1
    pl.stop("up")          # twice is fine


def test_a_new_server_beyond_the_limit_stops_the_one_used_least_recently(monkeypatch):
    stopped = []
    monkeypatch.setattr(pl, "stop", lambda sid: (stopped.append(sid), pl._servers.pop(sid, None)))
    monkeypatch.setattr(pl, "MAX_SERVERS", 2)

    async def never(server):
        await asyncio.sleep(3600)
    monkeypatch.setattr(pl, "_start", never)
    _server("old", used=1.0)
    _server("newer", used=5.0)

    async def go():
        pl.start("/tmp/x", "third")
        for task in pl._servers["third"].tasks:
            task.cancel()
        if pl._reaper:
            pl._reaper.cancel()
    asyncio.run(go())
    assert stopped == ["old"]


def test_asking_again_while_it_starts_does_not_start_a_second(monkeypatch):
    started = []

    async def fake(server):
        started.append(server.short_id)
        await asyncio.sleep(3600)
    monkeypatch.setattr(pl, "_start", fake)

    async def go():
        a = pl.start("/tmp/x", "abc")
        b = pl.start("/tmp/x", "abc")
        await asyncio.sleep(0)
        for task in pl._servers["abc"].tasks:
            task.cancel()
        if pl._reaper:
            pl._reaper.cancel()
        return a, b
    a, b = asyncio.run(go())
    assert a["state"] == b["state"] == "starting" and started == ["abc"]


# ---- the proxy, against a small fake dev server ------------------------------------------------------------------------------

class _Dev(BaseHTTPRequestHandler):
    seen: list[str] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Dev.seen.append(self.path)
        if self.path.split("?")[0] == "/":
            body, kind = PAGE.encode(), "text/html"
        elif self.path.split("?")[0].endswith("withassets.bundle"):
            body = (b'var icons = {"httpServerLocation": "/assets/?unstable_path=.%2F..%2Fnative%2FFonts", "name": "Ionicons"};'
                    b' var other = "/assetsmith"; var same = {"httpServerLocation": "/assets/?unstable_path=.%2Fx"};')
            kind = "application/javascript"
        elif self.path.split("?")[0].endswith(".bundle"):
            body, kind = b"console.log('the app')" * 2000, "application/javascript"
        else:
            body, kind = b"x", "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def dev():
    _Dev.seen = []
    http = HTTPServer(("127.0.0.1", 0), _Dev)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield http.server_address[1]
    http.shutdown()


@pytest.fixture
def client(dev):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.phone_live import router
    app = FastAPI()
    app.include_router(router)
    _server("abc", port=dev)
    return TestClient(app)


def test_the_page_comes_back_under_the_prefix_with_the_editors_scripts(client):
    r = client.get("/api/projects/abc/phone/live/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'window.__FORGE_LIVE__="/api/projects/abc/phone/live"' in r.text and "/phone/live/__bridge.js" in r.text
    assert 'src="/api/projects/abc/phone/live/..%5Cnative' in r.text


def test_the_bundle_is_passed_on_whole_with_its_path_and_query_untouched(client):
    r = client.get("/api/projects/abc/phone/live/..%5Cnative%5Cexpo-router%5Centry.bundle?platform=web&dev=true")
    assert r.status_code == 200 and r.content.startswith(b"console.log('the app')") and len(r.content) > 40000
    assert _Dev.seen[-1] == "/..%5Cnative%5Cexpo-router%5Centry.bundle?platform=web&dev=true"


def test_a_tool_of_the_dev_server_never_reaches_it(client):
    for path in ("open-stack-frame", "launch-js-devtools", "symbolicate", "src/screens/PAGE-001.tsx"):
        assert client.get(f"/api/projects/abc/phone/live/{path}").status_code == 404
    assert not any("open-stack" in p or "devtools" in p or "symbolicate" in p or "PAGE-001" in p for p in _Dev.seen)


def test_a_screens_own_address_reloaded_gets_the_page(client):
    r = client.get("/api/projects/abc/phone/live/bought", headers={"accept": "text/html"})
    assert r.status_code == 200 and "__FORGE_LIVE__" in r.text


def test_the_editors_scripts_are_the_platforms_own_and_never_asked_of_the_dev_server(client):
    r = client.get("/api/projects/abc/phone/live/__bridge.js")
    assert r.status_code == 200 and "design2ui" in r.text and "/__bridge.js" not in "".join(_Dev.seen)


def test_nothing_is_passed_on_when_it_is_not_running(dev):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.phone_live import router
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/api/projects/nope/phone/live/").status_code == 503


# ---- the sockets ---------------------------------------------------------------------------------------------------------------

def test_a_live_update_socket_is_carried_both_ways(dev):
    """A message sent by the page reaches the dev server, and what the dev server sends comes back."""
    import websockets.sync.server as wss
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.phone_live import router

    got: list[str] = []

    def handler(connection):
        got.append(connection.request.path)
        for message in connection:
            connection.send("echo:" + message)

    server = wss.serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        _server("abc", port=server.socket.getsockname()[1])
        app = FastAPI()
        app.include_router(router)
        with TestClient(app).websocket_connect("/api/projects/abc/phone/live/hot") as ws:
            ws.send_text(json.dumps({"type": "register-entrypoints"}))
            assert ws.receive_text() == 'echo:{"type": "register-entrypoints"}'
        assert got == ["/hot"], "the dev server sees its own path, without the prefix"
        with TestClient(app).websocket_connect("/api/projects/abc/phone/live/message") as ws:
            ws.send_text("reload")
            assert ws.receive_text() == "echo:reload"
        assert got == ["/hot", "/message"]
    finally:
        server.shutdown()


def test_a_socket_for_a_server_that_is_not_running_is_turned_away(dev):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from routers.phone_live import router
    app = FastAPI()
    app.include_router(router)
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/api/projects/none/phone/live/hot") as ws:
            ws.receive_text()


# ---- the crash that a live run found (2026-10-22) ---------------------------------------------------------------------------

def test_what_the_page_says_over_a_socket_is_said_without_the_prefix():
    """The page names its bundle by full address; the dev server reads the path as a file, and stopped when it had the prefix in it."""
    prefix = "/api/projects/abc/phone/live"
    said = json.dumps({"type": "register-entrypoints", "entryPoints": [
        f"http://localhost:6501{prefix}/..%5Cnative%5Cexpo-router%5Centry.bundle?platform=web&transform.baseUrl=%2Fapi%2Fprojects%2Fabc%2Fphone%2Flive"]})
    heard = proxy.unprefixed(said, prefix)
    assert "http://localhost:6501/..%5Cnative%5Cexpo-router%5Centry.bundle?" in heard and prefix + "/" not in heard
    assert "transform.baseUrl=%2Fapi%2Fprojects%2Fabc%2Fphone%2Flive" in heard, "the app's own base path, in the query, is the bundle's and stays"


def test_the_socket_tells_the_dev_server_the_address_it_built_the_bundle_for(dev):
    import websockets.sync.server as wss
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.phone_live import router
    heard: list[str] = []

    def handler(connection):
        for message in connection:
            heard.append(message)
            connection.send("ok")

    server = wss.serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        _server("abc", port=server.socket.getsockname()[1])
        app = FastAPI()
        app.include_router(router)
        said = json.dumps({"type": "register-entrypoints",
                           "entryPoints": ["https://forge.test/api/projects/abc/phone/live/..%5Cnative%5Centry.bundle?platform=web"]})
        with TestClient(app).websocket_connect("/api/projects/abc/phone/live/hot") as ws:
            ws.send_text(said)
            assert ws.receive_text() == "ok"
        assert heard == [said.replace("/api/projects/abc/phone/live/", "/")]
        assert "phone/live" not in heard[0]
    finally:
        server.shutdown()


def test_a_dev_server_that_stopped_is_not_ready_and_is_not_asked(monkeypatch):
    s = _server("dead", code=1)
    assert pl.port_of("dead") is None
    assert s.state == "failed" and s.error == "The live preview stopped."


def test_a_dev_server_that_stops_answering_is_marked_so_the_editor_shows_the_build(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.phone_live import router
    s = _server("abc", port=1)                     # nothing listens on port 1
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).get("/api/projects/abc/phone/live/")
    assert r.status_code == 503 and "not answering" in r.json()["detail"]
    assert s.state == "failed" and pl.status("abc")["state"] == "failed"


# ---- Linux writes the climb out of the project with plain slashes (found by reasoning, 2026-10-22) ------------------------------

LINUX_PAGE = ('<html><head></head><body><div id="root"></div>'
              '<script src="/../../../native/node_modules/expo-router/entry.bundle?platform=web&dev=true&transform.baseUrl=%2Fapi%2Fprojects%2Fabc%2Fphone%2Flive" defer></script></body></html>')


def test_a_climb_out_of_the_project_is_written_so_a_browser_does_not_remove_it():
    """`/prefix/../../../native/…` would be collapsed by the browser to `/api/projects/native/…` before the request is made."""
    out = proxy.rewrite_html(LINUX_PAGE, "/api/projects/abc/phone/live")
    assert 'src="/api/projects/abc/phone/live/..%2F..%2F..%2Fnative/node_modules/expo-router/entry.bundle?platform=web' in out
    from urllib.parse import urlsplit
    from posixpath import normpath
    path = urlsplit("http://h" + out.split('src="')[1].split("?")[0]).path
    assert normpath(path) == path, "nothing in the path is left for a browser to collapse"


def test_the_query_after_the_climb_is_left_exactly_as_it_was():
    out = proxy.rewrite_html(LINUX_PAGE, "/api/projects/abc/phone/live")
    assert "?platform=web&dev=true&transform.baseUrl=%2Fapi%2Fprojects%2Fabc%2Fphone%2Flive" in out


def test_the_encoded_climb_is_an_app_bundle_the_page_may_ask_for():
    assert proxy.allowed("/..%2F..%2F..%2Fnative/node_modules/expo-router/entry.bundle")
    assert not proxy.allowed("/..%2F..%2F..%2Fnative/node_modules/expo-router/entry.ts"), "only a bundle, not a file of the project"


def test_a_path_with_no_climb_is_written_as_it_was():
    out = proxy.rewrite_html('<head></head><body><script src="/_expo/static/js/web/a.js"></script></body>', "/p")
    assert 'src="/p/_expo/static/js/web/a.js"' in out


# ---- the icon font was asked for at the top of the host (Cart Buddy, 2026-10-22) --------------------------------------------------

def test_the_addresses_of_fonts_and_pictures_in_the_code_move_under_the_prefix():
    code = 'x = {"httpServerLocation": "/assets/?unstable_path=.%2F..%2Fnative%2FFonts"}; y = "/assetsmith"; z = "/api/other"'
    out = proxy.rewrite_bundle(code, "/api/projects/abc/phone/live")
    assert '"/api/projects/abc/phone/live/assets/?unstable_path=.%2F..%2Fnative%2FFonts"' in out
    assert '"/assetsmith"' in out and '"/api/other"' in out, "only the dev server's asset address is moved"


def test_the_bare_asset_address_and_a_file_under_assets_are_what_a_page_may_ask_for():
    assert proxy.allowed("/assets/") and proxy.allowed("/assets") and proxy.allowed("/assets/fonts/Ionicons.ttf")
    assert not proxy.allowed("/assetsmith") and not proxy.allowed("/assets-private/x")


def test_a_font_is_passed_on_by_its_asset_address(client):
    r = client.get("/api/projects/abc/phone/live/assets/?unstable_path=.%2F..%2Fnative%2FFonts%2FIonicons.ttf&platform=web&hash=abc")
    assert r.status_code == 200 and _Dev.seen[-1] == "/assets/?unstable_path=.%2F..%2Fnative%2FFonts%2FIonicons.ttf&platform=web&hash=abc"


def test_a_bundle_comes_back_with_its_assets_under_the_prefix(client):
    r = client.get("/api/projects/abc/phone/live/withassets.bundle?platform=web")
    assert r.status_code == 200
    assert r.text.count('"/api/projects/abc/phone/live/assets/?unstable_path=') == 2
    assert '"/assetsmith"' in r.text and "content-length" not in {k.lower() for k in r.headers if k.lower() == "content-length" and int(r.headers[k]) != len(r.content)}


def test_a_live_update_carries_its_assets_under_the_prefix_too(dev):
    import websockets.sync.server as wss
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.phone_live import router

    def handler(connection):
        for _ in connection:
            connection.send('update {"httpServerLocation": "/assets/?unstable_path=.%2Fx"}')

    server = wss.serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        _server("abc", port=server.socket.getsockname()[1])
        app = FastAPI()
        app.include_router(router)
        with TestClient(app).websocket_connect("/api/projects/abc/phone/live/hot") as ws:
            ws.send_text("go")
            assert ws.receive_text() == 'update {"httpServerLocation": "/api/projects/abc/phone/live/assets/?unstable_path=.%2Fx"}'
    finally:
        server.shutdown()
