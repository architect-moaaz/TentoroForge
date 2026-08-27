"""Tests for services.route_intent_apply (B-022.6, .7, .9 wiring)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.route_intent_apply import apply_route_intent


def _make_app(root: Path, *, plan: dict, schemas: dict[str, dict]) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    for name, doc in schemas.items():
        (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps(doc))


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "src" / "schemas" / f"{name}.json").read_text())


class TestSingletonCollapse:
    def test_profile_page_drops_users_table(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"User": {"fields": []}},
            "pages": [{"route": "/profile", "entity": "User"}],
        }, schemas={"profile": {
            "route": "/profile",
            "nodes": [
                {"type": "Heading", "props": {"content": "Profile"}},
                {"type": "Table", "props": {"dataSource": "users"}},
                {"type": "Form", "props": {"fields": []}},
            ],
        }})
        r = apply_route_intent(str(tmp_path))
        assert r["singleton_pages"] == 1
        after = _read(tmp_path, "profile")
        # Table gone.
        types = [n.get("type") for n in after["nodes"]]
        assert "Table" not in types
        # Form rebound to currentUser.
        form = next(n for n in after["nodes"] if n["type"] == "Form")
        assert form["props"]["defaultValues"] == "{{currentUser}}"
        assert form["props"]["record"] == "{{currentUser}}"
        # Marker set.
        assert after["_route_intent"] == "singleton_current_user"


class TestUserScopeList:
    def test_my_recipes_gets_owner_filter(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Recipe": {"fields": []}, "User": {"fields": []}},
            "pages": [{"route": "/my-recipes", "entity": "Recipe"}],
        }, schemas={"my-recipes": {
            "route": "/my-recipes",
            "dataSources": [{"name": "recipes", "entity": "Recipe", "op": "list"}],
            "nodes": [
                {"type": "Heading", "props": {"content": "My recipes"}},
                {"type": "Table", "props": {"dataSource": "recipes"}},
            ],
        }})
        r = apply_route_intent(str(tmp_path))
        assert r["user_scope_lists"] == 1
        after = _read(tmp_path, "my-recipes")
        assert after["dataSources"][0]["filter"] == {"ownerId": "{{currentUser.id}}"}


class TestRoleScopeList:
    def test_home_cooks_gets_role_filter(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"User": {"fields": []}},
            "pages": [{"route": "/home-cooks", "entity": "User"}],
        }, schemas={"home-cooks": {
            "route": "/home-cooks",
            "dataSources": [{"name": "users", "entity": "User", "op": "list"}],
            "nodes": [
                {"type": "Heading", "props": {"content": "Home cooks"}},
                {"type": "Table", "props": {"dataSource": "users"}},
            ],
        }})
        r = apply_route_intent(str(tmp_path))
        assert r["role_scope_lists"] == 1
        after = _read(tmp_path, "home-cooks")
        assert after["dataSources"][0]["filter"] == {"role": "cook"}


class TestIdempotency:
    def test_second_run_no_op(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"User": {"fields": []}},
            "pages": [{"route": "/profile", "entity": "User"}],
        }, schemas={"profile": {
            "route": "/profile",
            "nodes": [
                {"type": "Table", "props": {}},
                {"type": "Form", "props": {}},
            ],
        }})
        r1 = apply_route_intent(str(tmp_path))
        r2 = apply_route_intent(str(tmp_path))
        assert r1["singleton_pages"] == 1
        assert r2["singleton_pages"] == 0


class TestNoOpForCrud:
    def test_ordinary_orders_page_unchanged(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Order": {"fields": []}},
            "pages": [{"route": "/orders", "entity": "Order"}],
        }, schemas={"orders": {
            "route": "/orders",
            "dataSources": [{"name": "orders", "entity": "Order", "op": "list"}],
            "nodes": [{"type": "Table", "props": {"dataSource": "orders"}}],
        }})
        r = apply_route_intent(str(tmp_path))
        assert r["singleton_pages"] == 0
        assert r["user_scope_lists"] == 0
        assert r["role_scope_lists"] == 0
        after = _read(tmp_path, "orders")
        # No filter injected — /orders isn't a scoped route.
        assert "filter" not in after["dataSources"][0]
