"""Tests for the A2UI → Forge page-schema binder.

Every case here is a contract bug that actually shipped from this module in a
single afternoon, which is the point: the binder is a new translation seam, and
a translation seam between two systems that each hold a plausible contract is
exactly the failure this whole effort is trying to stop. Four of them landed
before any test existed:

  1. ``filter`` written at the source level, where ``AggregateSource`` has no
     such field — silently dropped, so every KPI reported the unfiltered total
     ("In Progress" read 10 against 3 real rows).
  2. ``series`` sources emitting ``metrics``; ``SeriesSource`` reads ``agg``.
  3. Chart bound to rows with no ``xKey``/``series``, so Recharts had data and
     no encoding and drew nothing.
  4. Enum labels matched by substring only, so "Completed" never reached the
     enum value ``done``.

The binder's other job is subtractive and equally load-bearing: an A2UI payload
carries an invented ``updateDataModel``, and importing it would produce pages
full of convincing fiction that never touch Postgres.
"""

import json

import pytest

from services.a2ui_to_forge import dangling_bindings, translate

REG = {
    "entities": {
        "Task": {
            "slug": "tasks",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "title", "type": "varchar"},
                {"name": "status", "type": "varchar",
                 "enum": ["todo", "in_progress", "done"]},
                {"name": "createdAt", "type": "timestamp"},
            ],
        },
        "User": {
            "slug": "users",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "name", "type": "varchar"},
                {"name": "isActive", "type": "boolean"},
            ],
        },
    }
}


def payload(components, data=None):
    msgs = [{"version": "v0.9", "updateComponents": {"components": components}}]
    if data is not None:
        msgs.insert(0, {"version": "v0.9", "updateDataModel": {"value": data}})
    return {"messages": msgs}


def kpi(cid, label, path):
    return {"id": cid, "component": "MetricTile", "label": label,
            "value": {"path": path}}


def sources(result):
    return {s["name"]: s for s in result["schema"]["dataSources"]}


def nodes(result, kind):
    out = []

    def walk(n):
        if not isinstance(n, dict):
            return
        if n.get("type") == kind:
            out.append(n)
        for c in n.get("children") or []:
            walk(c)

    walk(result["schema"]["root"])
    return out


# Every KPI-only fixture needs a surface that NAMES an entity, or the binder
# correctly refuses to resolve "In Progress" to anything. Real dashboards carry
# a recent-activity table; these fixtures mirror that rather than relying on
# the binder to guess.
ANCHOR = {"id": "anchor", "component": "Table", "rows": {"path": "/tasks/rows"}}


def _root(children, anchor=True):
    kids = ([*children, ANCHOR] if anchor else list(children))
    return [{"id": "root", "component": "Stack", "children": [c["id"] for c in kids]},
            *kids]


# ─────────────────────────────────── 1. aggregate filter lives on the metric

def test_kpi_filter_is_written_inside_the_metric():
    """AggregateSource has no source-level `filter` field. Putting one there
    is accepted silently and dropped at query time, so the tile reports the
    unfiltered total — the "In Progress reads 10 against 3 rows" bug."""
    r = translate(payload(_root([kpi("k", "In Progress", "/kpis/inProgress")]),
                          {"kpis": {"inProgress": 3}, "tasks": {"rows": []}}), REG)
    src = sources(r)["inprogress"]
    assert src["op"] == "aggregate"
    assert src["metrics"]["value"]["filter"] == {"status": "in_progress"}
    assert "filter" not in src, "source-level filter is silently ignored"


def test_unfiltered_kpi_carries_no_filter_at_all():
    r = translate(payload(_root([kpi("k", "Total Tasks", "/kpis/total")]),
                          {"kpis": {"total": 10}, "tasks": {"rows": []}}), REG)
    assert "filter" not in sources(r)["totaltasks"]["metrics"]["value"]


# ─────────────────────────────────────────── 4. enum label synonyms

def test_completed_resolves_to_the_done_enum_value():
    """Substring matching alone never bridges the label a designer writes to
    the value the column stores."""
    r = translate(payload(_root([kpi("k", "Completed", "/kpis/completed")]),
                          {"kpis": {"completed": 3}, "tasks": {"rows": []}}), REG)
    assert sources(r)["completed"]["metrics"]["value"]["filter"] == {"status": "done"}


def test_boolean_column_wins_over_an_enum_substring_coincidence():
    """"Active Users" must bind isActive:true, not the `in_progress` enum it
    happens to share letters with."""
    r = translate(payload(_root([kpi("k", "Active Users", "/kpis/activeUsers")]),
                          {"kpis": {"activeUsers": 2}}), REG)
    assert sources(r)["activeusers"]["metrics"]["value"]["filter"] == {"isActive": True}


# ────────────────────────────────────── 2 + 3. series shape and chart encoding

def _chart_payload():
    chart = {"id": "c", "component": "Chart", "chartType": "bar",
             "title": "Tasks by Status", "data": {"path": "/chart/data"}}
    return payload(_root([chart]),
                   {"chart": {"data": [{"label": "todo", "value": 4}]},
                    "tasks": {"rows": []}})


def test_series_source_uses_agg_not_metrics():
    """SeriesSource reads `agg`; the aggregate shape does not carry over."""
    src = next(s for s in sources(translate(_chart_payload(), REG)).values()
               if s.get("op") == "series")
    assert src["agg"] == {"fn": "count"}
    assert "metrics" not in src
    assert src["groupBy"] == "status"


def test_chart_gets_the_encoding_recharts_needs():
    """Rows alone plot nothing: an empty `series` means no marks are drawn."""
    chart = nodes(translate(_chart_payload(), REG), "Chart")[0]
    assert chart["props"]["xKey"] == "label"
    assert chart["props"]["series"] == [{"name": "Tasks by Status", "dataKey": "value"}]
    assert chart["props"]["data"].startswith("{{")


def test_a2ui_series_pointer_never_survives_as_an_encoding():
    """A2UI's `series` is another DATA pointer, not a Recharts descriptor. It
    resolves to nothing, so the prop vanished and the chart drew nothing."""
    chart = {"id": "c", "component": "Chart", "chartType": "bar",
             "data": {"path": "/chart/data"}, "series": {"path": "/chart/series"}}
    r = translate(payload(_root([chart]),
                          {"chart": {"data": [], "series": []},
                           "tasks": {"rows": []}}), REG)
    got = nodes(r, "Chart")[0]["props"]["series"]
    assert isinstance(got, list) and got and got[0]["dataKey"] == "value"


# ───────────────────────────────────── the subtractive job: invented data dies

def test_invented_sample_data_never_reaches_the_page():
    """updateDataModel is fiction. Importing it produces a page that looks
    right and never touches Postgres."""
    r = translate(payload(_root([kpi("k", "Total Tasks", "/kpis/total")]),
                          {"kpis": {"total": 9999}, "tasks": {"rows": []}}), REG)
    blob = str(r["schema"])
    assert "9999" not in blob
    assert r["schema"]["dataSources"], "real sources must replace the fiction"


