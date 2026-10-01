"""F&B (forge-v3, 2026-10-01): Smith's "Mark Notifications Read" wrote
`notifications.readAt`, a table the app does not have; every press was a 422
and no check said so — the column check skipped any table no entity matched."""
from services.blueprint.functional_completeness import authoring_findings, table_findings

DATA = {"entities": [{"id": "ENTITY-003", "name": "Order", "table": "orders",
                      "fields": [{"name": "id"}, {"name": "customerName"}]}]}


def _doc(table):
    return {"workflows": [{"id": "FLOW-006", "name": "Mark Notifications Read", "steps": [
        {"key": "mark_all", "type": "action", "config": {"actionType": "db_update", "table": table,
                                                         "values": {"read": True}, "where": {"read": False}}}]}],
            "data": DATA, "businessRules": []}


def test_a_table_the_app_does_not_have_is_named():
    found = table_findings(_doc("notifications"))
    assert len(found) == 1 and found[0]["rule"] == "unknown-table"
    assert "names the table 'notifications', which is no record of this application (its records: orders)" in found[0]["detail"]
    assert "send_notification" in found[0]["detail"]
    assert any(f["rule"] == "unknown-table" for f in authoring_findings(_doc("notifications")))


def test_the_apps_records_and_the_login_table_pass():
    assert table_findings(_doc("orders")) == [] and table_findings(_doc("users")) == []
