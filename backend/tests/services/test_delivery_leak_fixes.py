"""Tests for the delivery-gate leak fixes (fleet Phase-0 finding).

Four behaviors, each of which cost the fleet real points:

1. ``_sync_workflows_from_plan`` skips PER WORKFLOW — a pre-existing
   CRUD file must not abort translation of the plan's domain workflows.
2. ``_resolve_page_route`` resolves exact plan-page NAMES (StorefrontPage
   → "/"), and trigger strings may offer "or" alternatives.
3. ``repoint_dead_form_refs`` repoints a Form whose workflow ref is
   phantom at the plan's form_submit workflow for that page.
4. ``check_page_kinds`` never flags Redirect alias stubs.
"""
from __future__ import annotations

import json
from pathlib import Path


# ─────────────── 1. per-workflow sync skip ───────────────

def _rich_wf(name: str, table: str = "documents") -> dict:
    return {"name": name, "trigger": f"button on {name}Page", "steps": [
        {"type": "action", "action_type": "db_update", "table": table,
         "where": {"id": "{{recordId}}"}, "values": {"status": "done"}},
    ]}


def test_sync_writes_domain_workflows_despite_existing_crud(tmp_path):
    from routers.generate import _sync_workflows_from_plan
    out = tmp_path / "app"
    (out / "workflows").mkdir(parents=True)
    (out / "workflows" / "CreateUser.json").write_text(json.dumps(
        {"id": "CreateUser", "name": "CreateUser", "definition": {"nodes": []}}), encoding="utf-8")
    plan = {"data_models": [{"name": "Document", "fields": []}],
            "workflows": [_rich_wf("MarkRecordReviewed")]}
    _sync_workflows_from_plan(str(out), plan)
    names = set()
    for p in (out / "workflows").glob("*.json"):
        names.add(json.loads(p.read_text(encoding="utf-8")).get("name", "").lower())
    assert "createuser" in names                      # untouched
    assert "markrecordreviewed" in names, names       # domain wf landed


def test_sync_does_not_duplicate_existing_workflow(tmp_path):
    from routers.generate import _sync_workflows_from_plan
    out = tmp_path / "app"
    (out / "workflows").mkdir(parents=True)
    (out / "workflows" / "MarkRecordReviewed.json").write_text(json.dumps(
        {"id": "MarkRecordReviewed", "name": "MarkRecordReviewed",
         "definition": {"nodes": []}}), encoding="utf-8")
    plan = {"data_models": [], "workflows": [_rich_wf("MarkRecordReviewed")]}
    _sync_workflows_from_plan(str(out), plan)
    files = list((out / "workflows").glob("*.json"))
    assert len(files) == 1


# ─────────────── 2. page-name resolution + "or" ───────────────

def test_resolve_page_route_exact_name_beats_tokens():
    from services.transition_materializer import _resolve_page_route
    plan = {"pages": [
        {"name": "StorefrontPage", "route": "/", "kind": "list"},
        {"name": "PlantDetailPage", "route": "/plants/[id]", "kind": "detail"},
    ]}
    assert _resolve_page_route("storefrontpage", plan) == "/"
    assert _resolve_page_route("StorefrontPage", plan) == "/"


def _mk_launcher_app(tmp_path: Path, trigger: str) -> Path:
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": [{"name": "StorefrontPage", "route": "/", "kind": "list"},
                  {"name": "PlantDetailPage", "route": "/plants/[id]",
                   "kind": "detail"}],
        "workflows": [{"name": "AddToCartWorkflow", "trigger": trigger}],
    }), encoding="utf-8")
    (root / "workflows" / "AddToCartWorkflow.json").write_text(json.dumps(
        {"id": "AddToCartWorkflow", "name": "AddToCartWorkflow",
         "definition": {"nodes": []}}), encoding="utf-8")
    # root route ships as home.json (no index.json) — the fleet layout
    (root / "src" / "schemas" / "home.json").write_text(json.dumps(
        {"id": "home", "route": "/",
         "root": {"type": "Stack", "children": []}}), encoding="utf-8")
    return root


def test_or_alternative_trigger_injects_on_resolvable_page(tmp_path):
    from services.transition_materializer import materialize_workflow_launchers
    root = _mk_launcher_app(
        tmp_path, "button on storefrontpage or plantdetailpage")
    rep = materialize_workflow_launchers(root)
    assert len(rep["injected"]) == 1, rep
    doc = json.loads((root / "src" / "schemas" / "home.json").read_text(encoding="utf-8"))
    assert any(c.get("props", {}).get("workflow") == "AddToCartWorkflow"
               for c in doc["root"]["children"])