def test_unresolvable_binding_is_recorded_not_guessed():
    """A silently wrong binding renders just as convincingly as a right one,
    which makes it the most expensive thing this module can produce."""
    r = translate(payload(_root([
        {"id": "t", "component": "Table", "rows": {"path": "/nothing/here"}},
    ], anchor=False)), {"entities": {}})
    assert r["warnings"], "an unresolved binding must surface"


def test_dominant_entity_fallback_is_recorded_as_an_assumption():
    r = translate(payload(_root([
        {"id": "tbl", "component": "Table", "rows": {"path": "/tasks/rows"}},
        kpi("k", "In Progress", "/kpis/inProgress"),
    ], anchor=False), {"kpis": {"inProgress": 3}, "tasks": {"rows": []}}), REG)
    assert any("assumed Task" in a for a in r["assumptions"])


# ───────────────────────────────────────────────────────── structural fidelity

def test_enum_synonyms_normalise_css_vocabulary():
    """A composer told `direction` is an enum still emitted CSS's "column"
    before the catalog carried enum members; the binder keeps the floor."""
    r = translate(payload([
        {"id": "root", "component": "Stack", "direction": "column", "children": []},
    ]), REG)
    assert r["schema"]["root"]["props"]["direction"] == "vertical"


def test_output_is_a_v2_page_schema():
    r = translate(payload(_root([kpi("k", "Total Tasks", "/kpis/total")]),
                          {"tasks": {"rows": []}}), REG, route="/", page_id="home")
    s = r["schema"]
    assert s["schemaVersion"] == "2" and s["route"] == "/" and s["id"] == "home"
    assert isinstance(s["root"], dict) and isinstance(s["dataSources"], list)


def test_handles_an_empty_payload():
    r = translate({"messages": []}, REG)
    assert isinstance(r["schema"]["root"], dict)


# ─────────────────────────────────────────────── template children (A2UI-2)
#
# A2UI has no repeat node and no clone: it says "draw component X once per
# element of array Y". Forge has neither construct, and the two things this
# collapses to are different pages — N independently-bound widgets, or one
# Repeat over a live list. Picking wrong is silent: four KPIs become one empty
# Repeat, or four rows of invented sample data ship as if they were real.

def _template(container_extra=None, template_extra=None, path="/kpis"):
    row = {"id": "kpiRow", "component": "Row",
           "children": {"componentId": "kpiTile", "path": path},
           **(container_extra or {})}
    tile = {"id": "kpiTile", "component": "MetricTile", "format": "number",
            "label": {"path": "label"}, "value": {"path": "value"},
            **(template_extra or {})}
    return [{"id": "root", "component": "Stack", "children": ["kpiRow", "anchor"]},
            row, tile, ANCHOR]


KPI_ITEMS = [{"label": "Total Tasks", "value": "186"},
             {"label": "In Progress", "value": "42"},
             {"label": "Completed", "value": "128"}]


def test_a_spec_template_becomes_one_node_per_element():
    r = translate(payload(_template(), {"kpis": KPI_ITEMS,
                                        "tasks": {"rows": []}}), REG)
    tiles = nodes(r, "MetricTile")
    assert [t["props"]["label"] for t in tiles] == [
        "Total Tasks", "In Progress", "Completed"]


def test_each_expanded_tile_gets_its_own_filtered_source():
    """The whole reason these are separate nodes and not a Repeat: "In
    Progress" and "Completed" are different queries. Collapsing the template
    onto one source is how three tiles all read the same total."""
    r = translate(payload(_template(), {"kpis": KPI_ITEMS,
                                        "tasks": {"rows": []}}), REG)
    filters = [s["metrics"]["value"].get("filter")
               for s in r["schema"]["dataSources"] if s["op"] == "aggregate"]
    assert filters == [None, {"status": "in_progress"}, {"status": "done"}]


def test_the_templates_sample_values_never_ship():
    r = translate(payload(_template(), {"kpis": KPI_ITEMS,
                                        "tasks": {"rows": []}}), REG)
    blob = str(r["schema"])
    assert "186" not in blob and "42" not in blob
    assert all(t["props"]["value"].startswith("{{") for t in nodes(r, "MetricTile"))


def test_expanded_nodes_get_distinct_ids():
    """Same id on every clone means React keys collide and the list flickers
    or drops nodes on re-render."""
    r = translate(payload(_template(), {"kpis": KPI_ITEMS,
                                        "tasks": {"rows": []}}), REG)
    ids = [t.get("id") for t in nodes(r, "MetricTile")]
    assert len(set(ids)) == len(ids) == 3


def test_a_record_template_becomes_a_repeat_not_clones():
    """Rows are a runtime fact. Cloning the sample model here would ship three
    hard-coded cards reading invented task titles."""
    comps = [{"id": "root", "component": "Stack", "children": ["list"]},
             {"id": "list", "component": "Stack",
              "children": {"componentId": "row", "path": "/tasks/rows"}},
             {"id": "row", "component": "Text", "content": {"path": "title"}}]
    r = translate(payload(comps, {"tasks": {"rows": [
        {"title": "Follow up with client"}, {"title": "Ship the thing"}]}}), REG)
    rep = nodes(r, "Repeat")
    assert len(rep) == 1
    assert rep[0]["props"]["source"] == "tasks"
    assert "Follow up with client" not in str(r["schema"])


def test_repeat_children_bind_to_the_row_in_scope():
    comps = [{"id": "root", "component": "Stack", "children": ["list"]},
             {"id": "list", "component": "Stack",
              "children": {"componentId": "row", "path": "/tasks/rows"}},
             {"id": "row", "component": "Text", "content": {"path": "title"}}]
    r = translate(payload(comps, {"tasks": {"rows": [{"title": "x"}]}}), REG)
    assert nodes(r, "Text")[0]["props"]["content"] == "{{item.title}}"


def test_an_unexpandable_template_is_reported_not_silently_dropped():
    """No entity in the path and no sample array means the instance count is
    unknowable. Drawing nothing is right; drawing nothing quietly is not."""
    r = translate(payload(_template(path="/mystery"), {"tasks": {"rows": []}}), REG)
    assert nodes(r, "MetricTile") == []
    assert any("unknowable" in w for w in r["warnings"])


def test_a_template_naming_a_missing_component_is_reported():
    comps = [{"id": "root", "component": "Stack", "children": ["row"]},
             {"id": "row", "component": "Row",
              "children": {"componentId": "ghost", "path": "/kpis"}}]
    r = translate(payload(comps, {"kpis": KPI_ITEMS}), REG)
    assert any("ghost" in w for w in r["warnings"])


# ────────────────────────────────────────────────── copy pointers vs data
def test_a_pointer_on_a_copy_prop_resolves_to_its_literal():
    """Headings are authored copy, so the sample model is the right source for
    them. Left as a pointer, the raw {"path": ...} dict reaches `props` and the
    strict string field rejects the entire page."""
    comps = [{"id": "root", "component": "Stack", "children": ["h"]},
             {"id": "h", "component": "Text", "content": {"path": "/header/title"}}]
    r = translate(payload(comps, {"header": {"title": "Operations"}}), REG)
    assert nodes(r, "Text")[0]["props"]["content"] == "Operations"


