"""Verify design_agent populates entityPhotos on the saved design spec."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.design_agent import _populate_entity_photos


def test_populate_entity_photos_calls_picker_per_entity():
    entities = [
        {"name": "User", "kind": "person"},
        {"name": "Property", "kind": "thing"},
    ]
    calls = []
    def fake_picker(entity_name, domain, size="1600x900"):
        calls.append((entity_name, domain))
        return f"https://images.unsplash.com/photo-{entity_name.lower()}"
    with patch("agents.design_agent.pick_photo_for", side_effect=fake_picker):
        result = _populate_entity_photos(entities, domain="real-estate")
    assert ("User", "real-estate") in calls
    assert ("Property", "real-estate") in calls
    assert result["User"].startswith("https://images.unsplash.com/")
    assert result["Property"].startswith("https://images.unsplash.com/")


def test_populate_entity_photos_handles_empty_list():
    with patch("agents.design_agent.pick_photo_for"):
        result = _populate_entity_photos([], domain="saas")
    assert result == {}


def test_populate_entity_photos_skips_on_picker_error():
    """If the picker raises for one entity, others should still succeed."""
    entities = [{"name": "User"}, {"name": "BadEntity"}, {"name": "Property"}]
    def fake_picker(entity_name, domain, size="1600x900"):
        if entity_name == "BadEntity":
            raise RuntimeError("network down")
        return f"https://images.unsplash.com/photo-{entity_name.lower()}"
    with patch("agents.design_agent.pick_photo_for", side_effect=fake_picker):
        result = _populate_entity_photos(entities, domain="saas")
    assert "User" in result
    assert "Property" in result
    assert "BadEntity" not in result


def test_populate_entity_photos_dedups_by_entity_name():
    """Duplicate entity names in the plan should only fire one picker call."""
    entities = [{"name": "User"}, {"name": "User"}]
    calls = []
    def fake_picker(entity_name, domain, size="1600x900"):
        calls.append(entity_name)
        return "https://images.unsplash.com/photo-x"
    with patch("agents.design_agent.pick_photo_for", side_effect=fake_picker):
        _populate_entity_photos(entities, domain="saas")
    assert calls.count("User") == 1
