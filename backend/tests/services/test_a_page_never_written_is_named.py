"""F&B (forge-v3, 2026-10-01): "Incoming Orders page is not done" — its page
step had failed, a review scoped to it had nothing to open, and Smith's whole
reply was the review's internal "no coded pages"."""
from __future__ import annotations

import json

from services.blueprint.page_review import unbuilt_pages
from services.blueprint.service import BlueprintService


def _svc(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="F&B", domain="Food")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Categories", "route": "/admin/categories"},
                        {"id": "PAGE-007", "name": "Incoming Orders", "route": "/admin/orders"},
                        {"id": "PAGE-009", "name": "Old", "route": "/old", "status": "DEPRECATED"}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": "", "view": "\"use client\";"}]
    svc.save()
    return svc


def test_a_page_with_no_code_is_found(tmp_path):
    svc = _svc(tmp_path)
    assert [p["id"] for p in unbuilt_pages(svc.doc)] == ["PAGE-007"]
    assert unbuilt_pages({"pages": svc.doc["pages"]}) == []   # an app not written as code has no "unbuilt" page


def test_verifying_a_page_never_written_says_to_write_it(tmp_path, monkeypatch):
    from services.smith import writes
    _svc(tmp_path)
    monkeypatch.setattr("services.blueprint.orchestrator.review_coded_pages",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nothing to review")))
    out = writes.verify_pages(str(tmp_path), routes=["/admin/orders"])
    assert not out["applied"] and "Incoming Orders (/admin/orders) has no code yet" in out["finding"]
    assert "compose_route" in out["finding"] and "no coded pages" not in out["said"]


def test_a_whole_review_names_what_it_could_not_open(tmp_path, monkeypatch):
    from services.smith import writes
    _svc(tmp_path)
    monkeypatch.setattr("services.blueprint.orchestrator.review_coded_pages",
                        lambda svc, root, only=None, **k: {"pages": {"PAGE-001": {"passed": True, "scores": [8]}}})
    out = writes.verify_pages(str(tmp_path), routes=[])
    assert "Never written, so not opened: Incoming Orders (/admin/orders)" in out["said"]
