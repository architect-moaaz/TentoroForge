"""The store carries a design-template pick from the chat phase to the pipeline."""
import asyncio
import json

from services.design_template_store import (
    save_offered, load_offered, save_selection, load_selection, select_by_id,
)
from services.design_templates import HOUSE_TEMPLATES
from agents.design_researcher import research_design_templates


def test_offer_and_select_roundtrip(tmp_path):
    out = str(tmp_path)
    save_offered(out, HOUSE_TEMPLATES)
    assert len(load_offered(out)) == len(HOUSE_TEMPLATES)

    picked = select_by_id(out, HOUSE_TEMPLATES[1]["id"])
    assert picked and picked["id"] == HOUSE_TEMPLATES[1]["id"]
    # persisted + guarded
    sel = load_selection(out)
    assert sel and sel["id"] == HOUSE_TEMPLATES[1]["id"]
    assert sel["palette"]["primary"].startswith("#")


def test_select_unknown_id_returns_none(tmp_path):
    save_offered(str(tmp_path), HOUSE_TEMPLATES)
    assert select_by_id(str(tmp_path), "does-not-exist") is None


def test_no_selection_is_none(tmp_path):
    assert load_selection(str(tmp_path)) is None


def test_researcher_falls_back_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = asyncio.get_event_loop().run_until_complete(
        research_design_templates("dentistry", "clinic management", n=3, use_cache=False))
    assert len(out) == 3
    # falls back to guarded house presets — every one is renderable.
    for t in out:
        assert t["palette"]["primary"].startswith("#")
        assert t["shell"]["frame"] in ("sidebar", "topbar", "rail")


def test_research_cache_roundtrip(monkeypatch):
    from agents import design_researcher as dr
    from services.design_templates import house_templates
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # force miss path if no cache
    key = dr._cache_key("cafe pos", "point of sale for a coffee shop")
    marker = house_templates(3)
    marker[0]["name"] = "CACHED-MARKER"
    dr._cache_set(key, marker)
    try:
        out = asyncio.get_event_loop().run_until_complete(
            dr.research_design_templates("cafe pos", "point of sale for a coffee shop", n=3))
        assert out[0]["name"] == "CACHED-MARKER"   # returned from cache, no research
    finally:
        import os
        os.remove(dr._CACHE_DIR / f"{key}.json")
