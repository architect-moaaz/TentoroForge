"""What was decided once is enforced by the platform, not re-decided by a page.

E-commerce (2026-10-09): GBP on the catalogue, US$ in the cart, $ at the
checkout — each page guessed; £6.99 shipping shown and 0 stored — the page
recomputed what the process wrote; an order moved to any status at all.
Now the SDK's one formatter reads the decided currency, a page that names a
currency is refused, the page writer is told what each process writes and
the life cycles its records follow, the step writer declares what it writes,
and the engine refuses a move the life cycle does not allow (proven on the
shipped engine by run-lifecycle-tests.sh).
"""
from __future__ import annotations

import inspect
from pathlib import Path

_SDK = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "sdk"

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Merchant"}],
    "data": {"entities": [
        {"id": "ENTITY-005", "name": "Order", "table": "orders", "fields": [
            {"name": "status", "type": "string", "enumValues": ["pending", "processing", "shipped"]}]},
        {"id": "ENTITY-003", "name": "Product", "table": "products", "fields": []}]},
    "workflows": [{"id": "FLOW-004", "name": "Place Order", "launchedFrom": ["PAGE-005"],
                   "writes": [{"entity": "ENTITY-005", "fields": ["total", "status"], "states": ["pending"]}]},
                  {"id": "FLOW-001", "name": "Log Water", "launchedFrom": ["PAGE-005"]}],
    "pages": [{"id": "PAGE-005", "route": "/checkout", "pattern": "form", "data": {"primaryEntity": "ENTITY-005"}}],
    "policies": {"money": {"currency": "GBP", "locale": "en-GB"},
                 "quantities": [{"workflow": "FLOW-001", "mode": "add"}],
                 "lifecycles": [{"entity": "ENTITY-005", "field": "status", "initial": "pending",
                                 "moves": [{"from": "pending", "to": "processing", "by": ["ROLE-002"]}]},
                                {"entity": "ENTITY-003", "field": "state", "initial": "x"}]},
}


def test_the_sdk_formats_money_in_the_decided_currency():
    src = (_SDK / "money.tsx").read_text(encoding="utf-8")
    assert 'require("@/contracts/policies.json")' in src and "export function money(" in src
    assert "export function Money(" in src
    widgets = (_SDK / "widget-view.tsx").read_text(encoding="utf-8")
    assert 'import { localeOf, money } from "./money";' in widgets
    assert 'money(v, { currency: currency || undefined })' in widgets
    assert 'new Intl.NumberFormat("en-US", { style: "currency"' not in widgets


def test_a_page_that_names_a_currency_is_refused():
    from services.blueprint.ui_engineer import _hard_coded_money
    assert _hard_coded_money('const money = (v) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(v);')
    assert _hard_coded_money('<Chart currency="USD" data={rows} />')
    assert _hard_coded_money('money(v, { currency: "GBP" })')
    assert not _hard_coded_money('import { money, Money } from "@/sdk/money"; <Money value={row.total} />')
    assert not _hard_coded_money('money(row.amount, { currency: row.currency })'), "a record's own currency passes"
    said = _hard_coded_money('<Chart currency="USD" />')[0]
    assert '"@/sdk/money"' in said


def test_the_page_writer_is_told_the_sdk_formats_money():
    from services.blueprint import ui_engineer
    src = inspect.getsource(ui_engineer)
    assert 'currency?="GBP"' not in src and "MoneyDisplay value={1240.5}" not in src
    assert "MONEY IS THE APPLICATION'S CURRENCY" in src and '"@/sdk/money"' in src
    assert "_hard_coded_money(view)" in src and "_hard_coded_money(code)" in src


def test_the_brief_carries_what_each_process_writes_and_the_decisions():
    from services.blueprint.ui_engineer import _page_brief, page_policies
    page = DOC["pages"][0]
    pol = page_policies(DOC, page)
    assert pol["money"] == {"currency": "GBP", "locale": "en-GB"}
    assert pol["lifecycles"] == [{"entity": "Order", "field": "status", "initial": "pending",
                                  "moves": [{"from": "pending", "to": "processing", "by": ["Merchant"]}]}], \
        "the page's own records' life cycles, with roles by name"
    assert pol["quantities"] == [{"workflow": "FLOW-001", "mode": "add"}]
    assert page_policies({**DOC, "policies": {}}, page) == {}
    brief = _page_brief(DOC, page)
    launched = {w["name"]: w for w in brief["workflowsLaunchedHere"]}
    assert launched["Place Order"]["writes"] == [{"entity": "Order", "fields": ["total", "status"], "states": ["pending"]}]
    assert "writes" not in launched["Log Water"]
    assert brief["policies"]["money"]["currency"] == "GBP"


def test_the_step_writer_declares_what_it_writes_and_follows_the_decisions():
    from services.blueprint.executors import NODE_TASKS
    task = NODE_TASKS["workflow_steps"]
    assert "WHAT A PROCESS WRITES IS DECLARED WITH ITS STEPS" in task and "`writes`" in task
    assert "`policies.quantities`" in task and "`policies.lifecycles`" in task


def test_the_engine_refuses_a_move_the_life_cycle_does_not_allow():
    engine = Path(__file__).resolve().parents[2] / "templates" / "runtime" / "workflows" / "index.ts"
    src = engine.read_text(encoding="utf-8")
    assert "export function lifecycleRefusal(" in src
    assert "lifecyclesOf(getTableName(table)).filter((r) => r.field in raw)" in src
    assert "values = { ...values, [rule.field]: rule.initial };" in src
    assert (Path(__file__).resolve().parents[2] / "templates" / "runtime" / "__tests__" / "run-lifecycle-tests.sh").is_file()
