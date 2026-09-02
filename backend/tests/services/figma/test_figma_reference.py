"""§44-§55 — the design reference, and what it refuses to invent."""
import asyncio
import json

import pytest

from services.figma.reference import (
    DesignReference,
    ScreenRef,
    extract,
    payload_of,
    _screens_from_metadata,
    _tokens_from_variables,
)
from services.figma.url import FigmaTarget


TARGET = FigmaTarget(file_key="AbcDef123456", node_id=None)

METADATA = {
    "document": {
        "id": "0:0", "type": "DOCUMENT", "name": "Doc",
        "children": [{
            "id": "0:1", "type": "CANVAS", "name": "Screens",
            "children": [
                {"id": "1:2", "type": "FRAME", "name": "Candidate List",
                 "absoluteBoundingBox": {"width": 1440, "height": 900}},
                {"id": "1:3", "type": "FRAME", "name": "Candidate Details",
                 "absoluteBoundingBox": {"width": 1440, "height": 900}},
                {"id": "1:9", "type": "FRAME", "name": "Cover",
                 "absoluteBoundingBox": {"width": 400, "height": 300}},
            ],
        }],
    }
}

VARIABLES = {
    "color/brand/primary": "#3B5BDB",
    "color/surface/base": "#FFFFFF",
    "font/heading/lg": {"size": 32, "weight": 700},
    "spacing/md": 16,
    "radius/card": 12,
    "shadow/raised": "0 2px 8px rgba(0,0,0,.12)",
    "motion/duration": 200,
}


class FakeGateway:
    """Replays canned tool results; records what was asked for."""

    def __init__(self, results=None, fail=()):
        self.results = results or {}
        self.fail = set(fail)
        self.asked = []

    async def call(self, tool, *, file_key, node_id=None, **kw):
        self.asked.append((tool, node_id))
        if tool in self.fail:
            from services.figma.gateway import FigmaGatewayError
            raise FigmaGatewayError("tool_error", f"{tool} unavailable")
        value = self.results.get(tool, {})
        if callable(value):
            value = value(node_id)
        return [{"type": "structured", "data": value}] if isinstance(value, dict) else value


def run(coro):
    return asyncio.run(coro)


# -- normalisers -----------------------------------------------------------

def test_frames_become_screens_with_geometry():
    screens = _screens_from_metadata(
        [{"type": "structured", "data": METADATA}], limit=40
    )
    names = [s.name for s in screens]
    assert "Candidate List" in names and "Candidate Details" in names
    first = next(s for s in screens if s.name == "Candidate List")
    assert (first.node_id, first.canvas, first.width) == ("1:2", "Screens", 1440.0)


def test_non_screen_frames_are_marked_not_dropped():
    """§49 — inference carries confidence. A filter that guesses wrong deletes
    evidence with no trace that it did."""
    screens = _screens_from_metadata(
        [{"type": "structured", "data": METADATA}], limit=40
    )
    cover = next(s for s in screens if s.name == "Cover")
    assert cover.looks_like_screen is False
    assert cover in screens


def test_tokens_are_bucketed_by_the_authors_own_names():
    tokens = _tokens_from_variables([{"type": "structured", "data": VARIABLES}])
    assert tokens.colors == {
        "color/brand/primary": "#3B5BDB", "color/surface/base": "#FFFFFF"
    }
    assert "font/heading/lg" in tokens.typography
    assert "spacing/md" in tokens.spacing
    assert "radius/card" in tokens.radius
    assert "shadow/raised" in tokens.elevation
    assert "motion/duration" in tokens.other


def test_payload_of_accepts_structured_json_text_and_prose():
    assert payload_of([{"type": "structured", "data": {"a": 1}}]) == {"a": 1}
    assert payload_of([{"type": "text", "text": json.dumps({"a": 1})}]) == {"a": 1}
    assert payload_of([{"type": "text", "text": "just words"}]) == "just words"
    assert payload_of([]) is None


# -- extraction ------------------------------------------------------------

def test_extract_builds_a_reference():
    gw = FakeGateway({"get_metadata": METADATA, "get_variable_defs": VARIABLES})
    ref = run(extract(gw, TARGET, with_images=False))
    assert ref.summary()["screens"] == 2      # Cover excluded from the count
    assert ref.summary()["frames"] == 3       # but still present
    assert ref.tokens.colors


def test_structure_is_only_fetched_for_likely_screens():
    gw = FakeGateway({"get_metadata": METADATA, "get_variable_defs": VARIABLES})
    run(extract(gw, TARGET, with_images=False))
    contexts = [n for t, n in gw.asked if t == "get_design_context"]
    assert sorted(contexts) == ["1:2", "1:3"]


def test_missing_tokens_records_a_gap_rather_than_failing():
    gw = FakeGateway({"get_metadata": METADATA}, fail={"get_variable_defs"})
    ref = run(extract(gw, TARGET, with_images=False))
    assert ref.screens
    assert any("design tokens unavailable" in g for g in ref.gaps)
    assert any("publishes no design variables" in g for g in ref.gaps)


