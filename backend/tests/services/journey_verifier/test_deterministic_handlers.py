"""Unit tests for the 5 new deterministic autofix handlers (M1).

Each handler is exercised against a minimal fake ``output_dir`` — just
enough files to satisfy the code path — with the underlying seam
monkeypatched OR its side effect verified on-disk. We check:

  1. The handler returns a well-shaped DispatchResult with class_name
     populated and smith_turns_used == 0.
  2. The correct seam / underlying function was invoked.
  3. Idempotency: a second call is a no-op (no double writes / no crash).

Fixtures stay small — no full generated-app tree — so the tests stay
readable and don't tie us to whatever the current app-foundation
template looks like this week.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.journey_verifier.autofix import DispatchResult
from services.journey_verifier.deterministic_handlers import (
    _infer_entity,
    _infer_page_kind,
    _rewrite_datasource,
    handle_add_page,
    handle_db_migrate,
    handle_orphan_wiring,
    handle_rewire_datasource,
    handle_router_regen,
)
from services.journey_verifier.fault_classifier import ClassifiedFault


def _cf(*, route: str = "/applicants", class_name: str = "missing-page",
        seam: str = "deterministic:add-page", interaction_id: str | None = None) -> ClassifiedFault:
    return ClassifiedFault(
        interaction_id=interaction_id or f"route:{route}",
        route=route,
        class_name=class_name,
        seam=seam,
        evidence_slice="test",
        needed_context=[],
        raw={"interaction": {"id": interaction_id or f"route:{route}",
                             "route": route, "kind": "route"},
             "evidence": {}},
    )


# ── handle_add_page ────────────────────────────────────────────────────────


def test_handle_add_page_dispatches_to_seam(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_apply_add_page(output_dir: str, diagnosis: dict, *, git: bool):
        calls.append({"output_dir": output_dir, "diagnosis": diagnosis, "git": git})
        return {"applied": True, "changes": [{"path": "src/schemas/applicants.json"}]}

    monkeypatch.setattr(
        "services.fix_applier._apply_add_page",
        fake_apply_add_page,
    )

    fault = _cf(route="/applicants", class_name="missing-page")
    result = handle_add_page(fault, tmp_path)

    assert isinstance(result, DispatchResult)
    assert result.seam == "deterministic:add-page"
    assert result.class_name == "missing-page"
    assert result.smith_turns_used == 0
    assert result.fixed is True
    assert result.ok is True
    assert calls and calls[0]["diagnosis"]["proposedFix"]["patch"]["route"] == "/applicants"
    assert calls[0]["diagnosis"]["proposedFix"]["patch"]["archetype"] == "list"
    assert calls[0]["git"] is False


def test_handle_add_page_infers_kind_from_route(monkeypatch, tmp_path):
    seen: list[str] = []

    def fake_apply_add_page(output_dir: str, diagnosis: dict, *, git: bool):
        seen.append(diagnosis["proposedFix"]["patch"]["archetype"])
        return {"applied": True, "changes": []}

    monkeypatch.setattr("services.fix_applier._apply_add_page", fake_apply_add_page)

    handle_add_page(_cf(route="/apps/new"), tmp_path)
    handle_add_page(_cf(route="/apps/[id]/edit"), tmp_path)
    handle_add_page(_cf(route="/apps/[id]"), tmp_path)
    handle_add_page(_cf(route="/apps"), tmp_path)

    assert seen == ["create", "edit", "detail", "list"]


def test_handle_add_page_recovers_from_seam_error(monkeypatch, tmp_path):
    def boom(output_dir, diagnosis, *, git):
        raise RuntimeError("simulated seam failure")
    monkeypatch.setattr("services.fix_applier._apply_add_page", boom)

    result = handle_add_page(_cf(route="/x"), tmp_path)
    assert result.ok is False
    assert "simulated seam failure" in (result.error or "")
    assert result.class_name == "missing-page"


# ── handle_router_regen ────────────────────────────────────────────────────


def test_handle_router_regen_calls_pipeline_helper(monkeypatch, tmp_path):
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    called: list[str] = []

    def fake_regen(od: str):
        called.append(od)
        # Simulate the file existing after the call.
        (tmp_path / "src" / "schemas" / "registry.ts").write_text("// stub", encoding="utf-8")

    monkeypatch.setattr(
        "services.schema_pipeline._regenerate_route_registry",
        fake_regen,
    )
    fault = _cf(class_name="catch-all-router-broken",
                seam="deterministic:router-regen")
    result = handle_router_regen(fault, tmp_path)
    assert called == [str(tmp_path)]
    assert result.ok is True
    assert result.fixed is True
    assert any("registry.ts" in p for p in result.files_touched)
    assert result.class_name == "catch-all-router-broken"


def test_handle_router_regen_idempotent(monkeypatch, tmp_path):
    """Calling twice is fine — the helper is idempotent."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    calls: list[int] = []
    def fake_regen(od: str):
        calls.append(1)
        (tmp_path / "src" / "schemas" / "registry.ts").write_text("x", encoding="utf-8")
    monkeypatch.setattr("services.schema_pipeline._regenerate_route_registry", fake_regen)
    handle_router_regen(_cf(), tmp_path)
    handle_router_regen(_cf(), tmp_path)
    assert len(calls) == 2  # each call runs, but the file is the same on-disk


# ── handle_db_migrate ──────────────────────────────────────────────────────


