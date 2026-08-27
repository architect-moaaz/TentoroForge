"""Tests for services.figma_binding_extractor — auto-binding Figma-derived
schemas to the resource registry."""
from __future__ import annotations

import copy

import pytest

from services.figma_binding_extractor import extract_bindings


# ── Helpers to build test schemas ──────────────────────────────────────

_PRODUCT_REGISTRY = {
    "entities": {
        "Product": {
            "fields": {
                "id":        {"type": "uuid", "primaryKey": True},
                "name":      {"type": "text"},
                "price":     {"type": "decimal", "semantic": "currency"},
                "imageUrl":  {"type": "text"},
                "createdAt": {"type": "timestamp"},
            }
        }
    }
}


def _text(content, name=""):
    n = {"type": "Text", "props": {"content": content}}
    if name:
        n["props"]["data-name"] = name
    return n


def _card(children, name=""):
    n = {"type": "Card", "props": {}, "children": children}
    if name:
        n["props"]["data-name"] = name
    return n


def _stack(children):
    return {"type": "Stack", "children": children}


# ── Fail-safe / no-op cases ────────────────────────────────────────────

def test_no_op_when_registry_empty():
    schema = {"root": _stack([_card([_text("Hello")])])}
    out = extract_bindings(schema, {"entities": {}})
    assert out is schema  # unchanged


def test_no_op_when_no_registry_key():
    schema = {"root": _stack([_card([_text("Hello")])])}
    assert extract_bindings(schema, {}) is schema


def test_does_not_mutate_input():
    schema = {"root": _stack([_card([_text("$99")], name="ProductCard"),
                              _card([_text("$149")], name="ProductCard")])}
    before = copy.deepcopy(schema)
    _ = extract_bindings(schema, _PRODUCT_REGISTRY)
    assert schema == before  # input untouched


def test_single_card_no_repeat():
    """A single card alone (no siblings) should NOT be collapsed to a Repeat."""
    schema = {"root": _stack([_card([_text("$99")], name="ProductCard")])}
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    root = out["root"]
    types = [c.get("type") for c in root["children"]]
    assert "Repeat" not in types


# ── Repeat detection ───────────────────────────────────────────────────

def test_detects_3_identical_siblings_as_repeat():
    """3 identical ProductCards → 1 Repeat + 1 template child."""
    cards = [_card([_text("$99")], name="ProductCard") for _ in range(3)]
    schema = {"root": _stack(cards)}
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    kids = out["root"]["children"]
    assert len(kids) == 1
    repeat = kids[0]
    assert repeat["type"] == "Repeat"
    assert repeat["bind"] == "products"
    assert len(repeat["children"]) == 1  # ONE template


def test_two_siblings_also_collapse():
    """MIN_REPEAT_SIBLINGS=2 — a pair is a list."""
    cards = [_card([_text("$99")], name="ProductCard") for _ in range(2)]
    out = extract_bindings({"root": _stack(cards)}, _PRODUCT_REGISTRY)
    assert out["root"]["children"][0]["type"] == "Repeat"


def test_signature_ignores_position_classes():
    """Cards positioned differently (absolute top-[X]) still collapse."""
    a = {"type": "Card", "props": {"className": "absolute top-[10px]"}, "children": []}
    b = {"type": "Card", "props": {"className": "absolute top-[100px]"}, "children": []}
    c = {"type": "Card", "props": {"className": "absolute top-[200px]"}, "children": []}
    out = extract_bindings({"root": _stack([a, b, c])}, _PRODUCT_REGISTRY)
    kids = out["root"]["children"]
    # Nothing to bind (no text tokens matching Product cols) but the
    # repeat SHOULD still collapse structurally.
    assert len(kids) == 1
    assert kids[0]["type"] == "Repeat"


def test_mixed_siblings_only_matched_run_collapses():
    """[Heading, Card, Card, Card, Footer] → [Heading, Repeat(Card), Footer]."""
    schema = {"root": _stack([
        {"type": "Heading", "props": {"content": "Products"}},
        _card([_text("$99")], name="ProductCard"),
        _card([_text("$149")], name="ProductCard"),
        _card([_text("$199")], name="ProductCard"),
        {"type": "Text", "props": {"content": "Footer"}},
    ])}
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    kids = out["root"]["children"]
    types = [k.get("type") for k in kids]
    assert types == ["Heading", "Repeat", "Text"]


def test_datasource_added_to_root_when_repeat_binds():
    cards = [_card([_text("$99")], name="ProductCard") for _ in range(3)]
    schema = {"root": _stack(cards)}
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    ds = out.get("dataSources") or []
    assert {"name": "products", "entity": "Product", "op": "list"} in ds


# ── Field binding inside the Repeat template ──────────────────────────

def test_currency_pattern_binds_to_currency_column():
    """$149.99 inside a ProductCard repeat → bound to Product.price."""
    cards = [_card([_text(f"${99 + i}")], name="ProductCard") for i in range(3)]
    out = extract_bindings({"root": _stack(cards)}, _PRODUCT_REGISTRY)
    template = out["root"]["children"][0]["children"][0]
    # dig for the Text node
    txt = template["children"][0]
    assert txt["props"]["content"] == "{{item.price}}"


