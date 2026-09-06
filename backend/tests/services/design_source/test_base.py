"""DesignScope.to_plan and DesignTokens are the seam every adapter feeds; pin
the plan shape the pipeline reads and the token dict the brief takes."""
from __future__ import annotations

from services.design_source import DesignPage, DesignScope, DesignTokens


def _scope(provider, **kw):
    pages = (
        DesignPage(route="/", title="Home", ref="r1", kind="dashboard"),
        DesignPage(route="/orders", title="Orders", ref="r2", kind="list", prompt="orders list"),
    )
    return DesignScope(provider=provider, container="C", name="Shop", pages=pages, ref="REF", **kw)


def test_to_plan_carries_provider_neutral_keys():
    plan = _scope("uxpilot").to_plan()
    assert plan["_design_driven"] is True
    assert plan["design"] == {"provider": "uxpilot", "container": "C", "ref": "REF"}
    assert [p["route"] for p in plan["pages"]] == ["/", "/orders"]
    assert plan["pages"][0]["design_ref"] == "r1"
    assert plan["pages"][0]["file"] == "src/schemas/home.json"
    assert plan["pages"][1]["file"] == "src/schemas/orders.json"
    assert plan["pages"][1]["prompt"] == "orders list"
    assert "prompt" not in plan["pages"][0]
    # A UX Pilot plan must never look like a Figma one to the Figma phases.
    assert "_figma_driven" not in plan
    assert "figma_node_id" not in plan["pages"][0]


def test_to_plan_keeps_figma_keys_for_the_figma_provider():
    plan = _scope("figma").to_plan()
    assert plan["_figma_driven"] is True and plan["_design_driven"] is True
    assert plan["figma_file_key"] == "C"
    assert plan["figma_url"] == "REF"
    assert plan["pages"][0]["figma_node_id"] == "r1"
    assert plan["pages"][0]["design_ref"] == "r1"


def test_to_plan_includes_flows_when_present():
    plan = _scope("uxpilot", flows=({"id": "d1", "kind": "sitemap"},)).to_plan()
    assert plan["design"]["flows"] == [{"id": "d1", "kind": "sitemap"}]


def test_tokens_as_dict_is_sorted_and_deduped():
    t = DesignTokens(colors=("#FFFFFF", "#000000", "#FFFFFF"), fonts=("Inter",),
                     font_sizes=(16, 14, 16), border_radii=(8,), spacings=(24, 8))
    assert t.as_dict() == {
        "colors": ["#000000", "#FFFFFF"], "fonts": ["Inter"],
        "font_sizes": [14.0, 16.0], "border_radii": [8.0], "spacings": [8.0, 24.0],
    }
    assert not t.is_empty
    assert DesignTokens().is_empty


def test_tokens_round_trip_and_merge():
    a = DesignTokens.from_dict({"colors": ["#111111"], "font_sizes": [12, "x"]})
    assert a.font_sizes == (12.0,)
    b = a.merged(DesignTokens(colors=("#222222",)))
    assert b.as_dict()["colors"] == ["#111111", "#222222"]