def test_handle_db_migrate_skips_without_config(tmp_path):
    result = handle_db_migrate(
        _cf(class_name="db-schema-mismatch", seam="deterministic:db-migrate"),
        tmp_path,
    )
    assert result.ok is True
    assert "no drizzle.config.ts" in result.summary
    assert result.fixed is False


def test_handle_db_migrate_refuses_without_database_url(monkeypatch, tmp_path):
    (tmp_path / "drizzle.config.ts").write_text("export default {};", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = handle_db_migrate(
        _cf(class_name="db-schema-mismatch", seam="deterministic:db-migrate"),
        tmp_path,
    )
    assert result.ok is False
    assert "DATABASE_URL" in (result.error or "")


def test_handle_db_migrate_runs_drizzle_push(monkeypatch, tmp_path):
    (tmp_path / "drizzle.config.ts").write_text("export default {};", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@y/z")

    calls: list[list[str]] = []
    class FakeProc:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(cmd, cwd=None, env=None, capture_output=None, text=None, timeout=None):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr("services.journey_verifier.deterministic_handlers.subprocess.run", fake_run)
    result = handle_db_migrate(_cf(class_name="db-schema-mismatch"), tmp_path)
    assert result.ok is True
    assert result.fixed is True
    assert calls[0] == ["npx", "drizzle-kit", "push"]


# ── handle_rewire_datasource ───────────────────────────────────────────────


def test_handle_rewire_datasource_patches_schema_json(monkeypatch, tmp_path):
    """A Table node bound to a wrong slug gets rewritten to the canonical one."""
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    page_path = schemas / "applicants.json"
    page_path.write_text(json.dumps({
        "route": "/applicants",
        "children": [
            {"type": "Table", "props": {"dataSource": "applicantsRecent"}},
        ],
    }), encoding="utf-8")

    # Fake the schema-tables reader so we don't need a real drizzle schema.
    def fake_tables(od: str):
        return [{"const": "applicants", "arg": "applicants", "columns": {}}]

    monkeypatch.setattr(
        "services.binding_validator._read_schema_tables", fake_tables,
    )
    fault = _cf(
        route="/applicants",
        class_name="list-empty-data",
        seam="deterministic:rewire-datasource",
        interaction_id="list:/applicants",
    )
    result = handle_rewire_datasource(fault, tmp_path)
    assert result.ok is True
    assert result.fixed is True
    patched = json.loads(page_path.read_text(encoding="utf-8"))
    assert patched["children"][0]["props"]["dataSource"] == "applicants"


def test_handle_rewire_datasource_idempotent(monkeypatch, tmp_path):
    """Second call is a no-op — the slug already matches."""
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    page = {"route": "/applicants",
            "children": [{"type": "Table", "props": {"dataSource": "applicants"}}]}
    page_path = schemas / "applicants.json"
    page_path.write_text(json.dumps(page), encoding="utf-8")

    monkeypatch.setattr(
        "services.binding_validator._read_schema_tables",
        lambda od: [{"const": "applicants", "arg": "applicants", "columns": {}}],
    )
    fault = _cf(route="/applicants", class_name="list-empty-data",
                seam="deterministic:rewire-datasource")
    first = handle_rewire_datasource(fault, tmp_path)
    second = handle_rewire_datasource(fault, tmp_path)
    assert first.fixed is False and "already" in first.summary
    assert second.fixed is False


def test_rewrite_datasource_walks_nested_children():
    page = {
        "children": [
            {"type": "Section", "children": [
                {"type": "Table", "props": {"dataSource": "old"}},
                {"type": "Kanban", "props": {"dataSource": "old"}},
            ]},
        ],
    }
    changed = _rewrite_datasource(page, "new")
    assert changed is True
    assert page["children"][0]["children"][0]["props"]["dataSource"] == "new"
    assert page["children"][0]["children"][1]["props"]["dataSource"] == "new"


# ── handle_orphan_wiring ───────────────────────────────────────────────────


def test_handle_orphan_wiring_calls_pass(monkeypatch, tmp_path):
    calls: list[str] = []
    def fake_wire(od: str):
        calls.append(od)
        return {"wired": [{"workflow": "wfA", "page_route": "/x", "score": 1.0}],
                "unresolved": []}
    monkeypatch.setattr(
        "services.orphan_wiring_pass.wire_orphan_workflows", fake_wire,
    )
    result = handle_orphan_wiring(
        _cf(class_name="form-not-wired", seam="deterministic:orphan-wiring"),
        tmp_path,
    )
    assert result.ok is True
    assert result.fixed is True
    assert "wired=1" in result.summary
    assert calls == [str(tmp_path)]


def test_handle_orphan_wiring_reports_no_wire(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.orphan_wiring_pass.wire_orphan_workflows",
        lambda od: {"wired": [], "unresolved": [{"workflow": "wf", "reason": "nope"}]},
    )
    result = handle_orphan_wiring(_cf(class_name="form-not-wired"), tmp_path)
    assert result.ok is True
    assert result.fixed is False
    assert "wired=0" in result.summary and "unresolved=1" in result.summary


# ── helper coverage ────────────────────────────────────────────────────────


def test_infer_page_kind_variants():
    assert _infer_page_kind("/foo/new") == "create"
    assert _infer_page_kind("/foo/[id]/edit") == "edit"
    assert _infer_page_kind("/foo/[id]") == "detail"
    assert _infer_page_kind("/foo") == "list"
    assert _infer_page_kind("") == "list"


def test_infer_entity_variants():
    assert _infer_entity("/applicants/new") == "applicants"
    assert _infer_entity("/admin/roles/[id]/edit") == "roles"
    assert _infer_entity("/") == ""
