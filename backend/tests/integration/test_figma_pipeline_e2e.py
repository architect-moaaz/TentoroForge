"""End-to-end-ish test: the commitbiz login fixture, when run through the
deterministic mapper, must produce a tree where the Sign-In form contains
both inputs and the submit button. Validates the integration of the
walker + classifier + style extractor + orchestrator."""

import json
import pathlib
import pytest


FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "figma" / "commitbiz_login.json"


def _find_node_with_path(root, type_path):
    """Return True iff there's some descendant chain matching type_path.
    e.g. ["Form", "Input"] requires SOMEWHERE in the tree a Form node that
    contains (directly or transitively) an Input descendant."""
    if not type_path:
        return True
    head, *rest = type_path

    def search(node):
        if not isinstance(node, dict):
            return False
        if node.get("type") == head:
            if not rest:
                return True
            for child in node.get("children") or []:
                if _descendant_has(child, rest):
                    return True
        for child in node.get("children") or []:
            if search(child):
                return True
        return False

    def _descendant_has(node, remaining):
        if not isinstance(node, dict):
            return False
        if not remaining:
            return True
        head_, *rest_ = remaining
        if node.get("type") == head_:
            if not rest_:
                return True
            for c in node.get("children") or []:
                if _descendant_has(c, rest_):
                    return True
        for c in node.get("children") or []:
            if _descendant_has(c, remaining):
                return True
        return False

    return search(root)


@pytest.mark.parametrize("required_path", [
    ["Form"],
    ["Form", "Input"],
    ["Form", "Button"],
    ["Form", "Checkbox"],
])
def test_commitbiz_login_structure(required_path):
    from services.figma_to_schema import build_page_schema
    doc = json.loads(FIXTURE.read_text())
    page = build_page_schema(doc).page
    # The page wraps a list of children — wrap in a synthetic root for the search
    root = {"type": "_Root", "children": page.get("children") or []}
    assert _find_node_with_path(root, required_path), \
        f"path {' > '.join(required_path)} not found in {json.dumps(page, indent=2)[:400]}"


def test_login_page_emits_emerald_primary_token():
    from services.figma_to_schema import build_page_schema
    doc = json.loads(FIXTURE.read_text())
    tokens = build_page_schema(doc).tokens
    primary = tokens.get("color", {}).get("primary", {}).get("500", "")
    # Emerald-ish hex
    assert primary.lower().startswith(("#10", "#0f")), \
        f"expected emerald-ish primary 500, got {primary!r}"
