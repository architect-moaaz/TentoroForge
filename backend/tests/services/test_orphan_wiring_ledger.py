"""End-to-end: orphan_wiring_pass writes decision-ledger rows.

Isolates the ledger side-effect from the wiring logic — the wiring
tests already cover picking behaviour, these prove the ledger
integration doesn't silently drop rows.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.decision_ledger import (
    BAND_LOW, KIND_BUTTON_TARGET, load_ledger,
)


def _mk_project(tmp_path: Path, workflows: list[dict], forms: list[dict]) -> Path:
    """Minimal on-disk project shape orphan_wiring_pass can traverse.

    Page schemas MUST live at src/schemas/<route-path>.json — that's the
    layout the wire_form_to_workflow resolver uses to find a page by
    route. `/a/new` → src/schemas/a/new.json.
    """
    root = tmp_path / "proj"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)

    for wf in workflows:
        (root / "workflows" / f"{wf['name']}.json").write_text(
            json.dumps(wf), encoding="utf-8"
        )

    for form_page in forms:
        route = form_page.get("route", "/")
        parts = [p for p in route.strip("/").split("/") if p] or ["index"]
        p = root / "src" / "schemas"
        for seg in parts[:-1]:
            p = p / seg
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{parts[-1]}.json").write_text(
            json.dumps(form_page), encoding="utf-8"
        )

    # Empty plan.json so downstream helpers don't NPE.
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text("{}", encoding="utf-8")
    return root


def test_unresolved_workflow_writes_ledger_row(tmp_path: Path):
    """A workflow with no matching form → an unresolved candidate → a
    low-confidence ledger row so the chip UI surfaces it."""
    workflows = [
        {
            "id": "wf1",
            "name": "SendReminderWorkflow",
            "trigger": {"type": "manual"},
            "processVariables": [
                {"name": "recipient", "required": True},
                {"name": "subject", "required": True},
            ],
            "steps": [],
        },
    ]
    # A form that partially matches (has "subject" but not "recipient").
    # Fields must be real child components (Input/Textarea/etc) — the
    # form-indexer walks the tree, not props.fields.
    forms = [
        {
            "route": "/notes/new",
            "root": {
                "component": "Form",
                "children": [
                    {"component": "Input", "props": {"name": "subject"}},
                    {"component": "Textarea", "props": {"name": "body"}},
                ],
            },
        },
    ]
    root = _mk_project(tmp_path, workflows, forms)

    from services.orphan_wiring_pass import wire_orphan_workflows
    result = wire_orphan_workflows(str(root))

    # This form doesn't score above HIGH_CONFIDENCE (=1.0), so wiring
    # should NOT happen — but the candidate + score DID exist, so the
    # ledger should record it.
    assert result["wired"] == []
    assert any(u["workflow"] == "SendReminderWorkflow"
               for u in result["unresolved"])

    ledger = load_ledger(str(root))
    # Row should exist for the unresolved workflow with the near-miss form as target
    matching = [
        r for r in ledger
        if r["kind"] == KIND_BUTTON_TARGET
        and "SendReminderWorkflow" in r["identity"]
    ]
    assert len(matching) == 1
    row = matching[0]
    assert row["confidence"] == BAND_LOW
    assert "page:/notes/new" == row["target_picked"]
    assert row["source_emitter"] == "orphan_wiring_pass"


def test_confirmed_binding_bypasses_scorer(tmp_path: Path):
    """Once user confirms a binding, the pass calls the wire seam directly
    with that target — tagged source='binding' so audits can tell the
    binding-path picks apart from fuzzy-match picks.

    Uses a form whose fields cover every required workflow input so the
    wire seam accepts (it has its own resolvability gate that the binding
    can't override — the binding says WHICH form, not that inputs are OK)."""
    workflows = [
        {
            "id": "wf1",
            "name": "SendReminderWorkflow",
            "trigger": {"type": "manual"},
            "processVariables": [
                {"name": "recipient", "required": True},
                {"name": "subject", "required": True},
            ],
            "steps": [],
        },
    ]
    # Form covers BOTH required inputs so the wire seam is satisfiable.
    forms = [
        {
            "route": "/notes/new",
            "root": {
                "component": "Form",
                "children": [
                    {"component": "Input", "props": {"name": "recipient"}},
                    {"component": "Input", "props": {"name": "subject"}},
                ],
            },
        },
    ]
    root = _mk_project(tmp_path, workflows, forms)

    from services.decision_ledger import (
        KIND_BUTTON_TARGET, save_binding,
    )
    save_binding(
        str(root),
        kind=KIND_BUTTON_TARGET,
        scope="workflow:SendReminderWorkflow",
        identity="SendReminderWorkflow",
        target="page:/notes/new",
    )

    from services.orphan_wiring_pass import wire_orphan_workflows
    result = wire_orphan_workflows(str(root))

    # Wire took the binding path — tagged source='binding'.
    assert len(result["wired"]) == 1
    assert result["wired"][0]["workflow"] == "SendReminderWorkflow"
    assert result["wired"][0]["page_route"] == "/notes/new"
    assert result["wired"][0].get("source") == "binding"


def test_stale_binding_falls_through_to_scorer(tmp_path: Path):
    """A binding pointing at a route that no longer exists must not
    freeze the workflow — the pass falls through to scoring, which
    naturally overwrites the stale pick."""
    workflows = [
        {
            "id": "wf1", "name": "SendReminderWorkflow",
            "trigger": {"type": "manual"},
            "processVariables": [{"name": "subject", "required": True}],
            "steps": [],
        },
    ]
    # Only route /a/new exists; binding points at /gone
    forms = [
        {
            "route": "/a/new",
            "root": {
                "component": "Form",
                "children": [{"component": "Input", "props": {"name": "subject"}}],
            },
        },
    ]
    root = _mk_project(tmp_path, workflows, forms)

    from services.decision_ledger import KIND_BUTTON_TARGET, save_binding
    save_binding(
        str(root),
        kind=KIND_BUTTON_TARGET,
        scope="workflow:SendReminderWorkflow",
        identity="SendReminderWorkflow",
        target="page:/gone",
    )

    from services.orphan_wiring_pass import wire_orphan_workflows
    result = wire_orphan_workflows(str(root))
    # Stale binding → fell through to scoring. The only form scored
    # perfectly (all required inputs covered), so it wired.
    assert len(result["wired"]) == 1
    assert result["wired"][0]["page_route"] == "/a/new"
    # Not the "binding" source — normal scorer path.
    assert result["wired"][0].get("source") != "binding"


def test_no_candidates_no_ledger_write(tmp_path: Path):
    """Workflow with zero matching forms → unresolved but NO ledger row
    (there's nothing to record — no candidates existed)."""
    workflows = [
        {
            "id": "wf1",
            "name": "Loner",
            "trigger": {"type": "manual"},
            "processVariables": [{"name": "field_a", "required": True}],
            "steps": [],
        },
    ]
    forms: list[dict] = []  # no forms in project at all
    root = _mk_project(tmp_path, workflows, forms)

    from services.orphan_wiring_pass import wire_orphan_workflows
    result = wire_orphan_workflows(str(root))
    assert result["wired"] == []
    assert load_ledger(str(root)) == []
