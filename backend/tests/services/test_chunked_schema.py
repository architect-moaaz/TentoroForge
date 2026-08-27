import asyncio

import json

from services.chunked_schema import is_output_overflow_error, generate_skeleton, region_placeholders, fill_region, assemble, generate_chunked_schema


def test_overflow_error_matches_cap_messages():
    for msg in [
        "Claude's response exceeded the 32000 output token maximum",
        "response exceeded the 64000 output token maximum",
        "max_tokens: prompt is too long",
        "Output token limit exceeded",
    ]:
        assert is_output_overflow_error(Exception(msg)) is True


def test_overflow_error_ignores_unrelated():
    assert is_output_overflow_error(Exception("Could not parse JSON")) is False
    assert is_output_overflow_error(ValueError("connection reset")) is False
    assert is_output_overflow_error(None) is False


_SKELETON_JSON = """
{"schemaVersion":"2","root":{"type":"Stack","id":"root","children":[
  {"type":"Region","id":"kpis","brief":"KPI metric tiles"},
  {"type":"Region","id":"chart","brief":"trend chart"},
  {"type":"Region","id":"table","brief":"recent records table"}
]}}
"""


def _llm_returning(text):
    async def _fake(prompt):
        return text
    return _fake


def test_generate_skeleton_parses_and_extracts_regions():
    skel = asyncio.run(generate_skeleton("BASE PROMPT", _llm_returning(_SKELETON_JSON)))
    assert skel is not None
    regions = region_placeholders(skel)
    assert [r["id"] for r in regions] == ["kpis", "chart", "table"]
    assert regions[0]["brief"] == "KPI metric tiles"


def test_generate_skeleton_none_when_no_regions():
    bad = '{"schemaVersion":"2","root":{"type":"Stack","id":"root","children":[]}}'
    assert asyncio.run(generate_skeleton("BASE", _llm_returning(bad))) is None
    assert asyncio.run(generate_skeleton("BASE", _llm_returning("not json"))) is None


def test_fill_region_parses_and_forces_id():
    node_json = '{"type":"Grid","id":"WRONG","children":[{"type":"MetricTile","id":"m1"}]}'
    node = asyncio.run(fill_region("BASE", {"id": "kpis", "brief": "KPI tiles"}, _llm_returning(node_json)))
    assert node is not None
    assert node["type"] == "Grid"
    assert node["id"] == "kpis"          # forced to the region id


def test_fill_region_none_on_bad_output():
    assert asyncio.run(fill_region("BASE", {"id": "x", "brief": "y"}, _llm_returning("nope"))) is None
    assert asyncio.run(fill_region("BASE", {"id": "x", "brief": "y"}, _llm_returning('{"no":"type"}'))) is None


def _skeleton():
    return {"schemaVersion": "2", "root": {"type": "Stack", "id": "root", "children": [
        {"type": "Region", "id": "kpis", "brief": "KPI tiles"},
        {"type": "Region", "id": "chart", "brief": "trend chart"},
    ]}}


def test_assemble_splices_filled_regions_in_order():
    filled = [
        {"type": "Grid", "id": "kpis", "children": []},
        {"type": "Card", "id": "chart", "children": []},
    ]
    out = assemble(_skeleton(), filled, {"id": "overview", "route": "/overview"})
    assert out["schemaVersion"] == "2" and out["id"] == "overview" and out["route"] == "/overview"
    kids = out["root"]["children"]
    assert [k["type"] for k in kids] == ["Grid", "Card"]
    assert [k["id"] for k in kids] == ["kpis", "chart"]
    # No Region placeholders survive
    assert all(k["type"] != "Region" for k in kids)


def test_assemble_failed_region_becomes_placeholder():
    out = assemble(_skeleton(), [{"type": "Grid", "id": "kpis"}, None], {"id": "p", "route": "/p"})
    kids = out["root"]["children"]
    assert kids[0]["type"] == "Grid"                     # good region kept
    assert kids[1]["type"] in ("Card", "Stack")          # failed region → placeholder node
    assert "trend chart" in json.dumps(kids[1])          # brief carried into placeholder


def _router_llm(skeleton_json, region_json_by_id):
    """Fake call_llm: returns skeleton for the skeleton directive, else the region's JSON."""
    async def _fake(prompt):
        if "SKELETON ONLY" in prompt:
            return skeleton_json
        for rid, payload in region_json_by_id.items():
            if f"Region id: {rid}" in prompt:
                return payload
        return "{}"
    return _fake


def test_orchestrator_assembles_multi_region_schema():
    skel = _SKELETON_JSON
    regions = {
        "kpis": '{"type":"Grid","id":"kpis","children":[]}',
        "chart": '{"type":"Card","id":"chart","children":[]}',
        "table": '{"type":"Table","id":"table","children":[]}',
    }
    out = asyncio.run(generate_chunked_schema("BASE", {"id": "ov", "route": "/ov"},
                                              _router_llm(skel, regions)))
    assert out is not None
    assert [k["type"] for k in out["root"]["children"]] == ["Grid", "Card", "Table"]
    assert out["id"] == "ov"


def test_orchestrator_none_when_skeleton_fails():
    async def _bad(prompt):
        return "not json"
    assert asyncio.run(generate_chunked_schema("BASE", {"id": "p", "route": "/p"}, _bad)) is None


def test_assembled_schema_is_structurally_valid():
    from services.schema_normalizer import normalize_v2_schema
    skel = _SKELETON_JSON
    regions = {
        "kpis":  '{"type":"Grid","id":"kpis","props":{"columns":3},"children":[{"type":"Heading","id":"k1","props":{"level":2,"content":"KPIs"}}]}',
        "chart": '{"type":"Card","id":"chart","children":[{"type":"Heading","id":"c1","props":{"level":2,"content":"Trend"}}]}',
        "table": '{"type":"Table","id":"table","children":[{"type":"Heading","id":"t1","props":{"level":2,"content":"Recent"}}]}',
    }
    out = asyncio.run(generate_chunked_schema("BASE", {"id": "ov", "route": "/ov"},
                                              _router_llm(skel, regions)))
    out = normalize_v2_schema(out)            # pure-python normalizer must not raise
    # Envelope is well-formed
    assert out["schemaVersion"] == "2" and out["id"] == "ov" and out["route"] == "/ov"
    root = out["root"]
    assert root.get("type") and isinstance(root.get("children"), list) and root["children"]
    # Every placeholder was replaced — no Region nodes survive anywhere in the tree
    def _all_types(node, acc):
        if isinstance(node, dict):
            if node.get("type"):
                acc.append(node["type"])
            for c in node.get("children") or []:
                _all_types(c, acc)
        return acc
    types = _all_types(root, [])
    assert "Region" not in types
    assert [c["type"] for c in root["children"]] == ["Grid", "Card", "Table"]
