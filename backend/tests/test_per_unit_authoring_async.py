"""Task 3a — parallel per-page authoring for smith-arch.

Before: `author_all_units` is sequential, per its docstring. For a
20-page ATS at ~15-30s per page, that's 5-10 minutes just for units.
After: `author_all_units_async` fans out with `asyncio.gather` bounded
by a semaphore. Wall-clock ≈ slowest single page, not sum.

Tests here don't hit Anthropic — they inject a fake `_query` with a
controllable delay so we can measure that concurrency actually kicks in.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from services.per_unit_authoring import (
    author_all_units_async,
    author_page_detail_async,
)


def _form_page(route: str, entity: str = "Thing") -> dict:
    return {
        "id":        route.strip("/").replace("/", "-") or "page",
        "route":     route,
        "archetype": "form",
        "entity":    entity,
        "name":      route,
    }


def _crud_list_page(route: str) -> dict:
    """No archetype triggers the LLM path → short-circuits, no _query call."""
    return {"id": route.strip("/"), "route": route, "archetype": "list",
            "entity": "Thing", "name": route}


def _fake_query_factory(response_kind: str = "fields", per_call_delay: float = 0.05):
    """Return a fake ``_query`` that emits a well-formed response after
    ``per_call_delay`` seconds. Records every call for concurrency
    inspection."""
    calls: list[tuple[float, str]] = []

    async def _q(system: str, user: str) -> str:
        started = time.perf_counter()
        await asyncio.sleep(per_call_delay)
        calls.append((started, user[:40]))
        return json.dumps({
            response_kind: [
                {"name": "foo", "control": "Input", "semanticType": "text"},
            ]
        })

    _q.calls = calls  # type: ignore[attr-defined]
    return _q


# ── async twin sanity ──────────────────────────────────────────────

def test_author_page_detail_async_returns_enriched_page(tmp_path):
    q = _fake_query_factory()
    page = _form_page("/things/new", "Thing")
    result = asyncio.run(author_page_detail_async(page, str(tmp_path), _query=q))
    assert "fields" in result
    assert result["fields"][0]["name"] == "foo"


def test_author_page_detail_async_skips_crud_page(tmp_path):
    """A routine list page short-circuits — no LLM call at all."""
    q = _fake_query_factory()
    page = _crud_list_page("/things")
    result = asyncio.run(author_page_detail_async(page, str(tmp_path), _query=q))
    assert result == page
    assert q.calls == []


def test_author_page_detail_async_swallows_query_errors(tmp_path):
    async def _boom(_s: str, _u: str) -> str:
        raise RuntimeError("upstream down")
    page = _form_page("/things/new")
    result = asyncio.run(author_page_detail_async(page, str(tmp_path), _query=_boom))
    # Falls back to skeleton page — no exception propagated.
    assert result == page


def test_author_page_detail_async_malformed_response_falls_back(tmp_path):
    async def _q(_s: str, _u: str) -> str:
        return "not json at all"
    page = _form_page("/things/new")
    result = asyncio.run(author_page_detail_async(page, str(tmp_path), _query=_q))
    assert result == page


# ── parallel authoring — the whole point ──────────────────────────

def test_author_all_units_async_runs_pages_concurrently(tmp_path):
    """Fan-out proof: 6 pages at 200ms each should complete in ~200-400ms
    wall-clock, not 1200ms (which would be sequential). Concurrency
    default is 6, so all 6 pages run at once."""
    skeleton = {
        "data_models": [{"name": "Thing", "fields": []}],
        "pages": [_form_page(f"/things/{i}/new") for i in range(6)],
    }
    q = _fake_query_factory(per_call_delay=0.2)
    started = time.perf_counter()
    result = asyncio.run(author_all_units_async(
        skeleton, str(tmp_path), _query=q, concurrency=6,
    ))
    elapsed = time.perf_counter() - started

    assert elapsed < 0.7, (
        f"parallel authoring should complete in ~0.2s (concurrency=6, 6 pages), "
        f"took {elapsed:.2f}s — falling back to sequential?"
    )
    assert len(result["pages"]) == 6
    for p in result["pages"]:
        assert "fields" in p


def test_author_all_units_async_respects_concurrency_bound(tmp_path):
    """Concurrency=2 with 4 pages at 200ms each should take ~400ms
    (two batches of two), not 200ms (fully parallel) or 800ms (all
    sequential)."""
    skeleton = {
        "data_models": [{"name": "Thing", "fields": []}],
        "pages": [_form_page(f"/things/{i}/new") for i in range(4)],
    }
    q = _fake_query_factory(per_call_delay=0.2)
    started = time.perf_counter()
    asyncio.run(author_all_units_async(
        skeleton, str(tmp_path), _query=q, concurrency=2,
    ))
    elapsed = time.perf_counter() - started

    # Two batches: 0.35s <= elapsed <= 0.65s
    assert 0.3 < elapsed < 0.7, (
        f"concurrency=2 with 4×0.2s pages should take ~0.4s wall-clock, "
        f"got {elapsed:.2f}s"
    )


def test_author_all_units_async_emits_per_unit_events(tmp_path):
    """Each completed page emits one ``unit_authored`` event that the
    frontend renders as a chip."""
    events: list[tuple[str, dict]] = []

    def _emit(stage: str, payload: dict) -> None:
        events.append((stage, payload))

    skeleton = {
        "data_models": [{"name": "Thing", "fields": []}],
        "pages": [_form_page(f"/things/{i}/new") for i in range(3)],
    }
    q = _fake_query_factory(per_call_delay=0.02)
    asyncio.run(author_all_units_async(
        skeleton, str(tmp_path), _query=q, emit_fn=_emit,
    ))

    unit_events = [e for e in events if e[0] == "unit_authored"]
    assert len(unit_events) == 3
    assert all(e[1]["completed"] <= e[1]["total"] == 3 for e in unit_events)
    assert {e[1]["completed"] for e in unit_events} == {1, 2, 3}


def test_author_all_units_async_per_unit_timeout_falls_back(tmp_path):
    """A hung page can't stall the whole batch."""
    slow_delay = 5.0
    async def _slow(_s: str, _u: str) -> str:
        await asyncio.sleep(slow_delay)
        return json.dumps({"fields": []})

    skeleton = {
        "data_models": [{"name": "Thing", "fields": []}],
        "pages": [_form_page("/things/hung/new")],
    }
    started = time.perf_counter()
    result = asyncio.run(author_all_units_async(
        skeleton, str(tmp_path), _query=_slow, per_unit_timeout_sec=0.1,
    ))
    elapsed = time.perf_counter() - started

    # Timed out well under the 5-second delay.
    assert elapsed < 1.0, f"per_unit_timeout should abort quickly, took {elapsed:.2f}s"
    # Skeleton page returned as fallback.
    assert result["pages"][0]["route"] == "/things/hung/new"
    assert "fields" not in result["pages"][0]


