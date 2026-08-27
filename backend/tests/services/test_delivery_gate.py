"""Tests for services.delivery_gate — F1 plan↔artifact symmetry + G2
signature-move evidence.

Fixtures model the real reference-app failure modes: planned-page-404,
orphan button-triggered workflow, declared-but-missing Back button,
dashboard-vs-form kind drift, unshipped signature moves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.delivery_gate import (
    DeliveryGateError,
    check_page_kinds,
    check_planned_pages,
    check_signature_moves,
    check_transition_triggers,
    check_workflow_launchers,
    gate_mode,
    run_delivery_gate,
)


# ── fixture builder ──────────────────────────────────────────────────

def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(
    tmp_path: Path,
    *,
    plan: dict,
    nav_flow: dict | None = None,
    registry_routes: list[str] | None = None,
    schemas: dict[str, dict] | None = None,   # rel-path → doc
    brief: dict | None = None,
    css: str = "",
) -> Path:
    root = tmp_path / "app"
    _write(root, "src/contracts/plan.json", json.dumps(plan))
    _write(root, "src/contracts/nav-flow.json", json.dumps(nav_flow or {"pages": [], "transitions": []}))
    routes = registry_routes or []
    reg_lines = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts",
           "export const schemas = {\n" + reg_lines + "\n};\n")
    for rel, doc in (schemas or {}).items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    if brief is not None:
        _write(root, "contracts/brief.json", json.dumps(brief))
    _write(root, "src/app/globals.css", css)
    return root


# ── rule 1+2: planned pages live + reachable ─────────────────────────

def test_planned_page_missing_flags_404_route(tmp_path: Path):
    """The /admins case: in plan, not in registry → error."""
    plan = {"pages": [{"route": "/admins", "kind": "list"}]}
    nav = {"pages": [], "transitions": []}
    v = check_planned_pages(plan, {"/", "/documents"}, nav)
    assert len(v) == 1
    assert v[0].rule == "planned_page_missing"
    assert v[0].severity == "error"
    assert v[0].subject == "/admins"


def test_planned_page_present_and_reachable_passes(tmp_path: Path):
    plan = {"pages": [{"route": "/documents", "kind": "list"}]}
    nav = {"pages": [{"id": "docs", "route": "/documents"}], "transitions": []}
    assert check_planned_pages(plan, {"/documents"}, nav) == []


def test_live_but_unreachable_page_flags(tmp_path: Path):
    """Route exists in the registry but nothing links to it."""
    plan = {"pages": [{"route": "/reports", "kind": "list"}]}
    nav = {"pages": [{"id": "home", "route": "/"}], "transitions": []}
    v = check_planned_pages(plan, {"/reports", "/"}, nav)
    assert len(v) == 1
    assert v[0].rule == "page_unreachable"


def test_transition_target_counts_as_reachable(tmp_path: Path):
    """A page reached only via transition (e.g. detail from row-click
    flow) is NOT unreachable."""
    plan = {"pages": [{"route": "/documents/[id]", "kind": "detail"}]}
    nav = {
        "pages": [
            {"id": "docs", "route": "/documents"},
            {"id": "doc-detail", "route": "/documents/[id]"},
        ],
        "transitions": [{"id": "t", "from": "docs", "trigger": "row:click",
                         "to": "doc-detail"}],
    }
    assert check_planned_pages(plan, {"/documents/[id]", "/documents"}, nav) == []


def test_hidden_page_skipped(tmp_path: Path):
    plan = {"pages": [{"route": "/internal", "kind": "list", "hidden": True}]}
    assert check_planned_pages(plan, set(), {"pages": [], "transitions": []}) == []


def test_param_bracket_styles_collapse(tmp_path: Path):
    """`/x/{id}` in plan matches `/x/[id]` in registry."""
    plan = {"pages": [{"route": "/docs/{id}", "kind": "detail"}]}
    nav = {"pages": [{"id": "d", "route": "/docs/[id]"}], "transitions": []}
    assert check_planned_pages(plan, {"/docs/[id]"}, nav) == []


# ── rule 3: workflow launchers ───────────────────────────────────────

def _wf_plan(trigger: str) -> dict:
    return {"workflows": [{"name": "ReprocessDocumentWorkflow", "trigger": trigger}]}


def test_button_triggered_workflow_without_launcher_flags():
    """The Reprocess case: button trigger, no ref in any schema."""
    schemas = [("/documents/[id]", {"root": {"type": "Stack", "children": []}})]
    v = check_workflow_launchers(_wf_plan("button on DocumentDetailPage"), schemas)
    assert len(v) == 1
    assert v[0].rule == "workflow_launcher_missing"
    assert "ReprocessDocumentWorkflow" in v[0].subject


def test_workflow_with_launcher_passes():
    schemas = [("/documents/[id]", {
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Reprocess"},
             "workflow": "reprocess-document"},
        ]},
    })]
    assert check_workflow_launchers(
        _wf_plan("button on DocumentDetailPage"), schemas) == []


def test_launcher_name_canonicalization():
    """`ReprocessDocumentWorkflow` matches a `reprocess_document` ref —
    suffix stripped, separators ignored."""
    schemas = [("/x", {"root": {"type": "Form",
                                "props": {"workflow": "Reprocess_Document"}}})]
    assert check_workflow_launchers(
        _wf_plan("form_submit on X"), schemas) == []


def test_db_change_trigger_needs_no_launcher():
    """Background triggers (db_change/schedule) never require UI."""
    plan = {"workflows": [{"name": "ProcessDocumentWorkflow",
                           "trigger": "db_change on ProcessDocumentJob"}]}
    assert check_workflow_launchers(plan, []) == []


def test_dict_shaped_trigger_supported():
    plan = {"workflows": [{"name": "X", "trigger": {"type": "manual"}}]}
    v = check_workflow_launchers(plan, [])
    assert len(v) == 1


# ── rule 4: transition triggers ──────────────────────────────────────

_NAV_BACK = {
    "pages": [
        {"id": "detail", "route": "/documents/[id]"},
        {"id": "docs", "route": "/documents"},
    ],
    "transitions": [{"id": "t-back", "from": "detail",
                     "trigger": "button:Back", "to": "docs"}],
}


def test_missing_back_button_flags():
    """The audit's Back case: transition declared, button absent."""
    schemas = [("/documents/[id]", {"root": {"type": "Stack", "children": []}})]
    v = check_transition_triggers(_NAV_BACK, schemas)
    assert len(v) == 1
    assert v[0].rule == "transition_trigger_missing"
    assert "button:Back" in v[0].subject


