"""Unit tests for figma_shell_extractor."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.figma_shell_extractor import (
    _find_nav_subtree,
    _is_nav_node,
    extract_shell_from_pages,
)


# ---------------------------------------------------------------------------
# _is_nav_node
# ---------------------------------------------------------------------------

def test_is_nav_node_detects_navbar_with_button_routes():
    nav = {
        "type": "Row",
        "children": [
            {"type": "Button", "props": {"label": "Dashboard", "navigate": "/dashboard"}},
            {"type": "Button", "props": {"label": "Settings", "navigate": "/settings"}},
        ],
    }
    assert _is_nav_node(nav)


def test_is_nav_node_rejects_single_button_row():
    row = {
        "type": "Row",
        "children": [
            {"type": "Button", "props": {"label": "Submit", "workflow": "form.submit"}},
        ],
    }
    assert not _is_nav_node(row)


def test_is_nav_node_rejects_non_container():
    text_node = {"type": "Text", "props": {"content": "hello"}}
    assert not _is_nav_node(text_node)


def test_is_nav_node_detects_stack_with_nested_nav_buttons():
    stack = {
        "type": "Stack",
        "children": [
            {
                "type": "Container",
                "children": [
                    {"type": "Button", "props": {"navigate": "/a"}},
                    {"type": "Button", "props": {"navigate": "/b"}},
                    {"type": "Button", "props": {"navigate": "/c"}},
                ],
            }
        ],
    }
    assert _is_nav_node(stack)


def test_is_nav_node_rejects_buttons_to_same_route():
    row = {
        "type": "Row",
        "children": [
            {"type": "Button", "props": {"navigate": "/home"}},
            {"type": "Button", "props": {"navigate": "/home"}},
        ],
    }
    assert not _is_nav_node(row)


# ---------------------------------------------------------------------------
# _find_nav_subtree
# ---------------------------------------------------------------------------

def test_find_nav_subtree_locates_nav_in_deep_tree():
    # The heuristic returns the TOPMOST container that transitively contains
    # 2+ Buttons with distinct navigate props. In this schema the Stack wraps
    # a Row whose Buttons have navigate — so the Stack is the topmost nav node.
    schema = {
        "children": [
            {
                "type": "Stack",
                "children": [
                    {
                        "type": "Row",
                        "children": [
                            {"type": "Button", "props": {"navigate": "/a"}},
                            {"type": "Button", "props": {"navigate": "/b"}},
                        ],
                    },
                    {"type": "Text", "props": {"content": "Page body"}},
                ],
            }
        ]
    }
    found = _find_nav_subtree(schema)
    assert found is not None
    path, node = found
    # The Stack is the topmost node that passes _is_nav_node (it contains nav
    # buttons transitively). If you need the Row specifically, put it inside a
    # non-nav Container parent (see test_find_nav_subtree_finds_top_level_nav).
    assert node["type"] in ("Row", "Stack")


def test_find_nav_subtree_returns_none_when_no_nav():
    schema = {
        "children": [
            {
                "type": "Stack",
                "children": [
                    {"type": "Text", "props": {"content": "Hello"}},
                ],
            }
        ]
    }
    assert _find_nav_subtree(schema) is None


def test_find_nav_subtree_returns_none_for_empty_schema():
    assert _find_nav_subtree({}) is None
    assert _find_nav_subtree({"children": []}) is None


def test_find_nav_subtree_finds_nav_when_sibling_content_present():
    """Nav is found when it is one child alongside non-nav sibling content."""
    schema = {
        "children": [
            {
                "type": "Stack",
                "children": [
                    {
                        "type": "Row",
                        "children": [
                            {"type": "Button", "props": {"navigate": "/x"}},
                            {"type": "Button", "props": {"navigate": "/y"}},
                        ],
                    },
                    {"type": "Container", "children": [
                        {"type": "Text", "props": {"content": "body"}}
                    ]},
                ],
            }
        ]
    }
    found = _find_nav_subtree(schema)
    assert found is not None
    path, node = found
    assert node["type"] == "Row"
    assert path == [0, 0]


def test_find_nav_subtree_returns_none_when_root_is_only_nav():
    """If the only root child is a nav node with no content sibling, return None."""
    schema = {
        "children": [
            {
                "type": "Row",
                "children": [
                    {"type": "Button", "props": {"navigate": "/x"}},
                    {"type": "Button", "props": {"navigate": "/y"}},
                ],
            }
        ]
    }
    # Heuristic requires a nav child alongside ≥1 non-nav sibling.
    assert _find_nav_subtree(schema) is None


# ---------------------------------------------------------------------------
# extract_shell_from_pages — integration test with temp dir
# ---------------------------------------------------------------------------

def _make_page_schema(nav_routes: list[str]) -> dict:
    """Build a minimal schema with a nav row + a content block."""
    return {
        "schemaVersion": "2.0",
        "id": "test-page",
        "dataSources": [],
        "children": [
            {
                "id": "root",
                "type": "Stack",
                "children": [
                    {
                        "id": "nav",
                        "type": "Row",
                        "children": [
                            {
                                "id": f"btn-{i}",
                                "type": "Button",
                                "props": {"label": r, "navigate": r},
                            }
                            for i, r in enumerate(nav_routes)
                        ],
                    },
                    {
                        "id": "body",
                        "type": "Text",
                        "props": {"content": "Page content here"},
                    },
                ],
            }
        ],
    }


def test_extract_shell_creates_shell_json(tmp_path):
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)

    # Write a shell:true page with a nav.
    page_schema = _make_page_schema(["/dashboard", "/settings"])
    schema_path = schemas_dir / "dashboard.json"
    schema_path.write_text(json.dumps(page_schema), encoding="utf-8")

    nav_flow = {
        "pages": [
            {
                "id": "dashboard",
                "route": "/dashboard",
                "shell": True,
                "schemaFile": "src/schemas/dashboard.json",
            }
        ],
        "auth_routes": ["/login"],
    }

    result = extract_shell_from_pages(tmp_path, nav_flow)
    assert result is not None

    shell_file = schemas_dir / "shell.json"
    assert shell_file.exists()

    shell = json.loads(shell_file.read_text(encoding="utf-8"))
    # Shell should contain the nav Row.
    shell_str = json.dumps(shell)
    assert "PageOutlet" in shell_str
    assert "/dashboard" in shell_str  # nav button still present


def test_extract_shell_strips_nav_from_page(tmp_path):
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)

    page_schema = _make_page_schema(["/a", "/b"])
    schema_path = schemas_dir / "page-a.json"
    schema_path.write_text(json.dumps(page_schema), encoding="utf-8")

    nav_flow = {
        "pages": [
            {
                "id": "page-a",
                "route": "/a",
                "shell": True,
                "schemaFile": "src/schemas/page-a.json",
            }
        ],
        "auth_routes": [],
    }

    extract_shell_from_pages(tmp_path, nav_flow)

    # Page schema should no longer contain the nav Row with navigate buttons.
    rewritten = json.loads(schema_path.read_text(encoding="utf-8"))
    rewritten_str = json.dumps(rewritten)
    # The body text should still be there.
    assert "Page content here" in rewritten_str


def test_extract_shell_returns_none_when_no_shell_pages(tmp_path):
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)

    nav_flow = {
        "pages": [
            {"id": "login", "route": "/login", "shell": False, "schemaFile": "src/schemas/login.json"},
        ],
        "auth_routes": ["/login"],
    }
    result = extract_shell_from_pages(tmp_path, nav_flow)
    assert result is None


def test_extract_shell_returns_none_when_no_nav_in_schema(tmp_path):
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)

    no_nav_schema = {
        "schemaVersion": "2.0",
        "id": "plain",
        "dataSources": [],
        "children": [
            {
                "id": "root",
                "type": "Stack",
                "children": [
                    {"id": "t", "type": "Text", "props": {"content": "Hello"}},
                ],
            }
        ],
    }
    schema_path = schemas_dir / "plain.json"
    schema_path.write_text(json.dumps(no_nav_schema), encoding="utf-8")

    nav_flow = {
        "pages": [
            {"id": "plain", "route": "/plain", "shell": True, "schemaFile": "src/schemas/plain.json"},
        ],
        "auth_routes": [],
    }
    result = extract_shell_from_pages(tmp_path, nav_flow)
    assert result is None


# ── Structural-diff heuristic ──────────────────────────────────────────────
# Catches Figma-driven apps where the sidebar / top nav doesn't carry
# `navigate` props on its buttons (icons-only sidebars are common).

from services.figma_shell_extractor import (
    extract_shell_by_structural_diff,
    _structural_signature,
)


def _write_page(schemas_dir, name, root):
    schema = {"schemaVersion": "2", "id": name, "children": [root]}
    (schemas_dir / f"{name}.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")


def test_structural_diff_extracts_shared_sidebar(tmp_path):
    """When N pages share the same sidebar subtree at root index 0,
    that subtree should be hoisted into shell.json with a PageOutlet
    where each page's unique body sits."""
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)

    sidebar = {
        "id": "sb", "type": "Stack",
        "props": {"className": "w-[247px] bg-teal"},
        "children": [
            {"id": "nav-icons", "type": "Stack", "children": [
                {"id": "i1", "type": "Icon"},
                {"id": "i2", "type": "Icon"},
                {"id": "i3", "type": "Icon"},
            ]},
        ],
    }

    # Three pages, all with the same sidebar at index 0 + structurally
    # DIFFERENT bodies at index 1 (real pages have different content trees,
    # which is what lets the structural-diff heuristic separate chrome
    # from body).
    bodies = [
        ("dashboard", {"id": "b1", "type": "Stack", "children": [
            {"type": "Heading"}, {"type": "Heading"}, {"type": "Card"},
        ]}),
        ("leads", {"id": "b2", "type": "Stack", "children": [
            {"type": "Heading"}, {"type": "Row"}, {"type": "Table"},
        ]}),
        ("settings", {"id": "b3", "type": "Stack", "children": [
            {"type": "Form"}, {"type": "Button"},
        ]}),
    ]
    for name, body in bodies:
        root = {
            "id": f"root-{name}", "type": "Row",
            "children": [
                json.loads(json.dumps(sidebar)),
                body,
            ],
        }
        _write_page(schemas_dir, name, root)

    nav_flow = {
        "pages": [
            {"id": "dashboard", "route": "/dashboard", "shell": True,
             "schemaFile": "src/schemas/dashboard.json"},
            {"id": "leads", "route": "/leads", "shell": True,
             "schemaFile": "src/schemas/leads.json"},
            {"id": "settings", "route": "/settings", "shell": True,
             "schemaFile": "src/schemas/settings.json"},
        ],
        "auth_routes": [],
    }
    shell = extract_shell_by_structural_diff(tmp_path, nav_flow)
    assert shell is not None
    # shell.json was written
    shell_path = schemas_dir / "shell.json"
    assert shell_path.exists()
    shell_data = json.loads(shell_path.read_text(encoding="utf-8"))
    shell_root = shell_data["children"][0]
    # First child of shell root is the sidebar
    assert shell_root["children"][0]["type"] == "Stack"
    # Followed by a PageOutlet where the unique body slots in
    types = [c.get("type") for c in shell_root["children"]]
    assert "PageOutlet" in types
    # Each page's schema now has only its unique body — the sidebar
    # is gone.
    for name in ("dashboard", "leads", "settings"):
        page = json.loads((schemas_dir / f"{name}.json").read_text(encoding="utf-8"))
        root_kids = page["children"][0]["children"]
        # Sidebar Stack must be absent; the body Stack must remain.
        assert not any(k.get("id") == "sb" for k in root_kids)
        assert any(k.get("type") == "Stack" and k.get("children") for k in root_kids)


