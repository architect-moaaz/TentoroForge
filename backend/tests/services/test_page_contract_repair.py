"""Tests for the page-contract leak fixes:

1. page_contract_repair — deterministic required-prop backfills.
2. dashboard_page_composer — composed pages carry the authored
   dataSources (the 30-point Chart binding leak).
3. alias_unknown_components — TimelineList → Timeline.
"""
from __future__ import annotations

import json
from pathlib import Path


def _mk_app(tmp_path: Path, schemas: dict[str, dict],
            plan: dict | None = None) -> Path:
    root = tmp_path / "app"
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    if plan is not None:
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    for name, doc in schemas.items():
        (root / "src" / "schemas" / name).write_text(json.dumps(doc))
    return root


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "src" / "schemas" / name).read_text())


# ─────────────── required-prop backfills ───────────────

def test_hero_headline_and_layout_backfilled(tmp_path):
    from services.page_contract_repair import repair_required_props
    root = _mk_app(tmp_path, {"index.json": {
        "id": "HomePage", "route": "/",
        "root": {"type": "Stack", "children": [
            {"type": "Hero", "props": {"subheadline": "Welcome aboard"}}]}}})
    rep = repair_required_props(root)
    assert rep["repaired"], rep
    hero = _read(root, "index.json")["root"]["children"][0]
    assert hero["props"]["headline"] == "Home"
    assert hero["props"]["layout"] == "centered"


def test_hero_invalid_layout_normalized_but_headline_kept(tmp_path):
    from services.page_contract_repair import repair_required_props
    root = _mk_app(tmp_path, {"index.json": {
        "id": "Home", "route": "/",
        "root": {"type": "Hero",
                 "props": {"headline": "Real Headline", "layout": "hero-full"}}}})
    repair_required_props(root)
    hero = _read(root, "index.json")["root"]
    assert hero["props"]["headline"] == "Real Headline"   # never overwritten
    assert hero["props"]["layout"] == "centered"          # normalized


def test_empty_state_message_backfilled_from_title(tmp_path):
    from services.page_contract_repair import repair_required_props
    root = _mk_app(tmp_path, {"cal.json": {
        "id": "Calendar", "route": "/calendar",
        "root": {"type": "EmptyState", "props": {"title": "No interviews"}}}})
    repair_required_props(root)
    assert _read(root, "cal.json")["root"]["props"]["message"] == "No interviews"


def test_select_options_backfilled_from_plan_enum(tmp_path):
    from services.page_contract_repair import repair_required_props
    plan = {"data_models": [{"name": "Interview", "fields": [
        {"name": "status", "type": "varchar",
         "enum_values": ["scheduled", "completed"]}]}]}
    root = _mk_app(tmp_path, {"iv.json": {
        "id": "Interview", "route": "/interview",
        "root": {"type": "Select",
                 "props": {"label": "Status", "name": "status"}}}}, plan=plan)
    repair_required_props(root)
    opts = _read(root, "iv.json")["root"]["props"]["options"]
    assert {o["value"] for o in opts} == {"scheduled", "completed"}


def test_select_without_plan_enum_gets_empty_options(tmp_path):
    from services.page_contract_repair import repair_required_props
    root = _mk_app(tmp_path, {"f.json": {
        "id": "F", "route": "/f",
        "root": {"type": "Select",
                 "props": {"label": "Owner", "name": "ownerId"}}}})
    repair_required_props(root)
    assert _read(root, "f.json")["root"]["props"]["options"] == []


def test_repair_is_idempotent(tmp_path):
    from services.page_contract_repair import repair_required_props
    root = _mk_app(tmp_path, {"index.json": {
        "id": "Home", "route": "/",
        "root": {"type": "Hero", "props": {}}}})
    assert repair_required_props(root)["repaired"]
    assert repair_required_props(root)["repaired"] == []  # second run no-op


# ─────────────── composed page carries dataSources ───────────────

def test_composed_sub_dashboard_page_has_data_sources():
    from services.dashboard_page_composer import _compose_one
    page = {
        "name": "AnalyticsPage", "route": "/analytics", "type": "dashboard",
        "metrics": [{"label": "Total", "entity": "Document", "calc": "count"}],
        "widgets": [{"type": "chart", "entity": "Document",
                     "title": "By Status", "groupBy": "status"}],
    }
    entities = {"Document": {"fields": [{"name": "status"}, {"name": "id"}]}}
    out = _compose_one(page, entities, {"Chart", "Table", "Stat", "Card",
                                        "Heading", "Grid", "Stack"})
    names = {d["name"] for d in out["dataSources"]}
    assert len(names) == 2
    blob = json.dumps(out["root"])
    # Every binding the nodes reference is declared on the page.
    for n in names:
        assert f"{{{{{n}}}}}" in blob
    # The chart is contract-complete.
    assert '"chartType"' in blob and '"series"' in blob and '"xKey"' in blob


# ─────────────── TimelineList alias ───────────────

def test_timeline_list_aliases_to_timeline():
    from services.alias_unknown_components import _ALIASES
    assert _ALIASES.get("TimelineList") == "Timeline"


# ─────────── unknown-node drop + GlobalSearch backfill ───────────

def test_unregistered_node_dropped(tmp_path, monkeypatch):
    import services.page_contract_repair as m
    monkeypatch.setattr(m, "_registered_component_names",
                        lambda: {"Stack", "Table", "Card"})
    root = _mk_app(tmp_path, {"list.json": {
        "id": "L", "route": "/l",
        "root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"columns": [], "rows": "{{r}}"}},
            {"type": "Pagination", "props": {"page": 1}}]}}})
    rep = m.repair_required_props(root)
    assert "dropped:Pagination" in rep["repaired"][0]["props"]
    kids = _read(root, "list.json")["root"]["children"]
    assert [c["type"] for c in kids] == ["Table"]


def test_global_search_workflow_backfilled_from_disk(tmp_path):
    from services.page_contract_repair import repair_required_props
    root = _mk_app(tmp_path, {"s.json": {
        "id": "S", "route": "/search",
        "root": {"type": "GlobalSearch", "props": {}}}})
    (root / "workflows").mkdir()
    (root / "workflows" / "sw.json").write_text(json.dumps(
        {"id": "sw", "name": "SearchRecordsWorkflow",
         "definition": {"nodes": []}}))
    repair_required_props(root)
    assert _read(root, "s.json")["root"]["props"]["workflow"] == \
        "SearchRecordsWorkflow"
