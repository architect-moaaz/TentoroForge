"""Tests for services.plan_writeback — item 7, plan stays the SoT."""
from __future__ import annotations

import json
from pathlib import Path

from services.plan_writeback import write_back_plan


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(tmp_path: Path, *, plan: dict, schemas: dict[str, dict],
            dedup_report: dict | None = None,
            tables: list[str] = ("documents",)) -> Path:
    root = tmp_path / "app"
    lines = [f'export const {t} = pgTable("{t}", {{ id: uuid("id").primaryKey() }});'
             for t in tables]
    _write(root, "src/db/schema/entities.ts", "\n".join(lines))
    _write(root, "src/contracts/plan.json", json.dumps(plan))
    for rel, doc in schemas.items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    if dedup_report is not None:
        _write(root, "contracts/route-dedup.json", json.dumps(dedup_report))
    return root


def _plan_on_disk(root: Path) -> dict:
    return json.loads((root / "src/contracts/plan.json").read_text(encoding="utf-8"))


def _form_page(density: str | None = None) -> dict:
    doc = {"root": {"type": "Stack", "children": [
        {"type": "Form", "props": {"entity": "Document", "fields": []}}]}}
    if density:
        doc["density"] = density
    return doc


def _list_page() -> dict:
    return {"dataSources": [{"name": "documents", "entity": "Document", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"rows": "{{documents}}", "columns": []}}]}}


# ── kind drift ───────────────────────────────────────────────────────

def test_dashboard_vs_form_drift_corrected(tmp_path: Path):
    """The audit case: `/` planned as dashboard, ships as upload form."""
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/", "kind": "dashboard"}]},
                   schemas={"index.json": _form_page()})
    rep = write_back_plan(root)
    assert any(c["field"] == "kind" and c["from"] == "dashboard"
               and c["to"] == "create" for c in rep["changes"])
    assert _plan_on_disk(root)["pages"][0]["kind"] == "create"


def test_synonym_kinds_are_not_drift(tmp_path: Path):
    """upload ↔ create are the same class — vocabulary, not drift."""
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/", "kind": "upload"}]},
                   schemas={"index.json": _form_page()})
    rep = write_back_plan(root)
    assert not any(c["field"] == "kind" for c in rep["changes"])


def test_unknown_plan_kind_left_alone(tmp_path: Path):
    """`wizard` isn't in our vocabulary — unknown intent stays."""
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/", "kind": "wizard"}]},
                   schemas={"index.json": _form_page()})
    rep = write_back_plan(root)
    assert rep["changes"] == [] or all(c["field"] != "kind"
                                       for c in rep["changes"])
    assert _plan_on_disk(root)["pages"][0]["kind"] == "wizard"


def test_missing_kind_backfilled(tmp_path: Path):
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/documents"}]},
                   schemas={"documents.json": _list_page()})
    write_back_plan(root)
    assert _plan_on_disk(root)["pages"][0]["kind"] == "list"


def test_matching_kind_untouched(tmp_path: Path):
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/documents", "kind": "list"}]},
                   schemas={"documents.json": _list_page()})
    rep = write_back_plan(root)
    assert not any(c["field"] == "kind" for c in rep["changes"])


# ── aliases ──────────────────────────────────────────────────────────

def test_dedup_loser_gets_alias_of(tmp_path: Path):
    root = _mk_app(
        tmp_path,
        plan={"pages": [{"route": "/documents/new", "kind": "create"},
                        {"route": "/documents/upload", "kind": "create"}]},
        schemas={"documents/upload.json": _form_page()},
        dedup_report={"collapsed": [{"loser": "/documents/new",
                                     "winner": "/documents/upload"}]},
    )
    write_back_plan(root)
    pages = {p["route"]: p for p in _plan_on_disk(root)["pages"]}
    assert pages["/documents/new"]["alias_of"] == "/documents/upload"
    assert "alias_of" not in pages["/documents/upload"]


# ── density + unshipped ──────────────────────────────────────────────

def test_density_mirrored_to_plan(tmp_path: Path):
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/", "kind": "create"}]},
                   schemas={"index.json": _form_page(density="sparse")})
    write_back_plan(root)
    assert _plan_on_disk(root)["pages"][0]["density"] == "sparse"


def test_unshipped_page_never_removed_or_touched(tmp_path: Path):
    """Missing pages stay in the plan — the gate enforces the promise;
    writeback must never hide it."""
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/admins", "kind": "list"}]},
                   schemas={})
    rep = write_back_plan(root)
    assert rep["changes"] == []
    assert _plan_on_disk(root)["pages"][0] == {"route": "/admins",
                                               "kind": "list"}


# ── record + idempotency ─────────────────────────────────────────────

def test_changes_recorded_in_plan(tmp_path: Path):
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/", "kind": "dashboard"}]},
                   schemas={"index.json": _form_page()})
    write_back_plan(root)
    wb = _plan_on_disk(root)["writeback"]
    assert any(c["field"] == "kind" for c in wb["changes"])


def test_rerun_idempotent(tmp_path: Path):
    root = _mk_app(tmp_path,
                   plan={"pages": [{"route": "/", "kind": "dashboard"}]},
                   schemas={"index.json": _form_page(density="sparse")})
    write_back_plan(root)
    rep2 = write_back_plan(root)
    assert rep2["changes"] == []


def test_missing_plan_no_crash(tmp_path: Path):
    assert write_back_plan(tmp_path / "nope")["changes"] == []
