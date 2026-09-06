"""Tests for services.pipeline.source.PlanSource.

The dataclass is immutable + has invariants (design fields absent on text,
design_ref required on a design kind). These pin those invariants, and the
Figma-era property names routers.generate still reads.
"""
from __future__ import annotations

import pytest

from services.pipeline.source import PlanSource


class TestConstruction:
    def test_text_factory_no_design_fields(self):
        src = PlanSource.text()
        assert src.kind == "text"
        assert src.is_text
        assert not src.is_design
        assert not src.is_figma
        assert not src.is_uxpilot
        assert src.provider is None
        assert src.design_ref is None
        assert src.secret is None
        assert src.design_context is None

    def test_figma_factory_requires_url(self):
        src = PlanSource.figma(url="https://figma.com/file/abc")
        assert src.kind == "figma"
        assert src.is_design and src.is_figma
        assert src.provider == "figma"
        assert src.design_ref == "https://figma.com/file/abc"
        assert src.figma_url == "https://figma.com/file/abc"
        assert src.figma_token is None
        assert src.figma_context is None

    def test_figma_factory_with_token_and_context(self):
        ctx = {"pages": [{"name": "Home"}]}
        src = PlanSource.figma(
            url="https://figma.com/file/abc", token="figd_secret", context=ctx,
        )
        assert src.secret == "figd_secret"
        assert src.figma_token == "figd_secret"
        assert src.design_context is ctx
        assert src.figma_context is ctx

    def test_uxpilot_factory(self):
        src = PlanSource.uxpilot(page_id="pg_1", credential_id="row-9", secret="ep_k")
        assert src.kind == "uxpilot"
        assert src.is_design and src.is_uxpilot and not src.is_figma
        assert src.provider == "uxpilot"
        assert src.design_ref == "pg_1"
        assert src.credential_id == "row-9"
        assert src.secret == "ep_k"
        # The Figma-era names never resolve for another provider — a UX Pilot
        # import must not walk into the Figma REST client.
        assert src.figma_url is None
        assert src.figma_token is None
        assert src.figma_context is None

    def test_raw_text_construction_rejects_design_fields(self):
        with pytest.raises(ValueError, match="must not carry design"):
            PlanSource(kind="text", design_ref="https://figma.com/file/abc")
        with pytest.raises(ValueError, match="must not carry design"):
            PlanSource(kind="text", secret="figd_x")
        with pytest.raises(ValueError, match="must not carry design"):
            PlanSource(kind="text", design_context={"a": 1})
        with pytest.raises(ValueError, match="must not carry design"):
            PlanSource(kind="text", credential_id="row")

    def test_raw_design_construction_requires_ref(self):
        with pytest.raises(ValueError, match="requires design_ref"):
            PlanSource(kind="figma")
        with pytest.raises(ValueError, match="requires design_ref"):
            PlanSource(kind="uxpilot", design_ref="")

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="unknown PlanSource kind"):
            PlanSource(kind="notion")  # type: ignore[arg-type]


class TestImmutability:
    def test_frozen_cannot_mutate_kind(self):
        src = PlanSource.text()
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            src.kind = "figma"  # type: ignore[misc]

    def test_frozen_cannot_mutate_ref(self):
        src = PlanSource.figma(url="u")
        with pytest.raises(Exception):
            src.design_ref = "u2"  # type: ignore[misc]


class TestWithContext:
    def test_with_context_returns_new_instance_with_context(self):
        src = PlanSource.figma(url="u", token="t")
        ctx = {"pages": []}
        new_src = src.with_context(ctx)
        assert new_src is not src
        assert new_src.design_context is ctx
        assert new_src.design_ref == "u"
        assert new_src.secret == "t"
        assert src.design_context is None

    def test_with_context_keeps_kind_and_credential(self):
        src = PlanSource.uxpilot(page_id="p", credential_id="c")
        new_src = src.with_context({"x": 1})
        assert new_src.kind == "uxpilot"
        assert new_src.credential_id == "c"

    def test_with_context_on_text_returns_self(self):
        src = PlanSource.text()
        assert src.with_context({"x": 1}) is src


class TestReprHidesSecrets:
    def test_context_and_secret_absent_from_repr(self):
        big_ctx = {"nodes": [{"i": i} for i in range(500)]}
        src = PlanSource.figma(url="u", token="figd_hidden", context=big_ctx)
        r = repr(src)
        assert "nodes" not in r
        assert "figd_hidden" not in r
        assert "u" in r
