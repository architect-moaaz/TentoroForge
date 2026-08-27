"""The shell menu must carry the plan's sub-screens, not just first segments.

``derive_shell_groups`` collapsed every route to ``_top_route`` — its first
segment — so ``/stock/adjust``, ``/stock/transfer`` and ``/stock/movements``
all folded into ``/stock`` and were dropped as duplicates. On pkiuqdrq that
left 21 of 45 built pages unreachable from the shell, including three
screens the domain dossier named as core patterns (Stock Movement Audit
Log, Receive Stock Wizard) and both settings sub-pages.

CRUD leaves (``/new``, ``/edit``) stay OUT: they are reached from the
parent list's own buttons, and putting "New Product" in the sidebar
alongside "Products" is noise, not navigation.
"""
from __future__ import annotations

import pytest

from services.shell_menu_sync import derive_shell_groups


def _nav(*routes, auth=None):
    return {
        "pages": [{"route": r, "title": ""} for r in routes],
        "auth_routes": list(auth or []),
    }


def _group(groups, route):
    return next((g for g in groups if g["route"] == route), None)


def _child_routes(groups, route):
    g = _group(groups, route)
    return [c["route"] for c in (g or {}).get("items") or []]


class TestSubScreens:
    def test_named_sub_screens_become_children(self):
        groups = derive_shell_groups(_nav(
            "/stock", "/stock/adjust", "/stock/transfer", "/stock/movements",
        ))
        assert _child_routes(groups, "/stock") == [
            "/stock/adjust", "/stock/movements", "/stock/transfer",
        ]

    def test_settings_sub_pages_become_children(self):
        groups = derive_shell_groups(_nav(
            "/settings", "/settings/users", "/settings/categories",
        ))
        assert _child_routes(groups, "/settings") == [
            "/settings/categories", "/settings/users",
        ]

    def test_children_carry_a_human_label(self):
        groups = derive_shell_groups(_nav("/stock", "/stock/movements"))
        child = (_group(groups, "/stock")["items"])[0]
        assert child["label"] == "Movements"
        assert child["icon"]

    def test_authored_title_wins_over_slug(self):
        nav = {"pages": [
            {"route": "/stock", "title": "Stock"},
            {"route": "/stock/movements", "title": "Movement Log"},
        ]}
        groups = derive_shell_groups(nav)
        assert _group(groups, "/stock")["items"][0]["label"] == "Movement Log"


class TestExclusions:
    @pytest.mark.parametrize("leaf", ["/products/new", "/products/create"])
    def test_crud_create_leaves_are_not_children(self, leaf):
        groups = derive_shell_groups(_nav("/products", leaf))
        assert _child_routes(groups, "/products") == []

    def test_dynamic_children_are_not_menu_items(self):
        # /purchase-orders/[id] has no landing page of its own.
        groups = derive_shell_groups(_nav(
            "/purchase-orders", "/purchase-orders/[id]",
        ))
        assert _child_routes(groups, "/purchase-orders") == []

    def test_deeper_than_one_level_is_not_a_child(self):
        groups = derive_shell_groups(_nav(
            "/products", "/products/[id]/skus/new",
        ))
        assert _child_routes(groups, "/products") == []

    def test_shell_false_children_are_skipped(self):
        nav = {"pages": [
            {"route": "/stock"},
            {"route": "/stock/adjust", "shell": False},
        ]}
        assert _child_routes(derive_shell_groups(nav), "/stock") == []

    def test_auth_children_never_appear(self):
        groups = derive_shell_groups(
            _nav("/settings", "/settings/login", auth=["/settings/login"]))
        assert _child_routes(groups, "/settings") == []


class TestNoRegression:
    def test_top_level_groups_are_unchanged(self):
        groups = derive_shell_groups(_nav(
            "/", "/products", "/stock", "/stock/adjust"))
        assert [g["route"] for g in groups] == ["/", "/products", "/stock"]

    def test_childless_groups_carry_no_children_key(self):
        groups = derive_shell_groups(_nav("/products"))
        assert "items" not in _group(groups, "/products")