def test_present_back_button_passes():
    schemas = [("/documents/[id]", {
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Back"}},
        ]},
    })]
    assert check_transition_triggers(_NAV_BACK, schemas) == []


def test_submit_transition_requires_form():
    nav = {
        "pages": [{"id": "up", "route": "/upload"}, {"id": "d", "route": "/documents"}],
        "transitions": [{"id": "t", "from": "up",
                         "trigger": "submit:ProcessDocument", "to": "d"}],
    }
    no_form = [("/upload", {"root": {"type": "Stack", "children": []}})]
    with_form = [("/upload", {"root": {"type": "Form", "children": []}})]
    assert len(check_transition_triggers(nav, no_form)) == 1
    assert check_transition_triggers(nav, with_form) == []


def test_missing_source_page_not_double_reported():
    """Page-missing is rule 1's job — rule 4 skips absent schemas."""
    assert check_transition_triggers(_NAV_BACK, []) == []


# ── rule 5: kind mismatch (warn) ─────────────────────────────────────

def test_dashboard_kind_delivered_as_form_warns():
    """The `/` case: plan says dashboard, shipped page is a form."""
    plan = {"pages": [{"route": "/", "kind": "dashboard"}]}
    schemas = [("/", {"root": {"type": "Form", "children": [
        {"type": "Input", "props": {"name": "x"}}]}})]
    v = check_page_kinds(plan, schemas)
    assert len(v) == 1
    assert v[0].rule == "kind_mismatch"
    assert v[0].severity == "warn"
    assert "form" in v[0].msg


def test_matching_kind_passes():
    plan = {"pages": [{"route": "/", "kind": "dashboard"}]}
    schemas = [("/", {"root": {"type": "Grid", "children": [
        {"type": "MetricTile", "props": {}}]}})]
    assert check_page_kinds(plan, schemas) == []


# ── G2: signature moves ──────────────────────────────────────────────

_BRIEF = {"signature_moves": [
    {"kind": "document_status_rail", "detail": "left-edge 3px bar by state"},
    {"kind": "monospaced_metadata_strip", "detail": "mono file manifest strip"},
]}


def test_unshipped_moves_flag_as_warn():
    """Reference-app case: both moves authored, neither shipped."""
    v = check_signature_moves(_BRIEF, [], css_text="body { color: #000; }")
    kinds = {x.subject for x in v}
    assert kinds == {"document_status_rail", "monospaced_metadata_strip"}
    assert all(x.rule == "signature_move_missing" for x in v)
    assert all(x.severity == "warn" for x in v)


def test_shipped_move_via_css_evidence_passes():
    css = '[data-status="processing"] { border-left: 3px solid var(--amber); } .metadata-strip { font-family: var(--font-mono); }'
    assert check_signature_moves(_BRIEF, [], css_text=css) == []