def test_a_copy_pointer_with_no_literal_is_dropped_and_reported():
    comps = [{"id": "root", "component": "Stack", "children": ["h"]},
             {"id": "h", "component": "Text", "content": {"path": "/nope"}}]
    r = translate(payload(comps, {}), REG)
    assert "content" not in nodes(r, "Text")[0]["props"]
    assert r["warnings"]


# ───────────────────────────────────────── pointer-valued labels (live defect)
#
# Found by running the real MCP server, not by any fixture here: A2UI points at
# a label the same way it points at data, and the composer wrote
# `label: {"path": "/kpi1/label"}` on four hand-written tiles. Every test above
# passes a literal label, so none of them could see it.

def test_a_pointer_valued_label_still_drives_the_filter():
    """Read raw, the label became the string "{'path': '/kpi1/label'}", which
    names no enum value — so all four KPI tiles bound to the same unfiltered
    count and rendered the same number. That is precisely the defect
    `_enum_filter` exists to prevent, arriving through a different door."""
    tiles = [{"id": f"k{i}", "component": "MetricTile", "format": "number",
              "label": {"path": f"/kpi{i}/label"}, "value": {"path": f"/kpi{i}/value"}}
             for i in (1, 2)]
    r = translate(payload(_root(tiles),
                          {"kpi1": {"label": "In Progress", "value": 3},
                           "kpi2": {"label": "Completed", "value": 7},
                           "tasks": {"rows": []}}), REG)
    filters = [s["metrics"]["value"].get("filter")
               for s in r["schema"]["dataSources"] if s.get("op") == "aggregate"]
    assert filters == [{"status": "in_progress"}, {"status": "done"}]


def test_the_resolved_label_is_what_ships_as_copy():
    tile = {"id": "k", "component": "MetricTile", "format": "number",
            "label": {"path": "/kpi/label"}, "value": {"path": "/kpi/value"}}
    r = translate(payload(_root([tile]),
                          {"kpi": {"label": "Completed", "value": 7},
                           "tasks": {"rows": []}}), REG)
    assert nodes(r, "MetricTile")[0]["props"]["label"] == "Completed"


def test_a_row_relative_pointer_reads_as_a_field_name():
    """Kanban's `cardTitle` takes a field key, and A2UI writes that as a
    relative pointer. Dropping it left every card untitled."""
    board = {"id": "b", "component": "Kanban", "cardTitle": {"path": "title"},
             "data": {"path": "/tasks/rows"}}
    r = translate(payload(_root([board]), {"tasks": {"rows": []}}), REG)
    assert nodes(r, "Kanban")[0]["props"]["cardTitle"] == "title"
    assert not r["warnings"], "a field reference is not a missing literal"


# ──────────────────────────────── inlined fiction (found on a live composition)
#
# The module's subtractive job was scoped to `updateDataModel`, on the reading
# that A2UI never inlines data into a component. A real composed dashboard
# disproved that: it cleared the substance floor carrying invented numbers
# written straight onto the tiles, having never touched the data model at all.

def test_a_literal_trend_is_dropped():
    """`trend: [8, 9, 10, 11, 12]` renders as a real sparkline over a real
    tile. Eight what? Nothing — and no downstream gate can tell."""
    tile = {"id": "k", "component": "MetricTile", "label": "Total Tasks",
            "format": "number", "value": {"path": "/kpis/total"},
            "trend": [8, 9, 10, 11, 12], "trendWindow": "week"}
    r = translate(payload(_root([tile]),
                          {"kpis": {"total": 12}, "tasks": {"rows": []}}), REG)
    props = nodes(r, "MetricTile")[0]["props"]
    assert "trend" not in props
    assert props["trendWindow"] == "week", "the window is config, not a measurement"
    assert any("trend" in u for u in r["unresolved"]), (
        "a derivable-but-blocked prop belongs in `unresolved`, not `warnings` — "
        "the distinction is whether anyone should go and fix something")


def test_a_breakdown_is_bound_not_discarded():
    """The values are invented; the LABELS are real intent. Each names a
    subset of the tile's own entity, so each becomes its own filtered count.

    Discarding the row because its number was made up would throw the intent
    away with the fiction — and the number is recoverable."""
    tile = {"id": "k", "component": "MetricTile", "label": "Tasks",
            "format": "number", "value": {"path": "/kpis/total"},
            "breakdown": [{"label": "In Progress", "value": "20"},
                          {"label": "Completed", "value": "9"}]}
    r = translate(payload(_root([tile]), {"kpis": {"total": 29},
                                          "tasks": {"rows": []}}), REG)
    rows = nodes(r, "MetricTile")[0]["props"]["breakdown"]
    assert [x["label"] for x in rows] == ["In Progress", "Completed"]
    assert all(x["value"].startswith("{{") for x in rows)
    assert "20" not in str(r["schema"]), "the invented values still die"

    filters = [s["metrics"]["value"].get("filter")
               for s in r["schema"]["dataSources"] if s.get("op") == "aggregate"]
    assert {"status": "in_progress"} in filters
    assert {"status": "done"} in filters


def test_an_unmatchable_breakdown_row_is_reported_not_faked():
    """Binding it to the unfiltered total would render as a convincing
    duplicate of the headline number — the worst available outcome."""
    tile = {"id": "k", "component": "MetricTile", "label": "Tasks",
            "format": "number", "value": {"path": "/kpis/total"},
            "breakdown": [{"label": "Blocked by legal", "value": "3"}]}
    r = translate(payload(_root([tile]), {"kpis": {"total": 3},
                                          "tasks": {"rows": []}}), REG)
    assert "breakdown" not in nodes(r, "MetricTile")[0]["props"]
    assert any("Blocked by legal" in u for u in r["unresolved"])


def test_breakdown_resolves_against_the_tiles_own_entity():
    """Not the surface's dominant entity — a User tile broken down by task
    status would be silently, plausibly wrong."""
    tile = {"id": "k", "component": "MetricTile", "label": "Active Users",
            "format": "number", "value": {"path": "/kpis/activeUsers"},
            "breakdown": [{"label": "Completed", "value": "4"}]}
    r = translate(payload(_root([tile]), {"kpis": {"activeUsers": 2},
                                          "tasks": {"rows": []}}), REG)
    # "Completed" names no User column, so it is reported rather than bound
    # to Task's `done` just because Task dominates the page.
    assert any("User" in u for u in r["unresolved"])


def test_a_literal_rows_array_is_dropped():
    tbl = {"id": "t", "component": "Table",
           "rows": [{"title": "Invented row"}, {"title": "Another"}]}
    r = translate(payload(_root([tbl]), {"tasks": {"rows": []}}), REG)
    assert "Invented row" not in str(r["schema"])


