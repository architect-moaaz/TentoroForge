"""What a screen must contain is stated once and read by both sides.

Two things needed the same answer and each kept its own. `dashboard_anatomy`
and `page_kind_anatomy` decided what a composed page must carry; `_JOB` in
`a2ui_authority` told the composer what to put on it. Both hand-written, and
they agreed only where somebody noticed:

  * The dashboard job never mentioned a chart while the floor demanded one
    unconditionally, so every dashboard was refused for `dashboard_no_chart`
    after 140 seconds of composition.
  * The collection job named "a table, a board, a calendar, a timeline" as
    four ways to think about a list; the A2UI server reads a named capability
    as MANDATORY, so a two-entity plant tracker had to carry a Timeline.

`page_demands` states each demand once — the predicate beside the sentence a
composer is told. These hold that it stays one.
"""
import pathlib
import tempfile

import pytest

from services.a2ui_authority import _JOB, build_requirement
from services.dashboard_anatomy import dashboard_findings
from services.page_demands import DEMANDS, FAMILIES, brief, findings
from services.page_kind_anatomy import page_kind_findings

EMPTY = {"root": {"type": "Stack", "props": {}, "children": []}}


def test_every_family_has_demands_and_a_job():
    """A family the floor judges and the composer is never briefed on is the
    exact shape of the dashboard-chart failure."""
    for family in FAMILIES:
        assert DEMANDS.get(family), f"{family} has no demands"
        assert _JOB.get(family), f"{family} has no job statement"


@pytest.mark.parametrize("family", FAMILIES)
def test_every_demand_is_stated_to_the_composer(family):
    """A demand with no sentence can be enforced against a composer that was
    never shown it."""
    for demand in DEMANDS[family]:
        assert demand.demand.strip(), f"{family}/{demand.rule} says nothing"
        assert demand.detail.strip(), f"{family}/{demand.rule} reports nothing"


@pytest.mark.parametrize("family", FAMILIES)
def test_a_demand_says_what_it_means(family):
    """THE WORDING IS PART OF THE DATA. The A2UI server scans the brief for
    capability keywords and makes every match mandatory, so naming a component
    as an example reads as a demand for it. A demand satisfied by many
    surfaces must be worded in shapes; only a demand satisfied by exactly one
    may name it."""
    for demand in DEMANDS[family]:
        if len(demand.types) <= 1:
            continue
        named = sorted(t for t in demand.types
                       if t.lower() in demand.demand.lower())
        # A deliberate one is declared on the demand and says why in its
        # comment. The dashboard's chart is the only one: that demand IS
        # mandatory, so the composer has to be told the word.
        allowed = {demand.names_component} if demand.names_component else set()
        assert not (set(named) - allowed), (
            f"{family}/{demand.rule} names {sorted(set(named) - allowed)} as "
            f"an example, and the composer's checker will read that as "
            f"mandatory. Word it as a shape, or declare it in "
            f"`names_component` with the reason")


@pytest.mark.parametrize("family", FAMILIES)
def test_the_brief_names_every_demand_the_floor_holds(family):
    """The forwards rendering covers the backwards one."""
    text = brief(family)
    assert text, f"{family} briefs nothing"
    for demand in DEMANDS[family]:
        assert demand.demand in text


def test_the_floors_report_from_the_table():
    """One table, two consumers. `dashboard_anatomy` blocks delivery and
    `page_kind_anatomy` judges a composition; neither re-derives the rules."""
    dash = [f["rule"] for f in dashboard_findings("/", EMPTY, {})]
    assert dash == [d.rule for d in DEMANDS["dashboard"]]

    coll = [f["rule"] for f in page_kind_findings("entity_list", "/nurses", EMPTY)]
    assert coll == [d.rule for d in DEMANDS["collection"]]


def test_a_composer_is_told_what_it_will_be_refused_for():
    """The whole point. Every rule the floor can report appears in the brief
    the composer was handed before it composed."""
    root = pathlib.Path(tempfile.mkdtemp())
    requirement = build_requirement(root, "dashboard", "/",
                                    contract={"data": {"primaryEntity": "Nurse"}})
    for demand in DEMANDS["dashboard"]:
        assert demand.demand in requirement, (
            f"a dashboard can be refused for {demand.rule} and was never "
            f"told about it")


def test_a_tool_is_briefed_on_its_own_floor():
    root = pathlib.Path(tempfile.mkdtemp())
    requirement = build_requirement(root, "tool", "/", contract={"data": {}})
    for demand in DEMANDS["standalone"]:
        assert demand.demand in requirement


def test_the_type_sets_are_one_set():
    """They were duplicated frozensets in two modules, maintained by hand."""
    from services import dashboard_anatomy, page_demands, page_kind_anatomy

    assert page_kind_anatomy._LIST_TYPES is page_demands.LIST_TYPES
    assert page_kind_anatomy._ACTION_TYPES is page_demands.ACTION_TYPES
    assert page_kind_anatomy._BODY_TYPES is page_demands.BODY_TYPES
    assert page_kind_anatomy._FIELD_TYPES is page_demands.FIELD_TYPES
    assert dashboard_anatomy._KPI_TYPES is page_demands.KPI_TYPES
    assert dashboard_anatomy._CHART_TYPES is page_demands.CHART_TYPES
    assert dashboard_anatomy.KPI_FLOOR == page_demands.KPI_FLOOR
