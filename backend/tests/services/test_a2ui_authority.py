"""The A2UI composer may only own the dashboard when it earns it.

Why these tests are shaped this way
-----------------------------------
Adding a second writer to a slot that already has one is the exact failure the
dashboard single-writer fix removed a commit ago (two composers, and the one
that did the thinking lost). Doing it again is defensible only because the
handoff here is a GATE rather than a preference: A2UI ships if and only if the
page it produced clears the substance floor, and writes nothing otherwise.

So every test below pins one edge of "writes nothing": flag off, no entities,
composer throws, composed page is thin. The one positive case pins that a good
composition actually lands, with real sources and no sample data.

The MCP round trip is injected (`surface_provider`), because what needs pinning
is the decision, not the transport.
"""

import json
from pathlib import Path

import pytest

from services.a2ui_authority import (
    build_requirement,
    compose_dashboard_via_a2ui,
    compose_page_via_a2ui,
    compose_pages_via_a2ui,
    registry_for_binder,
)

PLAN = {
    "entities": {
        "Bill": {"table": "bills", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "title", "type": "varchar"},
            {"name": "status", "type": "varchar",
             "semantic": {"enum_values": ["draft", "in_progress", "done"]}},
        ]},
    },
    "pages": [{"route": "/", "kind": "dashboard"}],
}

MAQUETTE = {"primary_chart": {"kind": "bar", "entity": "Bill", "group_by": "status"}}

THIN_PAGE = {"schemaVersion": "2", "id": "home", "route": "/", "layout": "main",
             "root": {"type": "Stack", "props": {},
                      "children": [{"type": "Heading",
                                    "props": {"content": "Dashboard", "level": 1}}]},
             "dataSources": []}


def _app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(PLAN))
    (root / "src" / "contracts" / "dashboard-maquette.json").write_text(
        json.dumps(MAQUETTE))
    (root / "src" / "schemas" / "home.json").write_text(json.dumps(THIN_PAGE))
    return root


def _page(root: Path) -> dict:
    return json.loads((root / "src" / "schemas" / "home.json").read_text())


def _surface(components, data):
    return lambda *_: {"messages": [
        {"version": "v0.9", "updateDataModel": {"value": data}},
        {"version": "v0.9", "updateComponents": {"components": components}},
    ]}


# A composition that clears the floor: KPI row, chart, activity table.
GOOD = _surface(
    [
        {"id": "root", "component": "Stack", "children": ["kpis", "chart", "recent"]},
        {"id": "kpis", "component": "Row",
         "children": {"componentId": "tile", "path": "/kpis"}},
        {"id": "tile", "component": "MetricTile", "format": "number",
         "label": {"path": "label"}, "value": {"path": "value"}},
        {"id": "chart", "component": "Chart", "chartType": "bar",
         "title": "Bills by Stage", "data": {"path": "/chart/data"}},
        {"id": "recent", "component": "Table", "rows": {"path": "/bills/rows"}},
    ],
    # Three tiles, because KPI_FLOOR is three — a two-tile dashboard is one
    # the gate rejects, which is a different test (below).
    {"kpis": [{"label": "Total Bills", "value": "12"},
              {"label": "In Progress", "value": "4"},
              {"label": "Completed", "value": "8"}],
     "chart": {"data": [{"label": "draft", "value": 3}]},
     "bills": {"rows": [{"title": "Invented Bill 42"}]}},
)

