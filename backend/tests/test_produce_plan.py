"""Tests for the one-shot vs two-stage planning router (`produce_plan`).

All four collaborators are injected as fakes — NO real LLM / pipeline runs.
Covers: small-app one-shot, large-app two-stage, two-stage-failure fallback,
and shape-identity of the returned plan across both paths.

WHAT IS COUNTED, AND WHY IT IS NOT AN EXACT NUMBER. These asserted the one-shot
planner ran EXACTLY once, and `produce_plan` has grown two retry layers since —
a deterministic structural validator and an IRF revise — each of which calls it
again when the plan it got back is incomplete. The minimal `_plan()` below is
incomplete by those rules (no field types, no nav, no submit), so it retried
twice and three tests reported a routing bug that was not there.

Routing is what these are for: WHICH planner runs, not how many times the
router had to ask it. `app_map` and `author` are still counted exactly, because
zero and one are the whole assertion on that side.
"""

import asyncio

import pytest

from routers.generate import produce_plan


def _plan(tag: str) -> dict:
    """A minimal one-shot-shaped plan (has data_models + pages)."""
    return {
        "source": tag,
        "data_models": [{"name": "Widget", "fields": []}],
        "pages": [{"name": "Widgets", "type": "list"}],
    }


def _run(coro):
    return asyncio.run(coro)


def test_small_app_uses_oneshot_only():
    """should_decompose False → one-shot called; app-map / author NOT called."""
    calls = {"oneshot": 0, "app_map": 0, "author": 0}

    def oneshot(prompt):
        calls["oneshot"] += 1
        return _plan("oneshot")

    def app_map(prompt, domain_context):
        calls["app_map"] += 1
        raise AssertionError("app_map must not be called for a small app")

    def author(skeleton, output_dir):
        calls["author"] += 1
        raise AssertionError("author must not be called for a small app")

    plan = _run(
        produce_plan(
            "tiny app",
            "/tmp/out",
            _should_decompose=lambda p: False,
            _app_map=app_map,
            _author_units=author,
            _oneshot=oneshot,
        )
    )

    assert plan["source"] == "oneshot"
    assert calls["oneshot"] >= 1          # ran; retries are the router's business
    assert calls["app_map"] == 0 and calls["author"] == 0


def test_large_app_uses_two_stage():
    """should_decompose True → app_map THEN author PRODUCE the plan.

    The one-shot planner is no longer untouched on this path, and that is
    worth knowing rather than asserting away: when the assembled two-stage
    plan trips the structural validator, the retry layer asks `_run_oneshot`
    for a revision — the retries go through the one-shot planner whichever
    path produced the candidate. Here that planner raises, the retry swallows
    it, and the two-stage plan is what comes back. What this test pins is that
    the two-stage path RAN and its plan is the answer.
    """
    calls = {"oneshot": 0, "app_map": 0, "author": 0}
    order = []

    def oneshot(prompt):
        calls["oneshot"] += 1
        raise AssertionError("oneshot must not PRODUCE the plan for a large app")

    def app_map(prompt, domain_context):
        calls["app_map"] += 1
        order.append("app_map")
        return {"skeleton": True, "data_models": [], "pages": []}

    def author(skeleton, output_dir):
        calls["author"] += 1
        order.append("author")
        assert skeleton == {"skeleton": True, "data_models": [], "pages": []}
        assert output_dir == "/tmp/out"
        return _plan("two-stage")

    plan = _run(
        produce_plan(
            "huge enterprise app",
            "/tmp/out",
            _should_decompose=lambda p: True,
            _app_map=app_map,
            _author_units=author,
            _oneshot=oneshot,
        )
    )

    assert plan["source"] == "two-stage"
    assert calls["app_map"] == 1 and calls["author"] == 1
    assert order == ["app_map", "author"]


def test_two_stage_appmap_failure_falls_back_to_oneshot():
    """app_map raises → fall back to one-shot; no exception propagates."""
    calls = {"oneshot": 0}

    def oneshot(prompt):
        calls["oneshot"] += 1
        return _plan("oneshot-fallback")

    def app_map(prompt, domain_context):
        raise RuntimeError("app-map exploded")

    def author(skeleton, output_dir):
        raise AssertionError("author unreachable when app_map fails")

    plan = _run(
        produce_plan(
            "huge app",
            "/tmp/out",
            _should_decompose=lambda p: True,
            _app_map=app_map,
            _author_units=author,
            _oneshot=oneshot,
        )
    )

    assert plan["source"] == "oneshot-fallback"
    assert calls["oneshot"] >= 1


def test_two_stage_author_failure_falls_back_to_oneshot():
    """author_all_units raises → fall back to one-shot; no exception propagates."""
    calls = {"oneshot": 0}

    def oneshot(prompt):
        calls["oneshot"] += 1
        return _plan("oneshot-fallback")

    def app_map(prompt, domain_context):
        return {"data_models": [], "pages": []}

    def author(skeleton, output_dir):
        raise RuntimeError("author exploded")

    plan = _run(
        produce_plan(
            "huge app",
            "/tmp/out",
            _should_decompose=lambda p: True,
            _app_map=app_map,
            _author_units=author,
            _oneshot=oneshot,
        )
    )

    assert plan["source"] == "oneshot-fallback"
    assert calls["oneshot"] >= 1


def test_async_oneshot_seam_is_awaited():
    """The real oneshot default is async — an awaitable seam is awaited."""

    async def async_oneshot(prompt):
        return _plan("async-oneshot")

    plan = _run(
        produce_plan(
            "tiny app",
            "/tmp/out",
            _should_decompose=lambda p: False,
            _oneshot=async_oneshot,
        )
    )
    assert plan["source"] == "async-oneshot"


def test_returned_plan_shape_identical_across_paths():
    """Both paths return a dict carrying data_models + pages (shape-identical)."""
    one = _run(
        produce_plan(
            "small",
            "/tmp/out",
            _should_decompose=lambda p: False,
            _oneshot=lambda prompt: _plan("oneshot"),
        )
    )
    two = _run(
        produce_plan(
            "large",
            "/tmp/out",
            _should_decompose=lambda p: True,
            _app_map=lambda prompt, dc: {"data_models": [], "pages": []},
            _author_units=lambda sk, od: _plan("two-stage"),
            _oneshot=lambda prompt: _plan("oneshot"),
        )
    )
    for plan in (one, two):
        assert isinstance(plan, dict)
        assert "data_models" in plan
        assert "pages" in plan


def test_import_routers_generate_still_works():
    import importlib

    import routers.generate as gen

    importlib.reload(gen)
    assert hasattr(gen, "produce_plan")