def test_shipped_move_via_schema_evidence_passes():
    schemas = [("/documents", {"root": {"type": "Card", "props": {
        "className": "status-rail", "footer": "metadata-strip"}}})]
    assert check_signature_moves(_BRIEF, schemas, css_text="") == []


def test_unknown_move_kind_reports_unverifiable_info():
    brief = {"signature_moves": [{"kind": "floating_glass_orb", "detail": "?"}]}
    v = check_signature_moves(brief, [], css_text="")
    assert len(v) == 1
    assert v[0].rule == "signature_move_unverifiable"
    assert v[0].severity == "info"


def test_no_brief_no_findings():
    assert check_signature_moves({}, [], "") == []


# ── gate orchestration ───────────────────────────────────────────────

def _broken_app(tmp_path: Path) -> Path:
    """An app with one of each failure class."""
    return _mk_app(
        tmp_path,
        plan={
            "pages": [
                {"route": "/", "kind": "dashboard"},
                {"route": "/admins", "kind": "list"},
            ],
            "workflows": [
                {"name": "ReprocessDocumentWorkflow",
                 "trigger": "button on DocumentDetailPage"},
            ],
        },
        nav_flow={
            "pages": [{"id": "home", "route": "/"}],
            "transitions": [{"id": "t-back", "from": "home",
                             "trigger": "button:Back", "to": "home"}],
        },
        registry_routes=["/"],
        schemas={"index.json": {"route": "/", "root": {
            "type": "Form", "children": []}}},
        brief={"signature_moves": [
            {"kind": "document_status_rail", "detail": "rail"}]},
    )


def test_run_gate_writes_report_and_counts(tmp_path: Path):
    root = _broken_app(tmp_path)
    report = run_delivery_gate(root, mode="warn")
    assert report["summary"]["error"] >= 3   # missing page, launcher, trigger
    assert report["summary"]["warn"] >= 2    # kind mismatch + move missing
    on_disk = json.loads((root / "contracts" / "delivery-report.json").read_text())
    assert on_disk["summary"] == report["summary"]
    rules = {v["rule"] for v in on_disk["violations"]}
    assert {"planned_page_missing", "workflow_launcher_missing",
            "transition_trigger_missing", "kind_mismatch",
            "signature_move_missing"} <= rules


def test_strict_mode_raises_on_errors(tmp_path: Path):
    root = _broken_app(tmp_path)
    with pytest.raises(DeliveryGateError) as exc:
        run_delivery_gate(root, mode="strict")
    assert "undelivered promise" in str(exc.value)


def test_strict_mode_passes_clean_app(tmp_path: Path):
    root = _mk_app(
        tmp_path,
        plan={"pages": [{"route": "/", "kind": "form"}], "workflows": []},
        nav_flow={"pages": [{"id": "home", "route": "/"}], "transitions": []},
        registry_routes=["/"],
        # "/" is a dashboard route, so a clean app must also clear the
        # substance floor: KPIs, a chart, a recent-activity surface. A bare
        # container here is the exact shape 54 of 125 corpus dashboards
        # shipped with — "clean" has to mean clean.
        schemas={"index.json": {"route": "/", "root": {
            "type": "Stack", "children": [
                {"type": "MetricTile", "props": {"label": "Open"}},
                {"type": "MetricTile", "props": {"label": "Closed"}},
                {"type": "MetricTile", "props": {"label": "Total"}},
                {"type": "Chart", "props": {"chartType": "bar"}},
                {"type": "Table", "props": {"rows": "{{recent}}"}},
                {"type": "Form", "children": []},
            ]}}},
    )
    report = run_delivery_gate(root, mode="strict")
    assert report["summary"]["error"] == 0


def test_off_mode_skips(tmp_path: Path):
    report = run_delivery_gate(_broken_app(tmp_path), mode="off")
    assert report.get("skipped") is True


def test_gate_mode_env(monkeypatch):
    monkeypatch.delenv("FORGE_DELIVERY_GATE", raising=False)
    assert gate_mode() == "warn"
    monkeypatch.setenv("FORGE_DELIVERY_GATE", "strict")
    assert gate_mode() == "strict"
    monkeypatch.setenv("FORGE_DELIVERY_GATE", "off")
    assert gate_mode() == "off"
    monkeypatch.setenv("FORGE_DELIVERY_GATE", "bogus")
    assert gate_mode() == "warn"


def test_gate_never_raises_on_missing_artifacts(tmp_path: Path):
    """Empty dir → empty report, no crash (fail-open)."""
    report = run_delivery_gate(tmp_path / "nothing", mode="warn")
    assert report["summary"] == {"error": 0, "warn": 0, "info": 0}
