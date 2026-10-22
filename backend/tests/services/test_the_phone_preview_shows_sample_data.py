"""The editor's phone preview draws the app's native screens with sample data, so nobody signs in and nothing real is read.

What is checked here is what the preview stands on: the rows made from the Blueprint, the copy of the project it builds in
(the project itself untouched), and where a build stands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import phone_preview

DOC = {
    "data": {
        "entities": [
            {"id": "e1", "name": "User", "account": True, "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "text", "required": True},
                {"name": "name", "type": "text"},
            ]},
            {"id": "e2", "name": "PantryItem", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "userId", "type": "uuid"},
                {"name": "name", "type": "text", "required": True},
                {"name": "quantity", "type": "integer"},
                {"name": "status", "type": "text", "enumValues": ["Fresh", "Expired"]},
                {"name": "expiryDate", "type": "date"},
            ]},
        ],
        "relationships": [],
    },
}


def _data() -> dict:
    return phone_preview.sample_data(DOC)


def test_every_entity_gets_rows_and_a_label():
    data = _data()
    assert set(data["entities"]) == {"User", "PantryItem"}
    items = data["entities"]["PantryItem"]
    assert len(items["rows"]) == phone_preview.SAMPLE_ROWS
    assert items["label"] == "name"
    assert items["numeric"] == ["quantity"]


def test_values_follow_the_columns_types():
    row = _data()["entities"]["PantryItem"]["rows"][1]
    assert isinstance(row["quantity"], (int, float))
    assert row["status"] in ("Fresh", "Expired")
    assert row["expiryDate"].endswith("Z")
    assert row["name"] == "Pantry item 2"


def test_what_points_at_the_account_belongs_to_the_signed_in_person():
    data = _data()
    assert data["account"] == "User"
    me = data["user"]["id"]
    assert me == data["entities"]["User"]["rows"][0]["id"]
    # `userId` is not declared as a relationship: it is read from its name, and a "my items" list is never empty.
    assert {r["userId"] for r in data["entities"]["PantryItem"]["rows"]} == {me}


def test_the_sample_data_is_the_same_every_time():
    a, b = _data(), _data()
    assert [r["id"] for r in a["entities"]["PantryItem"]["rows"]] == [r["id"] for r in b["entities"]["PantryItem"]["rows"]]


def _project(tmp_path: Path) -> Path:
    native = tmp_path / "native"
    (native / "app").mkdir(parents=True)
    (native / "src" / "sdk").mkdir(parents=True)
    (native / "package.json").write_text("{}", encoding="utf-8")
    (native / "app.json").write_text(json.dumps({"expo": {"extra": {"appUrl": "https://live.example"}}}), encoding="utf-8")
    (native / "src" / "sdk" / "api.ts").write_text(
        'import { signedOut } from "./events";\nconst raw = createClient({\n  fetch: (url, init) => fetch(url, init),\n});\n',
        encoding="utf-8")
    blueprint = tmp_path / ".forge" / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "current.json").write_text(json.dumps({"mobile": {"native": {"enabled": True}}}), encoding="utf-8")
    return tmp_path


def test_a_web_or_pwa_app_is_not_previewed_as_a_phone_app_even_with_a_native_folder_left_over(tmp_path):
    out = _project(tmp_path)
    (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps({"mobile": {"surface": "web_pwa"}}), encoding="utf-8")
    assert phone_preview.status(out, "abc")["state"] == "unavailable"


def test_an_app_without_phone_screens_has_nothing_to_preview(tmp_path):
    assert phone_preview.status(tmp_path, "abc")["state"] == "unavailable"
    with pytest.raises(phone_preview.PhonePreviewError):
        phone_preview.start(tmp_path, "abc")


def test_the_copy_is_pointed_at_the_sample_backend_and_the_project_is_not(tmp_path):
    out = _project(tmp_path)
    staged = tmp_path / "copy"
    staged.mkdir()
    for rel in ("app.json", "src/sdk/api.ts"):
        (staged / rel).parent.mkdir(parents=True, exist_ok=True)
        (staged / rel).write_text((out / "native" / rel).read_text(encoding="utf-8"), encoding="utf-8")

    phone_preview._prepare_copy(staged, DOC, "abc123")

    api = (staged / "src" / "sdk" / "api.ts").read_text(encoding="utf-8")
    assert "previewFetch(url, init)" in api and 'from "./preview"' in api
    assert (staged / "src" / "sdk" / "preview-data.json").is_file()
    app = json.loads((staged / "app.json").read_text(encoding="utf-8"))["expo"]
    assert app["experiments"]["baseUrl"] == "/api/projects/abc123/phone/serve"
    assert app["extra"]["appUrl"] == "http://preview.local"
    # The project and its EAS build never see any of it.
    assert "previewFetch" not in (out / "native" / "src" / "sdk" / "api.ts").read_text(encoding="utf-8")
    assert json.loads((out / "native" / "app.json").read_text(encoding="utf-8"))["expo"]["extra"]["appUrl"] == "https://live.example"


def test_a_copy_of_unexpected_shape_is_refused_with_a_reason(tmp_path):
    staged = tmp_path / "copy"
    (staged / "src" / "sdk").mkdir(parents=True)
    (staged / "src" / "sdk" / "api.ts").write_text("export {};\n", encoding="utf-8")
    with pytest.raises(phone_preview.PhonePreviewError):
        phone_preview._patch_api(staged)


def test_a_built_preview_says_when_the_screens_changed_after_it(tmp_path):
    out = _project(tmp_path)
    phone_preview._write_status(out, state="ready", fingerprint=phone_preview._fingerprint(out))
    (phone_preview.dist_dir(out)).mkdir(parents=True)
    (phone_preview.dist_dir(out) / "index.html").write_text("<html></html>", encoding="utf-8")
    assert phone_preview.status(out, "abc")["stale"] is False
    (out / "native" / "app" / "index.tsx").write_text("export default 1;\n", encoding="utf-8")
    assert phone_preview.status(out, "abc")["stale"] is True


def test_a_build_the_server_lost_is_reported_as_interrupted(tmp_path):
    out = _project(tmp_path)
    phone_preview._write_status(out, state="building", step="Drawing the screens")
    state = phone_preview.status(out, "abc")
    assert state["state"] == "failed" and "interrupted" in state["error"]


def test_the_exported_page_gets_the_bridge_and_the_fit_script_once(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body><div id=root></div></body></html>", encoding="utf-8")
    phone_preview._inject_scripts(dist, "abc123")
    phone_preview._inject_scripts(dist, "abc123")
    html = (dist / "index.html").read_text(encoding="utf-8")
    assert html.count("/api/projects/abc123/phone/serve/__bridge.js") == 1
    assert html.count("/api/projects/abc123/phone/serve/__fit.js") == 1
    assert (dist / "__bridge.js").is_file() and (dist / "__fit.js").is_file()


def test_a_persons_name_reads_as_a_person():
    doc = {"data": {"entities": [{"id": "e1", "name": "Shopper", "account": True, "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "displayName", "type": "text"},
        {"name": "email", "type": "text"},
    ]}], "relationships": []}}
    rows = phone_preview.sample_data(doc)["entities"]["Shopper"]["rows"]
    assert rows[0]["displayName"] == "Preview User"            # the signed-in person
    assert all(" " in r["displayName"] and "DisplayName" not in r["displayName"] for r in rows)
    assert len({r["displayName"] for r in rows}) == len(rows)
