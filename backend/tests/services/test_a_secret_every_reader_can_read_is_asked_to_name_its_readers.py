"""A secret meant for one party must name who may read it.

Zomato's delivery code (the short code a customer reads out to the driver at the door) was marked
sensitive with a full mask but named no `readers`, so every role that could read an order — the
driver included — read it unmasked and could finish a delivery without being there (2026-11-13,
found by reading it back as the driver). The build now asks the data-model agent to name readers.
"""
from services.blueprint.data_gate import secret_findings


def _doc(field: dict, readers_of_order=("Customer", "Delivery Partner", "Admin")) -> dict:
    roles = [{"id": f"ROLE-00{i}", "name": n, "permissions": ["Read Order"]} for i, n in enumerate(readers_of_order, 1)]
    return {
        "roles": roles,
        "permissions": [{"id": "PERM-001", "name": "Read Order", "subject": "ENTITY-010", "action": "read"}],
        "data": {"entities": [{"id": "ENTITY-010", "name": "Order", "fields": [field]}]},
    }


SECRET = {"name": "deliveryCode", "type": "string", "sensitive": True, "mask": "full"}


def test_a_full_mask_secret_with_no_readers_on_a_record_several_roles_read_is_refused():
    found = secret_findings(_doc(SECRET))
    assert len(found) == 1
    assert "Order.deliveryCode" in found[0].detail
    assert "readers" in found[0].detail
    assert "Customer" in found[0].detail and "Delivery Partner" in found[0].detail
    assert found[0].artifact_id == "ENTITY-010"


def test_a_role_that_lists_its_permissions_by_id_is_read_the_same_way():
    """A built document carries ids ("PERM-001"), not names — the first version of this check read only names and missed the real one."""
    doc = _doc(SECRET)
    doc["permissions"][0]["id"] = "PERM-001"
    for r in doc["roles"]:
        r["permissions"] = ["PERM-001"]
    found = secret_findings(doc)
    assert len(found) == 1 and "Order.deliveryCode" in found[0].detail


def test_naming_the_readers_settles_it():
    assert secret_findings(_doc({**SECRET, "readers": ["Customer", "Admin"]})) == []


def test_a_secret_only_one_role_can_read_is_left_alone():
    assert secret_findings(_doc(SECRET, readers_of_order=("Customer", "Admin"))) == []


def test_a_partial_mask_is_left_alone():
    assert secret_findings(_doc({**SECRET, "mask": "phone"})) == []


def test_a_field_that_is_not_sensitive_is_left_alone():
    assert secret_findings(_doc({"name": "note", "type": "string"})) == []
