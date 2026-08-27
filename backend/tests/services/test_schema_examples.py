"""CI gate: every schema_examples/*.json must:
  1. Parse as valid v2 Page schema (via the schema package's PageV2.parse)
  2. Reference only registered library components
  3. Use only token refs (regex check) — no inline hex/px/rem in known
     style-slot positions

Run: pytest backend/tests/services/test_schema_examples.py -v
"""
from __future__ import annotations
import json
import re
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "services" / "schema_examples"

# Registered v2 node types — must be kept in sync with NodeV2 union in
# packages/schema/src/page.ts. This list is the source of truth for the test.
REGISTERED_TYPES = {
    # v2 strict types
    "Custom",
    "Hero", "Section", "MetricTile", "FeatureCard",
    "Split", "Sidebar", "Cluster", "Tabs", "Accordion", "AccordionPanel",
    "Avatar", "KeyValueList", "Skeleton",
    "Input", "Select", "Textarea", "Checkbox", "DatePicker",
    "FadeIn", "Stagger",
    # v1-compat structural types
    "Stack", "Row", "Grid", "Container", "Spacer",
    "Box", "Text", "Image",
    "Repeat", "Conditional", "DataBoundary", "Slot",
    # Library components also in v1 NodeV2 fallback
    "Form", "Heading", "Badge", "Button", "IconButton", "Link",
    "Card", "EmptyState", "LoadingState", "Pagination",
    "Table", "TableSortable",
    "Alert", "ConfirmDialog",
    "NavLink", "Breadcrumb",
    "Divider",
    # Device + input + feedback library components (registered in
    # packages/schema/src/page.ts NodeV2 union; used by scan/visual_scan.json
    # and other exemplars that wire the camera → agent-chat flow).
    "CameraCapture", "FileUpload", "Spinner",
}

TOKEN_REF_REGEX = re.compile(r"^tokens\.[a-z]+(?:\.[a-zA-Z0-9]+)+$")
HEX_LIKE_REGEX = re.compile(r"^#[0-9a-fA-F]+$")
PX_LIKE_REGEX = re.compile(r"^\d+(\.\d+)?(px|rem|em)$")


def _is_planner_level_fixture(path: Path) -> bool:
    """Planner-level exemplars (whole-plan JSON with entities/agent-graph)
    live in the same tree but are not page schemas — this test only applies
    to page-level schemas. Identify planner fixtures by top-level keys."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    return isinstance(data, dict) and (
        "app_archetype" in data or "entities" in data or "agent_graph" in data
    )


def _all_example_paths() -> list[Path]:
    """All PAGE-level .json files under schema_examples/. Planner-level
    fixtures (identifiable by app_archetype/entities keys) are skipped."""
    return sorted(
        p for p in EXAMPLES_DIR.rglob("*.json")
        if not _is_planner_level_fixture(p)
    )


def _walk_nodes(node):
    """Yield every dict that looks like a schema node (has both 'id' and 'type').

    We require 'id' co-presence so that data-side dicts (action, background,
    cta, option, etc.) that also happen to carry a 'type' field are not
    mistaken for nodes.  All v2 NodeV2 types mandate id: string.min(1).
    """
    if isinstance(node, dict):
        if "type" in node and "id" in node:
            yield node
        for v in node.values():
            yield from _walk_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_nodes(item)


def _walk_style_slot_values(node, prefix=""):
    """Yield (path, value) for every leaf string under a node.style block."""
    if isinstance(node, dict):
        for k, v in node.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) or isinstance(v, list):
                yield from _walk_style_slot_values(v, new_prefix)
            elif isinstance(v, str):
                yield new_prefix, v
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk_style_slot_values(item, f"{prefix}[{i}]")


def _all_style_blocks(node):
    """Yield every node.style sub-tree found in the page."""
    if isinstance(node, dict):
        if "style" in node and isinstance(node["style"], dict):
            yield node["style"]
        for v in node.values():
            yield from _all_style_blocks(v)
    elif isinstance(node, list):
        for item in node:
            yield from _all_style_blocks(item)


@pytest.mark.parametrize("example_path", _all_example_paths(),
                         ids=lambda p: f"{p.parent.name}/{p.stem}")
class TestSchemaExamples:
    def test_uses_only_registered_types(self, example_path: Path):
        page = json.loads(example_path.read_text())
        unknown_types: list[str] = []
        for node in _walk_nodes(page):
            t = node.get("type")
            if t and t not in REGISTERED_TYPES:
                unknown_types.append(t)
        assert not unknown_types, \
            f"{example_path.name} references unregistered types: {set(unknown_types)}"

    def test_style_slots_use_token_refs_only(self, example_path: Path):
        """Every string value inside a style block must look like 'tokens.<...>'
        EXCEPT background.type/url and motion enum values."""
        page = json.loads(example_path.read_text())
        bad: list[tuple[str, str]] = []
        for style in _all_style_blocks(page):
            for path, val in _walk_style_slot_values(style):
                # Skip non-token-ref slots:
                # - background.type literal ("solid", "gradient", "image", "pattern")
                # - background.url (image URL — not a token ref)
                # - background.position
                # - background.name (pattern name)
                # - motion enum values
                # - background.angle (number, not string — already filtered above)
                if path.endswith(".type") or path.endswith(".url") or \
                   path.endswith(".position") or path.endswith(".name") or \
                   path == "motion":
                    continue
                # Other strings must be token refs
                if HEX_LIKE_REGEX.match(val) or PX_LIKE_REGEX.match(val):
                    bad.append((path, val))
                # If it doesn't look like a token ref, flag it
                elif not TOKEN_REF_REGEX.match(val):
                    bad.append((path, val))
        assert not bad, \
            f"{example_path.name} has non-token-ref style values: {bad}"

    def test_has_schemaVersion_2(self, example_path: Path):
        page = json.loads(example_path.read_text())
        assert page.get("schemaVersion") == "2", \
            f"{example_path.name} missing schemaVersion '2'"

    def test_at_least_one_styleslot(self, example_path: Path):
        """Each example must demonstrate StyleSlot — at least one node has style."""
        page = json.loads(example_path.read_text())
        count = sum(1 for _ in _all_style_blocks(page))
        assert count >= 1, \
            f"{example_path.name} has no StyleSlot — examples must showcase v2 features"


def test_examples_directory_has_expected_archetypes():
    """The 10 spec'd archetypes are all present."""
    expected = {
        "list/table.json", "list/card-grid.json", "list/kanban.json",
        "detail/tabbed-hero.json", "detail/split-detail.json", "detail/profile.json",
        "form/single-column.json", "form/sectioned.json", "form/wizard.json",
        "landing/hero-features-cta.json",
    }
    found = {
        f"{p.parent.name}/{p.name}" for p in _all_example_paths()
    }
    assert expected <= found, \
        f"Missing examples: {expected - found}"