# Structurally valid, and a dashboard with nothing on it.
THIN = _surface(
    [{"id": "root", "component": "Stack", "children": ["h"]},
     {"id": "h", "component": "Heading", "content": "Overview", "level": 1}],
    {},
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("FORGE_A2UI", "1")


# ────────────────────────────────────────────────────────── the positive case

def test_a_composition_that_clears_the_floor_is_written(tmp_path):
    root = _app(tmp_path)
    res = compose_dashboard_via_a2ui(str(root), surface_provider=GOOD)
    assert res["applied"] is True, res["reason"]

    from services.dashboard_anatomy import dashboard_findings
    assert dashboard_findings("/", _page(root), {}) == []


def test_the_written_page_binds_to_real_sources(tmp_path):
    root = _app(tmp_path)
    compose_dashboard_via_a2ui(str(root), surface_provider=GOOD)
    ops = {s["op"] for s in _page(root)["dataSources"]}
    assert {"aggregate", "series", "list"} <= ops


def test_the_invented_sample_data_never_reaches_disk(tmp_path):
    """The payload carries fiction by design. A page that imported it would
    look finished, be false, and pass every structural gate in the pipeline."""
    root = _app(tmp_path)
    compose_dashboard_via_a2ui(str(root), surface_provider=GOOD)
    blob = (root / "src" / "schemas" / "home.json").read_text()
    assert "Invented Bill 42" not in blob and '"12"' not in blob


# ─────────────────────────────────────────────────────── every way it declines

def test_a_thin_composition_is_discarded_not_written(tmp_path):
    """The whole basis for allowing a second writer here."""
    root = _app(tmp_path)
    before = _page(root)
    res = compose_dashboard_via_a2ui(str(root), surface_provider=THIN)
    assert res["applied"] is False
    assert "dashboard_no_kpis" in res["findings"]
    assert _page(root) == before, "a rejected composition must not touch the page"


def test_a2ui_composes_by_default(tmp_path, monkeypatch):
    """§34: "The Page Design Agent shall use A2UI MCP as its primary
    page-generation capability."

    This asserted the opposite — that composition was a no-op unless
    FORGE_A2UI was set — for an A/B the PRD has since decided. A flag gating
    the specified default is the divergence, not the default.

    What still protects a build is not a flag: a composition that does not
    clear its substance floor writes nothing and the deterministic composer
    runs, which the two tests either side of this one cover.
    """
    monkeypatch.delenv("FORGE_A2UI", raising=False)
    root = _app(tmp_path)
    res = compose_dashboard_via_a2ui(str(root), surface_provider=GOOD)
    assert res["applied"] is True, res.get("reason")
    assert _page(root) != THIN_PAGE, "the composition should have been written"


def test_a_failing_composer_never_fails_the_build(tmp_path):
    def boom(*_):
        raise RuntimeError("mcp server died")

    root = _app(tmp_path)
    res = compose_dashboard_via_a2ui(str(root), surface_provider=boom)
    assert res["applied"] is False and "mcp server died" in res["reason"]
    assert _page(root) == THIN_PAGE


def test_no_entities_means_every_binding_would_be_a_guess(tmp_path):
    root = _app(tmp_path)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({"entities": {}}))
    res = compose_dashboard_via_a2ui(str(root), surface_provider=GOOD)
    assert res["applied"] is False and "no entities" in res["reason"]


def test_no_dashboard_page_means_nothing_to_own(tmp_path):
    root = _app(tmp_path)
    (root / "src" / "schemas" / "home.json").unlink()
    res = compose_dashboard_via_a2ui(str(root), surface_provider=GOOD)
    assert res["applied"] is False and "no landing dashboard" in res["reason"]


# ──────────────────────────────────────────────────────────────── the inputs

