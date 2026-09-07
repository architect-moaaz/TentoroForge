"""The montage producer — the missing half of the composition reference.

Three maquette authors already called ``load_composition_block``. Nothing
ever wrote the file they read, so every montage a user attached reached
exactly nothing: the readers got "" and authored as if no reference existed.

This is the one call that writes it. It runs once per build, before the
authors, and it is the *only* place the vision call happens — three authors
reading one file costs one call, not three.

Everything here is fail-soft by contract. A build with no montage, an
unreadable attachment, or a vision call that errors must behave exactly as
it did before this existed.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.plan_finalize import ensure_composition_reference

_REF = {"layout": "sidebar",
        "screens": {"collection": {"regions": ["table"], "density": "8 columns",
                                   "shape": "table", "columns_target": 8}}}


def _run(coro):
    # asyncio.run, not get_event_loop(): a sibling suite closing the loop
    # would otherwise leave these coroutines unawaited.
    return asyncio.run(coro)


def _written(out) -> Path:
    return Path(out) / "src" / "contracts" / "composition-reference.json"


@pytest.fixture
def montage(monkeypatch):
    """A designated montage + a vision call that returns `_REF`."""
    calls = {"n": 0}
    import services.plan_finalize as pf

    monkeypatch.setattr(pf, "_design_reference_blocks",
                        lambda pid: [{"type": "image"}])

    def _extract(blocks, **kw):
        calls["n"] += 1
        return _REF
    monkeypatch.setattr("services.montage_composition.extract_composition_reference",
                        _extract)
    return calls


class TestItWritesTheFileTheAuthorsRead:
    def test_the_reference_lands_where_load_composition_block_looks(self, tmp_path, montage):
        _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert json.loads(_written(tmp_path).read_text(encoding="utf-8"))["screens"]["collection"]["shape"] == "table"

    def test_the_authors_now_get_a_real_block(self, tmp_path, montage):
        """The end-to-end point: producer writes, reader reads."""
        from services.montage_composition import load_composition_block
        _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        block = load_composition_block({"_output_dir": str(tmp_path)})
        assert "REFERENCE COMPOSITION" in block
        assert "columns=8" in block

    def test_one_vision_call_serves_all_three_authors(self, tmp_path, montage):
        _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert montage["n"] == 1, "re-ran the vision call instead of reusing the file"


class TestNoDesignatedMontageFallsBackToTheBuiltIn:
    """The overwhelmingly common build: nobody attached a reference.

    This used to be the end of the road — no montage meant no reference, so
    the bar applied only to projects that uploaded one, which is none of them.
    It now falls back to the built-in general-business reference
    (:mod:`services.default_composition`). The old behaviour is still
    reachable, but it is now the opt-out rather than the default.
    """

    def test_the_built_in_reference_is_written_instead(self, tmp_path, monkeypatch):
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks", lambda pid: [])
        ref = _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert ref is not None
        assert _written(tmp_path).is_file()

    def test_no_project_id_is_not_an_error(self, tmp_path):
        assert _run(ensure_composition_reference({}, str(tmp_path), None)) is None

    def test_the_readers_get_the_inherited_block(self, tmp_path, monkeypatch):
        from services.montage_composition import load_composition_block
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks", lambda pid: [])
        _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert "REFERENCE COMPOSITION" in load_composition_block(
            {"_output_dir": str(tmp_path)})

    def test_opting_out_restores_the_empty_block(self, tmp_path, monkeypatch):
        """The pre-default contract, still available behind the flag."""
        from services.montage_composition import load_composition_block
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks", lambda pid: [])
        monkeypatch.setenv("FORGE_DEFAULT_MONTAGE", "0")
        assert _run(ensure_composition_reference({}, str(tmp_path), "proj-1")) is None
        assert not _written(tmp_path).exists()
        assert load_composition_block({"_output_dir": str(tmp_path)}) == ""


class TestAFailingMontageNeverFailsTheBuild:
    def test_a_raising_vision_call_is_swallowed(self, tmp_path, monkeypatch):
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks",
                            lambda pid: [{"type": "image"}])

        def _boom(blocks, **kw):
            raise RuntimeError("vision down")
        monkeypatch.setattr("services.montage_composition.extract_composition_reference",
                            _boom)
        assert _run(ensure_composition_reference({}, str(tmp_path), "proj-1")) is None
        assert not _written(tmp_path).exists()

    def test_a_raising_attachment_lookup_is_swallowed(self, tmp_path, monkeypatch):
        import services.plan_finalize as pf

        def _boom(pid):
            raise RuntimeError("attachment store down")
        monkeypatch.setattr(pf, "_design_reference_blocks", _boom)
        assert _run(ensure_composition_reference({}, str(tmp_path), "proj-1")) is None
