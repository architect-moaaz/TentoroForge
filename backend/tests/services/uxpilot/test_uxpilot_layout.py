"""A page designed in UX Pilot is built from its design's HTML through the
same layout seam a Figma frame uses."""
from __future__ import annotations

import pytest

from services.blueprint import figma_layout
from services.blueprint.service import BlueprintService
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget


@pytest.fixture()
def svc(tmp_path):
    return BlueprintService.create(output_dir=tmp_path, app_id="a", name="Shop", domain="Retail")


def _uxpilot_ref():
    ref = DesignReference(target=FigmaTarget(file_key="pg_42", kind="uxpilot"),
                          source_id="UXPILOT-001", provider="uxpilot")
    ref.screens = [ScreenRef(
        node_id="d1", name="Orders", canvas="Shop admin",
        structure={"source": "uxpilot_html",
                   "html": '<div style="display:flex;flex-direction:column"><h1>Orders</h1><p>All orders</p></div>',
                   "labels": ["Orders", "All orders"], "assets": []},
    )]
    return ref


def test_a_uxpilot_page_composes_from_its_html(svc, tmp_path, monkeypatch):
    store.connect(svc, _uxpilot_ref())
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Orders", "route": "/orders", "purpose": "x", "figmaFrame": "d1"}]
    out = figma_layout.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app")
    assert out is not None and out["provider"] == "uxpilot"
    root = out["root"]
    assert root["type"] == "Stack"
    types = []

    def walk(n):
        types.append(n.get("type"))
        for c in n.get("children") or []:
            walk(c)

    walk(root)
    assert "Heading" in types and "Text" in types


def test_a_page_with_no_stored_design_falls_through(svc, tmp_path):
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Orders", "route": "/orders", "purpose": "x", "figmaFrame": "d9"}]
    assert figma_layout.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app") is None
