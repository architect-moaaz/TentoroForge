"""Tests for services.pipeline.source.PlanSource.

The dataclass is immutable + has invariants (figma fields absent on text,
figma_url required on figma). These pin those invariants.
"""
from __future__ import annotations

import pytest

from services.pipeline.source import PlanSource


class TestConstruction:
    def test_text_factory_no_figma_fields(self):
        src = PlanSource.text()
        assert src.kind == "text"
        assert src.is_text
        assert not src.is_figma
        assert src.figma_url is None
        assert src.figma_token is None
        assert src.figma_context is None

    def test_figma_factory_requires_url(self):
        src = PlanSource.figma(url="https://figma.com/file/abc")
        assert src.kind == "figma"
        assert src.is_figma
        assert not src.is_text
        assert src.figma_url == "https://figma.com/file/abc"
        assert src.figma_token is None
        assert src.figma_context is None

    def test_figma_factory_with_token_and_context(self):
        ctx = {"pages": [{"name": "Home"}]}
        src = PlanSource.figma(
            url="https://figma.com/file/abc",
            token="figd_secret",
            context=ctx,
        )
        assert src.figma_url == "https://figma.com/file/abc"
        assert src.figma_token == "figd_secret"
        assert src.figma_context is ctx

    def test_raw_text_construction_rejects_figma_fields(self):
        with pytest.raises(ValueError, match="must not carry figma"):
            PlanSource(kind="text", figma_url="https://figma.com/file/abc")
        with pytest.raises(ValueError, match="must not carry figma"):
            PlanSource(kind="text", figma_token="figd_x")
        with pytest.raises(ValueError, match="must not carry figma"):
            PlanSource(kind="text", figma_context={"a": 1})

    def test_raw_figma_construction_requires_url(self):
        with pytest.raises(ValueError, match="requires figma_url"):
            PlanSource(kind="figma")
        with pytest.raises(ValueError, match="requires figma_url"):
            PlanSource(kind="figma", figma_url="")

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="unknown PlanSource kind"):
            PlanSource(kind="notion")  # type: ignore[arg-type]


class TestImmutability:
    def test_frozen_cannot_mutate_kind(self):
        src = PlanSource.text()
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            src.kind = "figma"  # type: ignore[misc]

    def test_frozen_cannot_mutate_url(self):
        src = PlanSource.figma(url="u")
        with pytest.raises(Exception):
            src.figma_url = "u2"  # type: ignore[misc]


class TestWithContext:
    def test_with_context_returns_new_instance_with_context(self):
        src = PlanSource.figma(url="u", token="t")
        assert src.figma_context is None
        ctx = {"pages": []}
        new_src = src.with_context(ctx)
        assert new_src is not src  # new instance
        assert new_src.figma_context is ctx
        assert new_src.figma_url == "u"
        assert new_src.figma_token == "t"
        # Original unchanged (frozen).
        assert src.figma_context is None

    def test_with_context_on_text_returns_self(self):
        src = PlanSource.text()
        result = src.with_context({"x": 1})
        # No-op — text sources don't carry figma_context.
        assert result is src


class TestReprHidesContext:
    def test_context_absent_from_repr(self):
        # figma_context can be a large dict — the dataclass repr suppresses
        # it so it doesn't fill logs on every SSE event that includes the
        # source.
        big_ctx = {"nodes": [{"i": i} for i in range(500)]}
        src = PlanSource.figma(url="u", context=big_ctx)
        r = repr(src)
        assert "nodes" not in r
        # But url + token identity are visible for debugging.
        assert "u" in r
