"""Tests for services.page_anatomy — per-kind UX floor (item 5)."""
from __future__ import annotations

import json
from pathlib import Path

from services.page_anatomy import apply_page_anatomy


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(tmp_path: Path, *, schemas: dict[str, dict],
            routes: list[str], tables: list[str] = ("documents",)) -> Path:
    root = tmp_path / "app"
    lines = [f'export const {t} = pgTable("{t}", {{ id: uuid("id").primaryKey() }});'
             for t in tables]
    _write(root, "src/db/schema/entities.ts", "\n".join(lines))
    reg = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts",
           "export const schemas = {\n" + reg + "\n};\n")
    _write(root, "src/contracts/plan.json", "{}")
    for rel, doc in schemas.items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    return root


def _read(root: Path, rel: str) -> dict:
    return json.loads((root / "src/schemas" / rel).read_text(encoding="utf-8"))


def _detail(children: list | None = None) -> dict:
    return {"dataSources": [{"name": "doc", "entity": "Document", "op": "get"}],
            "root": {"type": "Stack", "children": children or [
                {"type": "Heading", "props": {"text": "Doc"}}]}}


def _list(children: list | None = None) -> dict:
    base = [{"type": "Table", "props": {"rows": "{{documents}}", "columns": []}}]
    return {"dataSources": [{"name": "documents", "entity": "Document", "op": "list"}],
            "root": {"type": "Stack", "children": (children or []) + base}}


# ── detail back affordance ───────────────────────────────────────────

def test_detail_without_back_gets_one(tmp_path: Path):
    root = _mk_app(tmp_path, routes=["/documents", "/documents/[id]"],
                   schemas={"documents/[id].json": _detail()})
    rep = apply_page_anatomy(root)
    inj = [f for f in rep["findings"] if f["slot"] == "detail_back"]
    assert inj and inj[0]["action"] == "injected"
    kids = _read(root, "documents/[id].json")["root"]["children"]
    assert kids[0]["type"] == "Button"
    assert kids[0]["props"]["label"] == "Back"
    assert kids[0]["props"]["onClick"]["target"] == "/documents"


def test_detail_with_back_untouched(tmp_path: Path):
    doc = _detail([{"type": "Button", "props": {
        "label": "Back", "onClick": {"action": "navigate", "target": "/documents"}}}])
    root = _mk_app(tmp_path, routes=["/documents", "/documents/[id]"],
                   schemas={"documents/[id].json": doc})
    rep = apply_page_anatomy(root)
    assert not any(f["slot"] == "detail_back" and f["action"] == "injected"
                   for f in rep["findings"])


def test_detail_back_skipped_when_parent_unregistered(tmp_path: Path):
    """Never inject a button to a 404 — report instead."""
    root = _mk_app(tmp_path, routes=["/documents/[id]"],
                   schemas={"documents/[id].json": _detail()})
    rep = apply_page_anatomy(root)
    f = next(f for f in rep["findings"] if f["slot"] == "detail_back")
    assert f["action"] == "reported"


def test_detail_no_primary_action_reported_only(tmp_path: Path):
    root = _mk_app(tmp_path, routes=["/documents", "/documents/[id]"],
                   schemas={"documents/[id].json": _detail()})
    rep = apply_page_anatomy(root)
    f = next(f for f in rep["findings"] if f["slot"] == "detail_primary_action")
    assert f["action"] == "reported"
    assert f["severity"] == "info"


def test_detail_with_domain_action_not_flagged(tmp_path: Path):
    doc = _detail([{"type": "Button", "props": {"label": "Reprocess",
                                                "workflow": "ReprocessDocument"}}])
    root = _mk_app(tmp_path, routes=["/documents", "/documents/[id]"],
                   schemas={"documents/[id].json": doc})
    rep = apply_page_anatomy(root)
    assert not any(f["slot"] == "detail_primary_action" for f in rep["findings"])


# ── list create affordance ───────────────────────────────────────────

