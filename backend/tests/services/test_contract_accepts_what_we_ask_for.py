"""Every dataSource shape we ask an agent for is one the contract accepts.

Measured on a real 50-page application: 130 committed dataSources, and not one
`op: "series"`. Every chart source ever composed had been refused.

    BlueprintInvalid: pageLayouts/36/dataSources/4:
      Additional properties are not allowed ('agg', 'groupBy' were unexpected)

`services/schema_prompt.py` instructs the page author to emit exactly
`{"op": "series", "groupBy": …, "bucket": …, "agg": {"fn": "count"}}`, the
runtime has a full resolver for it (`SeriesSource` in
templates/runtime/data-engine.ts), eight modules produce it — and the Blueprint
contract had `op` enumerated as list|get|aggregate with
`additionalProperties: false`.

So the pipeline asked for a shape and then refused it, and the page carrying it
was lost. Fourteen routes 404ed on that application, four of them for this.

Downstream this is also why `dashboard_no_chart` could not be satisfied from
the composer's side: a dashboard cannot have a chart if a chart's data source
cannot be committed.
"""
from __future__ import annotations

import json
import pathlib

import pytest

_CONTRACT = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"


def _datasource_schema() -> dict:
    doc = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    return doc["properties"]["pageLayouts"]["items"]["properties"]["dataSources"]["items"]


#: Verbatim from `services/schema_prompt.py`'s CHART DATA block — the examples
#: the page author is shown and told to copy.
_AS_INSTRUCTED = [
    {"name": "signupsByWeek", "entity": "User", "op": "series",
     "groupBy": "createdAt", "bucket": "week", "agg": {"fn": "count"}},
    {"name": "ordersByStatus", "entity": "Order", "op": "series",
     "groupBy": "status", "agg": {"fn": "count"}, "sort": "value"},
]

#: What the other ops look like, so this test covers the whole vocabulary
#: rather than only the op that was broken.
_ALSO = [
    {"name": "openTickets", "entity": "Ticket", "op": "aggregate",
     "metrics": {"total": {"fn": "count"}}},
    {"name": "recentTickets", "entity": "Ticket", "op": "list", "limit": 10},
    {"name": "theTicket", "entity": "Ticket", "op": "get"},
]


@pytest.mark.parametrize("source", _AS_INSTRUCTED + _ALSO,
                         ids=lambda s: f'{s["op"]}:{s["name"]}')
def test_the_contract_accepts_it(source):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(source, _datasource_schema())


def test_the_series_op_exists_at_all():
    """The single fact behind four lost pages."""
    assert "series" in _datasource_schema()["properties"]["op"]["enum"]


def test_the_contract_still_refuses_an_invented_key():
    """Widening to `additionalProperties: true` would have made the error go
    away and let anything through — including the typo'd key that this check
    exists to catch. The fields added are the ones the runtime reads."""
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"name": "x", "entity": "Ticket", "op": "series", "grupBy": "status"},
            _datasource_schema())


def test_the_contract_allows_no_op_the_app_cannot_run():
    """The other direction. A contract that permits an op nothing dispatches
    lets a page commit a source that silently resolves to nothing — the same
    divergence as this bug, pointing the other way.

    Checked against the page-side resolvers (`data-engine-bridge.ts` dispatches
    series/aggregate, `AppNavigator` list/get) rather than `data-engine.ts`,
    which defines the shapes but is not where a page's sources are routed.

    `search` is deliberately absent from the contract: the runtime can resolve
    one, but nothing in the pipeline composes one, and a contract should not
    carry surface nobody produces.
    """
    app = pathlib.Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src"
    dispatched = "\n".join(
        f.read_text(encoding="utf-8", errors="replace")
        for f in app.rglob("*.ts*")
    )
    for op in _datasource_schema()["properties"]["op"]["enum"]:
        assert f'op === "{op}"' in dispatched, (
            f"the contract allows {op!r} and no page-side resolver dispatches it")