def test_unreachable_figma_propagates():
    """A reference built from nothing is not thin, it is wrong."""
    from services.figma.gateway import FigmaGatewayError
    gw = FakeGateway(fail={"get_metadata"})
    with pytest.raises(FigmaGatewayError):
        run(extract(gw, TARGET, with_images=False))


def test_empty_file_is_recorded_as_a_gap():
    gw = FakeGateway({"get_metadata": {"document": {"id": "0:0", "type": "DOCUMENT"}}})
    ref = run(extract(gw, TARGET, with_images=False))
    assert any("no frames found" in g for g in ref.gaps)


def test_components_and_interactions_come_off_the_structure():
    context = {
        "id": "1:2", "type": "FRAME", "name": "Candidate List",
        "children": [
            {"id": "5:1", "type": "COMPONENT", "name": "PrimaryButton",
             "variantProperties": {"size": "md", "tone": "brand"},
             "transitionNodeID": "1:3"},
        ],
    }
    gw = FakeGateway({
        "get_metadata": METADATA,
        "get_variable_defs": VARIABLES,
        "get_design_context": lambda node_id: context if node_id == "1:2" else {},
    })
    ref = run(extract(gw, TARGET, with_images=False))
    component = next(c for c in ref.components if c.name == "PrimaryButton")
    assert set(component.variants) == {"size", "tone"}
    assert any(
        i.source_node == "5:1" and i.target_node == "1:3" for i in ref.interactions
    )


def test_screenshots_attach_to_screens():
    gw = FakeGateway({
        "get_metadata": METADATA,
        "get_variable_defs": VARIABLES,
        "get_screenshot": [{"type": "image", "mimeType": "image/png", "data": "AAA"}],
    })
    ref = run(extract(gw, TARGET, with_images=True))
    rendered = [s for s in ref.screens if s.image]
    assert len(rendered) == 2
    assert rendered[0].image.startswith("data:image/png;base64,AAA")
    assert not ref.screen("1:9").image      # Cover is not rendered


# -- evidence (§14) --------------------------------------------------------

def test_evidence_entries_match_the_prd_shape():
    ref = DesignReference(target=TARGET, source_id="FIGMA-001")
    ref.screens = [ScreenRef(node_id="1:2", name="Candidate List", canvas="Screens")]
    entry = ref.evidence_for("1:2", ref.screens[0].evidence_locator)
    assert entry == {
        "type": "figma", "source": "FIGMA-001",
        "node": "1:2", "locator": "Screens/Candidate List",
    }


# -- against real recorded MCP output --------------------------------------

FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[2] / "fixtures" / "figma"


def test_hosted_mcp_returns_code_and_the_reference_says_so():
    """The hosted Figma MCP answers get_design_context with generated TSX, not
    a node tree. Walking it as a tree finds nothing and raises nothing, which
    is how a design with no components passes for a successful extraction."""
    code = (FIXTURES / "commitbiz_login_design_context.tsx").read_text("utf-8")
    gw = FakeGateway({
        "get_metadata": METADATA,
        "get_variable_defs": VARIABLES,
        "get_design_context": [{"type": "text", "text": code}],
    })
    ref = run(extract(gw, TARGET, with_images=False))

    structure = ref.screen("1:2").structure
    assert structure["source"] == "design_context_code"
    assert structure["code"].startswith("// Fixture")
    assert structure["assets"], "asset URLs are the screen's imagery evidence"
    assert all(a.startswith("https://www.figma.com/api/mcp/asset/") for a in structure["assets"])


def test_code_shaped_structure_yields_the_screens_vocabulary():
    """§49 infers capability from what the design says; the labels are that."""
    code = (FIXTURES / "commitbiz_login_design_context.tsx").read_text("utf-8")
    gw = FakeGateway({
        "get_metadata": METADATA,
        "get_variable_defs": VARIABLES,
        "get_design_context": [{"type": "text", "text": code}],
    })
    ref = run(extract(gw, TARGET, with_images=False))
    labels = ref.screen("1:2").structure["labels"]
    assert labels, "a login screen has visible copy"


def test_missing_interactions_are_reported_as_unavailable_not_absent():
    code = (FIXTURES / "commitbiz_login_design_context.tsx").read_text("utf-8")
    gw = FakeGateway({
        "get_metadata": METADATA,
        "get_variable_defs": VARIABLES,
        "get_design_context": [{"type": "text", "text": code}],
    })
    ref = run(extract(gw, TARGET, with_images=False))
    assert ref.interactions == []
    assert any("prototype interactions unavailable" in g for g in ref.gaps)


def test_rest_shaped_file_still_walks_as_a_tree():
    """The REST /files document shape must keep working — it is what a Dev
    Mode server and the fallback both return."""
    import json as _json
    doc = _json.loads((FIXTURES / "commitbiz_full_file.json").read_text("utf-8"))
    screens = _screens_from_metadata([{"type": "structured", "data": doc}], limit=40)
    assert screens, "the recorded file has frames"
    assert all(s.node_id for s in screens)
