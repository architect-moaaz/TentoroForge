"""A KPI label names its measure, and a table follows its columns.

The Criterion refunds dashboard asked for pending value, issued value and
awaiting-posting counts. Every tile was bound to `count` of a guessed entity:
"Amount requested outstanding" counted Approvals, "Awaiting posting" counted
every case, and "Cases needing attention" drew refund-case columns over the
approvals list — a dash in every cell.
"""
from services.a2ui_to_forge import translate

REG = {
    "entities": {
        "RefundCase": {
            "slug": "refund-cases",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "caseNumber", "type": "varchar"},
                {"name": "guestName", "type": "varchar"},
                {"name": "amountRequested", "type": "decimal"},
                {"name": "amountRefunded", "type": "decimal"},
                {"name": "status", "type": "varchar",
                 "enum": ["Pending approval", "Approved awaiting posting", "Issued", "Denied"]},
            ],
        },
        "Approval": {
            "slug": "approvals",
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "refundCaseId", "type": "uuid"},
                {"name": "stage", "type": "varchar"},
                {"name": "decision", "type": "varchar"},
            ],
        },
    }
}


def _payload(components, data):
    return {"messages": [
        {"version": "v0.9", "updateDataModel": {"value": data}},
        {"version": "v0.9", "updateComponents": {"components": components}},
    ]}


def _sources(r):
    return {s["name"]: s for s in r["schema"]["dataSources"]}


def _tile(cid, label, path):
    return {"id": cid, "component": "MetricTile", "label": label, "value": {"path": path}}


ROOT = {"id": "root", "component": "Stack", "children": ["t1", "t2", "t3", "t4", "tbl"]}
TABLE = {"id": "tbl", "component": "Table", "title": "Cases needing attention",
         "rows": {"path": "/approvals/rows"},
         "columns": [{"key": "caseNumber", "label": "Case"}, {"key": "guestName", "label": "Guest"},
                     {"key": "amountRequested", "label": "Amount"}, {"key": "status", "label": "Status"}]}
DATA = {"approvals": {"outstanding": 0, "posting": 0, "issued": 0, "rows": []},
        "refundCases": {"open": 0}}


def _run():
    return translate(_payload([
        ROOT,
        _tile("t1", "Amount requested outstanding", "/approvals/outstanding"),
        _tile("t2", "Awaiting posting", "/approvals/posting"),
        _tile("t3", "Issued value", "/approvals/issued"),
        _tile("t4", "Open refund cases", "/refundCases/open"),
        TABLE,
    ], DATA), REG)


def test_an_amount_label_is_a_sum_over_the_column_it_names():
    src = _sources(_run())
    outstanding = src["amountrequestedoutstanding"]
    assert outstanding["entity"] == "RefundCase"
    assert outstanding["metrics"]["value"] == {
        "fn": "sum", "field": "amountRequested", "filter": {"status": "Pending approval"}}


def test_a_label_naming_the_tail_of_an_enum_value_filters_on_it():
    src = _sources(_run())
    posting = src["awaitingposting"]
    assert posting["entity"] == "RefundCase"
    assert posting["metrics"]["value"] == {"fn": "count", "filter": {"status": "Approved awaiting posting"}}


def test_issued_value_sums_what_was_refunded_for_issued_cases():
    src = _sources(_run())
    issued = src["issuedvalue"]
    assert issued["entity"] == "RefundCase"
    assert issued["metrics"]["value"]["fn"] == "sum"
    assert issued["metrics"]["value"]["filter"] == {"status": "Issued"}


def test_a_count_label_stays_a_count():
    src = _sources(_run())
    assert src["openrefundcases"]["metrics"]["value"] == {"fn": "count"}


def test_a_table_follows_its_columns_not_its_pointer():
    r = _run()
    src = _sources(r)
    tables = [s for s in src.values() if s.get("op") == "list"]
    assert tables and tables[0]["entity"] == "RefundCase"
    assert any("columns are RefundCase" in a for a in r.get("assumptions", []))