def test_literal_columns_survive_because_they_are_config():
    """A column list says WHICH FIELDS to show. That is the composer's design
    decision, not a claim about the data."""
    tbl = {"id": "t", "component": "Table", "rows": {"path": "/tasks/rows"},
           "columns": [{"key": "title", "label": "Title"}]}
    r = translate(payload(_root([tbl], anchor=False), {"tasks": {"rows": []}}), REG)
    assert nodes(r, "Table")[0]["props"]["columns"] == [
        {"key": "title", "label": "Title"}]


def test_a_literal_delta_string_is_dropped():
    """The list rule let this through: `delta: "+34 since midnight"` is the
    same invented measurement, typed as prose."""
    tile = {"id": "k", "component": "MetricTile", "label": "Votes Cast Today",
            "format": "number", "value": {"path": "/kpis/votes"},
            "delta": "+34 since midnight"}
    r = translate(payload(_root([tile]), {"kpis": {"votes": 34},
                                          "tasks": {"rows": []}}), REG)
    assert "delta" not in nodes(r, "MetricTile")[0]["props"]


def test_a_bound_delta_survives():
    tile = {"id": "k", "component": "MetricTile", "label": "Votes",
            "format": "number", "value": {"path": "/kpis/votes"},
            "delta": "{{votes.change}}"}
    r = translate(payload(_root([tile]), {"kpis": {"votes": 3},
                                          "tasks": {"rows": []}}), REG)
    assert nodes(r, "MetricTile")[0]["props"]["delta"] == "{{votes.change}}"


def test_a_label_naming_a_boolean_column_binds_it():
    """"Quorum Met" against a `quorumMet` column is the same two words. The
    generic flag vocabulary has no entry for a domain's own flags and never
    will, so the column name itself has to be the signal."""
    reg = {"entities": {"Session": {"slug": "sessions", "columns": [
        {"name": "id", "type": "uuid"},
        {"name": "quorumMet", "type": "boolean"}]}}}
    tile = {"id": "k", "component": "MetricTile", "label": "Sessions",
            "format": "number", "value": {"path": "/kpis/sessions"},
            "breakdown": [{"label": "Quorum Met", "value": "9"}]}
    comps = [{"id": "root", "component": "Stack", "children": ["k", "a"]}, tile,
             {"id": "a", "component": "Table", "rows": {"path": "/sessions/rows"}}]
    r = translate(payload(comps, {"kpis": {"sessions": 12},
                                  "sessions": {"rows": []}}), reg)
    filt = [s["metrics"]["value"].get("filter")
            for s in r["schema"]["dataSources"] if s.get("op") == "aggregate"]
    assert {"quorumMet": True} in filt


# ─────────────────────────────────────────────────── form fields (A2UI-form)
#
# The catalog widening let the composer propose a Form for the first time. A
# form is the one place its component CHOICE is not the last word: the column
# has a SQL type, and when the two disagree the type wins. And a field bound to
# a column that does not exist fails at SUBMIT, not at render — so it looks
# perfect right up until someone uses it.

FORM_REG = {
    "entities": {"Bill": {"slug": "bills", "columns": [
        {"name": "id", "type": "uuid"},
        {"name": "title", "type": "varchar"},
        {"name": "introducedAt", "type": "timestamp"},
        {"name": "pageCount", "type": "integer"},
        {"name": "isUrgent", "type": "boolean"},
        {"name": "status", "type": "varchar", "enum": ["draft", "tabled", "passed"]},
    ]}},
    "workflows": ["CreateBillWorkflow"],
}


def form_payload(fields, form_props=None):
    form = {"id": "f", "component": "Form",
            "children": [f["id"] for f in fields], **(form_props or {})}
    comps = [{"id": "root", "component": "Stack", "children": ["f"]}, form, *fields]
    return {"messages": [{"updateComponents": {"components": comps}}]}


def field(fid, name, label="X", component="Input"):
    return {"id": fid, "component": component, "name": name, "label": label}


def form_nodes(r):
    out = []

    def walk(n):
        if not isinstance(n, dict):
            return
        if n.get("type") not in ("Stack", "Form", "Row", "Section"):
            out.append((n.get("type"), n.get("props") or {}))
        for c in n.get("children") or []:
            walk(c)

    walk(r["schema"]["root"])
    return out


def test_the_column_type_outranks_the_proposed_control():
    """The composer reached for Input on all five. The registry says one is a
    timestamp, one an integer, one a boolean and one an enum — and the SQL type
    is what the submit will actually receive."""
    r = translate(form_payload([
        field("a", "title"), field("b", "introducedAt"),
        field("c", "pageCount"), field("d", "isUrgent"), field("e", "status"),
    ]), FORM_REG, route="/bills/new")
    got = dict((p["name"], t) for t, p in form_nodes(r))
    assert got == {"title": "Input", "introducedAt": "DatePicker",
                   "pageCount": "NumberInput", "isUrgent": "Switch",
                   "status": "Select"}


def test_an_enum_column_carries_its_real_options():
    r = translate(form_payload([field("e", "status")]), FORM_REG, route="/bills/new")
    opts = form_nodes(r)[0][1]["options"]
    assert [o["value"] for o in opts] == ["draft", "tabled", "passed"]


def test_a_field_naming_no_column_is_dropped_and_reported():
    r = translate(form_payload([field("a", "title"), field("x", "sponsorEmail")]),
                  FORM_REG, route="/bills/new")
    assert [p["name"] for _, p in form_nodes(r)] == ["title"]
    assert any("sponsorEmail" in u for u in r["unresolved"])


def test_a_field_is_matched_on_its_label_when_the_name_misses():
    """"Full Name" finds fullName. The composer writes labels for people and
    names for machines, and it does not always get the second one right."""
    reg = {"entities": {"User": {"slug": "users", "columns": [
        {"name": "id", "type": "uuid"}, {"name": "fullName", "type": "varchar"}]}}}
    r = translate(form_payload([field("a", "name_of_user", "Full Name")]),
                  reg, route="/users/new")
    assert [p["name"] for _, p in form_nodes(r)] == ["fullName"]


def test_the_form_entity_comes_from_the_route_not_the_field():
    """A form writes to ONE record. Resolving per field would let a single
    typo split it silently across two tables — renders fine, fails on save."""
    reg = {"entities": {
        "Bill": {"slug": "bills", "columns": [{"name": "title", "type": "varchar"}]},
        "Vote": {"slug": "votes", "columns": [{"name": "title", "type": "varchar"}]}}}
    r = translate(form_payload([field("a", "title")]), reg, route="/votes/new")
    # `title` exists on both; the route decides which record is being written.
    assert r["schema"]["root"] is not None
    assert [p["name"] for _, p in form_nodes(r)] == ["title"]


# ──────────────────────────────────────────────────────────── submit target

def test_a_real_workflow_target_survives():
    r = translate(form_payload([field("a", "title")],
                               {"workflow": "CreateBillWorkflow"}),
                  FORM_REG, route="/bills/new")
    forms = [n for n in _all_nodes(r) if n.get("type") == "Form"]
    assert forms[0]["props"]["workflow"] == "CreateBillWorkflow"


