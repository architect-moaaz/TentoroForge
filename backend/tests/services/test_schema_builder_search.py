"""SEARCH-1 full-text search: schema-builder contract for `search: true`.

The deterministic schema builder emits, for every column flagged
``search: true``, a companion ``<name>_search`` tsvector column
(``GENERATED ALWAYS AS to_tsvector('english', coalesce(<name>,''))
STORED``) plus a GIN index on that column. The runtime Data Engine reads
``src/lib/searchable-columns.ts`` (also emitted here) at op:"search"
resolution time to know which entities carry which searchable columns.

Mirrors the shape of ``test_schema_builder_sensitive.py`` (Slice 4) and
``test_schema_builder_money.py`` (Slice 2).
"""
from __future__ import annotations

from services.plan_validator import validate_plan
from services.schema_builder import (
    build_schema_files,
    _is_search_field,
    _search_column_name,
)


def _plan(fields: list[dict],
          entity_name: str = "Document",
          table_name: str = "documents") -> dict:
    return {
        "data_models": [
            {
                "name": entity_name,
                "table": table_name,
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    *fields,
                ],
            }
        ]
    }


# ── unit-level: name derivations + predicate ────────────────────────────────


def test_search_column_name_variants():
    assert _search_column_name("content") == "content_search"
    assert _search_column_name("title") == "title_search"
    # Idempotent — already-suffixed name is left alone.
    assert _search_column_name("content_search") == "content_search"


def test_is_search_field_predicate():
    assert _is_search_field({"name": "content", "type": "text", "search": True})
    assert not _is_search_field({"name": "content", "type": "text"})
    assert not _is_search_field({"name": "content", "type": "text", "search": False})
    assert not _is_search_field(None)  # type: ignore[arg-type]


# ── validator: type + sensitive-conflict guards ─────────────────────────────


def test_validator_accepts_search_on_text():
    plan = _plan([{"name": "content", "type": "text", "search": True}])
    violations = [v for v in validate_plan(plan) if v["rule"].startswith("search_")]
    assert violations == []


def test_validator_accepts_search_on_varchar():
    plan = _plan([{"name": "title", "type": "varchar", "search": True}])
    violations = [v for v in validate_plan(plan) if v["rule"].startswith("search_")]
    assert violations == []


def test_validator_rejects_search_on_numeric():
    plan = _plan([{"name": "amount", "type": "numeric", "search": True}])
    violations = [v for v in validate_plan(plan) if v["rule"] == "search_field_type_unsupported"]
    assert len(violations) == 1
    assert "amount" in violations[0]["message"]
    assert "numeric" in violations[0]["message"]


def test_validator_rejects_search_on_jsonb():
    plan = _plan([{"name": "payload", "type": "jsonb", "search": True}])
    rules = {v["rule"] for v in validate_plan(plan)}
    assert "search_field_type_unsupported" in rules


def test_validator_rejects_search_on_uuid():
    plan = _plan([{"name": "ref", "type": "uuid", "search": True}])
    rules = {v["rule"] for v in validate_plan(plan)}
    assert "search_field_type_unsupported" in rules


def test_validator_rejects_search_on_boolean():
    plan = _plan([{"name": "flag", "type": "boolean", "search": True}])
    rules = {v["rule"] for v in validate_plan(plan)}
    assert "search_field_type_unsupported" in rules


def test_validator_rejects_search_on_timestamp():
    plan = _plan([{"name": "ts", "type": "timestamp", "search": True}])
    rules = {v["rule"] for v in validate_plan(plan)}
    assert "search_field_type_unsupported" in rules


def test_validator_rejects_sensitive_plus_search_conflict():
    # A GIN-indexed tsvector on plaintext defeats encrypt-at-rest — a
    # SELECT-holding attacker can enumerate the value via narrowing tsquery
    # matches. Structural incompatibility, not just a lint.
    plan = _plan(
        [{"name": "content", "type": "text",
          "search": True, "sensitive": True, "mask": "full"}],
        entity_name="Vault", table_name="vaults",
    )
    # Ensure the entity declares readers so the sensitive rule doesn't
    # emit its own ambiguity error — we're testing search+sensitive here.
    plan["data_models"][0]["sensitiveReaders"] = ["admin"]
    violations = validate_plan(plan)
    rules = {v["rule"] for v in violations}
    assert "search_field_sensitive_conflict" in rules


# ── integration: build_schema_files against a real plan ────────────────────