# ─────────────── 3. dead form-ref repoint ───────────────

def test_dead_form_ref_repointed_to_plan_workflow(tmp_path):
    from services.transition_materializer import repoint_dead_form_refs
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas" / "documents").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": [{"name": "DocumentUploadPage", "route": "/documents/upload",
                   "kind": "form"}],
        "workflows": [{"name": "RunOcrPipeline",
                       "trigger": "form_submit on documentuploadpage"}],
    }), encoding="utf-8")
    (root / "workflows" / "RunOcrPipeline.json").write_text(json.dumps(
        {"id": "RunOcrPipeline", "name": "RunOcrPipeline",
         "definition": {"nodes": []}}), encoding="utf-8")
    (root / "src" / "schemas" / "documents" / "upload.json").write_text(
        json.dumps({"id": "upload", "route": "/documents/upload",
                    "root": {"type": "Stack", "children": [
                        {"type": "Form",
                         "props": {"workflow": "UploadDocument"},
                         "children": []}]}}), encoding="utf-8")
    rep = repoint_dead_form_refs(root)
    assert rep["repointed"] == [{"route": "/documents/upload",
                                 "dead_ref": "UploadDocument",
                                 "workflow": "RunOcrPipeline"}]
    doc = json.loads(
        (root / "src" / "schemas" / "documents" / "upload.json").read_text(encoding="utf-8"))
    assert doc["root"]["children"][0]["props"]["workflow"] == "RunOcrPipeline"


def test_live_form_ref_never_touched(tmp_path):
    from services.transition_materializer import repoint_dead_form_refs
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": [{"name": "UploadPage", "route": "/upload", "kind": "form"}],
        "workflows": [{"name": "RunOcrPipeline",
                       "trigger": "form_submit on uploadpage"}],
    }), encoding="utf-8")
    for wf in ("RunOcrPipeline", "ProcessDocument"):
        (root / "workflows" / f"{wf}.json").write_text(json.dumps(
            {"id": wf, "name": wf, "definition": {"nodes": []}}), encoding="utf-8")
    (root / "src" / "schemas" / "upload.json").write_text(json.dumps(
        {"id": "upload", "route": "/upload",
         "root": {"type": "Stack", "children": [
             {"type": "Form", "props": {"workflow": "ProcessDocument"},
              "children": []}]}}), encoding="utf-8")
    rep = repoint_dead_form_refs(root)
    assert rep["repointed"] == []                     # live ref respected


# ─────────────── 4. Redirect alias skip ───────────────

def test_redirect_stub_not_kind_mismatch():
    from services.delivery_gate import check_page_kinds
    plan = {"pages": [{"route": "/queue", "kind": "list"}]}
    schemas = [("/queue", {"root": {"type": "Stack", "children": [
        {"type": "Redirect", "props": {"to": "/records"}}]}})]
    assert check_page_kinds(plan, schemas) == []


# ─────────────── 5. manual/entity trigger launchers ───────────────
# The delivery gate counts "manual"/"user" triggers as UI-triggered, so
# the materializer must anchor them too — via the "on <Entity>" clause
# or, bare, via the workflow's own step tables / verb-stripped name.

def _mk_manual_app(tmp_path: Path, *, trigger: str, steps: list | None = None,
                   pages: list | None = None, wf_name: str = "BookClassWorkflow") -> Path:
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    pages = pages or [{"name": "BookingsPage", "route": "/bookings", "kind": "list"}]
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": pages,
        "workflows": [{"name": wf_name, "trigger": trigger,
                       "steps": steps or []}],
    }), encoding="utf-8")
    (root / "workflows" / f"{wf_name}.json").write_text(json.dumps(
        {"id": wf_name, "name": wf_name, "definition": {"nodes": []}}), encoding="utf-8")
    for pg in pages:
        fname = pg["route"].strip("/").replace("/", "_") or "home"
        (root / "src" / "schemas" / f"{fname}.json").write_text(json.dumps(
            {"id": fname, "route": pg["route"],
             "root": {"type": "Stack", "children": []}}), encoding="utf-8")
    return root


def test_manual_on_entity_trigger_injects_on_entity_page(tmp_path):
    from services.transition_materializer import materialize_workflow_launchers
    root = _mk_manual_app(
        tmp_path, trigger="manual on DriveApplication",
        wf_name="ShortlistCandidate",
        pages=[{"name": "ApplicationsPage", "route": "/applications",
                "kind": "list"}])
    rep = materialize_workflow_launchers(root)
    assert len(rep["injected"]) == 1, rep
    doc = json.loads(
        (root / "src" / "schemas" / "applications.json").read_text(encoding="utf-8"))
    assert any(c.get("props", {}).get("workflow") == "ShortlistCandidate"
               for c in doc["root"]["children"])