def test_list_missing_create_button_injected(tmp_path: Path):
    root = _mk_app(tmp_path, routes=["/documents", "/documents/new"],
                   schemas={"documents.json": _list()})
    rep = apply_page_anatomy(root)
    f = next(f for f in rep["findings"] if f["slot"] == "list_create")
    assert f["action"] == "injected"
    kids = _read(root, "documents.json")["root"]["children"]
    assert kids[0]["type"] == "Button"
    assert kids[0]["props"]["label"] == "New Document"
    assert kids[0]["props"]["onClick"]["target"] == "/documents/new"


def test_list_upload_route_gets_upload_label(tmp_path: Path):
    root = _mk_app(tmp_path, routes=["/documents", "/documents/upload"],
                   schemas={"documents.json": _list()})
    apply_page_anatomy(root)
    kids = _read(root, "documents.json")["root"]["children"]
    assert kids[0]["props"]["label"] == "Upload"


def test_list_with_existing_affordance_untouched(tmp_path: Path):
    page = _list([{"type": "Button", "props": {
        "label": "Add", "onClick": {"action": "navigate",
                                    "target": "/documents/new"}}}])
    root = _mk_app(tmp_path, routes=["/documents", "/documents/new"],
                   schemas={"documents.json": page})
    rep = apply_page_anatomy(root)
    assert not any(f["slot"] == "list_create" for f in rep["findings"])


def test_list_without_create_route_no_injection(tmp_path: Path):
    """No create route on disk → nothing to link (ensure_create_routes'
    territory), never inject a dead button."""
    root = _mk_app(tmp_path, routes=["/documents"],
                   schemas={"documents.json": _list()})
    rep = apply_page_anatomy(root)
    assert not any(f["slot"] == "list_create" for f in rep["findings"])


# ── search states ────────────────────────────────────────────────────

def test_search_results_get_no_match_text(tmp_path: Path):
    page = {"dataSources": [{"name": "documents", "entity": "Document", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "SearchInput", "props": {}},
                {"type": "Table", "props": {"rows": "{{documents}}", "columns": []}}]}}
    root = _mk_app(tmp_path, routes=["/documents/search"],
                   schemas={"documents/search.json": page})
    rep = apply_page_anatomy(root)
    f = next(f for f in rep["findings"] if f["slot"] == "search_no_match")
    assert f["action"] == "injected"
    table = _read(root, "documents/search.json")["root"]["children"][1]
    assert table["props"]["emptyText"] == "No results match your search."


def test_search_authored_empty_text_respected(tmp_path: Path):
    page = {"dataSources": [{"name": "documents", "entity": "Document", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "SearchInput", "props": {}},
                {"type": "Table", "props": {"rows": "{{documents}}", "columns": [],
                                            "emptyText": "Nothing found."}}]}}
    root = _mk_app(tmp_path, routes=["/documents/search"],
                   schemas={"documents/search.json": page})
    rep = apply_page_anatomy(root)
    assert not any(f["slot"] == "search_no_match" for f in rep["findings"])


# ── idempotency + report ─────────────────────────────────────────────

def test_rerun_idempotent(tmp_path: Path):
    root = _mk_app(tmp_path, routes=["/documents", "/documents/[id]",
                                     "/documents/new"],
                   schemas={"documents/[id].json": _detail(),
                            "documents.json": _list()})
    apply_page_anatomy(root)
    rep2 = apply_page_anatomy(root)
    assert rep2["summary"]["injected"] == 0
    kids = _read(root, "documents/[id].json")["root"]["children"]
    assert sum(1 for k in kids if k.get("type") == "Button") == 1


def test_report_written(tmp_path: Path):
    root = _mk_app(tmp_path, routes=["/documents", "/documents/[id]"],
                   schemas={"documents/[id].json": _detail()})
    apply_page_anatomy(root)
    rep = json.loads((root / "contracts" / "page-anatomy.json").read_text(encoding="utf-8"))
    assert rep["summary"]["injected"] >= 1


def test_empty_app_no_crash(tmp_path: Path):
    assert apply_page_anatomy(tmp_path / "nope")["findings"] == []
