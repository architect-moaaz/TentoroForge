"""The schema agent must pin each schema's `route` to its slug (registry key).

Regression for the /dashboard 404: the LLM writes its own `route` into the
schema body (a dashboard-style page emits "/dashboard", a watchlist page emits
"/watchlist-items"). The file, id, and registry key are all derived from the
slug — so if the internal route is trusted, nav links to a route that was never
registered and 404s. run_page_schema_agent must overwrite route with the slug.
"""
import asyncio
import json

import agents.page_schema_agent as psa


def _run(tmp_path, page, llm_route):
    async def _fake_gen(plan, pg, slug, domain_context, output_dir=None):
        # Simulate the LLM writing its own (wrong) route into the schema body.
        return {"root": {"type": "Stack", "children": []}, "route": llm_route}

    psa._generate_schema_for_page = _fake_gen  # monkeypatch the LLM call
    asyncio.run(psa.run_page_schema_agent(str(tmp_path), {"pages": [page]}, page))


def _written(tmp_path, slug):
    return json.loads((tmp_path / "src" / "schemas" / f"{slug}.json").read_text(encoding="utf-8"))


def test_pins_route_over_llm_dashboard_hallucination(tmp_path):
    # Page filed at /analytics, but the LLM emitted route "/dashboard".
    _run(tmp_path, {"name": "Analytics", "route": "/analytics"}, llm_route="/dashboard")
    schema = _written(tmp_path, "analytics")
    assert schema["route"] == "/analytics"   # pinned, not the LLM's /dashboard
    assert schema["id"] == "analytics"


def test_pins_route_over_pluralised_hallucination(tmp_path):
    _run(tmp_path, {"name": "Watchlist", "route": "/watchlist"}, llm_route="/watchlist-items")
    assert _written(tmp_path, "watchlist")["route"] == "/watchlist"


def test_route_matches_id_and_filename(tmp_path):
    # Even when the LLM omits route entirely, the pinned route == the registry key.
    _run(tmp_path, {"name": "Orders", "route": "/orders"}, llm_route=None)
    schema = _written(tmp_path, "orders")
    assert schema["route"] == "/orders" == f"/{schema['id']}"