def test_a_phantom_workflow_target_is_cleared_not_shipped():
    """A submit pointed at a workflow the app does not define fails on click.
    Cleared rather than guessed at: the existing submit-authority passes
    (orphan_wiring_pass, the form_target guard) already own that decision, and
    a second opinion here is how two writers start disagreeing."""
    r = translate(form_payload([field("a", "title")],
                               {"workflow": "TotallyMadeUpWorkflow"}),
                  FORM_REG, route="/bills/new")
    forms = [n for n in _all_nodes(r) if n.get("type") == "Form"]
    assert "workflow" not in forms[0]["props"]
    assert any("TotallyMadeUpWorkflow" in u for u in r["unresolved"])


def _all_nodes(r):
    out = []

    def walk(n):
        if isinstance(n, dict):
            out.append(n)
            for c in n.get("children") or []:
                walk(c)

    walk(r["schema"]["root"])
    return out


# ─────────────────────────────── dashboard chrome: gauges and range pickers
#
# Both of these come from the live jcf0kgoi dashboard.


def gauge(cid, label, value):
    return {"id": cid, "component": "Gauge", "label": label, "value": value}


def test_a_gauge_value_becomes_an_aggregate_not_a_dropped_literal():
    """The live symptom: `quorumGauge.value dropped a literal on a data prop`,
    and the gauge shipped with no value at all — it renders empty.

    A MetricTile whose value arrives as a POINTER already gets an aggregate
    synthesised from its label. A Gauge arriving with a bare literal was caught
    one step earlier, by the rule that discards invented rows, and never
    reached that path. The literal is fiction, but the INTENT is real and
    derivable — same judgement already made for `breakdown`, whose invented
    numbers are re-bound rather than discarded."""
    r = translate(payload(_root([gauge("g", "In Progress", 87)]),
                          {"tasks": {"rows": []}}), REG)
    g = nodes(r, "Gauge")
    assert g, "the gauge must survive"
    val = g[0]["props"].get("value")
    assert isinstance(val, str) and val.startswith("{{"), (
        f"gauge value must bind to a source, got {val!r}")
    src = sources(r)[val.strip("{}").split(".")[0]]
    assert src["op"] == "aggregate"
    assert src["entity"] == "Task"
    assert src["metrics"]["value"]["filter"] == {"status": "in_progress"}, (
        "the label carries a real subset — the gauge should count that subset")


def test_a_gauge_with_a_bound_value_is_left_alone():
    r = translate(payload(_root([gauge("g", "Open", {"path": "/kpis/open"})]),
                          {"kpis": {"open": 4}, "tasks": {"rows": []}}), REG)
    assert nodes(r, "Gauge")[0]["props"]["value"].startswith("{{")


def test_a_dashboard_range_picker_is_chrome_not_a_form_field():
    """The live symptom: `dateRangeControl field 'dashboardRange' names no
    column of Bill`. It names no column because it is not a column — a
    dashboard date-range filter is chrome. Running it through the form-field
    resolver both DROPPED the control and reported a defect that isn't one."""
    ctrl = {"id": "dateRangeControl", "component": "DateRangePicker",
            "name": "dashboardRange", "label": "Date range"}
    r = translate(payload(_root([ctrl]), {"tasks": {"rows": []}}), REG,
                  kind="dashboard")
    assert nodes(r, "DateRangePicker"), "the range picker must survive"
    assert not [u for u in r.get("unresolved") or [] if "dashboardRange" in u], (
        f"chrome must not be reported as a broken field: {r.get('unresolved')}")


def test_a_dashboard_control_that_does_name_a_column_still_binds():
    ctrl = {"id": "statusFilter", "component": "Select",
            "name": "status", "label": "Status"}
    r = translate(payload(_root([ctrl]), {"tasks": {"rows": []}}), REG,
                  kind="dashboard")
    picked = nodes(r, "Select") or nodes(r, "Input")
    assert picked and picked[0]["props"]["name"] == "status"


def test_a_form_field_naming_no_column_is_still_dropped():
    """The dashboard exemption must not weaken the form rule — a field bound to
    a column that does not exist fails at submit, not at render."""
    ctrl = {"id": "f", "component": "Input", "name": "nonesuch", "label": "X"}
    r = translate(payload(_root([ctrl]), {"tasks": {"rows": []}}), REG,
                  route="/tasks/new", kind="form")
    assert not nodes(r, "Input"), "unbacked form field must not ship"
    assert [u for u in r.get("unresolved") or [] if "nonesuch" in u]


def test_a_percentage_gauge_is_not_given_a_raw_count():
    """A count is not a percentage.

    The first version of this fix bound every literal-valued gauge to
    count(entity). On the live dashboard that turned a `unit:"%"`, 0-100 quorum
    gauge into an unfiltered count of Bill — with 40 bills it renders "40%".
    An empty gauge is visibly broken; a confident wrong number is not, which
    makes it the worse failure.

    A ratio IS derivable when the label names a real subset (filtered/total).
    When it names none, nothing in the registry says what the percentage is
    OF, so it stays unbound and says why."""
    g = {"id": "g", "component": "Gauge", "label": "Quorum",
         "value": 82, "min": 0, "max": 100, "unit": "%"}
    r = translate(payload(_root([g]), {"tasks": {"rows": []}}), REG)
    node = nodes(r, "Gauge")[0]
    assert "value" not in node["props"], (
        f"a percentage with no derivable ratio must not bind a count: "
        f"{node['props'].get('value')!r}")
    assert [u for u in r.get("unresolved") or [] if "g." in u or "g:" in u], \
        r.get("unresolved")


def test_a_percentage_gauge_whose_label_names_a_subset_binds_a_ratio():
    g = {"id": "g", "component": "Gauge", "label": "In Progress",
         "value": 40, "min": 0, "max": 100, "unit": "%"}
    r = translate(payload(_root([g]), {"tasks": {"rows": []}}), REG)
    val = nodes(r, "Gauge")[0]["props"].get("value")
    assert isinstance(val, str) and val.startswith("{{"), val
    src = sources(r)[val.strip("{}").split(".")[0]]
    assert src["metrics"]["value"]["fn"] == "ratio", src
    assert src["metrics"]["value"]["filter"] == {"status": "in_progress"}


def test_a_plain_count_gauge_is_unaffected():
    """No unit, no 0-100 range — a count is exactly right."""
    g = {"id": "g", "component": "Gauge", "label": "In Progress", "value": 7}
    r = translate(payload(_root([g]), {"tasks": {"rows": []}}), REG)
    val = nodes(r, "Gauge")[0]["props"]["value"]
    src = sources(r)[val.strip("{}").split(".")[0]]
    assert src["metrics"]["value"]["fn"] == "count"


