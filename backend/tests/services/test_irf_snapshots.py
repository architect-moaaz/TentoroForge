"""IRF substrate snapshots (M7-T1 / M7-T2).

Guards the resolved outputs of the substrate against silent regressions.
Loads each fixture in `backend/tests/snapshots/fixtures/*.json`, runs the
picker / resolver, and diffs the result against the stored baseline in
`backend/tests/snapshots/stored/`.

Update: `SUBSTRATE_SNAPSHOT_UPDATE=1 pytest backend/tests/services/test_irf_snapshots.py`
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.aesthetic_profile_picker import pick as pick_aesthetic

_HERE = Path(__file__).resolve().parent.parent
_FIX_DIR = _HERE / "snapshots" / "fixtures"
_STORE_DIR = _HERE / "snapshots" / "stored"


def _fixtures() -> list[Path]:
    return sorted(_FIX_DIR.glob("*.json"))


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_aesthetic(plan: dict) -> dict:
    return {"picked": pick_aesthetic(plan)}


def _compute_recipes(plan: dict) -> list[str]:
    out = []
    for a in (plan.get("archetypes") or []):
        if isinstance(a, dict):
            r = a.get("recipe")
            out.append(r if isinstance(r, str) else "__capability_composition__")
    return out


def _compute_shape(plan: dict) -> dict:
    return plan.get("app_shape") or {}


COMPUTERS = {
    "aesthetic": _compute_aesthetic,
    "recipes": _compute_recipes,
    "shape": _compute_shape,
}


def _stored_path(name: str, kind: str) -> Path:
    return _STORE_DIR / f"{name}.{kind}.json"


def _write_stored(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _update_enabled() -> bool:
    return os.environ.get("SUBSTRATE_SNAPSHOT_UPDATE") == "1"


@pytest.mark.parametrize("fixture_path", _fixtures(), ids=lambda p: p.stem)
def test_substrate_snapshot(fixture_path: Path) -> None:
    plan = _load_fixture(fixture_path)
    name = fixture_path.stem

    for kind, fn in COMPUTERS.items():
        computed = fn(plan)
        stored_path = _stored_path(name, kind)

        if _update_enabled() or not stored_path.exists():
            _write_stored(stored_path, computed)
            continue

        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        assert computed == stored, (
            f"Snapshot drift for {name}.{kind}. "
            f"Re-run with SUBSTRATE_SNAPSHOT_UPDATE=1 to accept, "
            f"or investigate the substrate change.\n"
            f"stored:   {json.dumps(stored, sort_keys=True)}\n"
            f"computed: {json.dumps(computed, sort_keys=True)}"
        )


def test_all_recipe_references_resolve() -> None:
    """Every recipe named across the 8 anchor fixtures must exist in the recipe catalog."""
    recipes_path = Path(__file__).resolve().parent.parent.parent / "archetypes" / "recipes.json"
    catalog = set((json.loads(recipes_path.read_text(encoding="utf-8")).get("recipes") or {}).keys())
    unknown: set[str] = set()
    for fixture in _fixtures():
        plan = _load_fixture(fixture)
        for r in _compute_recipes(plan):
            if r != "__capability_composition__" and r not in catalog:
                unknown.add(r)
    assert not unknown, f"Anchor fixtures reference unknown recipes: {sorted(unknown)}"


def test_all_runtime_context_bundles_exist() -> None:
    """Every runtime_context named across the anchor fixtures must have a bundle dir."""
    bundles_root = Path(__file__).resolve().parent.parent.parent / "runtime" / "context_bundles"
    known = {p.name for p in bundles_root.iterdir() if p.is_dir()}
    unknown: set[str] = set()
    for fixture in _fixtures():
        plan = _load_fixture(fixture)
        for cap in (plan.get("runtime_context") or []):
            if isinstance(cap, str) and cap not in known:
                unknown.add(cap)
    assert not unknown, f"Anchor fixtures reference unknown runtime bundles: {sorted(unknown)}"
