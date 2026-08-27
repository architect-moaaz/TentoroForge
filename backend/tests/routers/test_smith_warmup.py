"""AM-5 — POST /api/projects/{id}/smith/warmup pre-populates the app-map
cache the frontend fires on chat-panel mount."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_FIXTURE = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")


@pytest.fixture()
def client(tmp_path):
    """TestClient over an isolated OUTPUT_ROOT with the bpxr6hsv contracts
    copied into a project named ``bpxr6hsv``."""
    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    import services.project_paths as pp
    from services import app_map as am
    original = pp.OUTPUT_ROOT
    pp.OUTPUT_ROOT = tmp_path
    am.clear_app_map_cache()
    try:
        # Seed a project on disk under the patched OUTPUT_ROOT.
        pdir = tmp_path / "bpxr6hsv"
        (pdir / "contracts").mkdir(parents=True)
        for name in ("resource-registry.json", "action-contract.json",
                     "generation-dossier.json"):
            shutil.copy(_FIXTURE / "contracts" / name, pdir / "contracts" / name)
        shutil.copy(_FIXTURE / "registry.json", pdir / "registry.json")
        shutil.copytree(_FIXTURE / "src" / "schemas", pdir / "src" / "schemas")

        from main import app
        yield TestClient(app)
    finally:
        pp.OUTPUT_ROOT = original
        am.clear_app_map_cache()


def test_warmup_returns_counts_and_intent(client):
    r = client.post("/api/projects/bpxr6hsv/smith/warmup")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["counts"]["entities"] == 7
    assert body["counts"]["pages"] >= 18
    assert body["counts"]["workflows"] >= 15
    assert "Applicant Tracking System" in body["intent"]


def test_warmup_second_call_hits_cache(client):
    """A second POST must return the same body without re-scanning
    contracts — we verify by asserting the cache holds the same map
    identity."""
    from services.app_map import get_app_map, _APP_MAP_CACHE

    r1 = client.post("/api/projects/bpxr6hsv/smith/warmup")
    assert r1.status_code == 200

    # Grab the cache entry key + map identity now.
    keys_before = list(_APP_MAP_CACHE.keys())
    map_before = _APP_MAP_CACHE[keys_before[0]][1]

    r2 = client.post("/api/projects/bpxr6hsv/smith/warmup")
    assert r2.status_code == 200

    # Same keys, same object identity — no rebuild.
    keys_after = list(_APP_MAP_CACHE.keys())
    assert keys_before == keys_after
    map_after = _APP_MAP_CACHE[keys_after[0]][1]
    assert map_after is map_before


def test_warmup_unknown_project_refuses(client):
    """A project id that neither maps to a short_id on disk nor to a UUID
    in the DB returns 4xx — the router's ``_resolve_root`` raises 400
    for non-UUID misses."""
    r = client.post("/api/projects/does-not-exist/smith/warmup")
    assert r.status_code in (400, 404)
