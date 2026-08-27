"""Tests for the dashboard substance floor.

Every "should fire" case here is a real shipped dashboard from the output
corpus, and every "should stay quiet" case is one a human looked at and
accepted. Measured across 223 generated apps: 125 carry a dashboard, of which
15 have zero KPI tiles and 43 have zero charts — all of them green through
every gate in the pipeline, because `page_signature` needs an entity to name a
job and a dashboard has none, so `apply_page_anatomy` skipped them entirely.
"""

from services.dashboard_anatomy import (
    dashboard_findings,
    is_dashboard_route,
    page_root,
    KPI_FLOOR,
)

REG = {
    "entities": {
        "Task": {
            "slug": "tasks",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "title", "type": "varchar"},
                {"name": "status", "type": "varchar",
                 "enum": ["todo", "in_progress", "done"]},
                {"name": "assigneeId", "type": "uuid", "fk": "User"},
                {"name": "createdAt", "type": "timestamp"},
            ],
        },
        "PoliticalBloc": {
            "slug": "political-blocs",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "name_ar", "type": "varchar"},
            ],
        },
    }
}


def _dash(nodes, sources=None):
    """A dashboard page whose root simply holds `nodes`."""
    return {
        "schemaVersion": "2",
        "route": "/",
        "root": {"type": "Stack", "props": {}, "children": nodes},
        "dataSources": sources or [],
    }


def _n(kind, **props):
    return {"type": kind, "props": props}


def _rules(findings):
    return {f["rule"] for f in findings}


# ------------------------------------------------------------ route detection

def test_recognises_dashboard_routes():
    for r in ("/", "/home", "/dashboard", "/admin/dashboard", "/overview"):
        assert is_dashboard_route(r), r


def test_does_not_claim_entity_routes():
    for r in ("/tasks", "/tasks/[id]", "/tasks/new", "/settings/integrations"):
        assert not is_dashboard_route(r), r


# ------------------------------------------------------------------- the floor

def test_empty_dashboard_is_caught():
    """zhebvtqk and dxlc5m31 both shipped exactly this: chrome and nothing else."""
    f = dashboard_findings("/", _dash([_n("Heading", content="Overview")]), REG)
    assert _rules(f) == {"dashboard_no_kpis", "dashboard_no_chart",
                         "dashboard_no_activity"}
    assert all(x["severity"] == "error" for x in f)


def test_kpis_but_no_chart_is_caught():
    """x4fcmdyi / 5r9ahdfk — 3-4 KPIs, zero charts."""
    nodes = [_n("MetricTile", label=f"K{i}", value=f"{{{{s{i}.value}}}}")
             for i in range(4)]
    nodes.append(_n("Table", rows="{{tasks}}"))
    f = dashboard_findings("/", _dash(nodes), REG)
    assert _rules(f) == {"dashboard_no_chart"}


def test_thin_kpi_row_is_caught():
    nodes = [_n("MetricTile", label="Only one", value="{{a.value}}"),
             _n("Chart", chartType="bar", data="{{s}}"),
             _n("Table", rows="{{tasks}}")]
    f = dashboard_findings("/", _dash(nodes), REG)
    assert _rules(f) == {"dashboard_no_kpis"}
    assert f"{KPI_FLOOR}" in f[0]["detail"]


def test_a_complete_dashboard_is_silent():
    """g5g6wxf4's shape — 4 KPIs, 2 charts, a recent-activity table."""
    nodes = [_n("MetricTile", label=f"K{i}", value=f"{{{{s{i}.value}}}}")
             for i in range(4)]
    nodes += [_n("Chart", chartType="bar", data="{{byStatus}}"),
              _n("Chart", chartType="line", data="{{overTime}}"),
              _n("Table", rows="{{tasks}}")]
    src = [{"name": "byStatus", "entity": "Task", "op": "series",
            "groupBy": "status"}]
    assert dashboard_findings("/", _dash(nodes, src), REG) == []


