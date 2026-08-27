"""Tests for the peer-patcher generation helpers."""
import json
import tempfile
from pathlib import Path

from services.peer_patcher_helpers import (
    load_current_artifacts, commit_artifacts,
    registry_snapshot, registry_digest, token_vocabulary,
)


def test_load_returns_none_for_empty_project():
    with tempfile.TemporaryDirectory() as td:
        assert load_current_artifacts(td) is None


def test_commit_then_load_round_trips():
    artifacts = {
        "pageSchemas": {
            "home": {
                "schemaVersion": "2", "id": "home", "route": "/",
                "root": {"id": "n1", "type": "Stack",
                         "children": [{"id":"n2","type":"Text","props":{"text":"hi"}}]},
            }
        },
        "navFlow": {
            "version": "1.0", "initialPage": "home",
            "pages": [{"id":"home","route":"/","title":"Home",
                       "schemaFile":"src/schemas/home.json","params":[]}],
            "transitions": [], "guards": {},
        },
        "tokens": {"color":{"brand":{"primary":"#13A8A8"}},"typography":{},"spacing":{},
                   "radius":{},"shadow":{},"motion":{},"breakpoints":{}},
    }
    with tempfile.TemporaryDirectory() as td:
        commit_artifacts(td, artifacts)
        loaded = load_current_artifacts(td)
        assert loaded is not None
        assert "home" in loaded["pageSchemas"]
        assert loaded["pageSchemas"]["home"]["root"]["id"] == "n1"
        assert loaded["navFlow"]["initialPage"] == "home"


def test_registry_digest_includes_common_components():
    d = registry_digest()
    assert "Stack" in d
    assert "Hero" in d
    assert "Button" in d


def test_token_vocabulary_handles_null_current():
    v = token_vocabulary(None)
    assert "color.brand.primary" in v


def test_token_vocabulary_from_existing_tokens():
    current = {"tokens": {"color": {"brand": {"primary": "#13A8A8"}}, "spacing": {"md": 16}}}
    v = token_vocabulary(current)
    assert "color.brand.primary" in v
    assert "spacing.md" in v
