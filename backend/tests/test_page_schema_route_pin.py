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

#: The real seam, captured at import. `_run` replaces it for the duration of a
#: test and the last test here asserts it came back — see that test for what a
#: bare assignment cost.
_REAL_GENERATE = psa._generate_schema_for_page


def _run(monkeypatch, tmp_path, page, llm_route):
    async def _fake_gen(plan, pg, slug, domain_context, output_dir=None):
        # Simulate the LLM writing its own (wrong) route into the schema body.
        return {"root": {"type": "Stack", "children": []}, "route": llm_route}

    # `psa._generate_schema_for_page = _fake_gen` — a bare assignment, with a
    # comment calling it a monkeypatch — is what this used to do. Nothing put
    # the real function back, so for the rest of the session every caller of
    # the page-schema agent got this three-line stub: three tests in
    # `test_page_schema_chunk_trigger` failed with "unexpected keyword
    # argument 'max_retries'" and two in `test_resource_registry_context`
    # read `_fake_gen`'s source where they expected the prompt builder's.
    # Five failures in two unrelated files, from this line, and all five
    # passed when run on their own.
    monkeypatch.setattr(psa, "_generate_schema_for_page", _fake_gen)
    asyncio.run(psa.run_page_schema_agent(str(tmp_path), {"pages": [page]}, page))


def _written(tmp_path, slug):
    return json.loads((tmp_path / "src" / "schemas" / f"{slug}.json").read_text())


def test_pins_route_over_llm_dashboard_hallucination(monkeypatch, tmp_path):
    # Page filed at /analytics, but the LLM emitted route "/dashboard".
    _run(monkeypatch, tmp_path, {"name": "Analytics", "route": "/analytics"},
         llm_route="/dashboard")
    schema = _written(tmp_path, "analytics")
    assert schema["route"] == "/analytics"   # pinned, not the LLM's /dashboard
    assert schema["id"] == "analytics"


def test_pins_route_over_pluralised_hallucination(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path, {"name": "Watchlist", "route": "/watchlist"},
         llm_route="/watchlist-items")
    assert _written(tmp_path, "watchlist")["route"] == "/watchlist"


def test_route_matches_id_and_filename(monkeypatch, tmp_path):
    # Even when the LLM omits route entirely, the pinned route == the registry key.
    _run(monkeypatch, tmp_path, {"name": "Orders", "route": "/orders"}, llm_route=None)
    schema = _written(tmp_path, "orders")
    assert schema["route"] == "/orders" == f"/{schema['id']}"


def test_the_llm_seam_is_left_as_it_was_found():
    """Whatever this file stubs out, it puts back.

    The stub used to be installed by assignment and never removed, so the
    damage landed on whichever files pytest happened to collect afterwards —
    which is why the five failures it caused read as bugs in the chunk
    trigger and the resource-registry prompt, and why every one of them
    passed when run on its own. A leak is only ever found by the test that
    did not cause it.
    """
    assert psa._generate_schema_for_page is _REAL_GENERATE
