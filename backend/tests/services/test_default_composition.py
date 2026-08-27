"""The built-in reference must be legal, and it must actually reach an app.

Encoding a montage as data buys determinism and review, but it also means the
values are hand-written and can rot: rename a hero kind in the maquette layer
and this file would go on recommending a shape the schema rejects, silently,
because no vision call is there to be constrained by the live vocabulary.
So the drift guard below checks every typed value against the modules that
own those vocabularies — the same ones the extractor clamps against.

The second half is the point of the whole exercise: a build that designates
no montage should still inherit a bar. That was the gap — the reference layer
worked but nothing in the product designates a montage, so it applied to
nobody.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.default_composition import (
    DEFAULT_COMPOSITION_REFERENCES,
    default_composition_reference,
    default_montage_enabled,
)
from services.montage_composition import (
    _COUNT_FIELDS, _ENUM_FIELDS, _enums, composition_targets,
    render_composition_block,
)
from services.plan_finalize import ensure_composition_reference


def _run(coro):
    return asyncio.run(coro)


class TestTheReferenceIsSchemaLegal:
    """Same clamping contract the extractor applies to a live vision call."""

    def test_every_enum_value_exists_in_the_owning_vocabulary(self):
        enums = _enums()
        assert enums, "maquette vocabularies unavailable — cannot verify"
        for name, ref in DEFAULT_COMPOSITION_REFERENCES.items():
            for kind, spec in ref["screens"].items():
                for field, vocab_key in _ENUM_FIELDS.get(kind, ()):
                    if field not in spec:
                        continue
                    allowed = enums[vocab_key]
                    assert spec[field] in allowed, (
                        f"{name}/{kind}.{field}={spec[field]!r} is not in {allowed}")

    def test_every_count_is_inside_its_renderable_range(self):
        for name, ref in DEFAULT_COMPOSITION_REFERENCES.items():
            for kind, spec in ref["screens"].items():
                for field, lo, hi in _COUNT_FIELDS.get(kind, ()):
                    if field not in spec:
                        continue
                    assert lo <= spec[field] <= hi, f"{name}/{kind}.{field} out of range"

    def test_no_colour_leaks_into_a_composition_reference(self):
        """Colour belongs to the picked design option, not to a montage."""
        assert "#" not in json.dumps(DEFAULT_COMPOSITION_REFERENCES)

    def test_only_screen_kinds_the_maquette_layer_authors(self):
        for ref in DEFAULT_COMPOSITION_REFERENCES.values():
            assert set(ref["screens"]) <= {"dashboard", "collection", "record"}

    def test_it_renders_to_a_prompt_block_with_targets(self):
        block = render_composition_block(default_composition_reference())
        assert "REFERENCE COMPOSITION" in block
        assert "columns=7" in block
        assert "kpis=5" in block


class TestEveryAppInheritsTheBar:
    """The gap this closes: nothing in the product designates a montage."""

    @pytest.fixture(autouse=True)
    def _no_designated_montage(self, monkeypatch):
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks", lambda pid: [])

    def test_a_build_with_no_montage_still_gets_a_reference(self, tmp_path):
        ref = _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert ref is not None
        assert (tmp_path / "src" / "contracts"
                / "composition-reference.json").is_file()

    def test_the_gate_can_read_the_inherited_targets(self, tmp_path):
        _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert composition_targets(str(tmp_path))["collection"]["columns_target"] == 7

    def test_the_default_is_not_shared_mutable_state(self, tmp_path):
        """One build editing the reference must not poison the next."""
        a = _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        a["screens"]["collection"]["columns_target"] = 99
        assert default_composition_reference()["screens"]["collection"]["columns_target"] == 7


class TestItYieldsToARealMontageAndToTheFlag:
    def test_a_designated_montage_wins_over_the_default(self, tmp_path, monkeypatch):
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks",
                            lambda pid: [{"type": "image"}])
        monkeypatch.setattr(
            "services.montage_composition.extract_composition_reference",
            lambda blocks, **kw: {"layout": "theirs", "screens": {
                "collection": {"regions": ["t"], "density": "d",
                               "columns_target": 4}}})
        ref = _run(ensure_composition_reference({}, str(tmp_path), "proj-1"))
        assert ref["layout"] == "theirs"
        assert ref["screens"]["collection"]["columns_target"] == 4

    def test_the_flag_restores_the_no_reference_behaviour(
            self, tmp_path, monkeypatch):
        import services.plan_finalize as pf
        monkeypatch.setattr(pf, "_design_reference_blocks", lambda pid: [])
        monkeypatch.setenv("FORGE_DEFAULT_MONTAGE", "0")
        assert not default_montage_enabled()
        assert _run(ensure_composition_reference({}, str(tmp_path), "proj-1")) is None
        assert not (tmp_path / "src" / "contracts"
                    / "composition-reference.json").exists()