def test_data_name_binds_to_matching_column():
    """A Text whose data-name is 'name' binds to Product.name."""
    inner = [_text("Sample Product Title", name="name")]
    cards = [_card(inner, name="ProductCard") for _ in range(3)]
    out = extract_bindings({"root": _stack(cards)}, _PRODUCT_REGISTRY)
    template = out["root"]["children"][0]["children"][0]
    inner_text = template["children"][0]
    assert inner_text["props"]["content"] == "{{item.name}}"


def test_image_src_binds_to_imageUrl():
    """<Image src="foo.png"> inside a repeat over Product → src becomes {{item.imageUrl}}."""
    img = {"type": "Image", "props": {"src": "https://cdn.example/sneakers.png"}}
    cards = [_card([img, _text(f"${99 + i}")], name="ProductCard") for i in range(3)]
    out = extract_bindings({"root": _stack(cards)}, _PRODUCT_REGISTRY)
    template = out["root"]["children"][0]["children"][0]
    img_out = template["children"][0]
    assert img_out["props"]["src"] == "{{item.imageUrl}}"


def test_prose_text_is_left_literal():
    """Marketing copy — text that doesn't match any column or pattern
    — stays as-is, not bound to a random column."""
    cards = [_card([_text("Snap. Shop. Save.")], name="ProductCard") for _ in range(3)]
    out = extract_bindings({"root": _stack(cards)}, _PRODUCT_REGISTRY)
    template = out["root"]["children"][0]["children"][0]
    txt = template["children"][0]
    assert txt["props"]["content"] == "Snap. Shop. Save."


def test_repeat_without_entity_match_leaves_empty_bind():
    """3 identical cards but text has no column overlap AND no data-name
    → still collapse to Repeat structurally, but leave bind empty for a
    downstream pass or human."""
    reg = {
        "entities": {
            "Order": {"fields": {"id": {"type": "uuid"}, "status": {"type": "varchar"}}}
        }
    }
    cards = [_card([_text("Lorem ipsum dolor")], name="AnonymousCard") for _ in range(3)]
    out = extract_bindings({"root": _stack(cards)}, reg)
    kids = out["root"]["children"]
    assert kids[0]["type"] == "Repeat"
    assert kids[0]["bind"] == ""  # unresolved


# ── Existing dataSources are preserved ────────────────────────────────

def test_preserves_existing_datasources():
    """If the schema already had a dataSource (e.g. from an earlier
    pass), extract_bindings must not clobber it."""
    cards = [_card([_text("$99")], name="ProductCard") for _ in range(3)]
    schema = {
        "root": _stack(cards),
        "dataSources": [{"name": "custom", "entity": "Custom", "op": "list"}],
    }
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    ds_names = [d["name"] for d in out["dataSources"]]
    assert "custom" in ds_names
    assert "products" in ds_names


def test_does_not_re_add_existing_source():
    """If products dataSource is already declared, don't duplicate it."""
    cards = [_card([_text("$99")], name="ProductCard") for _ in range(3)]
    schema = {
        "root": _stack(cards),
        "dataSources": [{"name": "products", "entity": "Product", "op": "list"}],
    }
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    products_entries = [d for d in out["dataSources"] if d.get("name") == "products"]
    assert len(products_entries) == 1


# ── Multi-entity: picks the entity with best column-name overlap ──────

def test_picks_entity_with_best_column_overlap():
    """3 cards whose text tokens overlap Product's cols (price, name)
    more than Order's — bind to Product."""
    reg = {
        "entities": {
            "Order":   {"fields": {"id": {"type": "uuid"}, "status": {"type": "text"}, "createdAt": {"type": "timestamp"}}},
            "Product": {"fields": {"id": {"type": "uuid"}, "price": {"type": "decimal", "semantic": "currency"}, "name": {"type": "text"}}},
        }
    }
    cards = [
        _card([_text("Widget", name="name"), _text("$29.99")], name="ProductCard")
        for _ in range(3)
    ]
    out = extract_bindings({"root": _stack(cards)}, reg)
    kids = out["root"]["children"]
    assert kids[0]["type"] == "Repeat"
    assert kids[0]["bind"] == "products"


# ── Nested walk: repeats inside a container ───────────────────────────

def test_repeats_detected_deep_in_tree():
    """A repeat inside a nested Stack is still detected."""
    cards = [_card([_text("$99")], name="ProductCard") for _ in range(3)]
    schema = {"root": _stack([
        {"type": "Heading", "props": {"content": "Featured"}},
        _stack([_stack(cards)]),
    ])}
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    inner_stack = out["root"]["children"][1]["children"][0]
    assert inner_stack["children"][0]["type"] == "Repeat"


def test_no_exception_on_malformed_schema():
    """None children, string children, missing props all handled."""
    schema = {"root": {"type": "Stack", "children": [
        None,
        "loose string",
        {"type": "Text"},  # no props
        {"props": {}},  # no type
    ]}}
    # Should not raise. May return schema unchanged.
    out = extract_bindings(schema, _PRODUCT_REGISTRY)
    assert isinstance(out, dict)
