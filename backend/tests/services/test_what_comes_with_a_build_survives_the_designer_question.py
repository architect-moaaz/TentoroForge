"""What a person sends with "build" is kept when the build stops to ask who designs the screens.

Review of 5ab23bf2: `_run_dag` returned at `ui_designer.gate` BEFORE it merged the request's description into
the brief and BEFORE it stored the attached documents. The answer starts the build again with neither, so a
brief or a file sent with "build" was lost for good."""
from __future__ import annotations

import pytest

from routers import blueprint_generate as router
from services.blueprint import documents
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_UI_DESIGNER", raising=False)
    s = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "A shopper sees products.", "status": "VERIFIED"}]
    s.validate()
    s.save()
    return s


def _stopped(tmp_path, description, docs):
    return router._run_dag(str(tmp_path), str(tmp_path / "app"), description, approved=True,
                           emit=lambda *a: None, documents=docs)


def test_the_brief_and_the_documents_are_kept_when_the_build_stops(svc, tmp_path):
    out = _stopped(tmp_path, "Shoppers pay by card.", ["The price list: tea 3, coffee 4."])
    assert out["status"] == "asked"
    kept = BlueprintService.load(output_dir=tmp_path).doc["application"]["description"]
    assert "Shoppers pay by card." in kept
    assert documents.texts(tmp_path) == ["The price list: tea 3, coffee 4."]


def test_sending_it_again_after_the_answer_keeps_one_copy(svc, tmp_path):
    _stopped(tmp_path, "Shoppers pay by card.", ["The price list: tea 3, coffee 4."])
    _stopped(tmp_path, "Shoppers pay by card.", ["The price list: tea 3, coffee 4."])
    kept = BlueprintService.load(output_dir=tmp_path).doc["application"]["description"]
    assert kept.count("Shoppers pay by card.") == 1
    assert len(documents.texts(tmp_path)) == 1


def test_a_build_with_nothing_attached_changes_nothing(svc, tmp_path):
    before = BlueprintService.load(output_dir=tmp_path).doc["application"].get("description")
    _stopped(tmp_path, "", [])
    assert BlueprintService.load(output_dir=tmp_path).doc["application"].get("description") == before
    assert documents.texts(tmp_path) == []
