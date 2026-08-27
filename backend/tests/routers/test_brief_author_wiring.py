"""Brief authoring must actually run on non-Figma builds.

Regression: ``_author_and_persist_brief`` documented an LLM authoring path
but never called one. Every prompt-based generation assigned ``brief = None``
and then hit ``brief.model_dump_json()``, so brief authoring raised
AttributeError 100% of the time. It was caught as "non-fatal", so the run
continued with no ``contracts/brief.json`` — leaving ``brief_consume``
nothing to read. ``design_brief_author.author`` had zero non-test callers.
"""
import json
from pathlib import Path

import pytest

import routers.generate as g


PLAN = {
    "entities": {"Session": {}, "Bill": {}},
    "pages": [{"type": "dashboard"}, {"type": "list"}],
}


class _FakePalette:
    """The Figma branch logs ``brief.palette.brand`` and counts
    ``locked_fields`` — a double without them raises inside the try and the
    outer except swallows it, which looks exactly like the bug under test."""
    brand = "#123456"
    locked_fields: tuple = ()


class _FakeBrief:
    def __init__(self, tag="llm"):
        self.tag = tag
        self.visual_lock = None
        self.palette = _FakePalette()

    def model_dump_json(self, indent=None):
        return json.dumps({"authored_by": self.tag}, indent=indent)


@pytest.fixture(autouse=True)
def _brief_author_on(monkeypatch):
    monkeypatch.setenv("FORGE_BRIEF_AUTHOR", "1")


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_non_figma_build_authors_and_persists_a_brief(tmp_path, monkeypatch):
    """The bug: this wrote nothing and logged an AttributeError."""
    called = {}

    async def _fake_author(domain, *, plan_summary="", **kw):
        called["domain"] = domain
        called["plan_summary"] = plan_summary
        return _FakeBrief()

    monkeypatch.setattr(
        "services.design_brief_author.author", _fake_author, raising=True,
    )
    _run(g._author_and_persist_brief(
        str(tmp_path), {"domain": "Legislative"}, PLAN, figma_context=None,
    ))

    written = tmp_path / "contracts" / "brief.json"
    assert written.is_file(), "no brief.json written for a non-Figma build"
    assert json.loads(written.read_text())["authored_by"] == "llm"
    assert called["domain"] == "Legislative"
    # The plan must reach the author — grounding is the whole point.
    assert "Session" in called["plan_summary"]


def test_author_failure_degrades_without_raising(tmp_path, monkeypatch):
    """A brief failure must never take the build down — that is what the
    original except-block intended, and the None-guard now honours."""
    from services.design_brief_author import BriefAuthorError

    async def _boom(domain, **kw):
        raise BriefAuthorError("LLM unreachable")

    monkeypatch.setattr(
        "services.design_brief_author.author", _boom, raising=True,
    )
    _run(g._author_and_persist_brief(
        str(tmp_path), {"domain": "Legislative"}, PLAN, figma_context=None,
    ))

    assert not (tmp_path / "contracts" / "brief.json").exists()


def test_flag_off_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_BRIEF_AUTHOR", "0")

    async def _never(domain, **kw):
        raise AssertionError("author must not run when the flag is off")

    monkeypatch.setattr(
        "services.design_brief_author.author", _never, raising=True,
    )
    _run(g._author_and_persist_brief(
        str(tmp_path), {"domain": "X"}, PLAN, figma_context=None,
    ))
    assert not (tmp_path / "contracts").exists()


def test_figma_path_still_wins_and_skips_the_llm(tmp_path, monkeypatch):
    """Figma-sourced projects keep the deterministic aggregator — the new
    LLM branch must only fire when nothing else produced a brief."""
    async def _never(domain, **kw):
        raise AssertionError("LLM author must not run when Figma succeeded")

    monkeypatch.setattr(
        "services.design_brief_author.author", _never, raising=True,
    )
    monkeypatch.setattr(
        "services.brief_from_figma.brief_from_figma",
        lambda ctx, domain=None: _FakeBrief("figma"),
        raising=True,
    )
    _run(g._author_and_persist_brief(
        str(tmp_path), {"domain": "X"}, PLAN,
        figma_context={"design_tokens": {"color": {"brand": "#123456"}}},
    ))

    written = tmp_path / "contracts" / "brief.json"
    assert written.is_file()
    assert json.loads(written.read_text())["authored_by"] == "figma"
