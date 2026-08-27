"""The manifest may only advertise props the runtime actually accepts.

`library_manifest` feeds `key_props` straight into the page-composer prompt,
where the model treats every listed name as a real prop. It used to union two
sources that speak different vocabularies:

* ``component-contracts.json`` — generated from the components' Zod props.
  This is what the runtime accepts; the registry's strict parse strips
  everything else.
* ``starter.json`` — the visual editor's property-panel catalog, whose
  entries carry editor affordances (``control: "binding"``, ``group: "data"``).

The union advertised ``binding`` on 38 input components whose real prop is
``bind``. The composer obediently emitted ``props.binding``; Zod dropped it
without erroring; every composed edit form rendered with no prefill. Observed
live on 6q7oqejv ``products/[id]/edit.json`` — five fields, all blank.

The page-schema validator did not catch it, because it only checks binding
VALUES resolve, never that prop NAMES exist.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.library_manifest import build_library_manifest

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS = _ROOT / "packages" / "registry" / "dist" / "component-contracts.json"

# Editor-panel names that must never reach a composer as runtime props,
# mapped to the prop the runtime really wants.
EDITOR_ONLY = {"binding": "bind", "validation": "validators"}


def _contracts() -> dict:
    if not _CONTRACTS.is_file():
        pytest.skip("component-contracts.json not built")
    return json.loads(_CONTRACTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict:
    return build_library_manifest()


def _key_prop_names(manifest: dict, comp: str) -> set[str]:
    entry = (manifest.get("components") or {}).get(comp) or {}
    return {p.get("name") for p in (entry.get("key_props") or [])
            if isinstance(p, dict)}


class TestNoGhostProps:
    def test_input_advertises_bind_not_binding(self, manifest):
        names = _key_prop_names(manifest, "Input")
        assert "binding" not in names, (
            "`binding` is an editor control name; the runtime prop is `bind`")
        assert "validation" not in names       # runtime name is `validators`

    def test_no_component_advertises_an_editor_only_name(self, manifest):
        offenders = {
            comp: sorted(_key_prop_names(manifest, comp) & EDITOR_ONLY.keys())
            for comp in (manifest.get("components") or {})
            if _key_prop_names(manifest, comp) & EDITOR_ONLY.keys()
        }
        assert offenders == {}, f"editor-only names leaked: {offenders}"

    def test_every_advertised_prop_exists_in_the_contract(self, manifest):
        """The general invariant — no ghost props of any name."""
        contracts = _contracts()
        ghosts: dict[str, list[str]] = {}
        for comp in (manifest.get("components") or {}):
            entry = contracts.get(comp)
            # A MISSING entry (layout primitives) and an EMPTY one mean the
            # same thing: the extractor produced no usable contract, so the
            # builder legitimately falls back to starter. FadeIn / Stagger
            # land here — their props live behind `FadeInNode.shape.props`
            # in the schema package, an indirection the extractor doesn't
            # follow, so their entry is `{}` even though delay/duration/
            # interval are real. Only a POPULATED contract is authoritative.
            if not isinstance(entry, dict) or not entry:
                continue
            extra = sorted(_key_prop_names(manifest, comp) - set(entry.keys()))
            if extra:
                ghosts[comp] = extra
        assert ghosts == {}, f"props advertised but not in the contract: {ghosts}"


class TestCoverageIsNotLost:
    """Tightening the source must not empty the manifest."""

    def test_contract_backed_components_still_carry_key_props(self, manifest):
        for comp in ("Input", "Select", "Table", "Form"):
            assert _key_prop_names(manifest, comp), f"{comp} lost all key_props"

    def test_layout_primitives_keep_starter_derived_props(self, manifest):
        # These 9 have no contract entry; starter is their only source, so the
        # fallback branch must still populate them.
        comps = manifest.get("components") or {}
        present = [c for c in ("Stack", "Row", "Grid", "Repeat", "Container")
                   if c in comps]
        assert present, "layout primitives missing from the manifest entirely"
        for c in present:
            assert _key_prop_names(manifest, c), f"{c} lost all key_props"
