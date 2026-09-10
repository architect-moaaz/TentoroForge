"""Concurrent page-composer prefetch (CREATIVE-6c).

The prefetch is only worth anything if the key it stores is the key the
per-page path later asks for. Most of these tests exist to pin that one
invariant from different angles, because a silent key mismatch would
look exactly like success — same logs, same output, same wall-clock.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import page_composer_pipeline as P


# ------------------------------------------------------------------ #
# Fixtures / doubles
# ------------------------------------------------------------------ #

class _Vocab:
    id = "test-vocab"

    def model_dump(self):
        return {"id": self.id}


class _Preset:
    id = "test-preset"

    def model_dump(self):
        return {"id": self.id}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv(P.FLAG_ENV, "1")
    monkeypatch.delenv(P.CONCURRENCY_ENV, raising=False)
    P._reset_manifest_cache_for_tests()
    yield
    P._reset_manifest_cache_for_tests()


@pytest.fixture
def app(tmp_path: Path) -> Path:
    (tmp_path / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": [
            {"route": "/bills", "title": "Bills", "entity": "bills"},
            {"route": "/members", "title": "Members", "entity": "members"},
        ],
    }), encoding="utf-8")
    return tmp_path


@pytest.fixture
def stub_inputs(monkeypatch):
    """Pin the run-scoped inputs so key computation is deterministic."""
    monkeypatch.setattr(P, "_get_library_manifest", lambda: {"components": {"Table": {}}})
    monkeypatch.setattr(P, "_load_vocab_and_preset", lambda *a, **k: (_Vocab(), _Preset()))


def _pages(n: int = 3) -> list[dict]:
    return [
        {"id": f"p{i}", "route": f"/r{i}", "kind": "list", "entity": f"e{i}",
         "title": f"T{i}", "description": ""}
        for i in range(n)
    ]


# ------------------------------------------------------------------ #
# The invariant: prefetch writes the key the single-page path reads
# ------------------------------------------------------------------ #

def test_prefetched_page_is_a_cache_hit_for_the_single_page_path(app, stub_inputs, monkeypatch):
    """The whole point. Prefetch one page, then ask for it the normal
    way: it must resolve from cache and never reach the LLM."""
    page = _pages(1)[0]
    composed = {"root": {"type": "Stack", "children": []}}

    calls = {"n": 0}

    async def _fake_compose(*a, **k):
        calls["n"] += 1
        return dict(composed), {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _fake_compose)

    stats = P.prefetch_pages_via_pipeline_sync([page], {}, app)
    assert stats["composed"] == 1
    assert calls["n"] == 1

    # Now the per-page path — must NOT call compose_page again.
    schema, prov = P.compose_page_via_pipeline_sync(page, {}, app)
    assert schema is not None
    assert prov["source"] == "cached"
    assert calls["n"] == 1, "single-page path recomputed a prefetched page"


def test_prefetch_skips_pages_already_cached(app, stub_inputs, monkeypatch):
    """A re-run must not re-pay for work already on disk."""
    page = _pages(1)[0]

    async def _fake(*a, **k):
        return {"root": {"type": "Stack"}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _fake)
    P.prefetch_pages_via_pipeline_sync([page], {}, app)

    calls = {"n": 0}

    async def _counting(*a, **k):
        calls["n"] += 1
        return {"root": {}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _counting)
    stats = P.prefetch_pages_via_pipeline_sync([page], {}, app)
    assert stats["cached"] == 1
    assert stats["composed"] == 0
    assert calls["n"] == 0


# ------------------------------------------------------------------ #
# Concurrency + isolation
# ------------------------------------------------------------------ #

def test_runs_concurrently_not_serially(app, stub_inputs, monkeypatch):
    """Observe real overlap rather than trusting the code shape: track
    how many calls are in flight at once and assert it exceeds 1."""
    inflight = {"now": 0, "peak": 0}

    async def _slow(*a, **k):
        inflight["now"] += 1
        inflight["peak"] = max(inflight["peak"], inflight["now"])
        await asyncio.sleep(0.05)
        inflight["now"] -= 1
        return {"root": {"type": "Stack"}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _slow)
    stats = P.prefetch_pages_via_pipeline_sync(_pages(6), {}, app, concurrency=3)
    assert stats["composed"] == 6
    assert inflight["peak"] > 1, "compositions never overlapped"
    assert inflight["peak"] <= 3, f"semaphore breached: peak={inflight['peak']}"


def test_concurrency_of_one_is_strictly_sequential(app, stub_inputs, monkeypatch):
    """The documented escape hatch back to old behaviour."""
    inflight = {"now": 0, "peak": 0}

    async def _slow(*a, **k):
        inflight["now"] += 1
        inflight["peak"] = max(inflight["peak"], inflight["now"])
        await asyncio.sleep(0.01)
        inflight["now"] -= 1
        return {"root": {}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _slow)
    P.prefetch_pages_via_pipeline_sync(_pages(4), {}, app, concurrency=1)
    assert inflight["peak"] == 1


def test_one_failure_does_not_abort_the_batch(app, stub_inputs, monkeypatch):
    """A single flaky page must not cost the other 84 their compositions."""
    async def _flaky(page, *a, **k):
        if page.get("route") == "/r1":
            raise RuntimeError("boom")
        return {"root": {"type": "Stack"}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _flaky)
    stats = P.prefetch_pages_via_pipeline_sync(_pages(3), {}, app)
    assert stats["composed"] == 2
    assert stats["failed"] == 1


def test_failures_are_never_persisted(app, stub_inputs, monkeypatch):
    """A failed composition must not stick as the cached answer — the
    next attempt has to be free to succeed."""
    async def _fail(*a, **k):
        return None, {"source": "failed", "reason": "llm_error"}

    monkeypatch.setattr(P, "compose_page", _fail)
    P.prefetch_pages_via_pipeline_sync(_pages(2), {}, app)

    cache = app / "contracts" / P.CACHE_FILENAME
    if cache.exists():
        assert json.loads(cache.read_text(encoding="utf-8")) == {}, "a failure was cached"


def test_flag_off_never_calls_the_llm(app, monkeypatch):
    monkeypatch.delenv(P.FLAG_ENV, raising=False)

    async def _boom(*a, **k):
        raise AssertionError("composer called with the flag off")

    monkeypatch.setattr(P, "compose_page", _boom)
    stats = P.prefetch_pages_via_pipeline_sync(_pages(3), {}, app)
    assert stats["composed"] == 0
    assert stats["skipped"] == 3


def test_missing_inputs_degrade_without_raising(app, monkeypatch):
    """Vocab pipeline down → prefetch reports failure and returns; the
    appliers then compose per page exactly as they did before."""
    monkeypatch.setattr(P, "_load_vocab_and_preset", lambda *a, **k: (None, None))
    stats = P.prefetch_pages_via_pipeline_sync(_pages(2), {}, app)
    assert stats["failed"] == 2
    assert stats["composed"] == 0


def test_pages_without_a_route_are_ignored(app, stub_inputs, monkeypatch):
    async def _fake(*a, **k):
        return {"root": {}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _fake)
    stats = P.prefetch_pages_via_pipeline_sync(
        [{"id": "no-route"}, {"route": "/ok", "kind": "list"}], {}, app,
    )
    assert stats["requested"] == 1


# ------------------------------------------------------------------ #
# Disk-cache memo
# ------------------------------------------------------------------ #

def test_disk_cache_memo_avoids_reparsing(app, monkeypatch):
    path = app / "contracts" / P.CACHE_FILENAME
    P._write_disk_cache(path, {"k": {"schema": {}}})

    reads = {"n": 0}
    real_read = Path.read_text

    def _counting_read(self, *a, **k):
        if self == path:
            reads["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _counting_read)
    for _ in range(5):
        assert P._load_disk_cache(path) == {"k": {"schema": {}}}
    assert reads["n"] == 0, "memo did not serve the repeat reads"


def test_disk_cache_memo_invalidates_on_external_write(app):
    path = app / "contracts" / P.CACHE_FILENAME
    P._write_disk_cache(path, {"a": 1})
    assert P._load_disk_cache(path) == {"a": 1}

    import os, time
    path.write_text(json.dumps({"b": 2}), encoding="utf-8")
    # Force a distinct mtime — some filesystems have coarse resolution.
    os.utime(path, (time.time() + 2, time.time() + 2))
    assert P._load_disk_cache(path) == {"b": 2}


# ------------------------------------------------------------------ #
# Maquette wrapper
# ------------------------------------------------------------------ #

def test_prefetch_maquette_pages_converts_entries(app, stub_inputs, monkeypatch):
    """Entries reach the composer as page dicts carrying the plan's
    title, not just the maquette's bare route."""
    seen: list[dict] = []

    async def _capture(page, *a, **k):
        seen.append(page)
        return {"root": {}}, {"source": "composed", "changes": {}}

    monkeypatch.setattr(P, "compose_page", _capture)
    entries = [{"route": "/bills", "entity": "bills"}, {"route": "/members", "entity": "members"}]
    stats = P.prefetch_maquette_pages(app, entries, "list")

    assert stats["composed"] == 2
    assert {p["route"] for p in seen} == {"/bills", "/members"}
    assert {p["title"] for p in seen} == {"Bills", "Members"}
    assert all(p["kind"] == "list" for p in seen)


def test_prefetch_maquette_pages_survives_a_bad_output_dir(stub_inputs):
    stats = P.prefetch_maquette_pages("/definitely/not/here", [{"route": "/x"}], "list")
    assert stats["composed"] == 0
