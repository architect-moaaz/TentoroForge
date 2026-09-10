"""Consolidated tests for the final 4 remaining pipeline items:
- rules_validator (Phase 2.3)
- planner_context (Phase 2.1)
- proof_sse (Phase 5.1 SSE emit)
- verify_trigger (Phase 5.2)
- archetype renames + extras + async spec builder
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.locked_spec import (
    Entity,
    LockedSpec,
    build_locked_spec_async,
    persist_locked_spec,
)
from services.scope_card import Manifest, Page, persist_manifest


def _run(coro):
    # asyncio.run, not get_event_loop(): asyncio.run clears the current
    # loop when it finishes, so any sibling suite that used it first left
    # get_event_loop() raising "no current event loop". These tests passed
    # alone and failed in the full run, which is the worst way to fail.
    return asyncio.run(coro)


# ─── rules_validator ─────────────────────────────────────────────────────

def test_rules_validator_flags_unknown_entity(tmp_path: Path):
    from services.rules_validator import validate_rules

    findings = validate_rules(
        [{"name": "bad-rule", "entity": "Ghost"}],
        "rules.json",
        entity_names={"scan", "retailer"},
        workflow_names=set(),
    )
    assert any(f.code == "rule-unknown-entity" for f in findings)


def test_rules_validator_accepts_known_entity(tmp_path: Path):
    from services.rules_validator import validate_rules
    findings = validate_rules(
        [{"name": "ok", "entity": "Scan"}],
        "rules.json",
        entity_names={"scan"},
        workflow_names=set(),
    )
    assert not any(f.code == "rule-unknown-entity" for f in findings)


def test_rules_validator_flags_unknown_workflow():
    from services.rules_validator import validate_rules
    findings = validate_rules(
        [{"name": "n", "entity": "Scan", "workflow": "DoesNotExist"}],
        "rules.json",
        entity_names={"scan"},
        workflow_names={"CreateScan"},
    )
    assert any(f.code == "rule-unknown-workflow" for f in findings)


def test_rules_validator_dotted_entity_field():
    """`entity: "Scan.userId"` splits into entity + field."""
    from services.rules_validator import validate_rules
    findings = validate_rules(
        [{"name": "n", "entity": "Ghost.field"}],
        "rules.json",
        entity_names={"scan"},
        workflow_names=set(),
    )
    assert any(f.code == "rule-unknown-entity" for f in findings)


def test_rules_validator_end_to_end(tmp_path: Path):
    """Full flow: persist spec + manifest + write rules JSON + validate."""
    from services.rules_validator import validate_output_dir

    spec = LockedSpec(entities=[Entity(name="Scan", kind="event")])
    persist_locked_spec(spec, tmp_path)
    manifest = Manifest(
        pages=[Page(path="/scans", kind="list")],
        entities_with_tables=["Scan"],
        workflows=["CreateScan"],
    )
    persist_manifest(manifest, tmp_path)

    rules_dir = tmp_path / "src" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "index.json").write_text(json.dumps([
        {"name": "scan-user-id-required", "entity": "Scan"},
        {"name": "phantom", "entity": "Ghost"},
    ]), encoding="utf-8")

    findings = validate_output_dir(tmp_path)
    codes = {f.code for f in findings}
    assert "rule-unknown-entity" in codes


# ─── planner_context ────────────────────────────────────────────────────

def test_planner_context_empty_when_no_spec(tmp_path: Path):
    from services.planner_context import build_authoritative_inputs_block
    assert build_authoritative_inputs_block(tmp_path) == ""


def test_planner_context_renders_spec_and_manifest(tmp_path: Path):
    from services.planner_context import build_authoritative_inputs_block

    persist_locked_spec(
        LockedSpec(entities=[Entity(name="Scan", kind="event")]),
        tmp_path,
    )
    persist_manifest(
        Manifest(
            pages=[Page(path="/scans", kind="list", entity="Scan")],
            entities_with_tables=["Scan"],
            workflows=["ScanProductWorkflow"],
        ),
        tmp_path,
    )
    block = build_authoritative_inputs_block(tmp_path)
    assert "AUTHORITATIVE INPUTS" in block
    assert "Scan" in block
    assert "/scans" in block
    assert "ScanProductWorkflow" in block


def test_planner_context_renders_archetype_and_renames(tmp_path: Path):
    from services.planner_context import build_authoritative_inputs_block

    persist_locked_spec(LockedSpec(), tmp_path)
    (tmp_path / "contracts" / "archetype.json").write_text(json.dumps({
        "archetype": "visual-product-search",
        "reason": "matched keywords",
        "renames": {"Scan": "ArtworkScan"},
    }), encoding="utf-8")
    block = build_authoritative_inputs_block(tmp_path)
    assert "visual-product-search" in block
    assert "ArtworkScan" in block
    assert "Scan" in block


# ─── proof_sse ──────────────────────────────────────────────────────────

def test_proof_sse_none_when_no_report(tmp_path: Path):
    from services.proof_sse import build_proof_sse_payload
    assert build_proof_sse_payload(tmp_path) is None


def test_proof_sse_payload_shape(tmp_path: Path):
    from services.proof_sse import build_proof_sse_payload
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "proof_report.json").write_text(json.dumps({
        "passed": False,
        "error_count": 1,
        "warning_count": 2,
        "findings": [
            {"severity": "warning", "code": "empty-page", "message": "w"},
            {"severity": "error", "code": "duplicate-route", "message": "e"},
        ],
    }), encoding="utf-8")
    payload = build_proof_sse_payload(tmp_path)
    assert payload is not None
    assert payload["passed"] is False
    assert payload["error_count"] == 1
    # Errors sort before warnings.
    assert payload["findings"][0]["severity"] == "error"


def test_proof_sse_truncation(tmp_path: Path):
    from services.proof_sse import build_proof_sse_payload
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "proof_report.json").write_text(json.dumps({
        "passed": True,
        "error_count": 0,
        "warning_count": 40,
        "findings": [
            {"severity": "warning", "code": "empty-page", "message": f"f{i}"}
            for i in range(40)
        ],
    }), encoding="utf-8")
    payload = build_proof_sse_payload(tmp_path)
    assert payload is not None
    assert len(payload["findings"]) == 25  # _MAX_INLINE_FINDINGS
    assert payload["truncated"] == 15


# ─── verify_trigger ─────────────────────────────────────────────────────

def test_verify_should_trigger_when_proof_failed(tmp_path: Path):
    from services.verify_trigger import should_trigger_verify
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "proof_report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    assert should_trigger_verify(tmp_path) is True


def test_verify_should_not_trigger_when_proof_passed(tmp_path: Path):
    from services.verify_trigger import should_trigger_verify
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "proof_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert should_trigger_verify(tmp_path) is False


def test_verify_should_not_trigger_env_opt_out(tmp_path: Path, monkeypatch):
    from services.verify_trigger import should_trigger_verify
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "proof_report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    monkeypatch.setenv("FORGE_VERIFY_AUTO", "false")
    assert should_trigger_verify(tmp_path) is False


def test_verify_trigger_writes_pending_marker(tmp_path: Path):
    """No runner installed → trigger writes a pending marker; returns
    dispatched=False without raising."""
    from services.verify_trigger import trigger_verify
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "proof_report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    result = trigger_verify(tmp_path)
    assert result["dispatched"] is False
    marker = tmp_path / "contracts" / "verify_pending.json"
    assert marker.exists()


# ─── archetype LLM renames + async spec builder ─────────────────────────

VISUAL_PRODUCT_SEARCH = (
    "Mobile-first app where a user scans a product with their phone camera "
    "or uploads an image. Compare prices across retailers via Firecrawl. "
    "Admin controls the retailer allow-list."
)


def test_apply_archetype_renames_entities():
    from services.archetype_detector import apply_archetype_to_spec
    from services.locked_spec import build_locked_spec

    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    # Confirm baseline: Scan is present with archetype's default name.
    assert any(e.name == "Scan" for e in spec.entities)
    apply_archetype_to_spec(
        spec,
        "visual-product-search",
        renames={"Scan": "ArtworkScan", "Retailer": "Marketplace"},
    )
    names = {e.name for e in spec.entities}
    assert "ArtworkScan" in names
    assert "Marketplace" in names
    assert "Scan" not in names
    assert "Retailer" not in names


def test_apply_archetype_extra_entities_added():
    from services.archetype_detector import apply_archetype_to_spec
    from services.locked_spec import LockedSpec

    spec = LockedSpec()
    apply_archetype_to_spec(
        spec,
        "visual-product-search",
        extra_entities=[{"name": "Artist", "kind": "entity"}],
    )
    assert any(e.name == "Artist" for e in spec.entities)


def test_build_locked_spec_async_applies_llm_renames(monkeypatch):
    """The async builder calls classify_app_archetype; when the LLM
    proposes renames, they must land in the persisted spec."""
    from services import archetype_classifier

    async def fake_llm(_desc):
        return {
            "archetype": "visual-product-search",
            "confidence": 0.9,
            "renames": {"Scan": "InventoryScan", "Retailer": "Vendor"},
            "extra_entities": [{"name": "Warehouse", "kind": "entity"}],
            "reason": "inventory scanner",
        }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(archetype_classifier, "_call_llm", fake_llm)

    spec = _run(build_locked_spec_async(VISUAL_PRODUCT_SEARCH))
    names = {e.name for e in spec.entities}
    assert "InventoryScan" in names
    assert "Vendor" in names
    assert "Warehouse" in names
    assert "Scan" not in names


def test_build_locked_spec_async_falls_back_without_llm():
    """No API key ⇒ falls back to the deterministic archetype application."""
    # No monkeypatching = no key set (see autouse fixture in
    # test_archetype_classifier). Here we just ensure no crash.
    spec = _run(build_locked_spec_async(VISUAL_PRODUCT_SEARCH))
    assert any(e.name == "Scan" for e in spec.entities)  # deterministic name kept