def test_author_all_units_async_one_bad_page_doesnt_break_others(tmp_path):
    """One page's query raises; the batch still returns all pages
    with the bad one falling back to skeleton form."""
    async def _q(system: str, user: str) -> str:
        if "bad" in user:
            raise RuntimeError("boom")
        return json.dumps({"fields": [{"name": "ok"}]})

    skeleton = {
        "data_models": [{"name": "Thing", "fields": []}],
        "pages": [
            _form_page("/things/good/new"),
            _form_page("/things/bad/new"),
            _form_page("/things/other/new"),
        ],
    }
    result = asyncio.run(author_all_units_async(
        skeleton, str(tmp_path), _query=_q,
    ))
    routes = {p["route"]: p for p in result["pages"]}
    assert "fields" in routes["/things/good/new"]
    assert "fields" not in routes["/things/bad/new"]   # skeleton fallback
    assert "fields" in routes["/things/other/new"]


def test_author_all_units_async_preserves_non_page_plan_sections(tmp_path):
    """Result shape must be plan-shape-identical to a one-shot plan:
    data_models, workflows, actors etc. carry through unchanged."""
    skeleton = {
        "actors":      [{"name": "Candidate"}],
        "data_models": [{"name": "Thing", "fields": []}],
        "workflows":   [{"name": "wf", "steps": []}],
        "pages":       [_crud_list_page("/things")],
    }
    q = _fake_query_factory()
    result = asyncio.run(author_all_units_async(
        skeleton, str(tmp_path), _query=q,
    ))
    assert result["actors"]      == skeleton["actors"]
    assert result["data_models"] == skeleton["data_models"]
    assert result["workflows"]   == skeleton["workflows"]
    assert result["pages"]       == skeleton["pages"]  # list page short-circuited


def test_author_all_units_async_empty_pages_returns_shape(tmp_path):
    skeleton = {"data_models": [], "pages": []}
    result = asyncio.run(author_all_units_async(skeleton, str(tmp_path)))
    assert result["pages"] == []


def test_author_all_units_async_none_skeleton_returns_verbatim(tmp_path):
    """Defensive — a non-dict skeleton passes through, never raises."""
    assert asyncio.run(author_all_units_async("not a dict", str(tmp_path))) == "not a dict"  # type: ignore
