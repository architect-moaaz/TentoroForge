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
    monkeypatch.setattr("services.blueprint.schema_push._answers", lambda url: True)
    asyncio.run(preview._ensure_database(str(app)))
    assert not (app / "ran.txt").exists()
