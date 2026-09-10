"""SEARCH-2 op:"search" resolver contract.

The runtime data-engine ships ``resolveSearch`` — a full-text query
across one or more entities' ``_search`` tsvector columns (emitted by
schema_builder for every ``search: true`` field). Ranked by ts_rank,
snippet from ts_headline, multi-entity results merged + sorted.

Structural checks over the template source (same shape as
``test_data_engine_aggregations.py``) — vitest is out of scope for the
runtime template dir; the Python schema tests catch regressions in the
emitted TS by string-matching load-bearing shapes.
"""
from pathlib import Path


_RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "backend" / "templates" / "runtime"


def test_data_engine_imports_searchable_columns_manifest():
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    assert 'from "./searchable-columns"' in src
    assert "searchableColumnsFor" in src


def test_resolve_search_exported():
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    assert "export async function resolveSearch(" in src


def test_resolve_search_uses_plainto_tsquery_and_rank():
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    assert "plainto_tsquery('english'" in src
    assert "ts_rank(" in src


def test_resolve_search_ts_headline_for_snippets():
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    # Snippet path uses ts_headline over the primary plaintext column,
    # gated on `snippet !== false` (default on).
    assert "ts_headline(" in src
    assert "wantSnippet" in src


def test_resolve_search_supports_multi_entity_and_merges():
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    # entities[] iteration + rank-sort + limit slice.
    assert "entities.map(async" in src
    assert ".flat()" in src
    assert "merged.sort" in src
    assert "b.rank - a.rank" in src


def test_resolve_search_empty_query_returns_empty():
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    # Empty q → [] (documented behavior, unit-testable by shape).
    assert "if (!q) return [];" in src


def test_resolve_search_uses_parameter_binding_not_string_concat():
    # Every reference to the user query `q` goes through the sql`` tagged
    # template — never string concat into the SQL. The presence of the
    # sql template literal with `${q}` embedded is the invariant.
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    assert "sql`plainto_tsquery('english', ${q})`" in src
    # And no obvious `+ q +` pattern in the resolver.
    resolver_start = src.index("export async function resolveSearch(")
    resolver_end = src.index("// ─── Error Classes ───", resolver_start)
    resolver = src[resolver_start:resolver_end]
    assert "+ q +" not in resolver
    assert '+ q + "' not in resolver


def test_resolve_search_columns_restriction_intersects_manifest():
    # When columns[] is provided, the resolver filters to the intersection
    # with the manifest (never lets the caller query a column that isn't
    # actually searchable — silent skip, never an error).
    src = (_RUNTIME_ROOT / "data-engine.ts").read_text(encoding="utf-8")
    assert "allSearchable.includes" in src