# ─────────────────────────────────────────── entity hints (resolver seam)
#
# `_resolve_entity` matches entity aliases as SUBSTRINGS of a path or label.
# When neither names an entity it falls back to the surface's dominant one —
# which is how a quorum gauge labelled 'نسبة النصاب القانوني' bound to Bill,
# and how a session detail page's KeyValueList bound to Attendance.
#
# Substring matching cannot fix that: the label contains no entity name in any
# language. It is a judgement, so the binder stops pretending otherwise — it
# ASKS, by emitting a structured question, and ACCEPTS an answer as a hint.


def test_a_hint_beats_the_dominant_fallback():
    r = translate(payload(_root([kpi("k", "Quorum", "/quorum/value")]),
                          {"tasks": {"rows": []}}), REG,
                  entity_hints={"k": "User"})
    src = [s for s in r["schema"]["dataSources"] if s.get("op") == "aggregate"]
    assert src and src[0]["entity"] == "User", src


def test_falling_back_emits_a_question_a_resolver_can_answer():
    r = translate(payload(_root([kpi("k", "Quorum", "/quorum/value")]),
                          {"tasks": {"rows": []}}), REG)
    qs = [q for q in r.get("questions") or [] if q["component"] == "k"]
    assert qs, r.get("questions")
    q = qs[0]
    assert q["label"] == "Quorum"
    assert q["path"] == "/quorum/value"
    assert q["assumed"] == "Task"
    assert set(q["candidates"]) == {"Task", "User"}, q["candidates"]


def test_a_hint_naming_no_registered_entity_is_ignored():
    """The resolver answers from a CLOSED set. A hallucinated entity must not
    become a dataSource — that is the failure the closed set exists to stop."""
    r = translate(payload(_root([kpi("k", "Quorum", "/quorum/value")]),
                          {"tasks": {"rows": []}}), REG,
                  entity_hints={"k": "Quorum"})
    src = [s for s in r["schema"]["dataSources"] if s.get("op") == "aggregate"]
    assert src and src[0]["entity"] == "Task", "must fall back, not invent"


def test_a_resolved_binding_emits_no_question():
    r = translate(payload(_root([kpi("k", "Total Tasks", "/kpis/total")]),
                          {"kpis": {"total": 1}, "tasks": {"rows": []}}), REG)
    assert not [q for q in r.get("questions") or [] if q["component"] == "k"]


def test_style_is_lifted_out_of_props():
    """NodeV2 puts `style` beside `type`, `id` and `bind` — not in props.
    A2UI emits it inside props, its own catalog accepts that, and ours
    rejected the same tree:

      InvalidPatternTemplate: root.children[0].props.(root):
      {'style': {'maxWidth': ...}} is not valid under any of the schemas

    Both pages of a live run were lost to it. Lifted here rather than
    widening NodeV2 to take both placements: two spellings of one thing in
    the Blueprint is the drift this binder exists to close.
    """
    surface = payload([
        {"id": "root", "component": "Stack", "style": {"maxWidth": "1200px"},
         "children": [{"id": "t", "component": "Text", "content": "hi",
                       "style": {"padding": "8px"}}]},
    ])
    out = translate(surface, REG, route="/x", page_id="PAGE-001",
                    kind="entity_list")
    root = out["schema"]["root"]
    assert root["style"] == {"maxWidth": "1200px"}
    assert "style" not in (root.get("props") or {})


def test_a_node_without_a_style_gains_no_empty_one():
    surface = payload([{"id": "root", "component": "Stack", "children": []}])
    out = translate(surface, REG, route="/x", page_id="PAGE-001",
                    kind="entity_list")
    assert "style" not in out["schema"]["root"]


def test_no_node_anywhere_keeps_style_in_props():
    """c051f6f lifted `style` in the general builder and missed the field
    builder, so a form field still arrived with style inside props and the
    identical rejection recurred on the next run. Walking the whole tree is
    what a per-builder test could not say."""
    surface = payload([
        {"id": "root", "component": "Stack", "style": {"maxWidth": "680px"},
         "children": ["form", "txt"]},
        {"id": "form", "component": "Form", "style": {"gap": "12px"},
         "children": ["field"]},
        {"id": "field", "component": "Input", "label": "Name",
         "field": "name", "style": {"width": "100%"}},
        {"id": "txt", "component": "Text", "content": "hi",
         "style": {"padding": "8px"}},
    ])
    out = translate(surface, REG, route="/x", page_id="PAGE-001", kind="form")

    offenders = []

    def walk(n):
        if not isinstance(n, dict):
            return
        if "style" in (n.get("props") or {}):
            offenders.append(n.get("type"))
        for kid in n.get("children") or []:
            walk(kid)

    walk(out["schema"]["root"])
    assert offenders == [], f"style left in props on: {offenders}"


# ---------------------------------------------------------------------------
# A workflow reference is nested as often as it is top-level.
# ---------------------------------------------------------------------------

def test_a_nested_invented_workflow_is_cleared():
    """A composed /plants shipped `Table.rowActions[0].workflow =
    "markPlantWatered"` — an id no workflow has. It reached the browser and
    answered "Workflow not found" on click. Six sibling bindings on the same
    page were correct FLOW ids; the check that exists to catch exactly this
    only looked at the component's own `workflow` prop."""
    from services.a2ui_to_forge import _dangling_workflows

    props = {"rowActions": [{"label": "Mark", "workflow": "markPlantWatered"}]}
    found = _dangling_workflows(props, {"FLOW-001"})

    assert found == [("props.rowActions[0].workflow", "markPlantWatered")]
    # Cleared, not left to fail on click: a binding that resolves to nothing
    # renders as a working control.
    assert "workflow" not in props["rowActions"][0]
    assert props["rowActions"][0]["label"] == "Mark"


def test_a_real_workflow_survives_at_any_depth():
    from services.a2ui_to_forge import _dangling_workflows

    props = {"workflow": "FLOW-001",
             "emptyAction": {"workflow": "FLOW-002"},
             "rowActions": [{"workflow": "FLOW-003"}]}
    assert _dangling_workflows(props, {"FLOW-001", "FLOW-002", "FLOW-003"}) == []
    assert props["emptyAction"]["workflow"] == "FLOW-002"
    assert props["rowActions"][0]["workflow"] == "FLOW-003"


def test_nothing_is_cleared_when_no_workflows_are_known():
    """An empty registry means "we cannot tell", not "none are valid" —
    clearing on no information would strip every binding in the app."""
    from services.a2ui_to_forge import _dangling_workflows

    props = {"workflow": "FLOW-001"}
    # The caller guards on `known_ids` being non-empty; this pins the reason.
    assert _dangling_workflows(props, {"FLOW-001"}) == []


def test_a_row_relative_pointer_on_an_enum_prop_is_dropped():
    """`Badge.variant` takes one of five fixed values. A2UI wrote
    `{"path": "statusVariant"}` — row-relative — which the field-name rule
    turned into the literal "statusVariant", and the page failed validation and
    did not ship. Dropped, so the default applies and the badge renders neutral:
    losing the colour is the small half, losing the page was the large one."""
    from services.a2ui_to_forge import _enum_members

    members = _enum_members("Badge", "variant")
    assert members and "statusVariant" not in members


