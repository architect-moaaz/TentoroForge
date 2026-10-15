"""A widget about a period reads that period.

AquaTrack (m1dck85j, 2026-10-12): "Entries Logged Today" and "Total Volume
Today" declared the date to count on but no period, so they counted every
drink ever logged, and Today's Log showed 7 entries and 2,865 ml above a list
that rightly showed none. A query widget now carries `window`, applied by the
data engine on its `timeField`.
"""
import json
from pathlib import Path

from services.blueprint.app_sdk import widget_query
from services.blueprint.verification import _query_findings

ROOT = Path(__file__).resolve().parents[2]


def _doc() -> dict:
    return {"data": {"entities": [{"id": "ENTITY-002", "name": "HydrationLog", "table": "hydration_logs",
                                   "fields": [{"name": "id", "type": "uuid"}, {"name": "volume", "type": "integer"},
                                              {"name": "loggedAt", "type": "datetime"}, {"name": "status", "type": "string"}]}]}}


def _widget(**src) -> dict:
    return {"id": "WIDGET-007", "key": "entriesLoggedToday", "kind": "metric", "label": "Entries Logged Today",
            "dataSource": {"op": "query", "entity": "ENTITY-002", "filter": {"status": "active"},
                           "measures": [{"aggregation": "count", "key": "count"}], **src}}


def test_the_period_reaches_the_app():
    out = widget_query(_doc(), _widget(timeField="loggedAt", window="today"))
    assert out["window"] == "today" and out["timeField"] == "loggedAt"


def test_a_period_with_no_date_to_count_back_on_is_refused():
    w = _widget(window="today")
    found = _query_findings(w, w["dataSource"], _doc()["data"]["entities"][0])
    assert any("needs a timeField" in f for f in found)
    w = _widget(window="today", timeField="loggedAt")
    assert not any("needs a timeField" in f for f in _query_findings(w, w["dataSource"], _doc()["data"]["entities"][0]))


def test_the_contract_and_the_agent_know_the_periods():
    schema = json.loads((ROOT / "contracts/blueprint.schema.json").read_text())
    text = json.dumps(schema)
    assert '"last_7_days"' in text and '"last_30_days"' in text
    from services.blueprint.executors import NODE_TASKS
    assert "`window`" in NODE_TASKS["analytics"] and "last_30_days" in NODE_TASKS["analytics"]


def test_the_sdk_and_the_refresh_carry_the_period():
    server = (ROOT / "templates/app-foundation/src/sdk/server.ts").read_text()
    assert "window: src.window" in server and "window: opts.window" in server
    from services.smith.sync_app import RUNTIME_FILES
    assert ("data-engine/aggregate-window.ts", "src/lib/data-engine/aggregate-window.ts") in RUNTIME_FILES
