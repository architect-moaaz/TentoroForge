"""Tests for services.transition_materializer — B1 transition-button
injection + B2 workflow-launcher injection.

Fixtures model the real 9y8de8i7 findings: declared-but-missing Back
button, ReprocessDocumentWorkflow with a button trigger but no launcher
(and, crucially, no on-disk definition → must NOT inject).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.delivery_gate import (
    check_transition_triggers,
    check_workflow_launchers,
    _load_page_schemas,
)
from services.transition_materializer import (
    _humanize,
    _resolve_page_route,
    materialize_transitions,
    materialize_workflow_launchers,
    run,
)


# ── fixture builder ──────────────────────────────────────────────────

def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(
    tmp_path: Path,
    *,
    plan: dict | None = None,
    nav_flow: dict | None = None,
    schemas: dict[str, dict] | None = None,   # rel-path → doc
    workflows: dict[str, dict] | None = None,  # filename → doc
) -> Path:
    root = tmp_path / "app"
    _write(root, "src/contracts/plan.json", json.dumps(plan or {}))
    _write(root, "src/contracts/nav-flow.json",
           json.dumps(nav_flow or {"pages": [], "transitions": []}))
    for rel, doc in (schemas or {}).items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    for fname, doc in (workflows or {}).items():
        _write(root, f"workflows/{fname}", json.dumps(doc))
    return root


def _read_schema(root: Path, rel: str) -> dict:
    return json.loads((root / "src/schemas" / rel).read_text())


def _page(children: list | None = None) -> dict:
    return {"root": {"type": "Stack", "children": children or []}}


# ── B1: transition buttons ───────────────────────────────────────────

NAV_BACK = {
    "pages": [
        {"id": "detail", "route": "/documents/[id]"},
        {"id": "docs", "route": "/documents"},
    ],
    "transitions": [
        {"id": "t1", "from": "detail", "to": "docs", "trigger": "button:Back"},
    ],
}


def test_injects_missing_back_button(tmp_path: Path):
    """The 9y8de8i7 case: nav-flow declares button:Back on the detail
    page, schema has no such button → inject it."""
    root = _mk_app(tmp_path, nav_flow=NAV_BACK,
                   schemas={"documents/[id].json": _page([{"type": "Heading", "props": {"text": "Doc"}}])})
    res = materialize_transitions(root)
    assert len(res["injected"]) == 1
    assert res["injected"][0]["label"] == "Back"
    doc = _read_schema(root, "documents/[id].json")
    kids = doc["root"]["children"]
    # back-ish label → prepended
    assert kids[0]["type"] == "Button"
    assert kids[0]["props"]["label"] == "Back"
    assert kids[0]["props"]["onClick"] == {"action": "navigate", "target": "/documents"}


def test_injection_satisfies_delivery_gate(tmp_path: Path):
    """The whole point: after the repair, the gate error clears."""
    root = _mk_app(tmp_path, nav_flow=NAV_BACK,
                   schemas={"documents/[id].json": _page()})
    nav = json.loads((root / "src/contracts/nav-flow.json").read_text())
    assert check_transition_triggers(nav, _load_page_schemas(root)) != []
    materialize_transitions(root)
    assert check_transition_triggers(nav, _load_page_schemas(root)) == []


def test_existing_button_not_duplicated(tmp_path: Path):
    """Idempotency: matching button already present → no-op."""
    page = _page([{"type": "Button", "props": {"label": "Back",
                                               "onClick": {"action": "navigate", "target": "/documents"}}}])
    root = _mk_app(tmp_path, nav_flow=NAV_BACK,
                   schemas={"documents/[id].json": page})
    res = materialize_transitions(root)
    assert res["injected"] == []
    doc = _read_schema(root, "documents/[id].json")
    assert len(doc["root"]["children"]) == 1


def test_rerun_is_idempotent(tmp_path: Path):
    root = _mk_app(tmp_path, nav_flow=NAV_BACK,
                   schemas={"documents/[id].json": _page()})
    materialize_transitions(root)
    res2 = materialize_transitions(root)
    assert res2["injected"] == []
    doc = _read_schema(root, "documents/[id].json")
    buttons = [n for n in doc["root"]["children"] if n.get("type") == "Button"]
    assert len(buttons) == 1


def test_label_match_case_insensitive(tmp_path: Path):
    """'back' in schema satisfies 'button:Back' — same as gate."""
    page = _page([{"type": "Button", "props": {"label": "back"}}])
    root = _mk_app(tmp_path, nav_flow=NAV_BACK,
                   schemas={"documents/[id].json": page})
    assert materialize_transitions(root)["injected"] == []


def test_non_backish_label_appended(tmp_path: Path):
    nav = {
        "pages": [{"id": "docs", "route": "/documents"},
                  {"id": "up", "route": "/documents/upload"}],
        "transitions": [{"id": "t1", "from": "docs", "to": "up",
                         "trigger": "button:Upload Document"}],
    }
    root = _mk_app(tmp_path, nav_flow=nav,
                   schemas={"documents.json": _page([{"type": "Table", "props": {}}])})
    materialize_transitions(root)
    kids = _read_schema(root, "documents.json")["root"]["children"]
    assert kids[0]["type"] == "Table"          # content stays first
    assert kids[-1]["type"] == "Button"
    assert kids[-1]["props"]["label"] == "Upload Document"


def test_non_button_triggers_ignored(tmp_path: Path):
    nav = {
        "pages": [{"id": "a", "route": "/a"}, {"id": "b", "route": "/b"}],
        "transitions": [{"id": "t1", "from": "a", "to": "b", "trigger": "submit:form"},
                        {"id": "t2", "from": "a", "to": "b", "trigger": "auto"}],
    }
    root = _mk_app(tmp_path, nav_flow=nav, schemas={"a.json": _page()})
    res = materialize_transitions(root)
    assert res["injected"] == []
    assert _read_schema(root, "a.json")["root"]["children"] == []


def test_source_schema_missing_skips(tmp_path: Path):
    """Page 404s — that's planned_page_missing's territory, not ours."""
    root = _mk_app(tmp_path, nav_flow=NAV_BACK, schemas={})
    res = materialize_transitions(root)
    assert res["injected"] == []
    assert any("not on disk" in s["reason"] for s in res["skipped"])


def test_unresolvable_endpoints_skip(tmp_path: Path):
    nav = {"pages": [{"id": "a", "route": "/a"}],
           "transitions": [{"id": "t1", "from": "a", "to": "ghost",
                            "trigger": "button:Go"}]}
    root = _mk_app(tmp_path, nav_flow=nav, schemas={"a.json": _page()})
    res = materialize_transitions(root)
    assert res["injected"] == []
    assert res["skipped"][0]["reason"] == "unresolvable endpoints"


def test_nested_container_used_when_root_has_no_children(tmp_path: Path):
    """Root without children list → first descendant container."""
    doc = {"root": {"type": "Page",
                    "body": {"type": "Stack", "children": [{"type": "Text", "props": {}}]}}}
    root = _mk_app(tmp_path, nav_flow=NAV_BACK, schemas={"documents/[id].json": doc})
    res = materialize_transitions(root)
    assert len(res["injected"]) == 1
    out = _read_schema(root, "documents/[id].json")
    kids = out["root"]["body"]["children"]
    assert kids[0]["type"] == "Button"


def test_index_route_maps_to_index_json(tmp_path: Path):
    nav = {"pages": [{"id": "home", "route": "/"}, {"id": "d", "route": "/documents"}],
           "transitions": [{"id": "t1", "from": "home", "to": "d",
                            "trigger": "button:View Documents"}]}
    root = _mk_app(tmp_path, nav_flow=nav, schemas={"index.json": _page()})
    res = materialize_transitions(root)
    assert len(res["injected"]) == 1
    assert res["injected"][0]["route"] == "/"


# ── B2: workflow launchers ───────────────────────────────────────────

PLAN_REPROCESS = {
    "pages": [
        {"route": "/documents", "kind": "list"},
        {"route": "/documents/[id]", "kind": "detail"},
    ],
    "workflows": [
        {"name": "ReprocessDocumentWorkflow",
         "trigger": "button on DocumentDetailPage"},
    ],
}

WF_REPROCESS = {"id": "reprocessdocumentworkflow", "name": "ReprocessDocument",
                "steps": []}


def test_injects_launcher_when_workflow_on_disk(tmp_path: Path):
    root = _mk_app(
        tmp_path, plan=PLAN_REPROCESS,
        schemas={"documents/[id].json": _page([{"type": "Heading", "props": {}}])},
        workflows={"reprocessdocumentworkflow.json": WF_REPROCESS},
    )
    res = materialize_workflow_launchers(root)
    assert len(res["injected"]) == 1
    inj = res["injected"][0]
    assert inj["route"] == "/documents/[id]"
    assert inj["dispatch"] == "ReprocessDocument"   # runtime name, not file id
    kids = _read_schema(root, "documents/[id].json")["root"]["children"]
    assert kids[-1]["type"] == "Button"
    assert kids[-1]["props"]["workflow"] == "ReprocessDocument"
    assert kids[-1]["props"]["label"] == "Reprocess Document"


def test_launcher_injection_satisfies_delivery_gate(tmp_path: Path):
    root = _mk_app(
        tmp_path, plan=PLAN_REPROCESS,
        schemas={"documents/[id].json": _page()},
        workflows={"reprocessdocumentworkflow.json": WF_REPROCESS},
    )
    assert check_workflow_launchers(PLAN_REPROCESS, _load_page_schemas(root)) != []
    materialize_workflow_launchers(root)
    assert check_workflow_launchers(PLAN_REPROCESS, _load_page_schemas(root)) == []


def test_no_disk_workflow_skips_injection(tmp_path: Path):
    """The actual 9y8de8i7 state: ReprocessDocumentWorkflow is planned
    but never emitted. A button dispatching nothing would turn a visible
    gate error into an invisible runtime failure — must skip."""
    root = _mk_app(tmp_path, plan=PLAN_REPROCESS,
                   schemas={"documents/[id].json": _page()})
    res = materialize_workflow_launchers(root)
    assert res["injected"] == []
    assert any("no on-disk workflow" in s["reason"] for s in res["skipped"])
    assert _read_schema(root, "documents/[id].json")["root"]["children"] == []


def test_existing_launcher_not_duplicated(tmp_path: Path):
    """Any page already referencing the workflow (canon match) → no-op."""
    page = _page([{"type": "Form", "props": {"workflow": "reprocess-document"}}])
    root = _mk_app(tmp_path, plan=PLAN_REPROCESS,
                   schemas={"documents/[id].json": page},
                   workflows={"reprocessdocumentworkflow.json": WF_REPROCESS})
    assert materialize_workflow_launchers(root)["injected"] == []


def test_form_trigger_not_ours(tmp_path: Path):
    plan = {"pages": [{"route": "/documents", "kind": "list"}],
            "workflows": [{"name": "UploadDocumentsWorkflow",
                           "trigger": "form_submit on UploadPage"}]}
    root = _mk_app(tmp_path, plan=plan, schemas={"documents.json": _page()},
                   workflows={"uploaddocumentsworkflow.json":
                              {"id": "uploaddocumentsworkflow", "name": "UploadDocuments"}})
    res = materialize_workflow_launchers(root)
    assert res["injected"] == []


def test_dict_trigger_shape_supported(tmp_path: Path):
    plan = {
        "pages": [{"route": "/documents/[id]", "kind": "detail"}],
        "workflows": [{"name": "ReprocessDocumentWorkflow",
                       "trigger": {"type": "button on DocumentDetailPage"}}],
    }
    root = _mk_app(tmp_path, plan=plan,
                   schemas={"documents/[id].json": _page()},
                   workflows={"reprocessdocumentworkflow.json": WF_REPROCESS})
    assert len(materialize_workflow_launchers(root)["injected"]) == 1


def test_unresolvable_trigger_page_skips(tmp_path: Path):
    plan = {"pages": [{"route": "/documents", "kind": "list"}],
            "workflows": [{"name": "ReprocessDocumentWorkflow",
                           "trigger": "button on BillingPage"}]}
    root = _mk_app(tmp_path, plan=plan, schemas={"documents.json": _page()},
                   workflows={"reprocessdocumentworkflow.json": WF_REPROCESS})
    res = materialize_workflow_launchers(root)
    assert res["injected"] == []
    assert any("cannot resolve trigger page" in s["reason"] for s in res["skipped"])


def test_rerun_is_idempotent_launchers(tmp_path: Path):
    root = _mk_app(tmp_path, plan=PLAN_REPROCESS,
                   schemas={"documents/[id].json": _page()},
                   workflows={"reprocessdocumentworkflow.json": WF_REPROCESS})
    materialize_workflow_launchers(root)
    assert materialize_workflow_launchers(root)["injected"] == []
    kids = _read_schema(root, "documents/[id].json")["root"]["children"]
    assert len([n for n in kids if n.get("type") == "Button"]) == 1


# ── page-name resolution ─────────────────────────────────────────────

def test_resolve_detail_page():
    assert _resolve_page_route("DocumentDetailPage", PLAN_REPROCESS) == "/documents/[id]"


def test_resolve_list_page():
    assert _resolve_page_route("DocumentListPage", PLAN_REPROCESS) == "/documents"


def test_resolve_requires_entity_hit():
    assert _resolve_page_route("BillingDetailPage", PLAN_REPROCESS) is None


def test_resolve_empty_name():
    assert _resolve_page_route("", PLAN_REPROCESS) is None


# ── label humanization ───────────────────────────────────────────────

def test_humanize_strips_workflow_suffix_and_splits_camel():
    assert _humanize("ReprocessDocumentWorkflow") == "Reprocess Document"


def test_humanize_snake_case():
    assert _humanize("reprocess_document_workflow") == "Reprocess Document"


# ── combined entry point ─────────────────────────────────────────────

def test_run_never_raises_on_empty_dir(tmp_path: Path):
    out = run(tmp_path / "nope")
    assert out["transitions"]["injected"] == []
    assert out["workflow_launchers"]["injected"] == []
