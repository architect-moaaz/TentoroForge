"""Tests for services.binding_smoke — F2: no binding-backed container
ships empty against seed data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.binding_smoke import (
    BindingSmokeError,
    run_binding_smoke,
    smoke_mode,
)


# ── fixture builder ──────────────────────────────────────────────────

def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(
    tmp_path: Path,
    *,
    schemas: dict[str, dict] | None = None,
    seed_plan: dict | None = None,
    tables: list[str] | None = None,   # pgTable names, e.g. ["documents"]
) -> Path:
    root = tmp_path / "app"
    for rel, doc in (schemas or {}).items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    if seed_plan is not None:
        _write(root, "contracts/seed-plan.json", json.dumps(seed_plan))
    lines = []
    for t in tables or []:
        lines.append(
            f'export const {t} = pgTable("{t}", {{\n'
            f'  id: uuid("id").primaryKey(),\n'
            f'  status: varchar("status"),\n'
            f'}});\n'
        )
    _write(root, "src/db/schema/entities.ts", "\n".join(lines))
    return root


def _page(ds: list[dict], binding: str | None = None) -> dict:
    children = []
    if binding:
        children.append({"type": "Table",
                         "props": {"rows": "{{%s}}" % binding, "columns": []}})
    return {"dataSources": ds, "root": {"type": "Stack", "children": children}}


SEEDED = {"tables": [{"name": "Document",
                      "seed_data": [{"id": "1", "status": "complete"},
                                    {"id": "2", "status": "pending"}]}]}
DRY = {"tables": [{"name": "Document", "seed_data": []}]}


# ── core verdicts ────────────────────────────────────────────────────

def test_seeded_consumed_binding_passes(tmp_path: Path):
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    rep = run_binding_smoke(root, mode="warn")
    assert rep["summary"]["error"] == 0
    assert rep["findings"] == []


def test_dry_consumed_binding_errors(tmp_path: Path):
    """The empty-tables class: valid slug, zero seed rows → error."""
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=DRY,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    rep = run_binding_smoke(root, mode="warn")
    assert rep["summary"]["error"] == 1
    f = rep["findings"][0]
    assert f["verdict"] == "empty"
    assert f["route"] == "/documents"


def test_entity_absent_from_seed_plan_errors(tmp_path: Path):
    """Registered entity that the seed plan never mentions — same
    first-paint outcome as zero rows."""
    root = _mk_app(tmp_path, tables=["documents"],
                   seed_plan={"tables": []},
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    assert run_binding_smoke(root, mode="warn")["summary"]["error"] == 1


def test_unconsumed_dry_source_is_info(tmp_path: Path):
    """Nothing renders it → nothing is visibly empty → info only."""
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=DRY,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}])})
    rep = run_binding_smoke(root, mode="warn")
    assert rep["summary"]["error"] == 0
    assert rep["findings"][0]["verdict"] == "empty_unconsumed"
    assert rep["findings"][0]["severity"] == "info"


def test_auth_entity_dry_is_info_not_error(tmp_path: Path):
    """users is deliberately unseeded (signup populates it) — must not
    fail the build."""
    root = _mk_app(tmp_path, tables=["users"],
                   seed_plan={"tables": [{"name": "User", "seed_data": []}]},
                   schemas={"admins.json": _page(
                       [{"name": "users", "entity": "User", "op": "list"}],
                       binding="users")})
    rep = run_binding_smoke(root, mode="warn")
    assert rep["summary"]["error"] == 0
    assert rep["findings"][0]["severity"] == "info"


# ── filters ──────────────────────────────────────────────────────────

def test_eq_filter_surviving_rows_passes(tmp_path: Path):
    page = _page([{"name": "pending", "entity": "Document", "op": "list",
                   "filters": [{"field": "status", "op": "eq", "value": "pending"}]}],
                 binding="pending")
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"inbox.json": page})
    assert run_binding_smoke(root, mode="warn")["summary"]["error"] == 0


def test_eq_filter_killing_all_rows_errors(tmp_path: Path):
    """Rows exist but the filter excludes every one — as empty as no
    rows at all, and invisible to a pure existence check."""
    page = _page([{"name": "archived", "entity": "Document", "op": "list",
                   "filters": [{"field": "status", "op": "eq", "value": "archived"}]}],
                 binding="archived")
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"archive.json": page})
    rep = run_binding_smoke(root, mode="warn")
    assert rep["summary"]["error"] == 1
    assert rep["findings"][0]["verdict"] == "filtered_empty"


def test_binding_valued_filter_not_statically_judged(tmp_path: Path):
    """Filter value is a runtime binding ({{params.id}}) — cannot be
    checked statically; must not fail."""
    page = _page([{"name": "doc", "entity": "Document", "op": "get",
                   "filters": [{"field": "id", "op": "eq",
                                "value": "{{params.id}}"}]}],
                 binding="doc")
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"documents/[id].json": page})
    assert run_binding_smoke(root, mode="warn")["summary"]["error"] == 0


def test_where_dict_shape_supported(tmp_path: Path):
    page = _page([{"name": "archived", "entity": "Document", "op": "list",
                   "where": {"status": "archived"}}],
                 binding="archived")
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"archive.json": page})
    assert run_binding_smoke(root, mode="warn")["findings"][0]["verdict"] == "filtered_empty"


# ── naming tolerance ─────────────────────────────────────────────────

def test_plural_slug_matches_singular_seed_name(tmp_path: Path):
    """The real join: pgTable 'documents' ↔ seed-plan 'Document'."""
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"documents.json": _page(
                       [{"name": "docs", "source": "documents", "op": "list"}],
                       binding="docs")})
    assert run_binding_smoke(root, mode="warn")["summary"]["error"] == 0


def test_sample_data_fallback_counts(tmp_path: Path):
    """seed.ts falls back to the sample_data bag — so do we."""
    plan = {"tables": [{"name": "Document", "seed_data": []}],
            "sample_data": {"Document": [{"id": "1"}]}}
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=plan,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    assert run_binding_smoke(root, mode="warn")["summary"]["error"] == 0


def test_unresolved_ref_left_to_binding_gate(tmp_path: Path):
    """Unknown entity is datasource_unresolved territory — not ours."""
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"x.json": _page(
                       [{"name": "ghosts", "entity": "Ghost", "op": "list"}],
                       binding="ghosts")})
    assert run_binding_smoke(root, mode="warn")["findings"] == []


# ── modes + report ───────────────────────────────────────────────────

def test_off_mode_skips_analysis(tmp_path: Path):
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=DRY,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    rep = run_binding_smoke(root, mode="off")
    assert rep["findings"] == []


def test_strict_mode_raises_on_errors(tmp_path: Path):
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=DRY,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    with pytest.raises(BindingSmokeError):
        run_binding_smoke(root, mode="strict")


def test_strict_mode_passes_clean_app(tmp_path: Path):
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=SEEDED,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    run_binding_smoke(root, mode="strict")  # must not raise


def test_report_written_to_contracts(tmp_path: Path):
    root = _mk_app(tmp_path, tables=["documents"], seed_plan=DRY,
                   schemas={"documents.json": _page(
                       [{"name": "documents", "entity": "Document", "op": "list"}],
                       binding="documents")})
    run_binding_smoke(root, mode="warn")
    rep = json.loads((root / "contracts" / "binding-smoke.json").read_text())
    assert rep["summary"]["error"] == 1


def test_env_mode_default_warn(monkeypatch):
    monkeypatch.delenv("FORGE_BINDING_SMOKE", raising=False)
    assert smoke_mode() == "warn"
    monkeypatch.setenv("FORGE_BINDING_SMOKE", "strict")
    assert smoke_mode() == "strict"
    monkeypatch.setenv("FORGE_BINDING_SMOKE", "bogus")
    assert smoke_mode() == "warn"


def test_empty_app_no_crash(tmp_path: Path):
    rep = run_binding_smoke(tmp_path / "nope", mode="warn")
    assert rep["findings"] == []
