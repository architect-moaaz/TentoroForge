"""Tests for the BarcodeSearchWorkflow archetype emitter + plan ensures +
barcode page wiring (LensShop back-port, 2026-08-19)."""
from __future__ import annotations

import json
import os

from services.archetype_workflows import find_emitter
from services.archetype_workflows.visual_product_search import (
    build_barcode_search_workflow,
)
from services.archetypes import (
    ensure_required_columns,
    ensure_required_workflows,
)
from services.archetype_page_fixes import add_barcode_capabilities


def test_barcode_aliases_route_to_emitter():
    for name in ("BarcodeSearchWorkflow", "Barcode Lookup Workflow",
                 "ScanBarcodeWorkflow", "barcode workflow"):
        assert find_emitter("visual-product-search", name) is build_barcode_search_workflow


def test_scan_product_alias_untouched():
    assert find_emitter("visual-product-search", "ScanProductWorkflow") \
        is not build_barcode_search_workflow


def _emit(tables=None, registry=None):
    return build_barcode_search_workflow(
        {"name": "BarcodeSearchWorkflow"}, {},
        tables or {"products", "scan_sessions", "price_results"}, registry)


def test_graph_integrity():
    d = _emit()["definition"]
    ids = {n["id"] for n in d["nodes"]}
    assert len(ids) == len(d["nodes"])
    for e in d["edges"]:
        assert e["source"] in ids and e["target"] in ids
    outs = {e["source"] for e in d["edges"]}
    for n in d["nodes"]:
        if n["id"] != "end":
            assert n["id"] in outs, f"dead end at {n['id']}"


def test_no_set_variable_indirection():
    # set_variable does NOT interpolate {{...}} in variableValue — the shared-
    # variable version of this workflow searched the literal template text.
    assert "set_variable" not in json.dumps(_emit())


def test_known_product_paths_rescrape_offers():
    s = json.dumps(_emit())
    assert s.count("firecrawl_scrape") == 9  # 3 offers x 3 paths
    assert "{{find_upc.rows[0].canonicalName}}" in s
    assert "{{find_ean.rows[0].canonicalName}}" in s


def test_business_rules_baked_in():
    s = json.dumps(_emit())
    assert '"confidenceScore": "1"' in s
    assert '"imageUrl"' in s and "image_url" in s
    assert '"scanSessionId": "{{create_session.inserted.id}}"' in s


def test_registry_column_resolution():
    registry = {"entities": {"Product": {
        "table": "products",
        "columns": [{"name": "title"}, {"name": "gtin"}, {"name": "photoUrl"}],
    }}}
    s = json.dumps(_emit(registry=registry))
    assert "{{find_upc.rows[0].title}}" in s
    assert '"gtin": "{{barcode}}"' in s


def _plan():
    return {
        "archetype": "visual-product-search",
        "workflows": [{"name": "ScanProductWorkflow"}],
        "data_models": [
            {"name": "Product", "fields": [{"name": "id", "type": "uuid"}]},
            {"name": "ScanSession", "fields": []},
        ],
    }


def test_ensure_required_workflows_injects_once():
    plan = _plan()
    assert ensure_required_workflows(plan) == 1
    assert ensure_required_workflows(plan) == 0
    assert "BarcodeSearchWorkflow" in [w["name"] for w in plan["workflows"]]


def test_ensure_required_workflows_fuzzy_satisfied():
    plan = _plan()
    plan["workflows"].append({"name": "Scan Barcode Workflow"})
    assert ensure_required_workflows(plan) == 0


def test_ensure_required_columns_fuzzy_field_match():
    plan = _plan()
    plan["data_models"][0]["fields"].append({"name": "image_url", "type": "string"})
    ensure_required_columns(plan)
    names = [f["name"] for f in plan["data_models"][0]["fields"]]
    assert "upc" in names and "ean" in names
    assert "imageUrl" not in names  # image_url already satisfies it


def test_add_barcode_capabilities_end_to_end(tmp_path):
    root = str(tmp_path)
    os.makedirs(f"{root}/contracts")
    os.makedirs(f"{root}/src/schemas/scans/[id]")
    os.makedirs(f"{root}/workflows")
    json.dump({"archetype": "visual-product-search"},
              open(f"{root}/contracts/plan.json", "w"))
    json.dump({"name": "BarcodeSearchWorkflow"},
              open(f"{root}/workflows/barcodesearchworkflow.json", "w"))
    json.dump({"root": {"type": "Stack", "children": []}},
              open(f"{root}/src/schemas/scan.json", "w"))
    json.dump({"root": {"type": "Stack", "children": [
        {"type": "Repeat", "props": {"source": "scanSessions"},
         "children": [{"type": "Container", "props": {}, "children": []}]}]}},
              open(f"{root}/src/schemas/history.json", "w"))
    json.dump({"props": {"dataSources": [
        {"name": "priceResults", "entity": "PriceResult", "op": "list"}]},
        "root": {"type": "Stack", "children": []}},
              open(f"{root}/src/schemas/scans/[id]/results.json", "w"))

    assert add_barcode_capabilities(root) == 3
    scan = json.dumps(json.load(open(f"{root}/src/schemas/scan.json")))
    assert "BarcodeScanner" in scan and '"autoSubmit": true' in scan
    assert '"navigate": "/history"' in scan
    res = json.load(open(f"{root}/src/schemas/scans/[id]/results.json"))
    assert res["props"]["dataSources"][0]["filter"] == {"scanSessionId": "$routeId"}
    assert add_barcode_capabilities(root) == 0  # idempotent


