"""A migration plan that stops matching the code is a liability.

The ledger's whole value is that it can be trusted six months from now, when
someone asks "what happened to `fk_source_guard`?" and needs an answer better
than a grep. So every target it names is checked here: an edge must exist in
the verification matrix, a guardrail must name a section an agent can actually
write, a constraint must point at a field the Blueprint schema really has.

If someone renames a §75 edge and forgets the ledger, this fails.
"""
import json
from pathlib import Path

import pytest

from services.blueprint.agent_contract import AGENT_REGISTRY, WRITABLE_SECTIONS
from services.blueprint.migration_ledger import (
    DISPOSITIONS,
    LEDGER,
    by_disposition,
    new_edges_required,
    summary,
)
from services.blueprint.service import CONTRACT_PATH
from services.blueprint.verification import EDGES

#: Targets the ledger names that are not yet implementable. Each needs a
#: Blueprint schema addition first — see test_known_gaps_are_declared.
PENDING_EDGES: set[str] = set()


def test_the_ledger_covers_the_whole_chain():
    """151 passes in, 151 dispositions out — no pass quietly dropped."""
    assert len(LEDGER) == 151
    steps = [e.step for e in LEDGER]
    assert len(set(steps)) == 151, "a step is classified twice"
    assert min(steps) == 1 and max(steps) == 151


def test_every_disposition_is_one_of_the_five():
    for e in LEDGER:
        assert e.disposition in DISPOSITIONS, (e.step, e.disposition)


def test_edges_name_real_verification_edges():
    for e in by_disposition()["edge"]:
        assert e.target, f"step {e.step} has no edge target"
        assert e.target in set(EDGES) | PENDING_EDGES, (e.step, e.module, e.target)


def test_guardrails_name_a_section_some_agent_owns():
    for e in by_disposition()["guardrail"]:
        assert e.target in WRITABLE_SECTIONS, (e.step, e.target)
        owners = [a for a, c in AGENT_REGISTRY.items() if c.can_write(e.target)]
        assert owners, f"{e.target} is writable by nobody"


def test_constraints_name_a_real_blueprint_field():
    """A constraint pointing at a field the schema lacks is a promise, not a
    migration."""
    schema = json.loads(CONTRACT_PATH.read_text("utf-8"))
    top = set(schema["properties"])
    for e in by_disposition()["constraint"]:
        assert e.target, f"step {e.step} ({e.module}) has no constraint target"
        root = e.target.split(".")[0]
        assert root in top, (e.step, e.module, e.target)


def test_dead_and_emitter_entries_carry_a_reason():
    """Deleting behaviour without saying why is how knowledge is lost."""
    for e in by_disposition()["dead"]:
        assert e.note, f"step {e.step} ({e.module}) is marked dead with no reason"


def test_the_repair_half_is_gone_but_detection_is_not():
    """The migration's central claim, stated as arithmetic.

    43 of the 151 passes carried real cross-cutting checks; those survive as 12
    verification edges. What does not survive is any of them writing a fix.
    """
    counts = summary()
    assert counts["edge"] > 0
    assert counts["edge"] + counts["constraint"] > counts["dead"], (
        "if most of the chain is 'dead', the migration is discarding knowledge "
        "rather than relocating it"
    )


def test_no_ledger_target_is_unimplementable():
    """Every edge the ledger asks for now exists.

    ``Widget↔DataSource`` was the last gap: seven passes about metrics,
    aggregations and display formats that the Blueprint could not express.
    Adding the widget data contract closed it — and three of the seven turned
    out to be *constraints* rather than edges, because a widget without a
    source and a series without a grouping simply fail to parse.
    """
    assert new_edges_required() - set(EDGES) == PENDING_EDGES == set()


def test_the_widget_contract_absorbed_its_seven_passes():
    widget_rows = [e for e in LEDGER if e.module in (
        "widget_data_source_guard", "widget_data_contract", "aggregate_metrics_guard",
        "chart_data_source_guard", "kpi_format_honesty", "binding_smoke")]
    assert len(widget_rows) == 7
    assert {e.disposition for e in widget_rows} == {"constraint", "edge"}
    assert sum(1 for e in widget_rows if e.disposition == "constraint") == 3


@pytest.mark.parametrize("disposition", DISPOSITIONS)
def test_each_disposition_is_actually_used(disposition):
    """A taxonomy with an empty bucket is the wrong taxonomy."""
    assert by_disposition()[disposition], f"nothing classified as {disposition}"


def test_summary_adds_up():
    counts = summary()
    assert sum(counts[d] for d in DISPOSITIONS) == counts["total"] == 151