def test_stat_counts_as_a_kpi_and_list_as_activity():
    """The floor is about the JOB each slot does, not one blessed component."""
    nodes = [_n("Stat", label=f"K{i}") for i in range(KPI_FLOOR)]
    nodes += [_n("Gauge", value="{{x.value}}"), _n("ActivityFeed", items="{{a}}")]
    assert dashboard_findings("/", _dash(nodes, []), REG) == []


# --------------------------------------------------------- groupBy sanity

def test_groupby_on_fk_is_caught():
    """A bar per UUID with UUID axis labels. 7 of these shipped."""
    nodes = _full_nodes() + [_n("Chart", chartType="bar", data="{{byAssignee}}")]
    src = [{"name": "byAssignee", "entity": "Task", "op": "series",
            "groupBy": "assigneeId"}]
    f = dashboard_findings("/", _dash(nodes, src), REG)
    assert _rules(f) == {"dashboard_groupby_unreadable"}
    assert "assigneeId" in f[0]["detail"]


def test_groupby_on_free_text_name_is_caught():
    """l8vrakiw grouped PoliticalBloc by name_ar: one bar per row, a list
    drawn as a chart."""
    nodes = _full_nodes() + [_n("Chart", chartType="bar", data="{{byName}}")]
    src = [{"name": "byName", "entity": "PoliticalBloc", "op": "series",
            "groupBy": "name_ar"}]
    f = dashboard_findings("/", _dash(nodes, src), REG)
    assert _rules(f) == {"dashboard_groupby_unreadable"}


def test_groupby_on_enum_or_date_is_fine():
    for col in ("status", "createdAt"):
        nodes = _full_nodes() + [_n("Chart", chartType="bar", data="{{g}}")]
        src = [{"name": "g", "entity": "Task", "op": "series", "groupBy": col}]
        assert dashboard_findings("/", _dash(nodes, src), REG) == [], col


def test_unknown_entity_groupby_is_not_guessed():
    """No registry entry means no basis for a verdict — staying quiet beats a
    false positive that trains people to ignore the gate."""
    nodes = _full_nodes() + [_n("Chart", chartType="bar", data="{{g}}")]
    src = [{"name": "g", "entity": "Ghost", "op": "series", "groupBy": "wat"}]
    assert dashboard_findings("/", _dash(nodes, src), REG) == []


# ------------------------------------------------------------------ robustness

def test_handles_malformed_input():
    assert dashboard_findings("/", _dash([]), None) != []  # still floors it


def test_unreadable_dashboard_is_reported_not_silently_clean():
    """The failure this module exists to stop, applied to itself: a page we
    cannot read must never score as flawless."""
    for doc in ({}, {"root": None}, {"schemaVersion": "2"}):
        f = dashboard_findings("/", doc, REG)
        assert _rules(f) == {"dashboard_unreadable"}, doc


def test_reads_the_legacy_flat_shape():
    """10 of the 125 corpus dashboards put type/props/children at the top
    level instead of under `root`. Reading only `root` scored all 10 clean."""
    flat = {"schemaVersion": "1", "id": "home", "type": "Stack", "props": {},
            "dataSources": [],
            "children": [_n("MetricTile", label=f"K{i}") for i in range(KPI_FLOOR)]
                        + [_n("Chart", chartType="bar"), _n("Table", rows="{{t}}")]}
    assert page_root(flat) is flat
    assert dashboard_findings("/", flat, REG) == []


def test_legacy_flat_shape_is_still_held_to_the_floor():
    flat = {"schemaVersion": "1", "type": "Stack", "props": {}, "children": []}
    assert _rules(dashboard_findings("/", flat, REG)) == {
        "dashboard_no_kpis", "dashboard_no_chart", "dashboard_no_activity"}


def test_non_dashboard_route_is_never_judged():
    assert dashboard_findings("/tasks", _dash([]), REG) == []


def _full_nodes():
    """A dashboard that satisfies the three slot rules, so groupBy tests
    isolate the rule under test."""
    return ([_n("MetricTile", label=f"K{i}", value=f"{{{{s{i}.value}}}}")
             for i in range(KPI_FLOOR)]
            + [_n("Chart", chartType="bar", data="{{ok}}"),
               _n("Table", rows="{{tasks}}")])
