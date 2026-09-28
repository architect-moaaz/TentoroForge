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


def test_a_database_that_answers_is_left_alone(tmp_path, monkeypatch):
    app = _app(tmp_path, "postgresql://postgres:postgres@localhost:5555/app")
    monkeypatch.setattr("services.blueprint.schema_push.database_exists", lambda url: True)
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
