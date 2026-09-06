"""The UX Pilot adapter against a fake MCP server: argument names come from
the tool schema, payloads are found without a fixed shape, and the four
inputs come out in the contract's vocabulary."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from services.design_source import DesignSourceError
from services.design_source.uxpilot import UxPilotSource, parse_uxpilot_ref, tokens_from_theme


@dataclass
class _Tool:
    name: str
    description: str
    input_schema: dict


_TOOLS = [
    _Tool("get_page_context", "", {"properties": {"pageId": {"type": "string"}}, "required": ["pageId"]}),
    _Tool("get_design", "", {"properties": {"designId": {"type": "string"}, "includeHtml": {"type": "boolean"}}, "required": ["designId"]}),
    _Tool("get_theme", "", {"properties": {"themeId": {"type": "string"}}, "required": ["themeId"]}),
    _Tool("list_diagrams", "", {"properties": {"pageId": {"type": "string"}}, "required": ["pageId"]}),
]

_HTML = {
    "d1": '<div style="display:flex;flex-direction:column;gap:24px;font-family:Manrope"><h1 style="color:#0F172A">Dashboard</h1><img src="https://img.uxpilot.ai/x/hero.png"></div>',
    "d2": '<div class="flex flex-col"><h2>Orders</h2><button class="bg-[#7C3AED] rounded-[6px]">New order</button></div>',
}


class _Server:
    def __init__(self, *, theme=True, diagrams=True):
        self.calls: list[tuple[str, dict]] = []
        self.theme = theme
        self.diagrams = diagrams

    async def list_tools(self):
        return _TOOLS

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == "get_page_context":
            payload = {"page": {"id": args["pageId"], "name": "Shop admin", "themeId": "t1" if self.theme else None},
                       "groups": [{"designs": [
                           {"id": "d1", "title": "Dashboard", "prompt": "an overview"},
                           {"id": "d2", "title": "Orders list"},
                           {"id": "d3", "title": "Orders list"},
                       ]}]}
        elif name == "get_design":
            payload = {"design": {"id": args["designId"], "html": _HTML.get(args["designId"], "")}}
        elif name == "get_theme":
            payload = {"theme": {"colors": {"primary": "#7C3AED", "bg": "#fff"},
                                 "typography": {"fontFamily": "Manrope, sans-serif", "fontSize": {"base": "14px"}},
                                 "radius": {"md": 8}, "spacing": {"lg": "24px"}}}
        elif name == "list_diagrams":
            if not self.diagrams:
                return {"content": [{"type": "text", "text": "no diagrams"}], "isError": True}
            payload = {"diagrams": [{"id": "g1", "type": "sitemap", "nodes": [], "edges": []}]}
        else:
            return {"content": [{"type": "text", "text": "unknown"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _source(server, page="pg_42"):
    return UxPilotSource(page, call_tool=server.call, list_tools=server.list_tools)


def test_parse_ref_accepts_ids_and_urls():
    assert parse_uxpilot_ref("pg_42") == "pg_42"
    assert parse_uxpilot_ref("https://uxpilot.ai/a/design/pg_42?x=1") == "pg_42"
    assert parse_uxpilot_ref("https://uxpilot.ai/app?pageId=pg_9") == "pg_9"


@pytest.mark.asyncio
async def test_scope_reads_designs_and_uses_schema_argument_names():
    srv = _Server()
    scope = await _source(srv).scope()
    assert scope.provider == "uxpilot" and scope.container == "pg_42"
    assert scope.name == "Shop admin"
    assert [p.ref for p in scope.pages] == ["d1", "d2", "d3"]
    # "Dashboard" is the home route to the shared route inferer.
    assert [p.route for p in scope.pages] == ["/", "/orders", "/orders-2"]
    assert scope.pages[0].prompt == "an overview"
    assert scope.pages[0].kind == "dashboard" and scope.pages[1].kind == "list"
    assert scope.flows == ({"id": "g1", "type": "sitemap", "nodes": [], "edges": []},)
    assert srv.calls[0] == ("get_page_context", {"pageId": "pg_42"})
    assert srv.calls[1] == ("list_diagrams", {"pageId": "pg_42"})


@pytest.mark.asyncio
async def test_scope_survives_a_failing_diagram_tool():
    scope = await _source(_Server(diagrams=False)).scope()
    assert scope.flows == ()


@pytest.mark.asyncio
async def test_markup_is_html_with_its_assets():
    srv = _Server()
    m = await _source(srv).markup("d1")
    assert m.kind == "html" and m.ref == "d1"
    assert "<h1" in m.source
    assert m.asset_urls == ("https://img.uxpilot.ai/x/hero.png",)
    assert srv.calls[-1] == ("get_design", {"designId": "d1", "includeHtml": True})


@pytest.mark.asyncio
async def test_markup_none_when_no_html_returned():
    assert await _source(_Server()).markup("d9") is None


@pytest.mark.asyncio
async def test_tokens_merge_theme_and_markup():
    t = await _source(_Server()).tokens()
    assert "#7C3AED" in t.colors and "#FFFFFF" in t.colors and "#0F172A" in t.colors
    assert "Manrope" in t.fonts
    assert 14.0 in t.font_sizes
    assert {8.0, 6.0} <= set(t.border_radii)
    assert 24.0 in t.spacings


@pytest.mark.asyncio
async def test_tokens_without_a_theme_come_from_markup_alone():
    t = await _source(_Server(theme=False)).tokens()
    assert "#0F172A" in t.colors and "Manrope" in t.fonts


def test_tokens_from_theme_reads_by_key_meaning():
    t = tokens_from_theme({"brand": "#abc", "font": {"body": "Inter"}, "borderRadius": {"sm": "4px"},
                           "gap": 12, "fontSize": 16, "weight": 700})
    assert t.colors == ("#AABBCC",)
    assert t.fonts == ("Inter",)
    assert t.border_radii == (4.0,)
    assert t.spacings == (12.0,)
    assert t.font_sizes == (16.0,)


@pytest.mark.asyncio
async def test_missing_tool_is_a_design_source_error():
    async def tools():
        return [_TOOLS[0]]

    src = UxPilotSource("pg", call_tool=_Server().call, list_tools=tools)
    with pytest.raises(DesignSourceError, match="get_design"):
        await src.markup("d1")


@pytest.mark.asyncio
async def test_page_without_designs_is_an_error():
    async def call(name, args):
        return {"content": [{"type": "text", "text": json.dumps({"page": {"name": "Empty"}, "designs": []})}], "isError": False}

    with pytest.raises(DesignSourceError, match="no designs"):
        await UxPilotSource("pg", call_tool=call, list_tools=_Server().list_tools).scope()
