"""Tests for services.pipeline.spine.run_pipeline.

The wrapper's contract: dispatch on ``source.kind`` and forward every
arg to the correct legacy implementation. These tests use stubs so no
real pipeline runs — we just verify the dispatch logic + arg forwarding.
"""
from __future__ import annotations

import pytest

from services.pipeline import PlanSource, run_pipeline


class _RecordingStub:
    """Async-generator stub that records how it was called."""

    def __init__(self, name: str, events: list[dict] | None = None):
        self.name = name
        self.events = events or [{"event": "log", "data": '{"text":"stub ran"}'}]
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._gen()

    async def _gen(self):
        for evt in self.events:
            yield evt


@pytest.fixture
def stub_pipelines(monkeypatch):
    """Replace the legacy pipeline functions with recording stubs.

    Returns (text_stub, design_stub). Assert on `.calls[0]` to inspect
    the kwargs the wrapper forwarded.
    """
    from routers import generate as gen_module
    text_stub = _RecordingStub("text")
    design_stub = _RecordingStub("design")
    monkeypatch.setattr(gen_module, "_run_relay_pipeline", text_stub)
    monkeypatch.setattr(gen_module, "_run_design_relay_pipeline", design_stub)
    return text_stub, design_stub


class TestDispatch:
    @pytest.mark.asyncio
    async def test_text_source_routes_to_text_pipeline(self, stub_pipelines):
        text_stub, figma_stub = stub_pipelines
        events = []
        async for evt in run_pipeline(
            output_dir="/tmp/x",
            plan={"a": 1},
            description="build me an app",
            source=PlanSource.text(),
        ):
            events.append(evt)
        assert len(text_stub.calls) == 1
        assert len(figma_stub.calls) == 0
        assert events == [{"event": "log", "data": '{"text":"stub ran"}'}]

    @pytest.mark.asyncio
    async def test_figma_source_routes_to_design_pipeline(self, stub_pipelines):
        text_stub, design_stub = stub_pipelines
        events = []
        async for evt in run_pipeline(
            output_dir="/tmp/x",
            plan={"a": 1},
            description="build from figma",
            source=PlanSource.figma(url="https://figma.com/file/abc", token="tok"),
        ):
            events.append(evt)
        assert len(text_stub.calls) == 0
        assert len(design_stub.calls) == 1

    @pytest.mark.asyncio
    async def test_uxpilot_source_routes_to_the_same_design_pipeline(self, stub_pipelines):
        text_stub, design_stub = stub_pipelines
        async for _ in run_pipeline(
            output_dir="/tmp/x",
            plan={"a": 1},
            description="build from ux pilot",
            source=PlanSource.uxpilot(page_id="pg_1", credential_id="row", secret="ep_k"),
        ):
            pass
        assert len(text_stub.calls) == 0
        assert len(design_stub.calls) == 1
        assert design_stub.calls[0]["source"].kind == "uxpilot"


class TestArgForwarding:
    @pytest.mark.asyncio
    async def test_text_forwards_core_args(self, stub_pipelines):
        text_stub, _ = stub_pipelines
        async for _ in run_pipeline(
            output_dir="/out",
            plan={"p": 1},
            description="d",
            source=PlanSource.text(),
            project_id="proj-1",
            domain_context={"domain": "yoga"},
        ):
            pass
        call = text_stub.calls[0]
        assert call["output_dir"] == "/out"
        assert call["plan"] == {"p": 1}
        assert call["description"] == "d"
        assert call["project_id"] == "proj-1"
        assert call["domain_context"] == {"domain": "yoga"}
        # figma_context is None for a text source; forwarded so the legacy
        # pipeline's signature is satisfied.
        assert call["figma_context"] is None

    @pytest.mark.asyncio
    async def test_design_forwards_the_source_itself(self, stub_pipelines):
        _, design_stub = stub_pipelines
        src = PlanSource.figma(url="https://figma.com/file/xyz", token="figd-x")
        async for _ in run_pipeline(
            output_dir="/out",
            plan={"p": 1},
            description="d",
            source=src,
            project_id="proj-2",
        ):
            pass
        call = design_stub.calls[0]
        assert call["source"] is src
        assert call["source"].figma_url == "https://figma.com/file/xyz"
        assert call["source"].figma_token == "figd-x"
        assert call["project_id"] == "proj-2"

    @pytest.mark.asyncio
    async def test_source_wins_over_loose_figma_kwargs(self, stub_pipelines):
        # If a legacy caller still passes figma_url/figma_token loose,
        # the source's own values take precedence — no accidental drift.
        _, design_stub = stub_pipelines
        async for _ in run_pipeline(
            output_dir="/out",
            plan={},
            description="d",
            source=PlanSource.figma(url="AUTHORITATIVE", token="AUTHORITATIVE_TOKEN"),
            figma_url="loose-should-lose",
            figma_token="loose-should-lose-too",
        ):
            pass
        call = design_stub.calls[0]
        assert "figma_url" not in call
        assert call["source"].figma_url == "AUTHORITATIVE"
        assert call["source"].figma_token == "AUTHORITATIVE_TOKEN"

    @pytest.mark.asyncio
    async def test_absorbs_unknown_extras(self, stub_pipelines):
        # `orchestrate_generation` forwards a bundle of kwargs; the
        # wrapper must not choke on extras it doesn't know.
        text_stub, _ = stub_pipelines
        async for _ in run_pipeline(
            output_dir="/out",
            plan={},
            description="d",
            source=PlanSource.text(),
            user_ask="the user's original prompt",
            some_future_kwarg="anything",
        ):
            pass
        # Stub was still called cleanly.
        assert len(text_stub.calls) == 1


class TestExportSurface:
    def test_run_pipeline_exported_from_package(self):
        # Callers should import from `services.pipeline`, not the
        # `.spine` submodule. Pin that public surface.
        from services.pipeline import run_pipeline as rp
        import services.pipeline.spine as spine_mod
        assert rp is spine_mod.run_pipeline
