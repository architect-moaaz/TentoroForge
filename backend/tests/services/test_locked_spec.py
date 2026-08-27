"""Tests for services.locked_spec — Layer 1 extraction correctness.

These tests pin the expected extraction on the two prompts we care about
most: the visual-product-search app (the one nni3wjf6 was over-generated
for) and a simple TODO app (regression against under-extraction).
"""
from __future__ import annotations

import pytest

from services.locked_spec import (
    Actor,
    Entity,
    ExternalDep,
    Feature,
    LockedSpec,
    build_locked_spec,
    extract_actors,
    extract_entities,
    extract_externals,
    extract_features,
    load_locked_spec,
    persist_locked_spec,
)


VISUAL_PRODUCT_SEARCH = (
    "Mobile-first app where a user scans a product with their phone camera "
    "or uploads an image. The app identifies the exact or similar-looking "
    "product using AI, then shows price comparison across retailers using "
    "the Firecrawl web-search MCP with tappable links to each seller. "
    "Admin can control the retailer allow-list (enable/disable, priority). "
    "Store scan history per user."
)


TODO_APP = "A simple todo app where users can add, complete, and delete tasks."


# ---------- actors --------------------------------------------------------

def test_actors_visual_product_search_has_user_and_admin():
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    roles = {a.role for a in actors}
    assert "user" in roles
    assert "admin" in roles


def test_actors_todo_app_has_only_user():
    actors = extract_actors(TODO_APP)
    roles = {a.role for a in actors}
    assert roles == {"user"}


# ---------- entities ------------------------------------------------------

def test_entities_visual_product_search_includes_retailer_and_scan():
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    names = {e.name for e in entities}
    # Retailer is a managed entity — admin CRUDs allow-list.
    assert "Retailer" in names
    # Scan is an event — user scans a product, we record scans.
    assert "Scan" in names


def test_entities_scan_is_event_kind():
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    scan = next(e for e in entities if e.name == "Scan")
    assert scan.kind == "event"


def test_entities_retailer_is_managed_entity_kind():
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    retailer = next(e for e in entities if e.name == "Retailer")
    assert retailer.kind == "entity"


def test_entities_todo_has_task():
    actors = extract_actors(TODO_APP)
    entities = extract_entities(TODO_APP, actors)
    names = {e.name for e in entities}
    assert "Task" in names
    task = next(e for e in entities if e.name == "Task")
    assert task.kind == "entity"


def test_entities_never_include_actors():
    """User/Admin/etc must show up in actors[], never in entities[]."""
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    names_lower = {e.name.lower() for e in entities}
    assert "user" not in names_lower
    assert "admin" not in names_lower
    assert "customer" not in names_lower


# ---------- features ------------------------------------------------------

def test_features_visual_product_search_covers_scan_upload_admin():
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    features = extract_features(VISUAL_PRODUCT_SEARCH, actors, entities)
    verbs = {f.verb for f in features}
    assert "scan" in verbs
    assert "upload" in verbs
    assert "compare" in verbs
    assert "manage" in verbs  # admin manages allow-list


def test_features_admin_owns_manage_action():
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    features = extract_features(VISUAL_PRODUCT_SEARCH, actors, entities)
    manage_features = [f for f in features if f.verb == "manage"]
    assert manage_features, "expected at least one manage feature"
    assert any(f.actor == "admin" for f in manage_features), \
        "admin should own the manage feature"


def test_features_add_auth_when_per_user():
    """'Store scan history per user' implies auth is needed."""
    actors = extract_actors(VISUAL_PRODUCT_SEARCH)
    entities = extract_entities(VISUAL_PRODUCT_SEARCH, actors)
    features = extract_features(VISUAL_PRODUCT_SEARCH, actors, entities)
    verbs = {f.verb for f in features}
    assert "auth" in verbs


def test_features_todo_covers_add_complete_delete():
    actors = extract_actors(TODO_APP)
    entities = extract_entities(TODO_APP, actors)
    features = extract_features(TODO_APP, actors, entities)
    verbs = {f.verb for f in features}
    assert "create" in verbs
    assert "delete" in verbs


# ---------- externals -----------------------------------------------------

def test_externals_detect_firecrawl_mcp():
    externals = extract_externals(VISUAL_PRODUCT_SEARCH)
    providers = {(x.type, x.provider) for x in externals}
    assert ("mcp", "Firecrawl") in providers


def test_externals_empty_for_todo():
    externals = extract_externals(TODO_APP)
    assert externals == []


# ---------- build_locked_spec (orchestrator) -------------------------------

def test_build_locked_spec_visual_product_search_shape():
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    assert isinstance(spec, LockedSpec)
    assert len(spec.actors) >= 2  # user + admin
    assert len(spec.entities) >= 2  # Retailer + Scan at minimum
    assert len(spec.features) >= 4  # scan, upload, compare, manage
    assert any(x.provider == "Firecrawl" for x in spec.externals)


def test_build_locked_spec_todo_shape():
    spec = build_locked_spec(TODO_APP)
    assert len(spec.actors) == 1
    assert any(e.name == "Task" for e in spec.entities)
    assert spec.externals == []


def test_persist_and_load_round_trip(tmp_path):
    spec = build_locked_spec(TODO_APP)
    persist_locked_spec(spec, tmp_path)
    loaded = load_locked_spec(tmp_path)
    assert loaded is not None
    assert loaded.to_dict() == spec.to_dict()


def test_load_returns_none_when_no_file(tmp_path):
    assert load_locked_spec(tmp_path) is None
