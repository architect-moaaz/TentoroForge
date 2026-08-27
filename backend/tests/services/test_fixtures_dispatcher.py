from services.fixtures.dispatcher import provide_records
from services.fixtures.types import FieldHint


def test_layer_1_hit_for_general_user():
    rs = provide_records(domain="general", entity_name="User", fields=[], count=10)
    assert len(rs) == 10
    # Sourced from the curated bank — first record's name is fixed
    assert rs[0]["name"] == "Sarah Chen"


def test_layer_2_fallback_when_bank_missing():
    fields = [FieldHint(name="id", type="uuid"), FieldHint(name="email", type="varchar(255)")]
    rs = provide_records(domain="general", entity_name="UnknownEntity", fields=fields, count=3)
    assert len(rs) == 3
    assert all("@" in r["email"] for r in rs)


def test_layer_3_fallback_when_no_fields_and_no_bank():
    rs = provide_records(domain="general", entity_name="UnknownEntity", fields=[], count=2)
    # Empty field list returns empty records (one per requested count)
    assert len(rs) == 2
    assert rs[0] == {}
