"""The editor's endpoints: a refusal reaches the client as `{code, message, …}`
with the status the service chose, and a mutation names the revision it was
made against. Driven as functions with the auth and DB dependencies stubbed,
the way test_preview_start drives its endpoint."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from routers import react_editor as router
from services.blueprint.service import BlueprintService

VIEW = '"use client";\nexport default function View() {\n  return <div className="p-6"><h1>Hi</h1></div>;\n}\n'
LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'


class _Project:
    def __init__(self, output_dir):
        self.output_dir = str(output_dir)
        self.id = uuid.uuid4()


@pytest.fixture()
def project(monkeypatch, tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/", "purpose": "x"}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": LOAD, "view": VIEW}]
    svc.save()
    (tmp_path / "app/src/app/_root").mkdir(parents=True)
    (tmp_path / "app/package.json").write_text("{}")
    proj = _Project(tmp_path)

    async def _fake_get_project(project_id, user, db):
        return proj
    monkeypatch.setattr(router, "get_project_with_auth", _fake_get_project)
    monkeypatch.setattr("services.react_editor.service._check", lambda *a: [])
    return proj


@pytest.mark.asyncio
async def test_open_apply_and_a_stale_apply_as_the_client_sees_them(project):
    pages = await router.list_pages(project.id, user=None, db=None)
    assert pages["entryPage"] == "PAGE-001"
    doc = await router.open_page(project.id, "PAGE-001", user=None, db=None)
    assert doc["coded"] and doc["model"]["nodes"]["r0.0"]["text"] == "Hi"

    out = await router.apply_transaction(project.id, "PAGE-001",
                                         router.ApplyRequest(baseRevision=doc["revision"], ops=[{"op": "setText", "id": "r0.0", "text": "Hello"}]),
                                         user=None, db=None)
    assert out["revision"] != doc["revision"] and out["model"]["nodes"]["r0.0"]["text"] == "Hello"

    with pytest.raises(HTTPException) as e:
        await router.apply_transaction(project.id, "PAGE-001",
                                       router.ApplyRequest(baseRevision=doc["revision"], ops=[{"op": "setText", "id": "r0.0", "text": "Late"}]),
                                       user=None, db=None)
    assert e.value.status_code == 409
    assert e.value.detail["code"] == "stale" and e.value.detail["current"] == out["revision"]
    assert "Reload" in e.value.detail["message"]

    hist = await router.page_history(project.id, "PAGE-001", user=None, db=None)
    assert [h["kind"] for h in hist["history"]] == ["baseline", "edit"]


@pytest.mark.asyncio
async def test_an_unknown_page_is_a_404_in_plain_words(project):
    with pytest.raises(HTTPException) as e:
        await router.open_page(project.id, "PAGE-999", user=None, db=None)
    assert e.value.status_code == 404 and e.value.detail["code"] == "no-page"
