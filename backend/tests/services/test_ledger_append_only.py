"""Tests for the Slice-3 ledger contract: an entity flagged
``lifecycle == "append_only"`` produces an IMMUTABLE surface end-to-end.

The contract, tested seam-by-seam:

  1. **Plan validator** accepts ``lifecycle: "append_only"`` and rejects any
     other lifecycle value that isn't ``"crud"`` or unset.
  2. **schema_builder** omits the auto-``updatedAt`` column and stamps a
     ledger comment at the top of the emitted table. It still emits every
     planner-declared column.
  3. **schema_builder** writes ``src/lib/append-only-entities.ts`` — the
     manifest the Data Engine catch-all reads to 405 PUT/DELETE.
  4. **resource_registry** propagates the ``lifecycle`` flag onto the
     entity record so downstream guards read it without re-parsing the plan.
  5. **ensure_edit_routes** skips append-only entities, so no phantom
     ``/entity/:id/edit`` route lands on disk.
  6. **detail_action_guard** refuses to wire Edit/Delete buttons on
     detail pages whose entity is append-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from services import ensure_edit_routes as eer
from services import plan_validator
from services.resource_registry import build_canonical_registry
from services.schema_builder import build_schema_files


# ── Seam 1a: plan_validator lifecycle rule ─────────────────────────────────

def _ledger_plan() -> dict:
    return {
        "entities": {
            "Transaction": {
                "table": "transactions",
                "lifecycle": "append_only",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "amount", "type": "money"},
                    {"name": "description", "type": "text"},
                ],
            },
        }
    }


def test_validator_accepts_append_only_lifecycle():
    v = plan_validator.validate_plan(_ledger_plan())
    lifecycle_violations = [x for x in v if x["rule"] == "entity_lifecycle_unknown"]
    assert lifecycle_violations == []


def test_validator_accepts_crud_lifecycle_and_absent():
    for lc in ("crud", None, "", ...):  # explicit crud, None, "", or omitted
        plan = _ledger_plan()
        if lc is ...:
            plan["entities"]["Transaction"].pop("lifecycle", None)
        else:
            plan["entities"]["Transaction"]["lifecycle"] = lc
        v = plan_validator.validate_plan(plan)
        lifecycle_violations = [x for x in v if x["rule"] == "entity_lifecycle_unknown"]
        assert lifecycle_violations == [], f"lifecycle={lc!r} should not violate"


def test_validator_rejects_unknown_lifecycle():
    for bad in ("immutable", "audit", "readonly", "read_only", "history"):
        plan = _ledger_plan()
        plan["entities"]["Transaction"]["lifecycle"] = bad
        v = plan_validator.validate_plan(plan)
        lifecycle_violations = [x for x in v if x["rule"] == "entity_lifecycle_unknown"]
        assert len(lifecycle_violations) == 1, f"{bad!r} should violate exactly once"
        assert lifecycle_violations[0]["severity"] == "error"
        assert "Transaction" in lifecycle_violations[0]["message"]


# ── Seam 1b: schema_builder omits updatedAt for ledgers ────────────────────

def _plan_for_builder(lifecycle: str | None) -> dict:
    ent: dict = {
        "name": "Transaction",
        "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "amount", "type": "money"},
            {"name": "description", "type": "text"},
        ],
    }
    if lifecycle is not None:
        ent["lifecycle"] = lifecycle
    return {"data_models": [ent]}


def test_schema_builder_omits_updated_at_for_append_only(tmp_path):
    build_schema_files(_plan_for_builder("append_only"), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    # createdAt still emitted — every ledger row needs an insertion timestamp.
    assert 'createdAt: timestamp("created_at")' in src
    # updatedAt MUST NOT be auto-appended.
    assert "updatedAt" not in src
    assert 'timestamp("updated_at")' not in src
    # Money sibling still emitted (Slice-2 contract intact).
    assert 'amount_currency: char("amount_currency", { length: 3 })' in src


def test_schema_builder_default_crud_still_emits_updated_at(tmp_path):
    build_schema_files(_plan_for_builder(None), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    assert 'updatedAt: timestamp("updated_at")' in src


def test_schema_builder_stamps_ledger_comment(tmp_path):
    build_schema_files(_plan_for_builder("append_only"), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    # The header comment makes the contract legible to a human reader.
    assert "APPEND-ONLY LEDGER" in src


# ── Seam 1c: append-only manifest emitted ──────────────────────────────────

def test_manifest_emitted_with_append_only_names(tmp_path):
    build_schema_files(_plan_for_builder("append_only"), str(tmp_path))
    manifest = (tmp_path / "src" / "lib" / "append-only-entities.ts").read_text()
    assert "APPEND_ONLY_ENTITIES" in manifest
    assert "isAppendOnly" in manifest
    # Every reachable name should be in the set — Pascal, snake_case table,
    # and both lowercase forms — so a lookup never misses.
    assert '"Transaction"' in manifest
    assert '"transaction"' in manifest
    assert '"transactions"' in manifest


def test_manifest_still_emitted_when_no_append_only(tmp_path):
    """Empty Set — but the file always exists so the template's static
    import never 404s."""
    build_schema_files(_plan_for_builder(None), str(tmp_path))
    manifest_path = tmp_path / "src" / "lib" / "append-only-entities.ts"
    assert manifest_path.is_file()
    manifest = manifest_path.read_text()
    assert "APPEND_ONLY_ENTITIES: ReadonlySet<string> = new Set([" in manifest
    # No entity names — only the export scaffold.
    assert '"Transaction"' not in manifest


# ── Seam 1d: resource_registry propagates lifecycle ───────────────────────

def test_resource_registry_propagates_lifecycle():
    reg = build_canonical_registry(_ledger_plan())
    tx = reg["entities"]["Transaction"]
    assert tx.get("lifecycle") == "append_only"


def test_resource_registry_omits_lifecycle_for_crud_entities():
    plan = _ledger_plan()
    plan["entities"]["Transaction"].pop("lifecycle", None)
    reg = build_canonical_registry(plan)
    tx = reg["entities"]["Transaction"]
    assert "lifecycle" not in tx


# ── Seam 2: ensure_edit_routes skips append-only ──────────────────────────

def _bootstrap_app(root: Path) -> Path:
    """Lay down a minimal generated-app tree with a registry + a `new.json`
    for two entities: Transaction (append-only) + Note (crud). The `new.json`
    Form workflow name is what ``ensure_edit_routes`` reads to resolve the
    entity — mirroring the real generator's convention."""
    sdir = root / "src" / "schemas"
    (sdir / "transactions").mkdir(parents=True)
    (sdir / "notes").mkdir(parents=True)
    (sdir / "transactions" / "new.json").write_text(json.dumps({
        "route": "/transactions/new",
        "root": {"type": "Form", "props": {"workflow": "CreateTransaction"},
                  "children": []},
    }))
    (sdir / "notes" / "new.json").write_text(json.dumps({
        "route": "/notes/new",
        "root": {"type": "Form", "props": {"workflow": "CreateNote"},
                  "children": []},
    }))
    contracts = root / "src" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "registry.json").write_text(json.dumps({
        "entities": {
            "Transaction": {"lifecycle": "append_only", "table": "transactions",
                             "slug": "transactions", "fields": {}},
            "Note": {"table": "notes", "slug": "notes", "fields": {}},
        }
    }))
    return sdir


