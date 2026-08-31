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

# The registry is generated, so the test reads it rather than restating it.
# This list used to be 53 names maintained by hand beside a comment saying it
# "must be kept in sync with NodeV2" — it had drifted 113 components behind the
# catalog, and every enterprise pattern failed against a vocabulary that was
# only stale in the test.
_CATALOG = (Path(__file__).parent.parent.parent
            / "contracts" / "component-catalog.json")

#: Node types that are NOT library components and so never appear in the
#: catalog: control flow the renderer interprets itself, the escape hatch, and
#: two components declared in the schema union without a registry entry.
_NON_CATALOG_TYPES = {
    "Repeat", "Conditional", "DataBoundary", "Slot", "Custom",
    "ConfirmDialog", "Pagination",
}


def _registered_types() -> set[str]:
    catalog = json.loads(_CATALOG.read_text())["components"]
    names = {c["name"] if isinstance(c, dict) else c for c in catalog} \
        if isinstance(catalog, list) else set(catalog)
    return names | _NON_CATALOG_TYPES


REGISTERED_TYPES = _registered_types()

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
    """Yield every dict that looks like a schema node.

    Node types are PascalCase; the data-side dicts that also carry a `type`
    are not — background is "solid"/"gradient", action is "navigate"/
    "workflow", an input is "email"/"tel"/"text". Case is the discriminator.

    This used to require `id` co-presence instead, on the grounds that every
    NodeV2 mandates one. stateful_scan_page.json does not carry ids, so all
    31 of its nodes were skipped and the file passed while being checked for
    nothing — which is how it kept a reference to a component named `Camera`
    that the registry has never had. Measured over the whole corpus: no
    id-carrying node has a lowercase type, so nothing that was checked
    before stops being checked now.
    """
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t[:1].isupper():
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


def _is_gold_example(path: Path) -> bool:
    """A gold example lives in a page-type directory (detail/, form/, list/,
    landing/, scan/) — exactly what `load_gold_example` globs. Patterns live
    in enterprise/ or at the top level and are loaded by other functions for
    other reasons."""
    return path.parent != EXAMPLES_DIR and path.parent.name != "enterprise"


def test_the_gold_set_is_not_empty():
    """Guards the skip above. If the layout moves and every example starts
    looking like a pattern, the StyleSlot rule would pass by skipping
    everything — which is the failure this file just had in another form."""
    gold = [p for p in _all_example_paths() if _is_gold_example(p)]
    assert len(gold) >= 10, f"expected the gold examples, found {gold}"


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
        """Every GOLD example must demonstrate StyleSlot.

        Gold examples are the ones `schema_prompt.load_gold_example` hands the
        agent as few-shots for a (page_type, archetype) — they teach what a
        styled page looks like, so one with no style teaches the opposite.
        All ten carry between 3 and 11 style blocks.

        The patterns are a different artifact and are exempt.
        `load_enterprise_pattern` returns enterprise/*.json by keyword to
        supply STRUCTURE (master-detail, wizard, approval-flow), and
        stateful_scan_page.json is the canonical state-machine shape for the
        planner. Neither is ever consulted about styling, and requiring style
        of them was the rule reaching past what it was for.
        """
        if not _is_gold_example(example_path):
            pytest.skip("pattern, not a gold example — teaches structure, not style")
        page = json.loads(example_path.read_text())
        count = sum(1 for _ in _all_style_blocks(page))
        assert count >= 1, \
            f"{example_path.name} has no StyleSlot — gold examples must showcase v2 features"


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
