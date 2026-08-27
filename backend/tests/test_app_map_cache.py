"""AM-3 — in-process cache keyed by (output_dir, contracts mtime).

The cache exists so injecting the map into every Smith turn is cheap:
build once, then return the same dict identity on every subsequent
turn — unless a contract file has been touched. That's the freshness
contract: writes invalidate; reads are O(1)."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from services import app_map as am


_FIXTURE = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Clear the module-level cache before every test."""
    am.clear_app_map_cache()
    yield
    am.clear_app_map_cache()


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    (tmp_path / "contracts").mkdir()
    for name in ("resource-registry.json", "action-contract.json",
                 "generation-dossier.json"):
        shutil.copy(_FIXTURE / "contracts" / name, tmp_path / "contracts" / name)
    shutil.copy(_FIXTURE / "registry.json", tmp_path / "registry.json")
    shutil.copytree(_FIXTURE / "src" / "schemas", tmp_path / "src" / "schemas")
    return tmp_path


def test_second_call_returns_cached_identity(app_root):
    m1 = am.get_app_map(str(app_root))
    m2 = am.get_app_map(str(app_root))
    assert m1 is m2, "cache should return the exact same dict object"


def test_touching_a_contract_invalidates(app_root):
    m1 = am.get_app_map(str(app_root))
    # Bump mtime forward to ensure change is observable regardless of FS resolution.
    contract = app_root / "contracts" / "resource-registry.json"
    future = time.time() + 5
    os.utime(contract, (future, future))
    m2 = am.get_app_map(str(app_root))
    assert m2 is not m1, "changed mtime must force a rebuild"


def test_writing_a_contract_invalidates(app_root):
    m1 = am.get_app_map(str(app_root))
    # Real write path — simulates a seam like edit_page persisting a change.
    contract = app_root / "contracts" / "action-contract.json"
    data = json.loads(contract.read_text())
    contract.write_text(json.dumps(data, indent=2))
    # Give the fs a nudge on file systems with second-resolution mtimes.
    future = os.stat(contract).st_mtime + 2
    os.utime(contract, (future, future))
    m2 = am.get_app_map(str(app_root))
    assert m2 is not m1


def test_two_different_output_dirs_do_not_share(app_root, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    m1 = am.get_app_map(str(app_root))
    m2 = am.get_app_map(str(other))
    assert m1 is not m2


def test_clear_cache_forces_rebuild(app_root):
    m1 = am.get_app_map(str(app_root))
    am.clear_app_map_cache()
    m2 = am.get_app_map(str(app_root))
    assert m2 is not m1
    # But structurally equivalent — same source, same output.
    assert m1["entities"].keys() == m2["entities"].keys()


def test_missing_output_dir_returns_empty_and_does_not_cache(tmp_path):
    """A path with no contracts still returns the empty shape, and doesn't
    poison the cache — a subsequent write to that dir should be picked up."""
    # First call: empty result (no contracts).
    m1 = am.get_app_map(str(tmp_path))
    assert m1["entities"] == {}
    # Materialize the contracts now.
    (tmp_path / "contracts").mkdir()
    shutil.copy(_FIXTURE / "contracts" / "resource-registry.json",
                tmp_path / "contracts" / "resource-registry.json")
    m2 = am.get_app_map(str(tmp_path))
    assert m2["entities"], "cache must have re-checked once contracts appeared"