def test_search_column_emitted_as_tsvector_generated(tmp_path):
    build_schema_files(
        _plan([{"name": "content", "type": "text", "search": True}]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "documents.ts").read_text()
    # tsvector customType is declared once per file, then used.
    assert 'customType<{ data: string }>({ dataType: () => "tsvector" })' in src
    # The `_search` column exists as tsvector, GENERATED ALWAYS AS to_tsvector.
    assert 'content_search: tsvector("content_search")' in src
    assert "generatedAlwaysAs(sql`to_tsvector('english'" in src
    assert "coalesce(content, '')" in src
    # sql template + customType + index imports all present.
    assert 'import { sql } from "drizzle-orm";' in src
    assert "customType" in src
    assert "index" in src


def test_search_column_emits_gin_index(tmp_path):
    build_schema_files(
        _plan([{"name": "content", "type": "text", "search": True}]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "documents.ts").read_text()
    # Third-arg callback carries the GIN index on the _search column.
    assert '}, (t) => ({' in src
    assert 'index("documents_content_search_idx").using("gin", t.content_search)' in src


def test_search_multi_column_emits_two_indexes(tmp_path):
    build_schema_files(
        _plan([
            {"name": "content", "type": "text", "search": True},
            {"name": "title", "type": "varchar", "search": True},
        ]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "documents.ts").read_text()
    # Two independent _search columns, two GIN indexes.
    assert 'content_search: tsvector' in src
    assert 'title_search: tsvector' in src
    assert 'documents_content_search_idx' in src
    assert 'documents_title_search_idx' in src


def test_no_search_column_leaves_pgtable_unchanged(tmp_path):
    build_schema_files(
        _plan([{"name": "title", "type": "text"}]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "documents.ts").read_text()
    # No tsvector, no GIN index, no third-arg pgTable callback.
    assert "tsvector" not in src
    assert "using(\"gin\"" not in src
    # The default 2-arg pgTable form.
    assert 'pgTable("documents", {' in src
    assert "}, (t) => ({" not in src


def test_search_idempotent_when_plan_predeclares_search_name(tmp_path):
    # A plan already carrying `content_search` should not double-emit
    # (would yield content_search_search).
    build_schema_files(
        _plan([{"name": "content_search", "type": "text", "search": True}]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "documents.ts").read_text()
    assert "content_search_search" not in src


# ── integration: searchable-columns.ts manifest ────────────────────────────


def test_manifest_emitted_with_column_lists(tmp_path):
    build_schema_files(
        _plan([
            {"name": "content", "type": "text", "search": True},
            {"name": "title", "type": "varchar", "search": True},
        ]),
        str(tmp_path),
    )
    manifest = (tmp_path / "src" / "lib" / "searchable-columns.ts").read_text()
    assert "SEARCHABLE_COLUMNS" in manifest
    assert "hasSearchableColumns" in manifest
    assert "searchableColumnsFor" in manifest
    # Original plaintext names appear in the array (the resolver appends _search).
    assert '"content"' in manifest
    assert '"title"' in manifest
    # Every reachable name form of the entity resolves.
    assert '"Document":' in manifest
    assert '"document":' in manifest
    assert '"documents":' in manifest


def test_manifest_still_emitted_when_no_search_columns(tmp_path):
    build_schema_files(
        _plan([{"name": "title", "type": "text"}]),
        str(tmp_path),
    )
    p = tmp_path / "src" / "lib" / "searchable-columns.ts"
    assert p.is_file()
    manifest = p.read_text()
    assert "SEARCHABLE_COLUMNS: Record<string, string[]>" in manifest
    assert '"Document":' not in manifest


def test_manifest_normalises_predeclared_search_suffix(tmp_path):
    # A field pre-declared as `content_search` still maps in the manifest
    # under the base key `content` — the runtime always references the
    # ORIGINAL plaintext column.
    build_schema_files(
        _plan([{"name": "content_search", "type": "text", "search": True}]),
        str(tmp_path),
    )
    manifest = (tmp_path / "src" / "lib" / "searchable-columns.ts").read_text()
    # Base key present; suffixed key absent.
    assert '"content"' in manifest
    assert '"content_search"' not in manifest


# ── coexistence with other slices ─────────────────────────────────────────


def test_search_plays_nice_with_append_only(tmp_path):
    # Append-only ledger + search column: schema still omits updatedAt,
    # still emits the _search tsvector + GIN index, still lands in both
    # manifests.
    plan = _plan(
        [{"name": "description", "type": "text", "search": True}],
        entity_name="Transaction",
        table_name="transactions",
    )
    plan["data_models"][0]["lifecycle"] = "append_only"
    build_schema_files(plan, str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    assert "APPEND-ONLY LEDGER" in src
    assert "updatedAt" not in src
    assert "description_search: tsvector" in src
    assert "transactions_description_search_idx" in src
    ao_manifest = (tmp_path / "src" / "lib" / "append-only-entities.ts").read_text()
    assert '"Transaction"' in ao_manifest
    s_manifest = (tmp_path / "src" / "lib" / "searchable-columns.ts").read_text()
    assert '"Transaction":' in s_manifest
