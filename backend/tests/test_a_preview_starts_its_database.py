"""A fresh build's preview gets its database before `next dev` starts.

Test4, 2026-09-28: the Preview tab ran `next dev` against a DATABASE_URL
nothing listened on, so the dropdowns were empty and nothing saved.
"""
import asyncio

import preview


def _app(tmp_path, url=""):
    (tmp_path / "start.sh").write_text('echo "$1" > ran.txt\n')
    if url:
        (tmp_path / ".env.local").write_text(f"DATABASE_URL={url}\n")
    return tmp_path


def test_the_app_boots_its_database_when_none_answers(tmp_path):
    app = _app(tmp_path, "postgresql://postgres:postgres@localhost:1/app")
    asyncio.run(preview._ensure_database(str(app)))
    assert (app / "ran.txt").read_text().strip() == "--seed-only"


def test_the_apps_own_database_that_answers_is_left_alone(tmp_path, monkeypatch):
    """Up means the app's own container serves its port (wz7a99ir: a Postgres
    installed on the machine answered on 5432 and was taken for the app's)."""
    from services.blueprint import page_review
    app = _app(tmp_path, "postgresql://postgres:postgres@localhost:5555/app")
    monkeypatch.setattr(page_review, "_listening", lambda port: port == 5555)
    monkeypatch.setattr(page_review, "_database_container", lambda port: "c1")
    asyncio.run(preview._ensure_database(str(app)))
    assert not (app / "ran.txt").exists()


def test_sign_in_is_told_the_preview_prefix(tmp_path):
    from pathlib import Path
    tpl = Path(__file__).resolve().parents[1] / "templates/app-foundation/src/app/providers.tsx"
    assert "NEXT_PUBLIC_BASE_PATH" in tpl.read_text()
    p = tmp_path / "src/app/providers.tsx"
    p.parent.mkdir(parents=True)
    p.write_text("return (<SessionProvider>{children}</SessionProvider>);")
    preview._session_under_prefix(str(tmp_path))
    assert 'basePath={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/auth`}' in p.read_text()


def test_the_preview_proxy_passes_every_cookie():
    import httpx
    from routers.preview_proxy import _filter_headers
    h = httpx.Headers([("set-cookie", "a=1; Path=/; Expires=Wed, 21 Oct 2026 07:28:00 GMT"),
                       ("set-cookie", "b=2; Path=/"), ("content-type", "application/json")])
    cookies = [v for k, v in _filter_headers(h) if k.lower() == "set-cookie"]
    assert cookies == ["a=1; Path=/; Expires=Wed, 21 Oct 2026 07:28:00 GMT", "b=2; Path=/"]


def test_a_stray_dev_server_in_the_same_app_is_stopped(tmp_path, monkeypatch):
    seen = []

    class P:
        async def wait(self):
            return 1

    async def fake(*args, **kw):
        seen.append(args)
        return P()
    monkeypatch.setattr(preview.asyncio, "create_subprocess_exec", fake)
    asyncio.run(preview._stop_strays(str(tmp_path)))
    assert seen == [("pkill", "-f", f"{tmp_path.resolve()}/node_modules/.bin/next dev")]
