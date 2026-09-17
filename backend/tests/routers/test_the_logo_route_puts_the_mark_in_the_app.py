"""Uploading a logo to a project puts it in the application, not in a folder.

`/api/brand/extract/logo` has always accepted a logo and always thrown it
away — it answers with a palette. This is the route that keeps it, and the
thing it must not become is a file-upload endpoint: the upload is only done
when the Blueprint records the mark and the generated tree carries it.

The handlers are called directly with `get_project_with_auth` stubbed. The
route's own body — the 400 for a file we cannot use, the 409 for a project with
nothing generated, and the hand-off to the one seam that writes
`designSystem.logo` — is what is under test; the auth dependency is FastAPI's.
"""
import io
import json
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from routers import brand
from services.blueprint.service import BlueprintService


def _png(size=(120, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 170, 120)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(name: str, data: bytes, content_type: str) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data),
                      headers={"content-type": content_type})


class _Project:
    def __init__(self, output_dir):
        self.id = "p1"
        self.output_dir = str(output_dir) if output_dir else None


@pytest.fixture
def project(tmp_path, monkeypatch):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="APP-1",
                                  name="Bright Care", domain="care")
    svc.doc["designSystem"] = {"colors": {"primary": "#0a7"}}
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/home",
                         "purpose": "where the day starts", "access": "authenticated"}]
    svc.doc["navigation"] = {"tree": [{"label": "Home", "page": "PAGE-001"}]}
    svc.save()
    p = _Project(tmp_path)

    async def _auth(project_id, user, db):
        return p

    monkeypatch.setattr(brand, "get_project_with_auth", _auth)
    return p


@pytest.mark.asyncio
async def test_the_upload_lands_in_the_document_and_in_the_tree(project, tmp_path):
    out = await brand.set_project_logo(
        project_id="p1", logo=_upload("logo.png", _png(), "image/png"),
        alt="Bright Care", user=None, db=None)

    doc = BlueprintService.load(output_dir=tmp_path).doc
    assert doc["designSystem"]["logo"] == out["logo"]
    assert out["logo"]["alt"] == "Bright Care"
    assert (tmp_path / out["logo"]["file"]).is_file()

    shell = json.loads((tmp_path / "app/src/schemas/shell.json").read_text())
    assert shell["children"][0]["props"]["logoSrc"] == "/" + out["logo"]["file"]
    assert (tmp_path / "app/public" / out["logo"]["file"]).is_file()
    assert f"public/{out['logo']['file']}" in out["edited_paths"]


@pytest.mark.asyncio
async def test_an_svg_wordmark_is_accepted(project, tmp_path):
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 60">'
           b'<rect width="300" height="60"/></svg>')
    out = await brand.set_project_logo(
        project_id="p1", logo=_upload("mark.svg", svg, "image/svg+xml"),
        alt="", user=None, db=None)
    assert out["logo"]["mediaType"] == "image/svg+xml"
    # No alt given, so the rail reads the application's name aloud instead of
    # the digest the file is stored under.
    shell = json.loads((tmp_path / "app/src/schemas/shell.json").read_text())
    assert shell["children"][0]["props"]["logoAlt"] == "Bright Care"


@pytest.mark.asyncio
async def test_a_file_we_cannot_render_is_a_400_with_words_for_the_owner(project):
    with pytest.raises(HTTPException) as exc:
        await brand.set_project_logo(
            project_id="p1", logo=_upload("guide.pdf", b"%PDF-1.4", "application/pdf"),
            alt="", user=None, db=None)
    assert exc.value.status_code == 400
    assert "PNG" in exc.value.detail


@pytest.mark.asyncio
async def test_removing_it_puts_the_rail_back(project, tmp_path):
    await brand.set_project_logo(
        project_id="p1", logo=_upload("logo.png", _png(), "image/png"),
        alt="", user=None, db=None)
    out = await brand.clear_project_logo(project_id="p1", user=None, db=None)
    assert out["logo"] is None
    assert "logo" not in BlueprintService.load(output_dir=tmp_path).doc["designSystem"]
    shell = json.loads((tmp_path / "app/src/schemas/shell.json").read_text())
    assert "logoSrc" not in shell["children"][0]["props"]


@pytest.mark.asyncio
async def test_removing_one_that_was_never_set_is_a_409_not_a_crash(project):
    with pytest.raises(HTTPException) as exc:
        await brand.clear_project_logo(project_id="p1", user=None, db=None)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_project_with_nothing_generated_says_so(tmp_path, monkeypatch):
    async def _auth(project_id, user, db):
        return _Project(None)

    monkeypatch.setattr(brand, "get_project_with_auth", _auth)
    with pytest.raises(HTTPException) as exc:
        await brand.set_project_logo(
            project_id="p1", logo=_upload("logo.png", _png(), "image/png"),
            alt="", user=None, db=None)
    assert exc.value.status_code == 409