def test_the_field_name_rule_still_applies_where_it_belongs():
    """`Kanban.cardTitle` names the field to read, and dropping it left the
    cards with no title. It is not an enum, so nothing changes for it."""
    from services.a2ui_to_forge import _enum_members

    assert _enum_members("Kanban", "cardTitle") == set()


def _row_with(**badge_props):
    """A Badge nested one level under a Repeat's template, not the template."""
    return [{"id": "root", "component": "Stack", "children": ["list"]},
            {"id": "list", "component": "Stack",
             "children": {"componentId": "row", "path": "/tasks/rows"}},
            {"id": "row", "component": "Stack", "children": ["badge"]},
            {"id": "badge", "component": "Badge", **badge_props}]


def test_a_descendant_of_a_repeat_template_binds_to_the_row_too():
    """`expand_records` rewrote the template's OWN props to `{{item.…}}` and
    its children's were built with no idea they were inside a repeat — so the
    same pointer that followed the row on the template became a bare field name
    one level down."""
    r = translate(payload(_row_with(content={"path": "title"}),
                          {"tasks": {"rows": [{"title": "x"}]}}), REG)
    assert nodes(r, "Badge")[0]["props"]["content"] == "{{item.title}}"


def test_an_enum_prop_inside_a_repeat_follows_the_row():
    """The colour the badge lost. `Repeat` binds each element under its `as`
    name, so the renderer can read `statusVariant` per row — and the A2UI
    catalog admits a binding beside the members, so this validates."""
    r = translate(payload(_row_with(variant={"path": "statusVariant"}),
                          {"tasks": {"rows": [{"statusVariant": "success"}]}}), REG)
    assert nodes(r, "Badge")[0]["props"]["variant"] == "{{item.statusVariant}}"
    assert not r["warnings"], "nothing was lost, so nothing to warn about"


def test_the_binding_is_recorded_as_an_assumption_not_a_silent_rewrite():
    r = translate(payload(_row_with(variant={"path": "statusVariant"}),
                          {"tasks": {"rows": [{"statusVariant": "success"}]}}), REG)
    assert any("follows the row" in a for a in r["assumptions"])


def test_an_enum_prop_outside_a_repeat_is_still_dropped():
    """Nothing binds the row there, so `{{item.…}}` would resolve to nothing.
    The drop and its warning stand."""
    comps = [{"id": "root", "component": "Stack", "children": ["x"]},
             {"id": "x", "component": "Badge",
              "variant": {"path": "statusVariant"}}]
    r = translate(payload(comps, {"tasks": {"rows": []}}), REG)
    assert nodes(r, "Badge")[0]["props"].get("variant") is None
    assert any("dropped" in w for w in r["warnings"])


def test_an_absolute_pointer_is_not_treated_as_row_relative():
    """A leading slash means the model root, and it means that inside a repeat
    too — reading it off the row would bind to the wrong thing."""
    r = translate(payload(_row_with(content={"path": "/tasks/label"}),
                          {"tasks": {"rows": [{"title": "x"}], "label": "All"}}),
                  REG)
    assert nodes(r, "Badge")[0]["props"]["content"] == "All"


def test_enum_members_come_from_the_contracts_not_a_list_here():
    """A second list would drift from the Zod components the way the A2UI
    catalog did."""
    from services.a2ui_to_forge import _enum_members

    assert _enum_members("Badge", "variant") == {
        "neutral", "primary", "success", "danger", "warning"}
    assert _enum_members("NoSuchComponent", "variant") == set()


# ──────────────────────────────── a prop no component accepts
#
# It did not fail here. It rode into `props` and met a `.strict()` field
# downstream, where the whole page failed to parse and the message named a
# schema path rather than the component that carried it.

def _badge(**props):
    return [{"id": "root", "component": "Stack", "children": ["x"]},
            {"id": "x", "component": "Badge", **props}]


def _warned(r, prop):
    return any(f".{prop}:" in w for w in r["warnings"])


def test_a_prop_no_component_accepts_is_named():
    r = translate(payload(_badge(content="Live", sparkle="yes"),
                          {"tasks": {"rows": []}}), REG)
    assert _warned(r, "sparkle")
    assert "Badge" in " ".join(r["warnings"])


def test_it_is_reported_not_dropped():
    """The catalog should be authoritative, but "should be" is the wrong
    footing on which to delete a value a composer meant: a thin catalog entry
    would silently strip props the renderer does accept."""
    r = translate(payload(_badge(content="Live", sparkle="yes"),
                          {"tasks": {"rows": []}}), REG)
    assert nodes(r, "Badge")[0]["props"]["sparkle"] == "yes"


def test_an_aliased_prop_is_not_an_unknown_one():
    """`Badge.label` is `content` by the time this looks. Reporting it would
    be reporting a rename this module performed itself."""
    r = translate(payload(_badge(label="Live"), {"tasks": {"rows": []}}), REG)
    assert nodes(r, "Badge")[0]["props"]["content"] == "Live"
    assert not _warned(r, "label")


def test_a_node_sibling_is_not_an_unknown_prop():
    """`style` sits beside `props` in NodeV2. A2UI emits it among the props and
    the binder lifts it out — not unknown, early."""
    r = translate(payload(_badge(content="Live", style={"maxWidth": "8rem"}),
                          {"tasks": {"rows": []}}), REG)
    assert not _warned(r, "style")


def test_a_component_the_catalog_does_not_know_reports_nothing():
    """Every prop would be "unknown" and the message would say nothing. That
    the component itself is unrecognised is a different problem."""
    comps = [{"id": "root", "component": "Stack", "children": ["x"]},
             {"id": "x", "component": "NoSuchComponent", "whatever": 1}]
    r = translate(payload(comps, {"tasks": {"rows": []}}), REG)
    assert not _warned(r, "whatever")


def test_a_real_composition_is_not_flooded():
    """A warning on every prop of every node is a warning nobody reads."""
    board = {"id": "b", "component": "Kanban", "cardTitle": {"path": "title"},
             "data": {"path": "/tasks/rows"}}
    r = translate(payload(_root([board]), {"tasks": {"rows": []}}), REG)
    assert not r["warnings"]


# --- row-relative bindings are not page bindings ---------------------------

def test_a_row_relative_binding_is_not_dangling():
    """`{{id}}` inside a Table means this row's id, not a missing source.

    /tickets was refused over `rowHref: "/tickets/{{id}}"` on a Table whose
    `rows` was bound to a declared source. Read as a page-level binding it
    looked dangling; the renderer resolves it against the row.
    """
    schema = {
        "dataSources": [{"name": "tickets"}],
        "root": {"type": "Table",
                 "props": {"rows": "{{tickets}}", "rowHref": "/tickets/{{id}}"}},
    }
    assert dangling_bindings(schema) == []


def test_a_phantom_source_outside_a_row_is_still_dangling():
    """The case the rule exists for. A composed /plants shipped four tiles
    reading invented sources against one declared `plants`, and rendered four
    blanks."""
    schema = {
        "dataSources": [{"name": "plants"}],
        "root": {"type": "Stack", "children": [
            {"type": "MetricTile", "props": {"value": "{{overdue.value}}"}}]},
    }
    assert dangling_bindings(schema) == ["overdue"]