def test_ensure_edit_routes_skips_append_only(tmp_path):
    sdir = _bootstrap_app(tmp_path)
    eer.ensure_edit_routes(str(tmp_path))
    # Note gets its edit route synthesised.
    assert (sdir / "notes" / "[id]" / "edit.json").is_file()
    # Transaction does NOT — its edit route would 405 on save.
    assert not (sdir / "transactions" / "[id]" / "edit.json").is_file()


def test_append_only_names_reads_from_registry(tmp_path):
    _bootstrap_app(tmp_path)
    names = eer._append_only_names(str(tmp_path))
    # Registry entry gets normalised into every reachable form.
    assert "Transaction" in names
    assert "transaction" in names
    assert "transactions" in names
    # Non-append-only entities are absent.
    assert "Note" not in names
    assert "notes" not in names


def test_append_only_names_falls_back_to_manifest(tmp_path):
    """Even with no registry.json, the ts-side manifest is authoritative
    enough to power the guard."""
    lib_dir = tmp_path / "src" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "append-only-entities.ts").write_text(
        'export const APPEND_ONLY_ENTITIES: ReadonlySet<string> = new Set([\n'
        '  "Transaction",\n  "transactions",\n]);\n'
    )
    names = eer._append_only_names(str(tmp_path))
    assert "Transaction" in names
    assert "transactions" in names