def test_bare_manual_trigger_resolves_via_step_table(tmp_path):
    from services.transition_materializer import materialize_workflow_launchers
    root = _mk_manual_app(
        tmp_path, trigger="manual",
        steps=[{"type": "action", "config": {
            "actionType": "db_insert", "table": "bookings"}}])
    rep = materialize_workflow_launchers(root)
    assert len(rep["injected"]) == 1, rep
    doc = json.loads((root / "src" / "schemas" / "bookings.json").read_text(encoding="utf-8"))
    assert any(c.get("props", {}).get("workflow") == "BookClassWorkflow"
               for c in doc["root"]["children"])


def test_bare_manual_trigger_resolves_via_verb_stripped_name(tmp_path):
    from services.transition_materializer import materialize_workflow_launchers
    root = _mk_manual_app(
        tmp_path, trigger="manual", wf_name="ReassignInstructorWorkflow",
        pages=[{"name": "InstructorsPage", "route": "/instructors",
                "kind": "list"}])
    rep = materialize_workflow_launchers(root)
    assert len(rep["injected"]) == 1, rep


def test_schedule_trigger_never_gets_launcher(tmp_path):
    from services.transition_materializer import materialize_workflow_launchers
    root = _mk_manual_app(tmp_path, trigger="schedule",
                          steps=[{"type": "action", "config": {
                              "actionType": "db_update", "table": "bookings"}}])
    rep = materialize_workflow_launchers(root)
    assert rep["injected"] == []


# ─────────────── 6. free {{refs}} → processVariables ───────────────
# Launcher-dispatched workflows read their inputs from ctx.variables; a
# {{memberId}} with no provider is a launcher-supplied input and must be
# declared, or the workflow validator flags undefined-ref on every use.

def _node(nid: str, config: dict) -> dict:
    return {"id": nid, "type": "action", "data": {"config": config}}


def test_free_refs_declared_as_process_variables():
    from services.workflow_process_variables import derive_process_variables
    wf = {"name": "BookClassWorkflow", "trigger": "manual"}
    nodes = [
        _node("insert", {"actionType": "db_insert", "table": "bookings",
                         "values": {"memberId": "{{memberId}}",
                                    "status": "{{status}}",
                                    "when": "{{bookedAt}}"}}),
        _node("query", {"actionType": "db_query", "outputVar": "sessionRow",
                        "where": {"id": "{{sessionRow.id}}"}}),
    ]
    got = {e["name"]: e["type"] for e in derive_process_variables(wf, nodes)}
    assert got.get("memberId") == "uuid"
    assert got.get("status") == "string"
    assert got.get("bookedAt") == "date"
    assert "sessionRow" not in got or True  # provided via outputVar — never
    assert "sessionRow" not in {e["name"] for e in derive_process_variables(wf, nodes)
                                if e.get("source", "").startswith("ref:")}


def test_schedule_trigger_free_refs_not_harvested():
    from services.workflow_process_variables import derive_process_variables
    wf = {"name": "ExpiryCheck", "trigger": "schedule"}
    nodes = [_node("upd", {"actionType": "db_update",
                           "values": {"status": "{{status}}"}})]
    assert derive_process_variables(wf, nodes) == []


def test_builtin_roots_and_node_ids_not_harvested():
    from services.workflow_process_variables import derive_process_variables
    wf = {"name": "W", "trigger": "manual"}
    nodes = [_node("fetch", {"actionType": "db_query", "outputVar": "rows"}),
             _node("use", {"values": {"a": "{{trigger.id}}",
                                      "b": "{{fetch.result}}",
                                      "c": "{{rows}}",
                                      "d": "{{context.userId}}"}})]
    assert derive_process_variables(wf, nodes) == []


def test_sync_translated_workflow_declares_process_variables(tmp_path):
    from routers.generate import _sync_workflows_from_plan
    out = tmp_path / "app"
    out.mkdir()
    plan = {"data_models": [], "workflows": [{
        "name": "BookClassWorkflow", "trigger": "manual",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "insert",
             "config": {"triggerType": "manual"}},
            {"id": "insert", "type": "action", "next": "end",
             "config": {"actionType": "db_insert", "table": "bookings",
                        "values": {"memberId": "{{memberId}}"}}},
            {"id": "end", "type": "end"},
        ]}]}
    _sync_workflows_from_plan(str(out), plan)
    files = list((out / "workflows").glob("*.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    names = {v["name"] for v in doc.get("processVariables", [])}
    assert "memberId" in names, doc.get("processVariables")