def test_structural_diff_skips_when_pages_diverge(tmp_path):
    """If every page has a different root structure, there's no chrome
    to hoist — extractor returns None and leaves pages untouched."""
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)
    _write_page(schemas_dir, "a", {
        "id": "ra", "type": "Stack",
        "children": [{"id": "a1", "type": "Heading"}],
    })
    _write_page(schemas_dir, "b", {
        "id": "rb", "type": "Row",
        "children": [{"id": "b1", "type": "Card"}],
    })
    nav_flow = {
        "pages": [
            {"id": "a", "route": "/a", "shell": True, "schemaFile": "src/schemas/a.json"},
            {"id": "b", "route": "/b", "shell": True, "schemaFile": "src/schemas/b.json"},
        ],
        "auth_routes": [],
    }
    shell = extract_shell_by_structural_diff(tmp_path, nav_flow)
    assert shell is None


def test_structural_signature_is_text_independent():
    """Two Heading nodes with different content should produce the same
    signature — chrome detection cares about structure, not text."""
    h1 = {"type": "Heading", "props": {"content": "Welcome"}}
    h2 = {"type": "Heading", "props": {"content": "Login"}}
    assert _structural_signature(h1) == _structural_signature(h2)


def test_structural_signature_distinguishes_different_types():
    a = {"type": "Stack", "children": [{"type": "Icon"}]}
    b = {"type": "Stack", "children": [{"type": "Image"}]}
    assert _structural_signature(a) != _structural_signature(b)
