"""Tests for the Pydantic Artifacts shape."""
from __future__ import annotations
import pytest
from agents.peer_patcher_schemas import (
    Artifacts, PageSchema, SchemaNode, Tokens, artifacts_json_schema,
)


def test_artifacts_parses_minimal_bundle():
    raw = {
        "pageSchemas": {
            "home": {
                "schemaVersion": "2", "id": "home", "route": "/",
                "root": {"id": "n1", "type": "Stack",
                         "children": [{"id": "n2", "type": "Text", "props": {"text": "hi"}}]},
            },
        },
        "navFlow": {
            "version": "1.0", "initialPage": "home",
            "pages": [{"id": "home", "route": "/", "title": "Home",
                       "schemaFile": "src/schemas/home.json", "params": []}],
            "transitions": [], "guards": {},
        },
        "tokens": {
            "color": {}, "typography": {}, "spacing": {},
            "radius": {}, "shadow": {}, "motion": {}, "breakpoints": {},
        },
    }
    a = Artifacts.model_validate(raw)
    assert a.pageSchemas["home"].id == "home"
    assert a.pageSchemas["home"].root.children[0].id == "n2"
    assert a.navFlow.initial_page == "home"


def test_artifacts_recursive_nodes():
    raw_node = {"id": "a", "type": "Stack", "children": [
        {"id": "b", "type": "Row", "children": [
            {"id": "c", "type": "Text", "props": {"text": "deep"}}
        ]}
    ]}
    n = SchemaNode.model_validate(raw_node)
    assert n.children[0].children[0].id == "c"


def test_artifacts_json_schema_includes_writeArtifacts_keys():
    schema = artifacts_json_schema()
    props = schema.get("properties", {})
    assert "pageSchemas" in props
    assert "navFlow" in props
    assert "tokens" in props


def test_tokens_defaults_to_empty_dicts():
    t = Tokens()
    assert t.color == {}
    assert t.typography == {}


def test_page_schema_dataSources_optional():
    p = PageSchema(
        id="x", root=SchemaNode(id="r", type="Stack")
    )
    assert p.dataSources == []
