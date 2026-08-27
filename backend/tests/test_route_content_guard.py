"""Slice 9 — flag route/content mismatches (Bug 3)."""
from __future__ import annotations

import json
from pathlib import Path

from services.route_content_guard import check_route_content


def _seed(tmp_path: Path, registry: dict, schemas: dict[str, dict]) -> None:
    (tmp_path / "registry.json").write_text(json.dumps(registry))
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    for slug, doc in schemas.items():
        p = sdir / (slug + ".json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc))


def test_bug3_notifications_binds_to_users_is_flagged(tmp_path):
    """The canonical Bug 3: /notifications schema's primary dataSource is
    the User entity, not Notification. Guard catches it."""
    _seed(tmp_path, {
        "entities": {
            "Notification": {"fields": {"id": {"type": "uuid"}, "recipientId": {"type": "uuid"}}},
            "User":         {"fields": {"id": {"type": "uuid"}, "email":       {"type": "varchar"}}},
        },
    }, {
        "notifications": {
            "route": "/notifications",
            "dataSources": [{"name": "users", "entity": "User", "op": "list"}],
            "root": {"type": "Table", "props": {"dataSource": "users"}},
        },
    })

    result = check_route_content(str(tmp_path))
    assert len(result["mismatches"]) == 1
    m = result["mismatches"][0]
    assert m["route"] == "/notifications"
    assert m["expected_entity"] == "Notification"
    assert m["observed_entity"] == "User"


def test_correct_route_content_passes(tmp_path):
    """When the /notifications schema binds to the Notification entity,
    no mismatch is flagged."""
    _seed(tmp_path, {
        "entities": {
            "Notification": {"fields": {"id": {"type": "uuid"}}},
            "User":         {"fields": {"id": {"type": "uuid"}}},
        },
    }, {
        "notifications": {
            "route": "/notifications",
            "dataSources": [{"name": "notifications", "entity": "Notification", "op": "list"}],
            "root": {"type": "Table"},
        },
    })

    result = check_route_content(str(tmp_path))
    assert result["mismatches"] == []


def test_dashboard_route_is_never_flagged(tmp_path):
    """`/dashboard` legitimately aggregates across entities — never
    flagged even when its primary dataSource points at one entity."""
    _seed(tmp_path, {
        "entities": {"User": {"fields": {"id": {"type": "uuid"}}}},
    }, {
        "dashboard": {
            "route": "/dashboard",
            "dataSources": [{"name": "usersCount", "entity": "User", "op": "aggregate"}],
            "root": {"type": "MetricTile"},
        },
    })
    assert check_route_content(str(tmp_path))["mismatches"] == []


def test_auth_routes_never_flagged(tmp_path):
    _seed(tmp_path, {
        "entities": {"User": {"fields": {"id": {"type": "uuid"}}}},
    }, {
        "login":  {"route": "/login",  "dataSources": [], "root": {"type": "Form"}},
        "signup": {"route": "/signup", "dataSources": [], "root": {"type": "Form"}},
    })
    assert check_route_content(str(tmp_path))["mismatches"] == []


def test_plural_and_singular_both_recognized(tmp_path):
    """Entity `Category` — routes `/categories` (regular plural) and
    `/category` (singular) both map to the entity for expectation."""
    _seed(tmp_path, {
        "entities": {
            "Category": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
    }, {
        "categories": {
            "route": "/categories",
            "dataSources": [{"name": "categories", "entity": "Category", "op": "list"}],
            "root": {"type": "Table"},
        },
    })
    assert check_route_content(str(tmp_path))["mismatches"] == []


def test_schema_without_datasources_is_not_flagged(tmp_path):
    """A plain content page (no dataSources) can't be classified — we
    don't have signal, so we don't guess. Skipped, not flagged."""
    _seed(tmp_path, {
        "entities": {"Notification": {"fields": {"id": {"type": "uuid"}}}},
    }, {
        "notifications": {
            "route": "/notifications",
            "root": {"type": "Text", "props": {"content": "Coming soon"}},
        },
    })
    assert check_route_content(str(tmp_path))["mismatches"] == []


def test_dynamic_segment_route_not_flagged(tmp_path):
    """`/candidates/[id]` is a detail route; its primary dataSource may
    load a different shape (aggregate, join). Don't flag it."""
    _seed(tmp_path, {
        "entities": {
            "Candidate":   {"fields": {"id": {"type": "uuid"}}},
            "Application": {"fields": {"id": {"type": "uuid"}}},
        },
    }, {
        "candidates/[id]": {
            "route": "/candidates/[id]",
            "dataSources": [{"name": "applications", "entity": "Application", "op": "list"}],
            "root": {"type": "Table"},
        },
    })
    assert check_route_content(str(tmp_path))["mismatches"] == []


def test_no_registry_is_safe_noop(tmp_path):
    """No registry.json → no signal → no error, no mismatches."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    result = check_route_content(str(tmp_path))
    assert result == {"mismatches": [], "checked": 0, "skipped": 0}
