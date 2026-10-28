"""Projecting the phone project again keeps what `eas init` and the build gave `app.json`.

A robot access token is refused without `expo.owner`, so when an Editor change rewrote `app.json` from the template (dropping the
owner and the build's unique slug) the platform could never read the status of a finished Expo build: it said "in progress"
for ever (Gather, 2026-10-23)."""
from __future__ import annotations

import json

from services.blueprint import native_projection
from services.blueprint.native_projection import native_root, project_fixed_half

DOC = {"application": {"name": "Gather"}}


def _app_json(tmp_path) -> dict:
    return json.loads((native_root(tmp_path) / "app.json").read_text(encoding="utf-8"))["expo"]


def _link(tmp_path, **expo):
    path = native_root(tmp_path) / "app.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expo"].update(expo)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_owner_the_project_id_and_the_unique_slug_survive_another_projection(tmp_path):
    project_fixed_half(DOC, tmp_path)
    base = _app_json(tmp_path)["slug"]
    _link(tmp_path, owner="tentoro", slug=f"{base}-8a74dt4a", extra={**_app_json(tmp_path)["extra"], "eas": {"projectId": "p-1"}})

    project_fixed_half(DOC, tmp_path)

    expo = _app_json(tmp_path)
    assert expo["owner"] == "tentoro"
    assert expo["slug"] == f"{base}-8a74dt4a"
    assert expo["extra"]["eas"]["projectId"] == "p-1"


def test_a_first_projection_has_no_owner_and_the_plain_slug(tmp_path):
    project_fixed_half(DOC, tmp_path)
    expo = _app_json(tmp_path)
    assert "owner" not in expo
    assert not expo["slug"].endswith("-8a74dt4a")


def test_a_slug_that_is_not_the_projects_own_is_not_carried_over(tmp_path):
    project_fixed_half(DOC, tmp_path)
    _link(tmp_path, slug="something-else")
    project_fixed_half(DOC, tmp_path)
    assert _app_json(tmp_path)["slug"] != "something-else"


def test_an_app_json_that_cannot_be_read_is_written_as_projected(tmp_path):
    root = native_root(tmp_path)
    root.mkdir(parents=True)
    (root / "app.json").write_text("not json", encoding="utf-8")
    assert native_projection._kept_link(root / "app.json", '{"expo": {"slug": "a"}}') == '{"expo": {"slug": "a"}}'
