"""The editor's save must land where its read came from.

Regression test for a P0: the GET falls through from `<output>/src/...` to
`<output>/app/src/...` (the Blueprint engine projects the app into `app/`), but
the POST always wrote the root path and created the directory if missing. For a
Blueprint-generated app that meant the first save forked the file into a shadow
copy the editor then preferred on every subsequent read — so the canvas showed
the user their own edits, the toolbar said "Saved", and the running application
never received another change.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from main import app
    import routers._debug_schema as mod

    async def _base(_short_id: str) -> Path:
        return tmp_path

    monkeypatch.setattr(mod, "_resolve_project_base", _base)
    return TestClient(app)


def _write(client, body="{\"schemaVersion\": \"2\"}"):
    return client.post(
        "/api/_debug/project-file/proj/src/schemas/page.json",
        json={"content": body},
    )


def test_blueprint_layout_writes_into_app_dir(client, tmp_path):
    """A file that lives under app/ must be UPDATED there, not shadowed."""
    real = tmp_path / "app" / "src" / "schemas" / "page.json"
    real.parent.mkdir(parents=True)
    real.write_text('{"old": true}', encoding="utf-8")

    r = _write(client, '{"edited": true}')
    assert r.status_code == 200

    assert json.loads(real.read_text(encoding="utf-8")) == {"edited": True}
    # and no shadow copy at the output root
    assert not (tmp_path / "src" / "schemas" / "page.json").exists()


def test_new_page_in_a_blueprint_app_lands_beside_its_siblings(client, tmp_path):
    """A page the user just created exists in neither place; it must follow the
    project's shape rather than defaulting to the root."""
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)

    assert _write(client).status_code == 200

    assert (tmp_path / "app" / "src" / "schemas" / "page.json").exists()
    assert not (tmp_path / "src" / "schemas" / "page.json").exists()


def test_flat_project_still_writes_at_the_root(client, tmp_path):
    """Older projects projected straight into output/<id> must be unaffected."""
    real = tmp_path / "src" / "schemas" / "page.json"
    real.parent.mkdir(parents=True)
    real.write_text('{"old": true}', encoding="utf-8")

    assert _write(client, '{"edited": true}').status_code == 200

    assert json.loads(real.read_text(encoding="utf-8")) == {"edited": True}
    assert not (tmp_path / "app" / "src" / "schemas" / "page.json").exists()


def test_project_with_no_app_dir_writes_at_the_root(client, tmp_path):
    """No app/ at all — nothing to fall through to."""
    assert _write(client).status_code == 200
    assert (tmp_path / "src" / "schemas" / "page.json").exists()


def test_path_traversal_still_blocked(client):
    r = client.post(
        "/api/_debug/project-file/proj/../../etc/passwd",
        json={"content": "x"},
    )
    assert r.status_code in (403, 404)
