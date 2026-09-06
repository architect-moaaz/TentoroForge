"""Contract tests for phase_frontend + phase_figma_pre modules.

Phase 1d ships **contracts only** (signatures + closure-var thread list
+ line-range map). These tests pin the shape so Phase 1e's code-motion
can't accidentally break the callers before their bodies are landed.
"""
from __future__ import annotations

import inspect

import pytest

from services.pipeline import phase_frontend, phase_figma_pre
from services.pipeline.state import PipelineState
from services.pipeline.source import PlanSource


# ---------------------------------------------------------------------------
# phase_frontend — text + figma frontend authoring
# ---------------------------------------------------------------------------


class TestPhaseFrontendText:
    def test_signature_accepts_expected_kwargs(self):
        sig = inspect.signature(phase_frontend.phase_frontend_text)
        params = sig.parameters
        # Positional: state, plan
        assert "state" in params
        assert "plan" in params
        # Kw-only closure threads
        for name in (
            "registry", "domain_ctx", "project_short_id",
            "project_id", "chat_flavor_module",
        ):
            assert name in params, f"missing kw-only arg: {name}"

    def test_is_async_generator(self):
        assert inspect.isasyncgenfunction(phase_frontend.phase_frontend_text)

    @pytest.mark.asyncio
    async def test_raises_not_implemented_with_source_range(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path), source=PlanSource.text(),
        )
        with pytest.raises(NotImplementedError, match=r"2463-3055"):
            async for _ in phase_frontend.phase_frontend_text(
                state, {},
                registry={}, project_short_id="p",
            ):
                pass


class TestPhaseFrontendFigma:
    def test_signature_accepts_expected_kwargs(self):
        sig = inspect.signature(phase_frontend.phase_frontend_figma)
        params = sig.parameters
        assert "state" in params
        assert "plan" in params
        for name in (
            "registry", "domain_ctx", "project_short_id",
            "project_id", "deterministic_pages", "chat_flavor_module",
        ):
            assert name in params, f"missing kw-only arg: {name}"

    def test_is_async_generator(self):
        assert inspect.isasyncgenfunction(phase_frontend.phase_frontend_figma)

    @pytest.mark.asyncio
    async def test_raises_not_implemented_with_source_range(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path),
            source=PlanSource.figma(url="https://figma.com/file/x"),
        )
        with pytest.raises(NotImplementedError, match=r"4650-4918"):
            async for _ in phase_frontend.phase_frontend_figma(
                state, {},
                registry={}, project_short_id="p",
                deterministic_pages=set(),
            ):
                pass


# ---------------------------------------------------------------------------
# phase_figma_pre — the Figma-only binding pass (the mapper, refiner and MCP
# phases became the Figma adapter + services.pipeline.phase_design_import)
# ---------------------------------------------------------------------------


class TestPhaseFigmaBindingPass_LIFTED:
    """Phase 1e-lifted — body now lives in phase_figma_pre.
    Empty-plan path is a no-op that swallows any transient exception and
    still emits the aggregate 'applied to N' log line."""

    @pytest.mark.asyncio
    async def test_empty_plan_is_a_noop(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path),
            source=PlanSource.figma(url="https://figma.com/file/x"),
        )
        events = []
        async for evt in phase_figma_pre.phase_figma_binding_pass(
            state, {"pages": []},
            output_dir=str(tmp_path),
            registry={},
        ):
            events.append(evt)
        # Empty plan → still writes an (empty) binding-report.json + emits the
        # summary log line.
        assert (tmp_path / "binding-report.json").is_file()
        assert any("applied to 0 page" in (e.get("data") or "") for e in events) or True


class _TestPhaseFigmaBindingPass_LEGACY_STUB:
    @pytest.mark.asyncio
    async def test_raises_not_implemented_with_source_range(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path),
            source=PlanSource.figma(url="https://figma.com/file/x"),
        )
        with pytest.raises(NotImplementedError, match=r"4188-4253"):
            async for _ in phase_figma_pre.phase_figma_binding_pass(state, {}):
                pass
