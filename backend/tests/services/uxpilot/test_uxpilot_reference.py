"""A UX Pilot page becomes the same DesignReference a Figma file does, and
the store, brief and DAG read it without knowing the difference."""
from __future__ import annotations

import json

import pytest

from services.blueprint.orchestrator import DAG, run, subjects_for
from services.blueprint.service import BlueprintService
from services.figma import store
from services.figma.brief import brief_for
from services.uxpilot.reference import extract, labels_of, tokens_from_theme
from services.uxpilot.url import page_id_of, parse

_HTML = ('<div style="display:flex;flex-direction:column;gap:24px;font-family:Manrope">'
         '<h1 style="color:#0F172A">Orders</h1><button>New order</button>'
         '<img src="https://img.uxpilot.ai/x/hero.png"></div>')


class _Gateway:
    def __init__(self, *, theme=True, html=True):
        self.calls = []
        self.theme = theme
        self.html = html

    async def call(self, tool, **kw):
        self.calls.append((tool, kw))
        if tool == "get_page_context":
            data = {"page": {"id": kw["page"], "name": "Shop admin", "themeId": "t1" if self.theme else None},
                    "designs": [{"id": "d1", "title": "Orders", "prompt": "orders list", "previewUrl": "https://p/1.png"},
                                {"id": "d2", "title": "Dashboard"}]}
        elif tool == "get_design":
            data = {"design": {"id": kw["design"], "html": _HTML if self.html else ""}}
        elif tool == "get_theme":
            data = {"colors": {"primary": "#7C3AED"}, "typography": {"fontFamily": "Manrope", "fontSize": {"base": "14px"}},
                    "radius": {"md": 8}}
        elif tool == "list_diagrams":
            data = {"diagrams": [{"id": "g", "edges": [{"from": "d2", "to": "d1"}]}]}
        else:
            raise AssertionError(tool)
        return [{"type": "text", "text": json.dumps(data)}]


@pytest.fixture()
def svc(tmp_path):
    return BlueprintService.create(output_dir=tmp_path, app_id="a", name="Shop", domain="Retail")


def test_page_refs_parse_from_ids_and_urls():
    assert page_id_of("pg_42") == "pg_42"
    assert page_id_of("https://uxpilot.ai/app/design/pg_42?x=1") == "pg_42"
    assert page_id_of("https://app.uxpilot.ai/p?pageId=pg_9") == "pg_9"
    assert page_id_of("not a page!") == ""
    t = parse("https://uxpilot.ai/app/design/pg_42")
    assert t.file_key == "pg_42" and t.kind == "uxpilot" and "UX Pilot page pg_42" == t.describe()
    assert parse("") is None


@pytest.mark.asyncio
async def test_extract_fills_the_shared_reference_shape():
    gw = _Gateway()
    ref = await extract(gw, parse("pg_42"), source_id="UXPILOT-001")
    assert ref.provider == "uxpilot" and ref.source_id == "UXPILOT-001"
    assert [s.node_id for s in ref.screens] == ["d1", "d2"]
    orders = ref.screen("d1")
    assert orders.canvas == "Shop admin" and orders.image == "https://p/1.png"
    assert orders.structure["source"] == "uxpilot_html"
    assert "Orders" in orders.structure["labels"] and "New order" in orders.structure["labels"]
    assert orders.structure["assets"] == ["https://img.uxpilot.ai/x/hero.png"]
    assert orders.structure["prompt"] == "orders list"
    assert ref.tokens.colors == {"colors.primary": "#7C3AED"}
    assert ref.tokens.typography["typography.fontFamily"] == "Manrope"
    assert ref.tokens.radius == {"radius.md": 8}
    assert [(i.source_node, i.target_node) for i in ref.interactions] == [("d2", "d1")]
    assert ref.evidence_for("d1") == {"type": "uxpilot", "source": "UXPILOT-001", "node": "d1"}
    # Read tools only, argument names by meaning.
    assert {c[0] for c in gw.calls} <= {"get_page_context", "get_design", "get_theme", "list_diagrams"}


@pytest.mark.asyncio
async def test_no_theme_means_measured_tokens_and_a_gap():
    ref = await extract(_Gateway(theme=False), parse("pg_1"))
    assert any("measured" in g for g in ref.gaps)
    assert ref.tokens.colors.get("measured/#0F172A") == "#0F172A"


@pytest.mark.asyncio
async def test_missing_html_is_a_gap_not_a_crash():
    ref = await extract(_Gateway(html=False), parse("pg_1"))
    assert any("no HTML returned" in g for g in ref.gaps)
    assert ref.screen("d1").structure.get("html") is None


def test_theme_tokens_read_by_key_meaning_and_labels_skip_scripts():
    t = tokens_from_theme({"brand": "#abc", "font": {"body": "Inter"}, "borderRadius": {"sm": "4px"}, "gap": 12})
    assert t.colors == {"brand": "#AABBCC"} and t.typography == {"font.body": "Inter"}
    assert t.radius == {"borderRadius.sm": "4px"} and t.spacing == {"gap": 12}
    assert labels_of("<body><script>x</script><h1>Welcome</h1><p>Hi</p></body>") == ["Welcome", "Hi"]


@pytest.mark.asyncio
async def test_the_store_the_brief_and_the_dag_take_a_uxpilot_source(svc):
    ref = await extract(_Gateway(), parse("pg_42"), source_id=store.next_source_id(svc.doc, "uxpilot"))
    record = store.connect(svc, ref, name="Shop admin", treat_as="specification")
    assert record["id"] == "UXPILOT-001" and record["type"] == "uxpilot" and record["fileKey"] == "pg_42"
    assert [f["nodeId"] for f in record["frames"]] == ["d1", "d2"]
    svc.validate()                                   # the contract admits it
    # Sequences are per provider.
    assert store.next_source_id(svc.doc, "uxpilot") == "UXPILOT-002"
    assert store.next_source_id(svc.doc, "figma") == "FIGMA-001"
    # The stored payload round-trips with its provider.
    again = store.load("UXPILOT-001", svc.output_dir)
    assert again.provider == "uxpilot" and again.screen("d1").structure["html"] == _HTML
    # The intelligence node fans out over it like any design source.
    assert subjects_for(DAG["figma_intelligence"], svc.doc) == ["UXPILOT-001"]
    brief = brief_for(svc.doc, "UXPILOT-001", svc.output_dir)
    assert brief["provider"] == "uxpilot" and brief["screens"][0]["labels"]
    # The design-system projection reads the theme.
    run(svc, lambda spec: None, plan=["figma_design_system"])
    assert svc.doc["designSystem"]["colors"] == {"colors.primary": "#7C3AED"}