def test_add_barcode_capabilities_skips_other_archetypes(tmp_path):
    root = str(tmp_path)
    os.makedirs(f"{root}/contracts")
    os.makedirs(f"{root}/src/schemas")
    json.dump({"archetype": "booking-platform"},
              open(f"{root}/contracts/plan.json", "w"))
    assert add_barcode_capabilities(root) == 0


def test_scrape_lanes_tolerant_spine_strict():
    """One failed retailer scrape must not strand the whole run as pending:
    per-offer scrape/insert lanes carry continueOnError, while the spine
    (trigger/lookup/product-attach) stays strict so real faults still fail."""
    from services.archetype_workflows.visual_product_search import (
        build_scan_product_workflow,
        _STRICT_IDS,
    )

    def _by_id(defn):
        return {n["id"]: n for n in defn["nodes"]}

    for wf in (
        _emit()["definition"],
        build_scan_product_workflow(
            {"name": "ScanProductWorkflow"}, {},
            {"products", "scan_sessions", "price_results"}, None)["definition"],
    ):
        nodes = _by_id(wf)
        tolerant = [
            nid for nid, n in nodes.items()
            if ((n.get("data") or {}).get("config") or {}).get("continueOnError")
        ]
        assert tolerant, "no tolerant lanes marked"
        # every scrape/insert lane node is tolerant
        for nid, n in nodes.items():
            cfg = (n.get("data") or {}).get("config") or {}
            if not cfg.get("actionType"):
                continue
            if nid.startswith(("extract", "insert_price", "insert_pb", "x", "i")) \
                    and nid not in _STRICT_IDS:
                assert cfg.get("continueOnError") is True, f"{nid} not tolerant"
        # the spine stays strict
        for nid in _STRICT_IDS & set(nodes):
            cfg = (nodes[nid].get("data") or {}).get("config") or {}
            assert not cfg.get("continueOnError"), f"spine node {nid} tolerant"


def test_on_failure_marks_session_failed():
    """A mid-run throw must not strand the session in processing — both
    builders declare an engine-level onFailure that flips status to failed."""
    from services.archetype_workflows.visual_product_search import (
        build_scan_product_workflow,
    )
    scan = build_scan_product_workflow(
        {"name": "ScanProductWorkflow"}, {},
        {"products", "scan_sessions", "price_results"}, None)
    barcode = _emit()
    for wf, ref in ((scan, "{{scanSessionId}}"),
                    (barcode, "{{create_session.inserted.id}}")):
        of = wf["onFailure"]
        assert of["actionType"] == "db_update"
        assert of["table"] == "scan_sessions"
        assert of["where"] == {"id": ref}
        assert of["values"] == {"status": "failed"}


def test_results_page_emitter(tmp_path):
    """visual-product-search apps get the proven /scans/[id]/results grid."""
    from services.archetype_page_fixes import (
        ensure_results_page_for_visual_product_search,
    )
    out = tmp_path / "app"
    (out / "src" / "schemas" / "scans" / "[id]").mkdir(parents=True)
    (out / "workflows").mkdir()
    (out / "contracts").mkdir()
    (out / "contracts" / "plan.json").write_text(json.dumps(
        {"archetype": "visual-product-search"}), encoding="utf-8")
    (out / "registry.json").write_text(json.dumps({"entities": {
        "ScanSession": {"id": "scan_sessions", "table": "scan_sessions",
                        "name": "ScanSession"},
        "PriceResult": {"id": "price_results", "table": "price_results",
                        "name": "PriceResult"},
    }}), encoding="utf-8")
    (out / "workflows" / "DeleteScanSession.json").write_text(json.dumps(
        {"name": "DeleteScanSession", "definition": {"nodes": [], "edges": []}}), encoding="utf-8")

    assert ensure_results_page_for_visual_product_search(str(out)) == 1
    page = json.loads(
        (out / "src" / "schemas" / "scans" / "[id]" / "results.json").read_text(encoding="utf-8"))
    assert page["route"] == "/scans/[id]/results"
    s = json.dumps(page)
    # proven anatomy: session-filtered offers, card grid, store link, nav
    assert '"scanSessionId": "$routeId"' in s
    assert '"source": "priceResults"' in s
    assert "{{item.imageUrl}}" in s and "{{item.retailerName}}" in s
    assert "View at store" in s
    assert '"navigate": "/"' in s  # Scan Another → home
    # Discard wired to the delete workflow with the bound id
    assert '"workflow": "DeleteScanSession"' in s
    assert '"id": "{{scanSession.id}}"' in s

    # idempotent re-run rewrites our page; foreign results.json is untouched
    assert ensure_results_page_for_visual_product_search(str(out)) == 1
    (out / "src" / "schemas" / "scans" / "[id]" / "results.json").write_text(
        json.dumps({"id": "custom", "route": "/scans/[id]/results"}), encoding="utf-8")
    assert ensure_results_page_for_visual_product_search(str(out)) == 0