def test_a_row_over_an_undeclared_source_opens_no_scope():
    """Otherwise the exemption would launder a phantom: bind rows to something
    that does not exist and everything under it stops being checked."""
    schema = {
        "dataSources": [{"name": "plants"}],
        "root": {"type": "Table",
                 "props": {"rows": "{{ghosts}}", "rowHref": "/x/{{id}}"}},
    }
    assert dangling_bindings(schema) == ["ghosts", "id"]


# --- a record page binds its record, it does not copy a sample -------------

def _record_surface():
    """A detail surface: fields pointing into one record object."""
    return {"messages": [
        {"updateDataModel": {"path": "/", "value": {
            "ticket": {"id": "TCK-1042", "subject": "Cannot reset password"},
        }}},
        {"updateComponents": {"components": [
            {"id": "root", "component": "Stack", "children": ["subj"]},
            {"id": "subj", "component": "Text",
             "content": {"path": "/ticket/subject"}},
        ]}},
    ]}


def test_a_record_page_binds_its_fields_rather_than_baking_the_sample():
    """/tickets/[id] shipped the sample ticket's text and rendered it for
    every ticket. The pointer names where the value lives; that has to
    survive to render time."""
    reg = {"entities": {"Ticket": {"table": "tickets", "columns": [
        {"name": "id"}, {"name": "subject"}]}}}
    out = translate(_record_surface(), reg, route="/tickets/[id]",
                    page_id="P", kind="record_workspace")
    blob = json.dumps(out["schema"])
    assert "Cannot reset password" not in blob, "sample copy reached the page"
    assert "{{" in blob, "nothing was bound"
    ops = {s["name"]: s.get("op") for s in out["schema"].get("dataSources") or []}
    assert "get" in ops.values(), f"no record source: {ops}"


def test_a_collection_page_still_reads_copy_from_the_sample():
    """The branch exists for headings and captions, and those are still read
    off the sample — only a record page's own fields change meaning."""
    reg = {"entities": {"Ticket": {"table": "tickets", "columns": [
        {"name": "id"}, {"name": "subject"}]}}}
    out = translate(_record_surface(), reg, route="/tickets",
                    page_id="P", kind="entity_list")
    ops = {s.get("op") for s in out["schema"].get("dataSources") or []}
    assert "get" not in ops, f"a list page minted a record source: {ops}"


# --- args carry a binding the renderer can resolve -------------------------

def _dispatch_surface():
    return {"messages": [
        {"updateDataModel": {"path": "/", "value": {
            "ticket": {"id": "TCK-1042", "subject": "Cannot reset password"},
        }}},
        {"updateComponents": {"components": [
            {"id": "root", "component": "Stack", "children": ["btn"]},
            {"id": "btn", "component": "Button", "label": "Close ticket",
             "workflow": "FLOW-002",
             "args": {"ticketId": {"path": "/ticket/id"}}},
        ]}},
    ]}


def test_args_bind_rather_than_shipping_a_pointer():
    """`fallbackDispatch` posts args verbatim and `interpolateDeep` resolves
    `{{...}}` strings only, so a raw {"path": ...} object reached the workflow
    where an id belonged — the null-column failure args exists to prevent."""
    reg = {"entities": {"Ticket": {"table": "tickets", "columns": [
        {"name": "id"}, {"name": "subject"}]}}}
    out = translate(_dispatch_surface(), reg, route="/tickets/[id]",
                    page_id="P", kind="record_workspace")
    btn = json.dumps(out["schema"])
    assert '"path"' not in btn, "a raw pointer reached the schema"
    args = None
    def walk(n):
        nonlocal args
        if isinstance(n, list):
            for i in n: walk(i)
        elif isinstance(n, dict):
            if (n.get("props") or {}).get("workflow"):
                args = n["props"].get("args")
            for v in n.values():
                if isinstance(v, (list, dict)): walk(v)
    walk(out["schema"].get("root"))
    assert args, "the dispatching button carries no args"
    assert str(args.get("ticketId", "")).startswith("{{"), args
    # and it must name a source the page actually declares
    names = {s["name"] for s in out["schema"].get("dataSources") or []}
    assert str(args["ticketId"]).strip("{}").split(".")[0] in names, (
        f"{args} names no declared source among {names}")


def test_args_never_carry_a_sample_value():
    """Reading the pointer off the sample would send every click the same id."""
    reg = {"entities": {"Ticket": {"table": "tickets", "columns": [
        {"name": "id"}, {"name": "subject"}]}}}
    out = translate(_dispatch_surface(), reg, route="/tickets/[id]",
                    page_id="P", kind="record_workspace")
    assert "TCK-1042" not in json.dumps(out["schema"])


# --- the page contract answers what the pointer could not ------------------

_ROUTE_NAMED = {"messages": [
    {"updateDataModel": {"path": "/", "value": {"team": [{"id": "1"}]}}},
    {"updateComponents": {"components": [
        {"id": "root", "component": "Stack", "children": ["t"]},
        {"id": "t", "component": "Table", "rows": {"path": "/team"},
         "columns": [{"key": "name", "label": "Name"}]},
    ]}},
]}

_REG = {"entities": {"TeamMember": {"slug": "team_members",
                                    "columns": [{"name": "id"},
                                                {"name": "name"}]}}}


def test_a_route_named_pointer_resolves_through_the_page_contract():
    """A2UI names data after the screen and the binder resolves by entity, so
    `/team` on a page whose entity is TeamMember matched nothing and the page
    ended with no sources at all — then failed the floor for bindings with
    nothing behind them. `primaryEntity` is what the page says it is about."""
    reg = {**_REG, "pageEntity": {"PAGE-004": "TeamMember"}}
    out = translate(_ROUTE_NAMED, reg, route="/team", page_id="PAGE-004",
                    kind="entity_list")
    names = [s["name"] for s in out["schema"].get("dataSources") or []]
    assert names, "the page still bound nothing"
    assert any("TeamMember" in a for a in out.get("assumptions") or []), \
        "the inference was not recorded"


def test_no_declaration_still_refuses_to_guess():
    reg = {**_REG, "pageEntity": {}}
    out = translate(_ROUTE_NAMED, reg, route="/team", page_id="PAGE-004",
                    kind="entity_list")
    assert not (out["schema"].get("dataSources") or [])
    assert any("could not resolve" in w for w in out.get("warnings") or [])


def test_a_declaration_naming_no_real_entity_is_ignored():
    """Otherwise the fallback would launder a bad contract into a binding."""
    reg = {**_REG, "pageEntity": {"PAGE-004": "Nonexistent"}}
    out = translate(_ROUTE_NAMED, reg, route="/team", page_id="PAGE-004",
                    kind="entity_list")
    assert not (out["schema"].get("dataSources") or [])
    assert any("could not resolve" in w for w in out.get("warnings") or [])
