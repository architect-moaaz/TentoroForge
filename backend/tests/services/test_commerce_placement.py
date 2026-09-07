"""Tests for services.commerce_placement (CART-P2).

The placement pass runs in post_generate_fixes and edits generated schemas
in-place to surface the cart runtime primitive. Tests exercise the pass on
a temp directory shaped like a real generated app.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.commerce_placement import apply_commerce_placement


def _make_app(root: Path, *,
              plan: dict,
              schemas: dict[str, dict] | None = None,
              shell: dict | None = None) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if shell is not None:
        (root / "src" / "contracts" / "shell.json").write_text(json.dumps(shell), encoding="utf-8")
    for name, doc in (schemas or {}).items():
        (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# no-op cases                                                                #
# ---------------------------------------------------------------------------

class TestNoOp:
    def test_no_commerce_entities_is_noop(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "name": "Ops app",
            "entities": {"Plant": {"fields": []}},
            "pages": [{"route": "/plants", "type": "list", "entity": "Plant"}],
        }, schemas={"plants": {"nodes": []}})
        r = apply_commerce_placement(str(tmp_path))
        assert r["entities"] == []
        assert r["list_edits"] == 0
        assert r["cart_page_created"] is False
        assert not (tmp_path / "src" / "schemas" / "cart.json").exists()

    def test_missing_plan_is_noop(self, tmp_path: Path):
        r = apply_commerce_placement(str(tmp_path))
        assert r["entities"] == []


# ---------------------------------------------------------------------------
# list-page injection                                                        #
# ---------------------------------------------------------------------------

class TestListInjection:
    def test_appends_addtocart_to_table_row_actions(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"commerce": True, "fields": []}},
            "pages": [{"route": "/plants", "type": "list", "entity": "Plant"}],
        }, schemas={"plants": {
            "nodes": [{"type": "Table", "props": {"dataSource": "plants"}}],
        }})
        r = apply_commerce_placement(str(tmp_path))
        assert r["list_edits"] == 1
        table = _read(tmp_path / "src" / "schemas" / "plants.json")["nodes"][0]
        assert table["type"] == "Table"
        row_actions = table["props"]["rowActions"]
        assert row_actions[0]["type"] == "AddToCart"
        assert row_actions[0]["props"]["entity"] == "Plant"

    def test_datagrid_also_receives_addtocart(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Product": {"commerce": True, "fields": []}},
            "pages": [{"route": "/products", "type": "list", "entity": "Product"}],
        }, schemas={"products": {
            "nodes": [{"type": "DataGrid", "props": {"dataSource": "products"}}],
        }})
        r = apply_commerce_placement(str(tmp_path))
        assert r["list_edits"] == 1
        grid = _read(tmp_path / "src" / "schemas" / "products.json")["nodes"][0]
        assert grid["props"]["rowActions"][0]["type"] == "AddToCart"


# ---------------------------------------------------------------------------
# detail-page injection                                                      #
# ---------------------------------------------------------------------------

class TestDetailInjection:
    def test_appends_row_with_addtocart_cta(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"commerce": True, "fields": []}},
            "pages": [{"route": "/plants/[id]", "type": "detail", "entity": "Plant"}],
        }, schemas={"plants-id": {
            "nodes": [{"type": "Heading", "props": {"text": "Detail"}}],
        }})
        r = apply_commerce_placement(str(tmp_path))
        assert r["detail_edits"] == 1
        doc = _read(tmp_path / "src" / "schemas" / "plants-id.json")
        # A trailing Row with AddToCart was appended.
        assert doc["nodes"][-1]["type"] == "Row"
        assert doc["nodes"][-1]["children"][0]["type"] == "AddToCart"


# ---------------------------------------------------------------------------
# /cart page + plan sync + shell badge                                       #
# ---------------------------------------------------------------------------

class TestCartArtifacts:
    def test_emits_cart_page_using_cartpage_node(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"commerce": True, "fields": []}},
            "pages": [{"route": "/plants", "type": "list", "entity": "Plant"}],
        }, schemas={"plants": {"nodes": [{"type": "Table", "props": {}}]}})
        r = apply_commerce_placement(str(tmp_path))
        assert r["cart_page_created"] is True
        cart = _read(tmp_path / "src" / "schemas" / "cart.json")
        assert cart["route"] == "/cart"
        assert cart["nodes"][0]["type"] == "CartPage"

    def test_adds_cart_route_to_plan(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"commerce": True, "fields": []}},
            "pages": [{"route": "/plants", "type": "list", "entity": "Plant"}],
        }, schemas={"plants": {"nodes": [{"type": "Table", "props": {}}]}})
        r = apply_commerce_placement(str(tmp_path))
        assert r["cart_in_plan"] is True
        plan = _read(tmp_path / "src" / "contracts" / "plan.json")
        routes = [p["route"] for p in plan["pages"]]
        assert "/cart" in routes

    def test_injects_cart_badge_into_shell(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"commerce": True, "fields": []}},
            "pages": [{"route": "/plants", "type": "list", "entity": "Plant"}],
        }, schemas={"plants": {"nodes": [{"type": "Table", "props": {}}]}},
        shell={"kind": "sidebar", "menu": [{"label": "Home", "route": "/"}]})
        r = apply_commerce_placement(str(tmp_path))
        assert r["shell_badge"] is True
        shell = _read(tmp_path / "src" / "contracts" / "shell.json")
        labels = [m["label"] for m in shell["menu"]]
        assert "Cart" in labels


# ---------------------------------------------------------------------------
# idempotency                                                                #
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_run_is_noop_everywhere(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"commerce": True, "fields": []}},
            "pages": [
                {"route": "/plants", "type": "list", "entity": "Plant"},
                {"route": "/plants/[id]", "type": "detail", "entity": "Plant"},
            ],
        }, schemas={
            "plants": {"nodes": [{"type": "Table", "props": {}}]},
            "plants-id": {"nodes": [{"type": "Heading", "props": {}}]},
        }, shell={"kind": "sidebar", "menu": []})

        r1 = apply_commerce_placement(str(tmp_path))
        assert r1["list_edits"] == 1
        assert r1["detail_edits"] == 1
        assert r1["cart_page_created"] is True
        assert r1["cart_in_plan"] is True
        assert r1["shell_badge"] is True

        r2 = apply_commerce_placement(str(tmp_path))
        assert r2["list_edits"] == 0
        assert r2["detail_edits"] == 0
        assert r2["cart_page_created"] is False
        assert r2["cart_in_plan"] is False
        assert r2["shell_badge"] is False


# ---------------------------------------------------------------------------
# multi-entity                                                               #
# ---------------------------------------------------------------------------

class TestMultipleCommerceEntities:
    def test_handles_multiple_entities_independently(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {
                "Plant":   {"commerce": True, "fields": []},
                "Pot":     {"commerce": True, "fields": []},
                "Batch":   {"fields": []},
            },
            "pages": [
                {"route": "/plants", "type": "list", "entity": "Plant"},
                {"route": "/pots", "type": "list", "entity": "Pot"},
                {"route": "/batches", "type": "list", "entity": "Batch"},
            ],
        }, schemas={
            "plants":  {"nodes": [{"type": "Table", "props": {}}]},
            "pots":    {"nodes": [{"type": "Table", "props": {}}]},
            "batches": {"nodes": [{"type": "Table", "props": {}}]},
        })
        r = apply_commerce_placement(str(tmp_path))
        assert r["list_edits"] == 2  # Plant + Pot, not Batch
        plants = _read(tmp_path / "src" / "schemas" / "plants.json")
        pots = _read(tmp_path / "src" / "schemas" / "pots.json")
        batches = _read(tmp_path / "src" / "schemas" / "batches.json")
        assert plants["nodes"][0]["props"]["rowActions"][0]["props"]["entity"] == "Plant"
        assert pots["nodes"][0]["props"]["rowActions"][0]["props"]["entity"] == "Pot"
        assert "rowActions" not in batches["nodes"][0]["props"]
