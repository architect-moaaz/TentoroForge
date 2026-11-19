"""A driver reads the orders nobody holds only once they are READY for pickup.

`readsUnclaimed` let a driver read every order nobody held, in every state: an order only placed or being cooked carries a
customer's name, number and address that no driver has any business with yet (Zomato, 2026-11-16). A rule can now say which
unclaimed rows are visible: `unclaimedWhere: {"status": "ready_for_pickup"}`.
"""
import json
from pathlib import Path

from services.blueprint import projection

BACKEND = Path(__file__).resolve().parents[2]

DOC = {
    "data": {"entities": [
        {"id": "ENTITY-002", "name": "Order", "table": "orders",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "driverId", "type": "uuid"}, {"name": "status", "type": "string"}]},
    ]},
    "security": {"ownershipRules": [
        {"entity": "Order", "column": "driverId", "kind": "scope", "scope": "user", "readsUnclaimed": True,
         "unclaimedWhere": {"status": "ready_for_pickup"}, "roles": ["Delivery Partner"], "unscopedRoles": ["Admin"]},
    ]},
}


def _rule(doc):
    return projection.ownership_rules(doc)["orders"][0] if "orders" in projection.ownership_rules(doc) else next(iter(projection.ownership_rules(doc).values()))[0]


def test_the_rule_carries_the_states_into_the_app():
    assert _rule(DOC)["unclaimedWhere"] == {"status": "ready_for_pickup"}
    assert _rule(DOC)["readsUnclaimed"] is True


def test_without_readsUnclaimed_the_states_mean_nothing():
    doc = json.loads(json.dumps(DOC))
    doc["security"]["ownershipRules"][0]["readsUnclaimed"] = False
    assert "unclaimedWhere" not in _rule(doc)


def test_a_list_of_states_is_kept_as_a_list():
    doc = json.loads(json.dumps(DOC))
    doc["security"]["ownershipRules"][0]["unclaimedWhere"] = {"status": ["ready_for_pickup", "driver_assigned"]}
    assert _rule(doc)["unclaimedWhere"] == {"status": ["ready_for_pickup", "driver_assigned"]}


def test_the_contract_describes_the_option():
    text = (BACKEND / "contracts" / "blueprint.schema.json").read_text(encoding="utf-8")
    assert '"unclaimedWhere"' in text


def test_the_engine_reads_only_those_states_and_fails_closed_on_a_missing_column():
    engine = (BACKEND / "templates" / "runtime" / "data-engine.ts").read_text(encoding="utf-8")
    assert "rule.unclaimedWhere" in engine and "and(isNull(col), ...unclaimedStates)" in engine
    assert "sql`false`" in engine   # a state on a column the table lacks reads nothing