def test_the_registry_adapter_reads_the_plan_not_a_second_source():
    """A second source of entity truth here would reintroduce exactly the
    naming drift this effort is closing."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "src" / "contracts").mkdir(parents=True)
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps(PLAN))
        reg = registry_for_binder(root)

    bill = reg["entities"]["Bill"]
    assert bill["slug"] == "bills"
    status = next(c for c in bill["columns"] if c["name"] == "status")
    assert status["enum"] == ["draft", "in_progress", "done"]


def test_the_requirement_does_not_dictate_the_composition(tmp_path):
    """This test used to assert the opposite, and that was the bug.

    The requirement handed over the whole maquette under "the content has
    already been decided — render exactly these", which reduced the composer
    to a renderer of Forge's decisions. Measured on a real app it obeyed
    exactly: the four KPI labels, the chart, the activity feed and even the
    Kanban all traced back to the maquette's own `signature_moves`. The one
    thing worth having from a second composer — its own read of what the
    domain needs — was constrained away before the model saw the question.
    """
    root = _app(tmp_path)
    req = build_requirement(root)
    assert "render exactly these" not in req
    assert "primary_chart" not in req and "Bills by Stage" not in req


def test_the_requirement_states_the_job_and_the_domain(tmp_path):
    root = _app(tmp_path)
    req = build_requirement(root)
    assert "Compose the / screen of" in req
    assert "Decide what belongs on it" in req
    # The one hard rule that survives: no invented numbers.
    assert "bind it, or leave it out" in req


# ───────────────────────────── the montage's layout language (shape, not content)
#
# `ensure_composition_reference` runs first in the maquettes node so the
# dashboard, collection and record authors all inherit one house style. It is
# why the maquette wrote exactly five KPIs on the legislative build — the
# reference reads "dense — 5 KPIs above the fold". A2UI was composing without
# it, which made the two composers incomparable: one following a design
# reference, one working from the domain alone.

REFERENCE = {
    "source": "BizHub Business Management montage (9 screens)",
    "screens": {
        "dashboard": {
            "regions": ["greeting header with a date-range control",
                        "kpi strip of 5 tiles, each with a delta"],
            "density": "dense — 5 KPIs above the fold, then three rows of three",
            "hero_kind": "personalised-greeting",
        },
        "collection": {"regions": ["table"], "density": "6-7 columns"},
    },
}


def _with_reference(root: Path) -> Path:
    (root / "src" / "contracts" / "composition-reference.json").write_text(
        json.dumps(REFERENCE), encoding="utf-8")
    return root


def test_the_house_layout_reaches_the_composer(tmp_path):
    req = build_requirement(_with_reference(_app(tmp_path)))
    assert "kpi strip of 5 tiles" in req
    assert "dense — 5 KPIs above the fold" in req
    assert "BizHub" in req, "name the reference — it is evidence, not folklore"


def test_only_the_dashboard_screen_is_sent(tmp_path):
    """A landing-page composer has no use for the collection's column count,
    and every irrelevant line is one more thing to drift against."""
    req = build_requirement(_with_reference(_app(tmp_path)))
    assert "6-7 columns" not in req


def test_the_layout_is_framed_as_shape_not_content(tmp_path):
    """The whole reason the requirement stopped shipping the maquette was that
    "render exactly these" reduced the composer to a renderer. Regions and
    density name no entity and no number, so they restore the shared design
    language without restoring that constraint — but only if the prompt says
    so plainly."""
    req = build_requirement(_with_reference(_app(tmp_path)))
    assert "names no metric, no entity and no number" in req
    assert "still your call from the domain" in req
    assert "render exactly these" not in req
    # and the maquette's actual content is still nowhere near it
    assert "Bills by Stage" not in req and "primary_chart" not in req


def test_an_app_with_no_montage_is_unaffected(tmp_path):
    req = build_requirement(_app(tmp_path))
    assert "HOUSE LAYOUT" not in req
    assert "Decide what belongs on it" in req, "the rest of it still stands"


def test_an_unreadable_reference_never_breaks_the_requirement(tmp_path):
    root = _app(tmp_path)
    (root / "src" / "contracts" / "composition-reference.json").write_text("{{{")
    req = build_requirement(root)
    assert "Decide what belongs on it" in req and "HOUSE LAYOUT" not in req


# ────────────────────────────────────── every page kind, one path (A2UI-full)

def _plan_with_pages(root: Path, pages):
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        **PLAN, "pages": pages}), encoding="utf-8")
    return root


def _page_file(root: Path, name: str, route: str, *types):
    kids = [{"type": t, "props": {}} for t in types]
    (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps({
        "schemaVersion": "2", "id": name, "route": route, "layout": "main",
        "root": {"type": "Stack", "props": {}, "children": kids},
        "dataSources": []}), encoding="utf-8")


COLLECTION_SURFACE = _surface(
    [{"id": "root", "component": "Stack", "children": ["t", "b"]},
     {"id": "t", "component": "Table", "rows": {"path": "/bills/rows"}},
     {"id": "b", "component": "Button", "label": "New Bill"}],
    {"bills": {"rows": []}})


def test_a_collection_route_is_judged_by_the_collection_floor(tmp_path):
    """Not the dashboard's. A list page has no business being asked for KPIs,
    and asking would decline every good one."""
    root = _app(tmp_path)
    _page_file(root, "bills", "/bills", "Heading")
    res = compose_page_via_a2ui(str(root), "/bills", "list",
                                surface_provider=COLLECTION_SURFACE)
    assert res["applied"] is True, res["reason"]
    doc = json.loads((root / "src" / "schemas" / "bills.json").read_text())
    types = {n["type"] for n in [doc["root"], *doc["root"]["children"]]}
    assert "Table" in types


def test_a_thin_collection_is_declined_by_its_own_floor(tmp_path):
    root = _app(tmp_path)
    _page_file(root, "bills", "/bills", "Heading")
    before = (root / "src" / "schemas" / "bills.json").read_text()
    res = compose_page_via_a2ui(str(root), "/bills", "list",
                                surface_provider=THIN)
    assert res["applied"] is False
    assert "collection_no_list_surface" in res["findings"]
    assert (root / "src" / "schemas" / "bills.json").read_text() == before


def test_the_route_finds_its_schema_file_by_route_not_filename(tmp_path):
    """`/dashboard` lives in dashboard.json, `/` sometimes in home.json. The
    two do not reliably agree and matching on the filename silently composes
    the wrong page."""
    root = _app(tmp_path)
    _page_file(root, "oddly-named", "/bills", "Heading")
    res = compose_page_via_a2ui(str(root), "/bills", "list",
                                surface_provider=COLLECTION_SURFACE)
    assert res["applied"] is True
    assert res["schema_path"].endswith("oddly-named.json")


def test_the_page_loop_is_capped_and_says_what_it_skipped(tmp_path, monkeypatch):
    """One composition is 4-6 minutes. A twenty-page app done page by page is
    two hours, which is not a build anybody waits for. A run that quietly did
    half the work reads exactly like one that did all of it.

    The cap only bites in FORGE_A2UI_SCOPE=pages — the shipped default is
    dashboard-only, where there is nothing to cap."""
    monkeypatch.setenv("FORGE_A2UI_SCOPE", "pages")
    root = _app(tmp_path)
    pages = [{"route": "/", "kind": "dashboard"},
             {"route": "/bills", "kind": "list"},
             {"route": "/votes", "kind": "list"},
             {"route": "/login", "kind": "auth"}]
    _plan_with_pages(root, pages)
    for n, r in (("bills", "/bills"), ("votes", "/votes"), ("login", "/login")):
        _page_file(root, n, r, "Heading")

    out = compose_pages_via_a2ui(str(root), surface_provider=COLLECTION_SURFACE,
                                 limit=2)
    assert out["attempted"] == 2
    assert out["skipped_by_cap"], "what the cap dropped must be reported"
    # auth has no shape opinion, so it is never a candidate at all
    assert "/login" not in out["skipped_by_cap"]
    assert "/login" not in [p["route"] for p in out["pages"]]


def test_the_dashboard_goes_first_when_the_cap_bites(tmp_path):
    """The cap should spend its budget on the screen a reader reaches first."""
    root = _app(tmp_path)
    _plan_with_pages(root, [{"route": "/bills", "kind": "list"},
                            {"route": "/votes", "kind": "list"},
                            {"route": "/", "kind": "dashboard"}])
    for n, r in (("bills", "/bills"), ("votes", "/votes")):
        _page_file(root, n, r, "Heading")
    out = compose_pages_via_a2ui(str(root), surface_provider=COLLECTION_SURFACE,
                                 limit=1)
    assert [p["route"] for p in out["pages"]] == ["/"]


# --- nested schema files ------------------------------------------------
#
# Detail and nested-create pages do not live at the top of ``src/schemas``.
# ``/sessions/[id]`` is ``src/schemas/sessions/[id].json``; a real app carries
# 48 of those against 17 top-level files. The route finder used to glob
# ``*.json``, so page authority reached about a quarter of the app and
# reported the rest as "no schema file serves this route" — a lookup miss
# wearing the costume of a missing page.


def _schema_at(root: Path, rel: str, route: str) -> Path:
    p = root / "src" / "schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schemaVersion": "2", "id": rel, "route": route, "layout": "main",
        "root": {"type": "Stack", "props": {}, "children": []},
        "dataSources": [],
    }), encoding="utf-8")
    return p


def test_a_nested_detail_schema_is_found(tmp_path):
    from services.a2ui_authority import _schema_path_for_route
    root = tmp_path / "app"
    want = _schema_at(root, "sessions/[id].json", "/sessions/[id]")
    _schema_at(root, "sessions.json", "/sessions")
    assert _schema_path_for_route(root, "/sessions/[id]") == want


def test_a_deeply_nested_schema_is_found(tmp_path):
    """Sub-resource routes nest three deep in real apps."""
    from services.a2ui_authority import _schema_path_for_route
    root = tmp_path / "app"
    want = _schema_at(root, "sessions/[id]/votes/new.json",
                      "/sessions/[id]/votes/new")
    assert _schema_path_for_route(root, "/sessions/[id]/votes/new") == want


def test_a_top_level_file_still_wins_its_own_route(tmp_path):
    from services.a2ui_authority import _schema_path_for_route
    root = tmp_path / "app"
    want = _schema_at(root, "sessions.json", "/sessions")
    _schema_at(root, "sessions/[id].json", "/sessions/[id]")
    assert _schema_path_for_route(root, "/sessions") == want


def test_the_shell_is_never_mistaken_for_a_page(tmp_path):
    """shell.json carries no route, but nested shells must skip too."""
    from services.a2ui_authority import _schema_path_for_route
    root = tmp_path / "app"
    _schema_at(root, "shell.json", "/sessions")
    assert _schema_path_for_route(root, "/sessions") is None


# --- error legibility ---------------------------------------------------
#
# A composition that fails should say WHY. anyio wraps whatever the stdio
# session raised in an ExceptionGroup whose message is "unhandled errors in a
# TaskGroup (1 sub-exception)" — and those groups nest, so peeling one level
# hands back the same sentence and reads as though nothing was unwrapped.


def test_a_single_wrapped_error_is_unwrapped():
    from services.a2ui_authority import _unwrap_group
    real = ValueError("catalog id did not match")
    assert _unwrap_group(ExceptionGroup("tg", [real])) is real


def test_nested_groups_are_peeled_all_the_way_down():
    """The bug: one peel is not enough, and the second group looks identical."""
    from services.a2ui_authority import _unwrap_group
    real = ValueError("catalog id did not match")
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [real])])
    assert _unwrap_group(nested) is real


def test_a_plain_exception_passes_through():
    from services.a2ui_authority import _unwrap_group
    real = RuntimeError("no content")
    assert _unwrap_group(real) is real


def test_several_real_errors_are_all_reported():
    """Collapsing to the first child would hide the others."""
    from services.a2ui_authority import _unwrap_group
    out = _unwrap_group(ExceptionGroup(
        "tg", [ValueError("bad id"), RuntimeError("no content")]))
    assert "2 concurrent failures" in str(out)
    assert "bad id" in str(out) and "no content" in str(out)


def test_a_cycle_of_wrappers_cannot_hang_the_build():
    from services.a2ui_authority import _unwrap_group

    class Loop(Exception):
        @property
        def exceptions(self):
            return (self,)

    assert isinstance(_unwrap_group(Loop()), BaseException)


# --- composition scope ---------------------------------------------------
#
# A2UI page authority proved out on four page kinds, but every composition is
# a 2-4 minute round trip and one of the four live attempts failed on a
# transient fault that a retry cleared. Until that failure rate is measured,
# the scope worth shipping is the one screen the whole app is judged by.
#
# FORGE_A2UI_SCOPE defaults to "dashboard". "pages" restores the capped
# multi-kind behaviour without a code change.


def _plan_app(tmp_path, pages) -> str:
    root = tmp_path / "app"
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({"pages": pages, "entities": []}), encoding="utf-8")
    for p in pages:
        slug = (p["route"].strip("/") or "home").replace("/", "-")
        (root / "src" / "schemas" / f"{slug}.json").write_text(json.dumps({
            "schemaVersion": "2", "id": slug, "route": p["route"],
            "root": {"type": "Stack", "props": {}, "children": []},
            "dataSources": [],
        }), encoding="utf-8")
    return str(root)


PAGES = [
    {"route": "/dashboard", "kind": "dashboard"},
    {"route": "/sessions", "kind": "list"},
    {"route": "/sessions/new", "kind": "form"},
]


def test_the_default_scope_offers_only_the_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_A2UI", "1")
    monkeypatch.delenv("FORGE_A2UI_SCOPE", raising=False)
    seen: list = []

    def _provider(**kw):
        seen.append(kw.get("route"))
        raise RuntimeError("stop after selection")

    res = compose_pages_via_a2ui(_plan_app(tmp_path, PAGES),
                                 surface_provider=_provider)
    assert res["attempted"] == 1, res
    assert [r["route"] for r in res.get("declined") or []] == ["/dashboard"]


def test_scope_pages_restores_the_multi_kind_behaviour(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_A2UI", "1")
    monkeypatch.setenv("FORGE_A2UI_SCOPE", "pages")

    def _provider(**kw):
        raise RuntimeError("stop after selection")

    res = compose_pages_via_a2ui(_plan_app(tmp_path, PAGES),
                                 surface_provider=_provider)
    assert res["attempted"] == 3, res


def test_an_app_with_no_dashboard_attempts_nothing_by_default(tmp_path, monkeypatch):
    """Not 'fall through to a collection' — the scope is the dashboard."""
    monkeypatch.setenv("FORGE_A2UI", "1")
    monkeypatch.delenv("FORGE_A2UI_SCOPE", raising=False)
    res = compose_pages_via_a2ui(
        _plan_app(tmp_path, [{"route": "/sessions", "kind": "list"}]),
        surface_provider=lambda **kw: None)
    assert res["attempted"] == 0, res


# --- §35: a screen is composed as part of a set -----------------------------


def test_the_domain_context_carries_the_rest_of_the_application(tmp_path):
    """Navigation presentation and density are properties of a set. Composed
    alone, a bike shop rendered its heading twice and wrote its empty states
    in three voices.

    Carried by the domain context rather than the requirement: the A2UI server
    scans the requirement alone for capability keywords, and a design system
    carries `typography` and `radius: {badge, pill}`, so every page was held
    to have asked for a chart and a status pill.
    """
    from services.a2ui_authority import build_domain_context

    ctx = build_domain_context(
        tmp_path, {"entities": {}},
        shared_context='{"pages": ["/articles/[id]"]}')
    assert "/articles/[id]" in ctx
    assert "belongs beside them" in ctx


def test_the_requirement_does_not_carry_the_design_system(tmp_path):
    """The requirement is the string that gets parsed as a list of demands."""
    from services.a2ui_authority import build_requirement

    root = _app(tmp_path)
    req = build_requirement(root, "entity_list", "/articles",
                            shared_context='{"radius": {"badge": "999px"}}')
    assert "badge" not in req


def test_without_a_shared_context_the_requirement_is_unchanged(tmp_path):
    """A composer with no siblings to know about asks exactly what it did."""
    from services.a2ui_authority import build_requirement

    root = _app(tmp_path)
    assert build_requirement(root, "entity_list", "/articles") == \
        build_requirement(root, "entity_list", "/articles", shared_context="")


def test_the_sibling_pages_are_context_not_a_specification(tmp_path):
    """The maquette was sent as "render exactly these" and A2UI obeyed,
    which constrained away the second opinion the step exists for. The page
    set must not repeat that mistake."""
    from services.a2ui_authority import build_domain_context

    ctx = build_domain_context(tmp_path, {"entities": {}},
                               shared_context='{"pages": ["/x"]}')
    assert "Reuse a pattern already established" in ctx
    assert "render exactly" not in ctx


# --- §34: compose before projection, return the surface ---------------------


def test_a_page_composes_without_a_schema_file(tmp_path):
    """It used to decline when no file served the route, which made it a
    post-projection composer — it could only improve a page `frontend` had
    already written. §34 puts A2UI inside the generation step, where by
    definition nothing has been projected yet."""
    from services.a2ui_authority import compose_page_via_a2ui

    root = _app(tmp_path)
    res = compose_page_via_a2ui(str(root), "/nowhere-on-disk", "dashboard",
                                surface_provider=GOOD, page_id="PAGE-007")
    assert "no schema file" not in (res.get("reason") or "")


def test_the_composition_comes_back_for_a_caller_to_emit(tmp_path):
    """`page_layouts` emits a pageLayouts artifact; it cannot read a file the
    composer wrote, because at wave 7 there is none."""
    from services.a2ui_authority import compose_page_via_a2ui

    root = _app(tmp_path)
    res = compose_page_via_a2ui(str(root), "/", "dashboard",
                                surface_provider=GOOD, page_id="PAGE-001")
    assert res["applied"] is True, res.get("reason")
    assert res["root"], "the tree the caller turns into an artifact"
    assert res["page_id"] == "PAGE-001"


def test_the_caller_s_page_id_wins_over_the_file(tmp_path):
    """Blueprint ids are allocated by the pipeline, not read back off disk."""
    from services.a2ui_authority import compose_page_via_a2ui

    root = _app(tmp_path)
    res = compose_page_via_a2ui(str(root), "/", "dashboard",
                                surface_provider=GOOD, page_id="PAGE-042")
    assert res["page_id"] == "PAGE-042"


def test_an_existing_page_is_still_written_in_place(tmp_path):
    """Improving a projected page keeps working — the write did not move, it
    became conditional on there being something to write to."""
    from services.a2ui_authority import compose_page_via_a2ui

    root = _app(tmp_path)
    before = _page(root)
    res = compose_page_via_a2ui(str(root), "/", "dashboard",
                                surface_provider=GOOD)
    assert res["applied"] is True
    assert _page(root) != before
    assert res["schema_path"]


# --- §115: the Blueprint is where this pipeline's entities live -------------


def test_the_registry_can_come_from_the_blueprint():
    """registry_for_binder adapts plan.json, which the Blueprint pipeline does
    not have. Every page declined with "no entities in the plan — every
    binding would be a guess" and fell through to the authoring agent. The
    composer was right to refuse; it was reading the wrong source."""
    from services.a2ui_authority import registry_from_blueprint

    doc = {"data": {"entities": [
        {"id": "E1", "name": "Habit", "table": "habits", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "name", "type": "string"},
            {"name": "cadence", "type": "string",
             "enumValues": ["daily", "weekly"]},
        ]},
    ]}, "workflows": [{"id": "FLOW-001", "name": "Tick a habit off",
                       "trigger": {"kind": "manual"}}]}
    reg = registry_from_blueprint(doc)
    habit = reg["entities"]["Habit"]
    assert habit["slug"] == "habits"
    assert {c["name"] for c in habit["columns"]} == {"id", "name", "cadence"}
    assert habit["columns"][2]["enum"] == ["daily", "weekly"]
    # Carried by id, because that is what the generated route resolves.
    assert [w["id"] for w in reg["workflows"]] == ["FLOW-001"]
    assert reg["workflows"][0]["name"] == "Tick a habit off"


def test_an_entity_without_a_table_falls_back_to_its_name():
    from services.a2ui_authority import registry_from_blueprint

    reg = registry_from_blueprint({"data": {"entities": [{"name": "Habit"}]}})
    assert reg["entities"]["Habit"]["slug"] == "habit"


def test_a_caller_supplied_registry_is_used_over_the_plan(tmp_path):
    """The plan.json adapter stays for the pipeline that has a plan."""
    import inspect

    from services.a2ui_authority import compose_page_via_a2ui

    assert "registry" in inspect.signature(compose_page_via_a2ui).parameters
    src = inspect.getsource(compose_page_via_a2ui)
    assert "registry if registry is not None else registry_for_binder" in src


# --- the job asked for must match the screen --------------------------------


def test_blueprint_patterns_map_to_their_job_family():
    """page_family knows the old pipeline's kinds and returns None for every
    Blueprint pattern but `form`, so a create screen was handed the dashboard
    job: "decide which numbers matter and what breakdown is worth charting",
    sent verbatim to /recipes/new."""
    from services.a2ui_authority import _family_of

    assert _family_of("entity_list") == "collection"
    assert _family_of("record_workspace") == "record"
    assert _family_of("master_detail") == "record"
    assert _family_of("form") == "form"
    assert _family_of("wizard") == "form"
    assert _family_of("dashboard") == "dashboard"


def test_an_unknown_kind_still_falls_back():
    """Right for a kind nobody declared; it was only wrong for known ones."""
    from services.a2ui_authority import _family_of

    assert _family_of("something-nobody-declared") == "dashboard"


def test_the_domain_context_can_come_from_a_supplied_registry():
    """It read plan.json through registry_for_binder — the same missing file
    that emptied the registry — so `domainContext` reached the server blank."""
    from services.a2ui_authority import build_domain_context

    reg = {"entities": {"Recipe": {"slug": "recipes", "columns": [
        {"name": "name", "type": "varchar"},
        {"name": "minutes", "type": "integer"}]}}}
    ctx = build_domain_context(None, reg)
    assert "Recipe" in ctx and "minutes" in ctx


# ---------------------------------------------------------------------------
# The domain context carries verbs, not only nouns.
#
# A composed /plants came back with no button of any kind, for an app whose
# description says marking a plant watered is the only action. Correctly, on
# what it was given: the job asks "what they do to a record", the closing rule
# says do not invent, and the context listed entities and columns alone.
# ---------------------------------------------------------------------------

def _watering_doc():
    return {
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Plant", "table": "plants",
             "fields": [{"name": "id", "type": "uuid"},
                        {"name": "name", "type": "varchar"}]},
        ]},
        "workflows": [
            {"id": "FLOW-001", "name": "Record Watering Today",
             "purpose": "Append one watering event dated today.",
             "trigger": {"kind": "manual"},
             "launchedFrom": ["PAGE-001", "PAGE-002"]},
            {"id": "FLOW-002", "name": "Evaluate Plant Watering Status",
             "purpose": "Derivation that runs on every read.",
             "trigger": {"kind": "condition"},
             "launchedFrom": ["PAGE-001", "PAGE-002"]},
            {"id": "FLOW-004", "name": "Seed Plant Catalogue",
             "purpose": "Database initialisation.",
             "trigger": {"kind": "event"}, "launchedFrom": []},
        ],
    }


def test_the_registry_carries_workflow_ids_not_only_names(tmp_path):
    from services.a2ui_authority import registry_from_blueprint

    flows = registry_from_blueprint(_watering_doc())["workflows"]
    # The generated route is /api/workflows/{id}/execute, so the id is the only
    # value a Button or Form can carry that reaches anything.
    assert {w["id"] for w in flows} == {"FLOW-001", "FLOW-002", "FLOW-004"}
    assert {w["trigger"] for w in flows} == {"manual", "condition", "event"}


def test_the_page_is_told_the_workflows_it_launches(tmp_path):
    from services.a2ui_authority import (
        build_domain_context, registry_from_blueprint,
    )

    reg = registry_from_blueprint(_watering_doc())
    ctx = build_domain_context(tmp_path, reg, "PAGE-001")
    assert "FLOW-001" in ctx
    assert "Record Watering Today" in ctx
    assert "`workflow`" in ctx


def test_only_workflows_a_user_can_start_are_offered(tmp_path):
    """`trigger.kind` is a required enum — manual | event | schedule |
    condition — and only `manual` is something a user starts. All three of this
    app's page-launched workflows name the page in `launchedFrom`; offering
    them unfiltered invites a button for a derivation that runs on every read.
    """
    from services.a2ui_authority import (
        build_domain_context, registry_from_blueprint,
    )

    reg = registry_from_blueprint(_watering_doc())
    ctx = build_domain_context(tmp_path, reg, "PAGE-001")
    assert "FLOW-002" not in ctx
    assert "FLOW-004" not in ctx


def test_a_page_that_launches_nothing_is_told_about_no_workflows(tmp_path):
    from services.a2ui_authority import (
        build_domain_context, registry_from_blueprint,
    )

    reg = registry_from_blueprint(_watering_doc())
    ctx = build_domain_context(tmp_path, reg, "PAGE-009")
    assert "The workflows this screen launches" not in ctx
    assert "Plant: id, name" in ctx


def test_the_closing_rule_scopes_actions_as_well_as_numbers(tmp_path):
    """Without this the context can list workflows and the requirement still
    reads as entities-and-columns-only."""
    from services.a2ui_authority import build_requirement

    req = build_requirement(tmp_path, "entity_list", "/plants", "")
    assert "every action must name one of its workflows" in req


def test_the_closing_rule_does_not_read_as_a_chart_request(tmp_path):
    """The A2UI server rejects a payload with no chart when the requirement
    names one (tools/a2ui-mcp/checks.py, _CAPABILITIES). "Do not write a
    number, a trend or a comparison as a literal" was read as asking for a
    trend, so a two-entity plant tracker got a bar chart on all three pages,
    including its create form, and every page lost a retry to it.
    """
    import re
    from services.a2ui_authority import build_requirement

    req = build_requirement(tmp_path, "entity_list", "/plants", "").lower()
    for word in ("chart", "graph", "trend", "distribution", "histogram",
                 "funnel", "sparkline", "plot", "over time"):
        assert not re.search(rf"\b{re.escape(word)}\b", req), word


def test_no_job_text_names_a_component_the_checker_will_demand():
    """The A2UI server scans the requirement for capability keywords and makes
    any match mandatory. "a table, a board, a calendar, a timeline" offered
    four ways to think about a list; the checker read two demands, so every
    collection page carried a Table and a Timeline or was rejected — a Timeline
    on a two-entity plant tracker, a table on a create form.

    Pinned across every family, so a future rewrite cannot put a component name
    back into any of them without this failing.
    """
    import re
    from services.a2ui_authority import _JOB

    # The server's own list, restated here so the test fails if the prose
    # drifts back even when the vendored copy is unavailable.
    keywords = (
        "chart", "graph", "trend", "distribution", "histogram", "funnel",
        "sparkline", "plot", "over time", "by hour", "by week", "by stage",
        "kpi", "metric", "stat tile", "stats", "scorecard", "key figure",
        "status pill", "pill", "badge", "chip", "table", "data grid",
        "datagrid", "timeline", "gantt", "kanban", "swimlane", "board column",
    )
    for family, text in _JOB.items():
        hits = [k for k in keywords
                if re.search(rf"\b{re.escape(k)}\b", text.lower())]
        assert not hits, f"{family}: {hits}"


def test_every_composition_attempt_keeps_its_own_surface(tmp_path):
    """A retry must not erase the surface of the attempt that shipped.

    Keyed on the route alone, the artifact overwrote itself: one run made six
    compositions and left four files, and a page stored a one-node tree while
    the surface on disk replayed to nine. Every hypothesis about that collapse
    was then tested against a payload from a different call, so each came back
    "fine" while the page stayed broken.
    """
    root = _app(tmp_path)
    for _ in range(3):
        compose_page_via_a2ui(str(root), "/plants", "entity_list",
                              surface_provider=GOOD, page_id="PAGE-001")

    art = root / "src" / "contracts" / "a2ui-surfaces"
    assert sorted(f.name for f in art.glob("plants.*.json")) == [
        "plants.1.json", "plants.2.json", "plants.3.json"]


# --- a dropped call is not a refusal ---------------------------------------

def test_an_empty_surface_is_retried(tmp_path):
    """Two of three parallel calls came back empty on one run while the third
    answered twice seconds apart. The composer had nothing against those pages
    — the transport dropped them, and one shipped with no layout at all."""
    root = _app(tmp_path)
    calls = {"n": 0}

    def flaky(req, ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return GOOD(req, ctx) if callable(GOOD) else GOOD

    res = compose_dashboard_via_a2ui(str(root), surface_provider=flaky)
    assert calls["n"] == 3, "the call was not retried"
    assert res["applied"] is True, res.get("reason")


def test_a_provider_that_never_answers_declines_with_a_reason(tmp_path):
    """And says the composer returned nothing, rather than reporting whatever
    the JSON parser said about an empty string."""
    root = _app(tmp_path)
    calls = {"n": 0}

    def silent(req, ctx):
        calls["n"] += 1
        return {"messages": []}

    res = compose_dashboard_via_a2ui(str(root), surface_provider=silent)
    assert calls["n"] == 3
    assert res["applied"] is False
    assert "returned nothing" in res["reason"], res["reason"]


def test_a_healthy_provider_is_asked_once(tmp_path):
    """Retry must cost a working composition nothing."""
    root = _app(tmp_path)
    calls = {"n": 0}

    def fine(req, ctx):
        calls["n"] += 1
        return GOOD(req, ctx) if callable(GOOD) else GOOD

    compose_dashboard_via_a2ui(str(root), surface_provider=fine)
    assert calls["n"] == 1
