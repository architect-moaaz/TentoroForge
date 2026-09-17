"""What each kind of screen must contain — stated once, read by both sides.

THE PROBLEM THIS EXISTS TO END. Two things needed the same answer and each
kept its own. `dashboard_anatomy` and `page_kind_anatomy` decided what a
composed page must carry, and `a2ui_authority._JOB` told the composer what to
put on it — in prose a person wrote by hand, beside a rule a person wrote by
hand. They agreed only where somebody noticed, and the places they did not are
recorded in both files: a dashboard job that never mentioned a chart while the
floor demanded one unconditionally, refusing every dashboard for
`dashboard_no_chart` after 140 seconds of composition; a collection job naming
"a table, a board, a calendar, a timeline" as four ways to think about a list,
which the A2UI server read as two mandatory components, so a two-entity plant
tracker had to carry a Timeline.

A demand here is one object with two renderings. Unmet, it renders as a
finding. Before composing, it renders as a sentence in the brief. There is no
second copy to drift, and a demand that cannot be stated to a composer cannot
be enforced against one.

WHY THE WORDING IS PART OF THE DATA. The A2UI server scans the brief for
capability keywords and makes every match MANDATORY (tools/a2ui-mcp/checks.py,
`_CAPABILITIES`) — so naming a component as an example reads as a demand for
it. A demand satisfied by eleven different surfaces must therefore be worded in
shapes, and only a demand satisfied by exactly one component may name that
component. `test_a_demand_says_what_it_means` holds that line, which was
impossible to hold while the sentence and the predicate lived in different
files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

#: Families a page can belong to. `standalone` is the one that is not about
#: the application's records — see :mod:`services.client_state_anatomy`.
FAMILIES = ("dashboard", "collection", "record", "form", "standalone")


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
        return
    if not isinstance(node, dict):
        return
    if node.get("type"):
        yield node
    yield from _walk(node.get("children") or [])


@dataclass(frozen=True)
class Demand:
    """One thing a page of this family owes its reader.

    `types` and `floor` build the ordinary predicate: this many nodes of these
    kinds. `check` replaces it for a demand that reads something other than the
    tree — the tool family's values live on the schema, not in it.
    """

    rule: str
    slot: str
    #: Component types that satisfy it. Matched by the JOB a component does,
    #: never by one blessed name: `Stat` counts as a KPI, `Gauge` as a chart.
    types: frozenset[str] = frozenset()
    floor: int = 1
    #: What the finding says when it is not met.
    detail: str = ""
    #: What the composer is told before it composes. Shapes, not components,
    #: unless `types` holds exactly one — see the module docstring.
    demand: str = ""
    #: Reads the whole page schema rather than counting node types.
    check: Callable[[dict], bool] | None = field(default=None, compare=False)
    #: A component this demand names ON PURPOSE, despite being satisfiable by
    #: others. Declared rather than silent: the A2UI server reads a named
    #: capability as mandatory, so naming one is a decision with a consequence,
    #: and `test_a_demand_says_what_it_means` allows exactly the one named
    #: here. Empty means the sentence must name none.
    names_component: str = ""

    def met(self, schema: dict, root: Any) -> bool:
        if self.check is not None:
            return self.check(schema)
        found = sum(1 for n in _walk(root) if str(n.get("type")) in self.types)
        return found >= self.floor

    def count(self, root: Any) -> int:
        return sum(1 for n in _walk(root) if str(n.get("type")) in self.types)


# --------------------------------------------------------------- the types

# A surface that shows many records. Kanban and Calendar qualify: they are
# lists with an opinion about layout, not a different job.
LIST_TYPES = frozenset({
    "Table", "TableSortable", "DataGrid", "List", "Kanban", "Calendar",
    "CalendarWeek", "Timeline", "ResourceTimeline", "Repeat",
    "SearchResults", "Tree",
})

# Anything that renders a single record's substance.
BODY_TYPES = frozenset({
    "DescriptionList", "KeyValueList", "Table", "List", "Card", "Tabs",
    "TabPanel", "Timeline", "ActivityFeed", "Form",
})

# A control that collects a value. `Form` counts on its own: it carries its
# fields as a prop rather than as child nodes.
FIELD_TYPES = frozenset({
    "Form", "Input", "Textarea", "Select", "MultiSelect", "Combobox",
    "Checkbox", "RadioGroup", "Switch", "NumberInput", "MoneyInput",
    "DatePicker", "DateRangePicker", "TimePicker", "FileUpload", "Slider",
    "Rating", "KeyValueInput", "MaskedInput", "InputOTP", "RichTextEditor",
    "ColorPicker", "SegmentedControl", "Cascader", "EditableLineGrid",
})

ACTION_TYPES = frozenset({
    "Button", "IconButton", "DropdownMenu", "AddToCart", "StickyPrimaryCta",
    "BulkActionBar", "Wizard", "Stepper",
})

KPI_TYPES = frozenset({"MetricTile", "Stat", "KpiTile", "SplitArc"})
CHART_TYPES = frozenset({"Chart", "Gauge", "Heatmap", "Sparkline", "Schematic"})
ACTIVITY_TYPES = frozenset({
    "Table", "List", "Timeline", "ActivityFeed", "Kanban", "DescriptionList",
    "ResourceTimeline", "Calendar",
})

# Three KPIs is the floor a scanning reader needs before a row reads as a
# summary rather than a stray number. Four is the common shipped shape.
KPI_FLOOR = 3


def _keeps_values(schema: dict) -> bool:
    return bool(schema.get("clientState"))


def _a_control_acts(schema: dict) -> bool:
    from services.client_state_anatomy import CONTROL_TYPES, DOES_SOMETHING

    controls = [n for n in _walk(schema.get("root")) if n.get("type") in CONTROL_TYPES]
    if not controls:
        # Judged by the family's own reading rule, not here: a page with
        # nothing to press is a dead end whatever it is made of.
        return True
    return any(any((n.get("props") or {}).get(p) for p in DOES_SOMETHING)
               for n in controls)


# ------------------------------------------------------------- the demands

DEMANDS: dict[str, tuple[Demand, ...]] = {
    "dashboard": (
        Demand(
            rule="dashboard_no_kpis", slot="kpis", types=KPI_TYPES,
            floor=KPI_FLOOR,
            detail=("dashboard has {count} KPI tile(s); the floor is "
                    "{floor}. A summary row is how a reader answers 'how are "
                    "we doing' without reading the tables."),
            demand=(f"At least {KPI_FLOOR} single-number summaries of the "
                    "figures that matter in this domain."),
        ),
        Demand(
            rule="dashboard_no_chart", slot="chart", types=CHART_TYPES,
            detail=("dashboard has no chart. Counts alone cannot answer 'is "
                    "this getting better or worse'."),
            # NAMES A COMPONENT ON PURPOSE, and it is the only demand here
            # that does. The A2UI server reads a named capability as
            # mandatory, and this one IS mandatory: the floor refuses a
            # dashboard without one. The server matched keywords as WHOLE
            # words, so "worth charting" matched nothing and every dashboard
            # was refused for a chart nobody had asked it to draw.
            demand=("One chart of the breakdown that deserves it — counts "
                    "alone cannot say whether something is getting better or "
                    "worse."),
            names_component="Chart",
        ),
        Demand(
            rule="dashboard_no_activity", slot="activity", types=ACTIVITY_TYPES,
            detail=("dashboard has no recent-activity surface (table, list, "
                    "timeline or feed) — nothing answers 'what just "
                    "happened'."),
            demand=("Somewhere a reader sees what just happened, in whatever "
                    "shape that domain's recent events take."),
        ),
    ),
    "collection": (
        Demand(
            rule="collection_no_list_surface", slot="list", types=LIST_TYPES,
            detail=("a collection page shows many records and this one "
                    "carries no table, list, board or calendar — it is a "
                    "title over nothing."),
            # NAMES NO COMPONENT, and "calendar" was one. Eleven surfaces
            # satisfy this demand and the checker would have made that one
            # mandatory — the same fault as the "a table, a board, a calendar,
            # a timeline" wording that put a Timeline on a two-entity plant
            # tracker. Shapes only.
            demand=("The records surveyed in the shape this data actually "
                    "has: rows of fields, cards on a board, where they fall "
                    "in time, points along a sequence. One of those, chosen "
                    "for the domain."),
        ),
        Demand(
            rule="collection_no_action", slot="action", types=ACTION_TYPES,
            detail=("nothing on this collection can be clicked: no create, "
                    "no row action, no filter control. A reader arrives and "
                    "leaves."),
            demand=("Something to do once a record is found. A list nobody "
                    "can act on is a reading dead end."),
        ),
    ),
    "record": (
        Demand(
            rule="record_no_body", slot="body", types=BODY_TYPES,
            detail=("a record page shows one thing in detail and this one "
                    "carries no description list, card or table — a heading "
                    "over whitespace."),
            demand=("The record's substance, in whatever shape reads best at "
                    "a glance for this domain."),
        ),
        Demand(
            rule="record_no_action", slot="action", types=ACTION_TYPES,
            detail=("the reader can see this record and do nothing with it — "
                    "no edit, no delete, no advance, not even a way back."),
            demand=("What a reader can DO with it: the actions that move this "
                    "record forward, not just a way back."),
        ),
    ),
    "form": (
        Demand(
            rule="form_no_fields", slot="fields", types=FIELD_TYPES,
            detail="a form with no field collects nothing.",
            demand=("The values a person actually has to supply, grouped into "
                    "a sequence they can work through."),
        ),
        Demand(
            rule="form_no_submit", slot="submit", types=ACTION_TYPES,
            detail="a form with no submit cannot deliver what it collected.",
            demand="One way to deliver what was collected.",
        ),
    ),
    "standalone": (
        Demand(
            rule="tool_has_no_values", slot="clientState", check=_keeps_values,
            detail=("this screen is a self-contained tool and declares no "
                    "values of its own, so its controls have nothing to "
                    "change. Declare what it keeps on screen in `clientState` "
                    "— a calculator's display, a converter's input and result "
                    "— and give each control a `clientAction` that sets or "
                    "computes one of them. Do not reach for an entity, a "
                    "table or a workflow: nothing here is stored"),
            demand=("The values this screen keeps while someone works, "
                    "declared in `clientState` and read as "
                    "`{{state.<name>}}`. Nothing here is stored."),
        ),
        Demand(
            rule="tool_controls_are_inert", slot="action", check=_a_control_acts,
            detail=("none of this screen's controls do anything: no "
                    "clientAction, no workflow, no navigation. A tool whose "
                    "buttons are decoration is not a tool"),
            demand=("Every control changes one of those values, through "
                    "`clientAction` — `set` writes a literal, `compute` "
                    "evaluates a formula over the current values."),
        ),
    ),
}


def _finding(demand: Demand, route: str, count: int) -> dict:
    return {
        "rule": demand.rule,
        "route": route,
        "slot": demand.slot,
        "severity": "error",
        "action": "reported",
        "detail": demand.detail.format(count=count, floor=demand.floor),
    }


def findings(family: str, route: str, schema: Any) -> list[dict]:
    """Every demand of `family` this page does not meet.

    Empty means the page does its job. An unknown family returns empty, which
    means "not my rule" and never "checked and fine" — the caller decides
    whether a family it cannot name may pass.
    """
    demands = DEMANDS.get(str(family or ""))
    if not demands or not isinstance(schema, dict):
        return []
    root = schema.get("root") if isinstance(schema.get("root"), dict) else schema
    return [_finding(d, route, d.count(root)) for d in demands
            if not d.met(schema, root)]


def brief(family: str) -> str:
    """What a composer of this family is told it will be judged on.

    The same demands, rendered forwards. A composer told this cannot be
    refused for a rule it was never shown, which is what `dashboard_no_chart`
    was for every dashboard this platform composed.
    """
    demands = DEMANDS.get(str(family or ""))
    if not demands:
        return ""
    lines = [f"- {d.demand}" for d in demands if d.demand]
    if not lines:
        return ""
    return ("This screen is judged on the following, and a composition "
            "missing any of them is refused:\n" + "\n".join(lines))


__all__ = ["Demand", "DEMANDS", "FAMILIES", "KPI_FLOOR", "brief", "findings",
           "LIST_TYPES", "BODY_TYPES", "FIELD_TYPES", "ACTION_TYPES",
           "KPI_TYPES", "CHART_TYPES", "ACTIVITY_TYPES"]
